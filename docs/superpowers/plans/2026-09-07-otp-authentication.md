# WhatsApp and Email OTP Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users sign in and recover a password with a six-digit code delivered over WhatsApp or email, without weakening the existing password and authenticator flows.

**Architecture:** A new `accounts.OtpChallenge` table holds one hashed, single-use, expiring code per user and purpose. Two endpoints issue and redeem it; delivery reuses the existing `integrations` outbox so codes inherit idempotency, retry and audit. `User.email` and `User.whatsapp_phone` become uniquely constrained so a typed identifier resolves to exactly one account.

**Tech Stack:** Django 5 + Django REST Framework, pytest + pytest-django, Next.js App Router + TanStack Query, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-07-otp-authentication-design.md`

## Global Constraints

- Python target `py311`; ruff `line-length = 100`, rules `E,F,I,UP,B`, migrations excluded.
- Backend tests: `cd apps/api && pytest`. Lint: `cd apps/api && ruff check .`.
- Frontend lint and types: `cd apps/web && npm run lint && npm run typecheck`.
- The plaintext OTP code is **never** written to `OtpChallenge`, `IntegrationMessage.subject`, `IntegrationMessage.body_summary`, an `AuditLog`, or a log line. It exists only in `IntegrationMessage.payload_encrypted` and the in-process request cycle.
- `apps/web/e2e/helpers.ts:loginAs` drives the password form with `getByLabel("Username")`, `getByLabel("Password")` and `getByRole("button", { name: "Sign in securely" })`. Those three accessible names must survive the login-page refactor unchanged or every existing e2e spec breaks.
- Existing callers of `integrations.services.queue_message` must not need edits; any new parameter is keyword-only with a default preserving today's behaviour.
- New settings read through `os.getenv` in `config/settings.py`, matching the surrounding style.
- Commit after every task with the message shown in its final step.

---

### Task 1: Unique login identifiers

Makes a typed email or phone resolve to exactly one account, and refuses to migrate a database where it would not.

**Files:**
- Modify: `apps/api/accounts/models.py`
- Create: `apps/api/accounts/migrations/0005_unique_login_identifiers.py`
- Create: `apps/api/accounts/management/commands/check_login_identifiers.py`
- Test: `apps/api/tests/test_login_identifiers.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `User` guarantees at most one active row per non-blank `Lower(email)` and per non-blank `whatsapp_phone`. `accounts.management.commands.check_login_identifiers.find_conflicts(rows) -> list[tuple[str, str, list[str]]]`, where `rows` is an iterable of `(username, email, whatsapp_phone)` and each result is `(field, value, sorted usernames)`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_login_identifiers.py`:

```python
import pytest
from django.db import IntegrityError, transaction

from accounts.management.commands.check_login_identifiers import find_conflicts
from accounts.models import User


@pytest.mark.django_db
def test_email_is_unique_case_insensitively():
    User.objects.create_user(username="one", email="Ops@Drona.test")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create_user(username="two", email="ops@drona.test")


@pytest.mark.django_db
def test_whatsapp_phone_is_unique():
    User.objects.create_user(username="one", whatsapp_phone="919811111111")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create_user(username="two", whatsapp_phone="919811111111")


@pytest.mark.django_db
def test_blank_identifiers_do_not_collide():
    User.objects.create_user(username="one", email="", whatsapp_phone="")
    User.objects.create_user(username="two", email="", whatsapp_phone="")
    assert User.objects.filter(email="").count() == 2


def test_find_conflicts_reports_colliding_usernames():
    """Pure logic, no database.

    Once the migration in this task has run, the database itself refuses to
    hold a conflict, so this detector can only be exercised over rows passed
    in. That is also how it earns its keep: it runs against an *old* database
    before the constraints exist.
    """
    rows = [
        ("alpha", "a@x.test", ""),
        ("beta", "A@X.test", ""),
        ("gamma", "g@x.test", "919811111111"),
        ("delta", "d@x.test", "919811111111"),
        ("epsilon", "", ""),
        ("zeta", "", ""),
    ]
    assert find_conflicts(rows) == [
        ("email", "a@x.test", ["alpha", "beta"]),
        ("whatsapp_phone", "919811111111", ["delta", "gamma"]),
    ]


def test_find_conflicts_is_quiet_on_clean_data():
    assert find_conflicts([("alpha", "a@x.test", "919811111111"), ("beta", "", "")]) == []


@pytest.mark.django_db
def test_check_login_identifiers_command_passes_on_clean_data(capsys):
    from django.core.management import call_command

    User.objects.create_user(username="alpha", email="a@x.test")
    call_command("check_login_identifiers")
    assert "No duplicate login identifiers" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_login_identifiers.py -v`
Expected: FAIL — `ModuleNotFoundError` for `check_login_identifiers`, and the two `IntegrityError` tests fail because no constraint exists yet.

- [ ] **Step 3: Add the constraints to the model**

In `apps/api/accounts/models.py`, add the imports and a `Meta` to `User`:

```python
from django.db.models import Q, UniqueConstraint
from django.db.models.functions import Lower
```

```python
    class Meta(AbstractUser.Meta):
        constraints = [
            UniqueConstraint(
                Lower("email"),
                condition=~Q(email=""),
                name="accounts_user_unique_email_ci",
            ),
            UniqueConstraint(
                fields=["whatsapp_phone"],
                condition=~Q(whatsapp_phone=""),
                name="accounts_user_unique_whatsapp_phone",
            ),
        ]
```

`User` declares no `Meta` today, so it inherits `AbstractUser.Meta` and its `verbose_name`. Subclassing `AbstractUser.Meta` rather than writing a bare `class Meta` keeps those options identical, so the migration adds constraints only and never an `AlterModelOptions`.

- [ ] **Step 4: Write the pre-check command**

Create `apps/api/accounts/management/commands/check_login_identifiers.py`:

```python
from collections import defaultdict

from django.core.management.base import BaseCommand

from accounts.models import User


def find_conflicts(rows):
    """Return [(field, value, sorted usernames)] for identifiers shared by more than one row.

    `rows` is an iterable of (username, email, whatsapp_phone). Taking rows as
    an argument rather than querying inside keeps the logic testable after the
    unique constraints make a conflicting database unreachable.
    """
    groups = {"email": defaultdict(list), "whatsapp_phone": defaultdict(list)}
    for username, email, phone in rows:
        if email:
            groups["email"][email.lower()].append(username)
        if phone:
            groups["whatsapp_phone"][phone].append(username)
    return [
        (field, value, sorted(usernames))
        for field in ("email", "whatsapp_phone")
        for value, usernames in sorted(groups[field].items())
        if len(usernames) > 1
    ]


class Command(BaseCommand):
    help = "Report active users that share an email address or WhatsApp number"

    def handle(self, *args, **options):
        conflicts = find_conflicts(
            User.objects.filter(is_active=True)
            .order_by("username")
            .values_list("username", "email", "whatsapp_phone")
        )
        if not conflicts:
            self.stdout.write(self.style.SUCCESS("No duplicate login identifiers"))
            return
        for field, value, usernames in conflicts:
            self.stdout.write(self.style.ERROR(f"{field} {value} is shared by {', '.join(usernames)}"))
        raise SystemExit(1)
```

- [ ] **Step 5: Write the migration with its guard**

Create `apps/api/accounts/migrations/0005_unique_login_identifiers.py`:

```python
from django.db import migrations, models
from django.db.models import Q, UniqueConstraint
from django.db.models.functions import Lower


def reject_duplicate_identifiers(apps, schema_editor):
    from collections import defaultdict

    User = apps.get_model("accounts", "User")
    problems = []
    for field, key in (("email", lambda value: value.lower()), ("whatsapp_phone", lambda value: value)):
        buckets = defaultdict(list)
        for username, value in User.objects.filter(is_active=True).values_list("username", field):
            if value:
                buckets[key(value)].append(username)
        problems.extend(
            f"{field} {value} is shared by {', '.join(sorted(names))}"
            for value, names in sorted(buckets.items())
            if len(names) > 1
        )
    if problems:
        raise RuntimeError(
            "Cannot add unique login identifiers until these are resolved:\n  "
            + "\n  ".join(problems)
            + "\nRun: python manage.py check_login_identifiers"
        )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_user_whatsapp_phone")]

    operations = [
        migrations.RunPython(reject_duplicate_identifiers, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="user",
            constraint=UniqueConstraint(
                Lower("email"), condition=~Q(email=""), name="accounts_user_unique_email_ci"
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=UniqueConstraint(
                fields=["whatsapp_phone"],
                condition=~Q(whatsapp_phone=""),
                name="accounts_user_unique_whatsapp_phone",
            ),
        ),
    ]
```

The `models` import is unused once `AlterModelOptions` is gone — drop it from the migration's imports so ruff stays clean.

- [ ] **Step 6: Confirm the migration matches the model**

Run: `cd apps/api && python manage.py makemigrations --check --dry-run accounts`
Expected: exit 0, "No changes detected". If it reports changes, reconcile the hand-written migration with the model rather than generating a second one.

- [ ] **Step 7: Run the tests**

Run: `cd apps/api && pytest tests/test_login_identifiers.py -v`
Expected: 4 passed.

- [ ] **Step 8: Clear duplicates on the local database**

Run: `cd apps/api && python manage.py check_login_identifiers`
Expected: exits 1 naming `whatsapp_phone 918582828432 is shared by approver, finance, management`. Clear two of the three, then re-run until it prints "No duplicate login identifiers", then `python manage.py migrate`.

- [ ] **Step 9: Commit**

```bash
git add apps/api/accounts apps/api/tests/test_login_identifiers.py
git commit -m "Require unique email and WhatsApp number for login identifiers"
```

---

### Task 2: OtpChallenge model and core issue/verify logic

Pure Python, no HTTP and no delivery. Everything security-critical about the code lives here.

**Files:**
- Modify: `apps/api/accounts/models.py`
- Create: `apps/api/accounts/otp.py`
- Create: `apps/api/accounts/migrations/0006_otpchallenge.py`
- Test: `apps/api/tests/test_otp_core.py`

**Interfaces:**
- Consumes: `accounts.models.User` from Task 1.
- Produces:
  - `accounts.models.OtpChallenge` with `Purpose.LOGIN` / `Purpose.PASSWORD_RESET`, `Channel.WHATSAPP` / `Channel.EMAIL`.
  - `accounts.otp.issue_challenge(user, *, purpose, channel, request=None) -> tuple[OtpChallenge, str]` returning the challenge and the plaintext code.
  - `accounts.otp.verify_challenge(challenge_id, code, *, purpose) -> OtpChallenge` raising `OtpInvalid`; does **not** consume.
  - `accounts.otp.consume(challenge) -> None`
  - `accounts.otp.register_failed_attempt(challenge) -> None`
  - `accounts.otp.resolve_identifier(identifier) -> tuple[User | None, str]` returning the user (or `None`) and the channel constant.
  - `accounts.otp.mask_destination(identifier) -> str`
  - Exceptions `OtpInvalid`, `OtpRateLimited`.
  - Constants `CODE_TTL`, `MAX_ATTEMPTS`, `RESEND_COOLDOWN`, `MAX_PER_HOUR`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_otp_core.py`:

```python
from datetime import timedelta

import pytest
from django.utils import timezone

from accounts import otp
from accounts.models import OtpChallenge, User


@pytest.fixture
def member(db):
    return User.objects.create_user(
        username="member", email="member@drona.test", whatsapp_phone="919811111111"
    )


@pytest.mark.django_db
def test_issue_returns_six_digit_code_that_is_never_stored(member):
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
    )
    assert len(code) == 6 and code.isdigit()
    assert code not in challenge.code_hash
    assert challenge.code_hash != code
    assert challenge.expires_at > timezone.now()


@pytest.mark.django_db
def test_verify_accepts_the_issued_code_without_consuming_it(member):
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
    )
    verified = otp.verify_challenge(challenge.id, code, purpose=OtpChallenge.Purpose.LOGIN)
    assert verified.pk == challenge.pk
    assert verified.consumed_at is None


@pytest.mark.django_db
def test_wrong_code_increments_attempts_then_locks_out(member):
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
    )
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(otp.MAX_ATTEMPTS):
        with pytest.raises(otp.OtpInvalid):
            otp.verify_challenge(challenge.id, wrong, purpose=OtpChallenge.Purpose.LOGIN)
    challenge.refresh_from_db()
    assert challenge.attempts == otp.MAX_ATTEMPTS
    with pytest.raises(otp.OtpInvalid):
        otp.verify_challenge(challenge.id, code, purpose=OtpChallenge.Purpose.LOGIN)


@pytest.mark.django_db
def test_consumed_and_expired_challenges_are_rejected(member):
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
    )
    otp.consume(challenge)
    with pytest.raises(otp.OtpInvalid):
        otp.verify_challenge(challenge.id, code, purpose=OtpChallenge.Purpose.LOGIN)

    stale, stale_code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.PASSWORD_RESET, channel=OtpChallenge.Channel.EMAIL
    )
    OtpChallenge.objects.filter(pk=stale.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(otp.OtpInvalid):
        otp.verify_challenge(stale.id, stale_code, purpose=OtpChallenge.Purpose.PASSWORD_RESET)


@pytest.mark.django_db
def test_issuing_again_supersedes_the_previous_code(member):
    first, first_code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
    )
    OtpChallenge.objects.filter(pk=first.pk).update(
        created_at=timezone.now() - otp.RESEND_COOLDOWN - timedelta(seconds=1)
    )
    otp.issue_challenge(member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL)
    with pytest.raises(otp.OtpInvalid):
        otp.verify_challenge(first.id, first_code, purpose=OtpChallenge.Purpose.LOGIN)


@pytest.mark.django_db
def test_resend_cooldown_and_hourly_cap_raise_rate_limited(member):
    otp.issue_challenge(member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL)
    with pytest.raises(otp.OtpRateLimited):
        otp.issue_challenge(member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL)

    aged = timezone.now() - otp.RESEND_COOLDOWN - timedelta(seconds=1)
    for _ in range(otp.MAX_PER_HOUR - 1):
        challenge, _ = otp.issue_challenge(
            member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
        )
        OtpChallenge.objects.filter(pk=challenge.pk).update(created_at=aged)
    with pytest.raises(otp.OtpRateLimited):
        otp.issue_challenge(member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL)


@pytest.mark.django_db
def test_resolve_identifier_matches_email_and_phone_and_skips_inactive(member):
    assert otp.resolve_identifier("MEMBER@drona.test") == (member, OtpChallenge.Channel.EMAIL)
    assert otp.resolve_identifier("+91 98111 11111") == (member, OtpChallenge.Channel.WHATSAPP)
    assert otp.resolve_identifier("nobody@drona.test") == (None, OtpChallenge.Channel.EMAIL)
    member.is_active = False
    member.save(update_fields=["is_active"])
    assert otp.resolve_identifier("member@drona.test") == (None, OtpChallenge.Channel.EMAIL)


def test_mask_destination_hides_most_of_the_identifier():
    assert otp.mask_destination("rintu.m@dronalogitech.com") == "r***@dronalogitech.com"
    assert otp.mask_destination("918777430172") == "+91 87****0172"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_otp_core.py -v`
Expected: FAIL — `ImportError: cannot import name 'otp' from 'accounts'`.

- [ ] **Step 3: Add the model**

Append to `apps/api/accounts/models.py`:

```python
import uuid
```

```python
class OtpChallenge(models.Model):
    class Purpose(models.TextChoices):
        LOGIN = "LOGIN", "Login"
        PASSWORD_RESET = "PASSWORD_RESET", "Password reset"

    class Channel(models.TextChoices):
        WHATSAPP = "WHATSAPP", "WhatsApp"
        EMAIL = "EMAIL", "Email"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="otp_challenges")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    code_hash = models.CharField(max_length=64)
    destination_masked = models.CharField(max_length=120)
    expires_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    # Set when the challenge stops being usable, whether it was redeemed or
    # superseded by a newer code for the same user and purpose.
    consumed_at = models.DateTimeField(null=True, blank=True)
    request_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "purpose", "-created_at"])]
```

- [ ] **Step 4: Write the core module**

Create `apps/api/accounts/otp.py`:

```python
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models.functions import Lower
from django.utils import timezone

from .models import OtpChallenge, User

CODE_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_PER_HOUR = 5
RESET_TICKET_MAX_AGE = 600


class OtpInvalid(Exception):
    """The challenge does not exist, has expired, is spent, or the code is wrong."""


class OtpRateLimited(Exception):
    """The user has asked for codes too often."""


def normalise_phone(value):
    return re.sub(r"[\s()+-]", "", value or "")


def hash_code(challenge_id, code):
    return hmac.new(
        settings.SECRET_KEY.encode(), f"{challenge_id}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def mask_destination(identifier):
    if "@" in identifier:
        name, _, domain = identifier.partition("@")
        return f"{name[:1] or '*'}***@{domain}"
    digits = normalise_phone(identifier)
    if len(digits) < 8:
        return "*" * 8
    return f"+{digits[:2]} {digits[2:4]}****{digits[-4:]}"


def resolve_identifier(identifier):
    identifier = (identifier or "").strip()
    if "@" in identifier:
        user = (
            User.objects.annotate(email_ci=Lower("email"))
            .filter(email_ci=identifier.lower(), is_active=True)
            .exclude(email="")
            .first()
        )
        return user, OtpChallenge.Channel.EMAIL
    digits = normalise_phone(identifier)
    user = (
        User.objects.filter(whatsapp_phone=digits, is_active=True).first() if digits else None
    )
    return user, OtpChallenge.Channel.WHATSAPP


def issue_challenge(user, *, purpose, channel, request=None):
    now = timezone.now()
    recent = OtpChallenge.objects.filter(
        user=user, purpose=purpose, created_at__gte=now - timedelta(hours=1)
    )
    if recent.filter(created_at__gt=now - RESEND_COOLDOWN).exists():
        raise OtpRateLimited("A code was sent moments ago")
    if recent.count() >= MAX_PER_HOUR:
        raise OtpRateLimited("Too many codes requested in the last hour")

    OtpChallenge.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).update(
        consumed_at=now
    )
    destination = user.email if channel == OtpChallenge.Channel.EMAIL else user.whatsapp_phone
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = OtpChallenge(
        user=user,
        purpose=purpose,
        channel=channel,
        destination_masked=mask_destination(destination),
        expires_at=now + CODE_TTL,
        request_ip=_client_ip(request),
    )
    # The UUID default is applied in __init__, so the id is available for hashing pre-save.
    challenge.code_hash = hash_code(challenge.id, code)
    challenge.save()
    return challenge, code


def _client_ip(request):
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


@transaction.atomic
def verify_challenge(challenge_id, code, *, purpose):
    try:
        challenge = OtpChallenge.objects.select_for_update().get(pk=challenge_id, purpose=purpose)
    except (OtpChallenge.DoesNotExist, ValueError, TypeError):
        raise OtpInvalid("Invalid or expired code") from None
    if (
        challenge.consumed_at is not None
        or challenge.expires_at <= timezone.now()
        or challenge.attempts >= MAX_ATTEMPTS
    ):
        raise OtpInvalid("Invalid or expired code")
    if not hmac.compare_digest(challenge.code_hash, hash_code(challenge.id, code or "")):
        challenge.attempts += 1
        challenge.save(update_fields=["attempts"])
        raise OtpInvalid("Invalid or expired code")
    return challenge


def consume(challenge):
    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at"])


def register_failed_attempt(challenge):
    challenge.attempts += 1
    challenge.save(update_fields=["attempts"])
```

- [ ] **Step 5: Generate the migration**

Run: `cd apps/api && python manage.py makemigrations accounts --name otpchallenge`
Expected: creates `0006_otpchallenge.py` adding the model. Confirm with `python manage.py makemigrations --check --dry-run accounts` (exit 0).

- [ ] **Step 6: Run the tests**

Run: `cd apps/api && pytest tests/test_otp_core.py -v`
Expected: 8 passed.

- [ ] **Step 7: Commit**

```bash
git add apps/api/accounts apps/api/tests/test_otp_core.py
git commit -m "Add OtpChallenge model with hashed single-use codes and rate limits"
```

---

### Task 3: Outbox and provider extensions

Two small, independently useful changes to `integrations` that Task 4 needs: a redactable summary, and an OTP button component for authentication-category templates.

**Files:**
- Modify: `apps/api/integrations/services.py:114-150`
- Modify: `apps/api/integrations/providers.py:190-245`
- Test: `apps/api/tests/test_integrations_otp_support.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `queue_message(..., summary=None)` — when `summary` is given it becomes `body_summary` instead of `body[:1000]`.
  - `WhatsAppProvider.send(..., options={"otp_button_type": "none" | "copy_code" | "url", "otp_button_code": str})`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_integrations_otp_support.py`:

```python
import json

import pytest

from core.crypto import decrypt_value
from integrations.models import IntegrationMessage
from integrations.providers import WhatsAppProvider
from integrations.services import queue_message


@pytest.mark.django_db
def test_queue_message_summary_override_keeps_body_out_of_the_log(settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    message = queue_message(
        channel=IntegrationMessage.Channel.EMAIL,
        recipient="member@drona.test",
        subject="Your code",
        body="Your code is 123456",
        object_type="account",
        object_id="1",
        idempotency_key="otp:test-1",
        summary="Sign-in code sent (code redacted)",
    )
    assert message.body_summary == "Sign-in code sent (code redacted)"
    assert "123456" not in message.body_summary
    assert "123456" in json.loads(decrypt_value(message.payload_encrypted))["body"]


@pytest.mark.django_db
def test_queue_message_defaults_summary_to_the_body(settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    message = queue_message(
        channel=IntegrationMessage.Channel.IN_APP,
        recipient="",
        subject="Hello",
        body="Body text",
        object_type="account",
        object_id="1",
        idempotency_key="otp:test-2",
    )
    assert message.body_summary == "Body text"


def test_whatsapp_copy_code_button_component(monkeypatch):
    sent = {}
    monkeypatch.setattr(
        "integrations.providers.request_json",
        lambda url, **kwargs: sent.update(kwargs) or {"messages": [{"id": "wamid.1"}]},
    )
    provider = WhatsAppProvider(access_token="t", phone_number_id="1")
    provider.send(
        recipient="919811111111",
        subject="",
        body="ignored",
        idempotency_key="otp:test-3",
        options={
            "template_name": "password_recovery",
            "body_parameters": ["123456"],
            "otp_button_type": "copy_code",
            "otp_button_code": "123456",
        },
    )
    components = sent["payload"]["template"]["components"]
    assert components[-1] == {
        "type": "button",
        "sub_type": "copy_code",
        "index": "0",
        "parameters": [{"type": "coupon_code", "coupon_code": "123456"}],
    }


def test_whatsapp_omits_the_button_by_default(monkeypatch):
    sent = {}
    monkeypatch.setattr(
        "integrations.providers.request_json",
        lambda url, **kwargs: sent.update(kwargs) or {"messages": [{"id": "wamid.2"}]},
    )
    provider = WhatsAppProvider(access_token="t", phone_number_id="1")
    provider.send(
        recipient="919811111111",
        subject="",
        body="ignored",
        idempotency_key="otp:test-4",
        options={"template_name": "vms_login", "body_parameters": ["123456", "Drona Logitech VMS"]},
    )
    components = sent["payload"]["template"]["components"]
    assert all(component["type"] != "button" for component in components)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_integrations_otp_support.py -v`
Expected: FAIL — `queue_message() got an unexpected keyword argument 'summary'`, and the copy-code assertion fails because no button is emitted.

- [ ] **Step 3: Add the summary override**

In `apps/api/integrations/services.py`, add `summary=None` to the keyword-only parameters of `queue_message` (after `provider_options=None`), and change the `body_summary` default:

```python
            "body_summary": (summary if summary is not None else body)[:1000],
```

- [ ] **Step 4: Add the OTP button to the provider**

In `apps/api/integrations/providers.py`, inside `WhatsAppProvider.send`, immediately after the `url_button_parameters` loop and before `content = {`:

```python
            otp_button_type = str(options.get("otp_button_type") or "none").lower()
            if otp_button_type == "copy_code":
                components.append({
                    "type": "button",
                    "sub_type": "copy_code",
                    "index": "0",
                    "parameters": [
                        {"type": "coupon_code", "coupon_code": str(options.get("otp_button_code", ""))}
                    ],
                })
            elif otp_button_type == "url":
                components.append({
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [{"type": "text", "text": str(options.get("otp_button_code", ""))}],
                })
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/api && pytest tests/test_integrations_otp_support.py tests/test_whatsapp_approval.py tests/test_smtp.py -v`
Expected: all pass. The two existing suites confirm no regression for current callers.

- [ ] **Step 6: Commit**

```bash
git add apps/api/integrations apps/api/tests/test_integrations_otp_support.py
git commit -m "Allow redacted outbox summaries and WhatsApp OTP button components"
```

---

### Task 4: OTP delivery

Wires a challenge to the outbox with the right template, parameters and redaction.

**Files:**
- Modify: `apps/api/accounts/otp.py`
- Modify: `apps/api/config/settings.py`
- Modify: `apps/api/integrations/views.py:163-190`
- Modify: `apps/api/.env.example` (repo root `.env.example`)
- Test: `apps/api/tests/test_otp_delivery.py`

**Interfaces:**
- Consumes: `issue_challenge` (Task 2), `queue_message(summary=...)` and `otp_button_type` (Task 3), `integrations.services._whatsapp_template_setting`.
- Produces: `accounts.otp.send_challenge(challenge, code) -> IntegrationMessage`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_otp_delivery.py`:

```python
import json

import pytest

from accounts import otp
from accounts.models import OtpChallenge, User
from core.crypto import decrypt_value
from integrations.models import IntegrationMessage


@pytest.fixture
def member(db):
    return User.objects.create_user(
        username="member", email="member@drona.test", whatsapp_phone="919811111111"
    )


@pytest.mark.django_db
def test_whatsapp_login_code_uses_vms_login_template(member, settings, monkeypatch):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    monkeypatch.delenv("WHATSAPP_LOGIN_OTP_TEMPLATE_NAME", raising=False)
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.WHATSAPP
    )
    message = otp.send_challenge(challenge, code)
    options = json.loads(decrypt_value(message.payload_encrypted))["provider_options"]
    assert message.channel == IntegrationMessage.Channel.WHATSAPP
    assert message.recipient == "919811111111"
    assert options["template_name"] == "vms_login"
    assert options["body_parameters"] == [code, "Drona Logitech VMS"]


@pytest.mark.django_db
def test_password_reset_code_uses_password_recovery_template(member, settings, monkeypatch):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    monkeypatch.delenv("WHATSAPP_PASSWORD_RECOVERY_TEMPLATE_NAME", raising=False)
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.PASSWORD_RESET, channel=OtpChallenge.Channel.WHATSAPP
    )
    message = otp.send_challenge(challenge, code)
    options = json.loads(decrypt_value(message.payload_encrypted))["provider_options"]
    assert options["template_name"] == "password_recovery"
    assert options["body_parameters"] == [code]
    assert options["otp_button_code"] == code


@pytest.mark.django_db
def test_code_is_redacted_from_every_readable_field(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
    )
    message = otp.send_challenge(challenge, code)
    assert code not in message.subject
    assert code not in message.body_summary
    assert code in json.loads(decrypt_value(message.payload_encrypted))["body"]
    assert message.event_key == "LOGIN_OTP"
    assert message.idempotency_key == f"otp:{challenge.id}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_otp_delivery.py -v`
Expected: FAIL — `AttributeError: module 'accounts.otp' has no attribute 'send_challenge'`.

- [ ] **Step 3: Add the setting**

In `apps/api/config/settings.py`, next to `WHATSAPP_INTERACTIVE_DECISIONS`:

```python
# Rendered into the vms_login template's second variable.
OTP_APP_LABEL = os.getenv("OTP_APP_LABEL", "Drona Logitech VMS")
```

- [ ] **Step 4: Write `send_challenge`**

Append to `apps/api/accounts/otp.py`:

```python
_TEMPLATE_KEYS = {
    OtpChallenge.Purpose.LOGIN: (
        "login_otp_template_name",
        "WHATSAPP_LOGIN_OTP_TEMPLATE_NAME",
        "vms_login",
        "login_otp_template_language",
        "WHATSAPP_LOGIN_OTP_TEMPLATE_LANGUAGE",
    ),
    OtpChallenge.Purpose.PASSWORD_RESET: (
        "password_recovery_template_name",
        "WHATSAPP_PASSWORD_RECOVERY_TEMPLATE_NAME",
        "password_recovery",
        "password_recovery_template_language",
        "WHATSAPP_PASSWORD_RECOVERY_TEMPLATE_LANGUAGE",
    ),
}

_COPY = {
    OtpChallenge.Purpose.LOGIN: (
        "Your Drona Logitech sign-in code",
        "Sign-in code sent (code redacted)",
        "LOGIN_OTP",
    ),
    OtpChallenge.Purpose.PASSWORD_RESET: (
        "Your Drona Logitech password recovery code",
        "Password recovery code sent (code redacted)",
        "PASSWORD_RESET_OTP",
    ),
}


def send_challenge(challenge, code):
    from integrations.services import _whatsapp_template_setting, queue_message

    subject, summary, event_key = _COPY[challenge.purpose]
    minutes = int(CODE_TTL.total_seconds() // 60)
    if challenge.purpose == OtpChallenge.Purpose.LOGIN:
        body = (
            f"OTP Code: {code}. This is your OTP code for {settings.OTP_APP_LABEL}. "
            f"For your security, do not share this code. It expires in {minutes} minutes."
        )
        body_parameters = [code, settings.OTP_APP_LABEL]
    else:
        body = (
            f"{code} is your password recovery code. For your security, do not share this code. "
            f"It expires in {minutes} minutes."
        )
        body_parameters = [code]

    provider_options = {}
    if challenge.channel == OtpChallenge.Channel.WHATSAPP:
        name_key, name_env, name_default, language_key, language_env = _TEMPLATE_KEYS[challenge.purpose]
        connection_option = _whatsapp_template_setting(
            f"{challenge.purpose.lower()}_button_type", "WHATSAPP_OTP_BUTTON_TYPE", "none"
        )
        provider_options = {
            "template_name": _whatsapp_template_setting(name_key, name_env, name_default),
            "template_language": _whatsapp_template_setting(language_key, language_env, "en"),
            "body_parameters": body_parameters,
            "otp_button_type": connection_option,
            "otp_button_code": code,
        }
        recipient = challenge.user.whatsapp_phone
        channel = "WHATSAPP"
    else:
        recipient = challenge.user.email
        channel = "EMAIL"

    return queue_message(
        channel=channel,
        recipient=recipient,
        subject=subject,
        body=body,
        summary=summary,
        object_type="account",
        object_id=str(challenge.user_id),
        idempotency_key=f"otp:{challenge.id}",
        user=challenge.user,
        event_key=event_key,
        provider_options=provider_options,
    )
```

- [ ] **Step 5: Register the template names in the WhatsApp connect endpoint**

In `apps/api/integrations/views.py`, extend `template_defaults` inside `whatsapp_connect`:

```python
            "login_otp_template_name": "vms_login",
            "login_otp_template_language": "en",
            "password_recovery_template_name": "password_recovery",
            "password_recovery_template_language": "en",
```

Then, after the existing validation loop, accept the two button-type switches (they are not template names, so they bypass the `[a-z0-9_]` name rule):

```python
        for key in ("login_button_type", "password_reset_button_type"):
            value = str(request.data.get(key, "none")).strip().lower()
            if value not in {"none", "copy_code", "url"}:
                return Response({"detail": f"{key} must be none, copy_code or url"}, status=400)
            configuration[key] = value
```

- [ ] **Step 6: Document the environment variables**

Append to the repository-root `.env.example`, next to `WHATSAPP_TEMPLATE_NAME`:

```
OTP_APP_LABEL=Drona Logitech VMS
WHATSAPP_LOGIN_OTP_TEMPLATE_NAME=vms_login
WHATSAPP_LOGIN_OTP_TEMPLATE_LANGUAGE=en
WHATSAPP_PASSWORD_RECOVERY_TEMPLATE_NAME=password_recovery
WHATSAPP_PASSWORD_RECOVERY_TEMPLATE_LANGUAGE=en
WHATSAPP_OTP_BUTTON_TYPE=none
```

- [ ] **Step 7: Run the tests**

Run: `cd apps/api && pytest tests/test_otp_delivery.py tests/test_integrations_import.py -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add apps/api/accounts/otp.py apps/api/config/settings.py apps/api/integrations/views.py .env.example apps/api/tests/test_otp_delivery.py
git commit -m "Deliver OTP codes through the outbox with redacted summaries"
```

---

### Task 5: OTP request and verify endpoints

**Files:**
- Modify: `apps/api/accounts/serializers.py`
- Modify: `apps/api/accounts/views.py`
- Modify: `apps/api/config/urls.py`
- Modify: `apps/api/config/settings.py:108-119`
- Test: `apps/api/tests/test_otp_endpoints.py`

**Interfaces:**
- Consumes: everything from Tasks 2 and 4.
- Produces:
  - `POST /api/auth/otp/request/` → `{challenge_id, channel, destination_masked, expires_in}`
  - `POST /api/auth/otp/verify/` → login session + user body, or `{reset_ticket}`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_otp_endpoints.py`:

```python
import pytest
from rest_framework.test import APIClient

from accounts import otp
from accounts.models import OtpChallenge, User
from core.crypto import encrypt_value


@pytest.fixture
def member(db):
    return User.objects.create_user(
        username="member",
        password="StrongPass123!",
        email="member@drona.test",
        whatsapp_phone="919811111111",
    )


def request_code(client, identifier, purpose="LOGIN"):
    return client.post(
        "/api/auth/otp/request/",
        {"identifier": identifier, "purpose": purpose},
        format="json",
    )


@pytest.mark.django_db
def test_login_with_an_emailed_code(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    client = APIClient()
    response = request_code(client, "member@drona.test")
    assert response.status_code == 200
    assert response.data["channel"] == "EMAIL"
    assert response.data["destination_masked"] == "m***@drona.test"

    challenge = OtpChallenge.objects.get(user=member)
    code = _code_for(challenge)
    verify = client.post(
        "/api/auth/otp/verify/",
        {"challenge_id": response.data["challenge_id"], "code": code},
        format="json",
    )
    assert verify.status_code == 200
    assert verify.data["username"] == "member"
    assert client.get("/api/auth/me/").status_code == 200


def _code_for(challenge):
    """Brute-force the six-digit space; only test code may do this."""
    for candidate in range(1_000_000):
        value = f"{candidate:06d}"
        if otp.hash_code(challenge.id, value) == challenge.code_hash:
            return value
    raise AssertionError("code not found")


@pytest.mark.django_db
def test_unknown_identifier_is_indistinguishable(settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    client = APIClient()
    response = request_code(client, "nobody@drona.test")
    assert response.status_code == 200
    assert set(response.data) == {"challenge_id", "channel", "destination_masked", "expires_in"}
    assert OtpChallenge.objects.count() == 0
    verify = client.post(
        "/api/auth/otp/verify/",
        {"challenge_id": response.data["challenge_id"], "code": "123456"},
        format="json",
    )
    assert verify.status_code == 400
    assert verify.data["detail"] == "Invalid or expired code"


@pytest.mark.django_db
def test_mfa_user_must_supply_the_authenticator_code(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    from accounts.mfa import generate_secret

    secret = generate_secret()
    member.mfa_secret_encrypted = encrypt_value(secret)
    member.mfa_enabled = True
    member.save(update_fields=["mfa_secret_encrypted", "mfa_enabled"])

    client = APIClient()
    requested = request_code(client, "member@drona.test")
    challenge = OtpChallenge.objects.get(user=member)
    code = _code_for(challenge)

    refused = client.post(
        "/api/auth/otp/verify/",
        {"challenge_id": requested.data["challenge_id"], "code": code},
        format="json",
    )
    assert refused.status_code == 400
    assert refused.data["mfa_required"] is True
    challenge.refresh_from_db()
    assert challenge.consumed_at is None
    assert challenge.attempts == 1

    from accounts.mfa import _code as totp

    import time

    accepted = client.post(
        "/api/auth/otp/verify/",
        {
            "challenge_id": requested.data["challenge_id"],
            "code": code,
            "otp": totp(secret, int(time.time()) // 30),
        },
        format="json",
    )
    assert accepted.status_code == 200
    challenge.refresh_from_db()
    assert challenge.consumed_at is not None


@pytest.mark.django_db
def test_resend_cooldown_returns_429(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    client = APIClient()
    assert request_code(client, "member@drona.test").status_code == 200
    assert request_code(client, "member@drona.test").status_code == 429
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_otp_endpoints.py -v`
Expected: FAIL — 404 on `/api/auth/otp/request/`.

- [ ] **Step 3: Add the serializers**

Append to `apps/api/accounts/serializers.py`:

```python
class OtpRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=180)
    purpose = serializers.ChoiceField(choices=["LOGIN", "PASSWORD_RESET"])


class OtpVerifySerializer(serializers.Serializer):
    challenge_id = serializers.CharField(max_length=64)
    # `code` is the six digits delivered over WhatsApp or email. `otp` is the
    # TOTP authenticator code, named to match LoginSerializer. Both may appear.
    code = serializers.CharField(min_length=6, max_length=6)
    purpose = serializers.ChoiceField(choices=["LOGIN", "PASSWORD_RESET"], default="LOGIN")
    otp = serializers.CharField(required=False, allow_blank=True, write_only=True)
```

- [ ] **Step 4: Add the views**

In `apps/api/accounts/views.py`, add imports:

```python
import uuid

from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

from . import otp as otp_service
from .models import OtpChallenge
from .serializers import OtpRequestSerializer, OtpVerifySerializer
```

Then append:

```python
class OtpRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "otp_request"

    @extend_schema(request=OtpRequestSerializer, responses=dict)
    def post(self, request):
        serializer = OtpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"].strip()
        purpose = serializer.validated_data["purpose"]
        user, channel = otp_service.resolve_identifier(identifier)
        expires_in = int(otp_service.CODE_TTL.total_seconds())
        if user is None or (channel == OtpChallenge.Channel.EMAIL and not user.email):
            # Answer unknown identifiers with the same shape so the endpoint
            # cannot be used to discover which accounts exist.
            return Response({
                "challenge_id": str(uuid.uuid4()),
                "channel": channel,
                "destination_masked": otp_service.mask_destination(identifier),
                "expires_in": expires_in,
            })
        try:
            challenge, code = otp_service.issue_challenge(
                user, purpose=purpose, channel=channel, request=request
            )
        except otp_service.OtpRateLimited:
            return Response({"detail": "Too many code requests. Try again shortly."}, status=429)
        otp_service.send_challenge(challenge, code)
        record_audit(actor=request.user, action="OTP_ISSUED", instance=challenge,
                     after={"purpose": purpose, "channel": channel})
        return Response({
            "challenge_id": str(challenge.id),
            "channel": challenge.channel,
            "destination_masked": challenge.destination_masked,
            "expires_in": expires_in,
        })


class OtpVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "otp_verify"

    @extend_schema(request=OtpVerifySerializer, responses=dict)
    def post(self, request):
        serializer = OtpVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purpose = serializer.validated_data["purpose"]
        try:
            challenge = otp_service.verify_challenge(
                serializer.validated_data["challenge_id"],
                serializer.validated_data["code"],
                purpose=purpose,
            )
        except otp_service.OtpInvalid:
            return Response({"detail": "Invalid or expired code"}, status=400)

        user = challenge.user
        if purpose == OtpChallenge.Purpose.PASSWORD_RESET:
            otp_service.consume(challenge)
            record_audit(actor=None, action="OTP_VERIFIED", instance=challenge)
            ticket = TimestampSigner().sign_object(
                {"user": user.pk, "challenge": str(challenge.id)}
            )
            return Response({"reset_ticket": ticket})

        if user.mfa_enabled and not verify_code(
            decrypt_value(user.mfa_secret_encrypted), serializer.validated_data.get("otp", "")
        ):
            # Keep the challenge alive so the user can retry with their
            # authenticator, but count the try so it cannot be ground down.
            otp_service.register_failed_attempt(challenge)
            return Response(
                {"detail": "A valid authenticator code is required", "mfa_required": True},
                status=400,
            )
        otp_service.consume(challenge)
        login(request, user)
        record_audit(actor=user, action="OTP_LOGIN", instance=challenge)
        return Response(UserSerializer(user).data)
```

Add `from audit.models import record_audit` to the imports at the top of the file.

- [ ] **Step 5: Register the routes and throttles**

In `apps/api/config/urls.py`, import `OtpRequestView, OtpVerifyView` from `accounts.views` and add:

```python
    path("api/auth/otp/request/", OtpRequestView.as_view()),
    path("api/auth/otp/verify/", OtpVerifyView.as_view()),
```

In `apps/api/config/settings.py`, add to `DEFAULT_THROTTLE_RATES`:

```python
        "otp_request": os.getenv("OTP_REQUEST_THROTTLE_RATE", "5/hour"),
        "otp_verify": os.getenv("OTP_VERIFY_THROTTLE_RATE", "20/hour"),
```

- [ ] **Step 6: Run the tests**

Run: `cd apps/api && pytest tests/test_otp_endpoints.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add apps/api/accounts apps/api/config apps/api/tests/test_otp_endpoints.py
git commit -m "Add OTP request and verify endpoints with MFA and throttling"
```

---

### Task 6: Password recovery by code

Replaces the emailed magic link.

**Files:**
- Modify: `apps/api/accounts/views.py` (delete `PasswordResetRequestView`, rewrite `PasswordResetConfirmView`)
- Modify: `apps/api/accounts/serializers.py` (delete `PasswordResetRequestSerializer`, rewrite `PasswordResetConfirmSerializer`)
- Modify: `apps/api/config/urls.py` (drop `/api/auth/password/reset/`)
- Test: `apps/api/tests/test_otp_password_reset.py`

**Interfaces:**
- Consumes: `OtpVerifyView` reset ticket (Task 5), `RESET_TICKET_MAX_AGE` (Task 2).
- Produces: `POST /api/auth/password/reset/confirm/` accepting `{reset_ticket, new_password}`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_otp_password_reset.py`:

```python
import pytest
from django.core.signing import TimestampSigner
from rest_framework.test import APIClient

from accounts import otp
from accounts.models import OtpChallenge, User
from tests.test_otp_endpoints import _code_for


@pytest.fixture
def member(db):
    return User.objects.create_user(
        username="member", password="StrongPass123!", email="member@drona.test"
    )


@pytest.mark.django_db
def test_password_is_reset_with_a_delivered_code(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    client = APIClient()
    requested = client.post(
        "/api/auth/otp/request/",
        {"identifier": "member@drona.test", "purpose": "PASSWORD_RESET"},
        format="json",
    )
    challenge = OtpChallenge.objects.get(user=member)
    verified = client.post(
        "/api/auth/otp/verify/",
        {
            "challenge_id": requested.data["challenge_id"],
            "code": _code_for(challenge),
            "purpose": "PASSWORD_RESET",
        },
        format="json",
    )
    assert verified.status_code == 200

    confirmed = client.post(
        "/api/auth/password/reset/confirm/",
        {"reset_ticket": verified.data["reset_ticket"], "new_password": "BrandNewPass456!"},
        format="json",
    )
    assert confirmed.status_code == 200
    member.refresh_from_db()
    assert member.check_password("BrandNewPass456!")


@pytest.mark.django_db
def test_forged_ticket_is_rejected(member):
    client = APIClient()
    forged = TimestampSigner().sign_object({"user": member.pk, "challenge": "not-a-challenge"})
    response = client.post(
        "/api/auth/password/reset/confirm/",
        {"reset_ticket": forged, "new_password": "BrandNewPass456!"},
        format="json",
    )
    assert response.status_code == 400
    member.refresh_from_db()
    assert member.check_password("StrongPass123!")


@pytest.mark.django_db
def test_ticket_for_an_unconsumed_challenge_is_rejected(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    challenge, _ = otp.issue_challenge(
        member,
        purpose=OtpChallenge.Purpose.PASSWORD_RESET,
        channel=OtpChallenge.Channel.EMAIL,
    )
    ticket = TimestampSigner().sign_object({"user": member.pk, "challenge": str(challenge.id)})
    response = APIClient().post(
        "/api/auth/password/reset/confirm/",
        {"reset_ticket": ticket, "new_password": "BrandNewPass456!"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_expired_ticket_is_rejected(member, settings, monkeypatch):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    challenge, _ = otp.issue_challenge(
        member,
        purpose=OtpChallenge.Purpose.PASSWORD_RESET,
        channel=OtpChallenge.Channel.EMAIL,
    )
    otp.consume(challenge)
    ticket = TimestampSigner().sign_object({"user": member.pk, "challenge": str(challenge.id)})
    monkeypatch.setattr("accounts.otp.RESET_TICKET_MAX_AGE", -1)
    response = APIClient().post(
        "/api/auth/password/reset/confirm/",
        {"reset_ticket": ticket, "new_password": "BrandNewPass456!"},
        format="json",
    )
    assert response.status_code == 400
    member.refresh_from_db()
    assert member.check_password("StrongPass123!")


@pytest.mark.django_db
def test_the_magic_link_endpoint_is_gone():
    response = APIClient().post(
        "/api/auth/password/reset/", {"email": "member@drona.test"}, format="json"
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_otp_password_reset.py -v`
Expected: FAIL — the confirm view still expects `uid`/`token`, and `/api/auth/password/reset/` still returns 200.

- [ ] **Step 3: Replace the confirm serializer**

In `apps/api/accounts/serializers.py`, delete `PasswordResetRequestSerializer` and replace `PasswordResetConfirmSerializer` with:

```python
class PasswordResetConfirmSerializer(serializers.Serializer):
    reset_ticket = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=12)
```

- [ ] **Step 4: Replace the confirm view**

In `apps/api/accounts/views.py`, delete `PasswordResetRequestView` entirely and replace `PasswordResetConfirmView` with:

```python
class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "password_reset"

    @extend_schema(request=PasswordResetConfirmSerializer, responses=dict)
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = TimestampSigner().unsign_object(
                serializer.validated_data["reset_ticket"],
                max_age=otp_service.RESET_TICKET_MAX_AGE,
            )
        except (BadSignature, SignatureExpired):
            return Response({"detail": "Reset request is invalid or expired"}, status=400)
        try:
            # A non-UUID challenge id makes the filter raise rather than miss.
            challenge = (
                OtpChallenge.objects.filter(
                    pk=payload.get("challenge"),
                    user_id=payload.get("user"),
                    purpose=OtpChallenge.Purpose.PASSWORD_RESET,
                    consumed_at__isnull=False,
                )
                .select_related("user")
                .first()
            )
        except (ValidationError, ValueError, TypeError):
            challenge = None
        if challenge is None:
            return Response({"detail": "Reset request is invalid or expired"}, status=400)
        user = challenge.user
        password = serializer.validated_data["new_password"]
        password_validation.validate_password(password, user)
        user.set_password(password)
        user.save(update_fields=["password"])
        record_audit(actor=None, action="PASSWORD_RESET", instance=challenge)
        return Response({"status": "password_reset"})
```

Add `from django.core.exceptions import ValidationError` to the imports at the top of the file.

- [ ] **Step 5: Remove the dead imports and route**

In `apps/api/accounts/views.py`, delete the now-unused imports: `default_token_generator`, `force_bytes`, `force_str`, `urlsafe_base64_decode`, `urlsafe_base64_encode`, `settings`, and `PasswordResetRequestSerializer`.

In `apps/api/config/urls.py`, remove the `PasswordResetRequestView` import and the `path("api/auth/password/reset/", ...)` line.

- [ ] **Step 6: Run the tests and lint**

Run: `cd apps/api && pytest tests/test_otp_password_reset.py -v && ruff check .`
Expected: 4 passed, no lint findings (ruff `F401` catches any import left behind).

- [ ] **Step 7: Run the whole backend suite**

Run: `cd apps/api && pytest`
Expected: all pass. Any failure here is an existing test still calling the deleted reset endpoint — update it to the new flow.

- [ ] **Step 8: Commit**

```bash
git add apps/api/accounts apps/api/config apps/api/tests/test_otp_password_reset.py
git commit -m "Reset passwords with a delivered code instead of an emailed link"
```

---

### Task 7: Login page split and OTP flows

**Files:**
- Modify: `apps/web/app/login/page.tsx`
- Create: `apps/web/components/auth/PasswordSignIn.tsx`
- Create: `apps/web/components/auth/OtpCodeStep.tsx`
- Create: `apps/web/components/auth/OtpSignIn.tsx`
- Create: `apps/web/components/auth/ForgotPassword.tsx`

**Interfaces:**
- Consumes: `POST /api/auth/otp/request/`, `POST /api/auth/otp/verify/`, `POST /api/auth/password/reset/confirm/` (Tasks 5 and 6); `api<T>` from `@/lib/api`.
- Produces: `type OtpChallengeResponse = { challenge_id: string; channel: "EMAIL" | "WHATSAPP"; destination_masked: string; expires_in: number }` exported from `components/auth/OtpCodeStep.tsx`.

- [ ] **Step 1: Extract the password form unchanged**

Create `apps/web/components/auth/PasswordSignIn.tsx` holding exactly the current `submit` handler and the non-reset branch of the JSX from `app/login/page.tsx`. The accessible names `Username`, `Password` and `Sign in securely` must be byte-identical to today's, because `e2e/helpers.ts:loginAs` selects on them.

```tsx
"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

export function PasswordSignIn({ onForgot, onUseOtp }: { onForgot: () => void; onUseOtp: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await api<User>("/auth/login/", {
        method: "POST",
        body: JSON.stringify({ username, password, otp }),
      });
      queryClient.setQueryData(["me"], user);
      const requested = new URLSearchParams(window.location.search).get("next") ?? "/";
      const destination = requested.startsWith("/") && !requested.startsWith("//") ? requested : "/";
      router.replace(destination);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="login-form" onSubmit={submit}>
      <div className="login-form-kicker">Drona Logitech</div>
      <h2>Welcome back</h2>
      <p>Sign in to your transport operations workspace.</p>
      {error && <div className="notice error">{error}</div>}
      <div className="field">
        <label htmlFor="username">Username</label>
        <input id="username" className="input" value={username} autoComplete="username"
          onChange={(event) => setUsername(event.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="password">Password</label>
        <input id="password" type="password" className="input" value={password} autoComplete="current-password"
          onChange={(event) => setPassword(event.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="otp">Authenticator code (when enabled)</label>
        <input id="otp" inputMode="numeric" maxLength={6} className="input" value={otp}
          autoComplete="one-time-code" onChange={(event) => setOtp(event.target.value)} />
      </div>
      <button className="button primary" disabled={busy}>
        {busy ? "Signing in…" : "Sign in securely"}
      </button>
      <button type="button" className="button" onClick={onUseOtp}>
        Sign in with a code instead
      </button>
      <button type="button" className="button" onClick={onForgot}>
        Forgot password?
      </button>
      <p style={{ fontSize: 11, marginTop: 18 }}>Need an account? Contact your administrator.</p>
    </form>
  );
}
```

- [ ] **Step 2: Build the shared code step**

Create `apps/web/components/auth/OtpCodeStep.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";

export type OtpChallengeResponse = {
  challenge_id: string;
  channel: "EMAIL" | "WHATSAPP";
  destination_masked: string;
  expires_in: number;
};

export function OtpCodeStep({
  challenge,
  code,
  onCodeChange,
  onResend,
  busy,
}: {
  challenge: OtpChallengeResponse;
  code: string;
  onCodeChange: (value: string) => void;
  onResend: () => void;
  busy: boolean;
}) {
  const [seconds, setSeconds] = useState(60);

  useEffect(() => {
    setSeconds(60);
    const timer = setInterval(() => setSeconds((value) => (value > 0 ? value - 1 : 0)), 1000);
    return () => clearInterval(timer);
  }, [challenge.challenge_id]);

  return (
    <>
      <p>
        We sent a {Math.round(challenge.expires_in / 60)}-minute code
        {challenge.channel === "WHATSAPP" ? " on WhatsApp" : " by email"} to {challenge.destination_masked}.
      </p>
      <div className="field">
        <label htmlFor="otp-code">Verification code</label>
        <input
          id="otp-code"
          className="input"
          required
          inputMode="numeric"
          maxLength={6}
          autoComplete="one-time-code"
          value={code}
          onChange={(event) => onCodeChange(event.target.value.replace(/\D/g, ""))}
        />
      </div>
      <button type="button" className="button" disabled={busy || seconds > 0} onClick={onResend}>
        {seconds > 0 ? `Resend code in ${seconds}s` : "Resend code"}
      </button>
    </>
  );
}
```

- [ ] **Step 3: Build the OTP sign-in flow**

Create `apps/web/components/auth/OtpSignIn.tsx`:

```tsx
"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { OtpCodeStep, type OtpChallengeResponse } from "./OtpCodeStep";

export function OtpSignIn({ onBack }: { onBack: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [identifier, setIdentifier] = useState("");
  const [challenge, setChallenge] = useState<OtpChallengeResponse | null>(null);
  const [code, setCode] = useState("");
  const [authenticator, setAuthenticator] = useState("");
  const [mfaRequired, setMfaRequired] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const requestCode = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api<OtpChallengeResponse>("/auth/otp/request/", {
        method: "POST",
        body: JSON.stringify({ identifier, purpose: "LOGIN" }),
      });
      setChallenge(result);
      setCode("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send a code");
    } finally {
      setBusy(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!challenge) return requestCode();
    setBusy(true);
    setError("");
    try {
      const user = await api<User>("/auth/otp/verify/", {
        method: "POST",
        body: JSON.stringify({
          challenge_id: challenge.challenge_id,
          code,
          purpose: "LOGIN",
          otp: authenticator,
        }),
      });
      queryClient.setQueryData(["me"], user);
      const requested = new URLSearchParams(window.location.search).get("next") ?? "/";
      router.replace(requested.startsWith("/") && !requested.startsWith("//") ? requested : "/");
    } catch (reason) {
      const data = (reason as { data?: { mfa_required?: boolean } }).data;
      if (data?.mfa_required) setMfaRequired(true);
      setError(reason instanceof Error ? reason.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="login-form" onSubmit={submit}>
      <div className="login-form-kicker">Drona Logitech</div>
      <h2>Sign in with a code</h2>
      {error && <div className="notice error">{error}</div>}
      {challenge ? (
        <>
          <OtpCodeStep challenge={challenge} code={code} onCodeChange={setCode} onResend={requestCode} busy={busy} />
          {mfaRequired && (
            <div className="field">
              <label htmlFor="otp-authenticator">Authenticator code</label>
              <input id="otp-authenticator" className="input" inputMode="numeric" maxLength={6}
                value={authenticator} onChange={(event) => setAuthenticator(event.target.value)} />
            </div>
          )}
        </>
      ) : (
        <div className="field">
          <label htmlFor="otp-identifier">Email or WhatsApp number</label>
          <input id="otp-identifier" className="input" required value={identifier}
            autoComplete="username" onChange={(event) => setIdentifier(event.target.value)} />
        </div>
      )}
      <button className="button primary" disabled={busy}>
        {busy ? "Working…" : challenge ? "Verify and sign in" : "Send code"}
      </button>
      <button type="button" className="button" onClick={onBack}>
        Back to sign in
      </button>
    </form>
  );
}
```

- [ ] **Step 4: Build the forgot-password flow**

Create `apps/web/components/auth/ForgotPassword.tsx`:

```tsx
"use client";

import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
import { OtpCodeStep, type OtpChallengeResponse } from "./OtpCodeStep";

export function ForgotPassword({ onBack }: { onBack: () => void }) {
  const [identifier, setIdentifier] = useState("");
  const [challenge, setChallenge] = useState<OtpChallengeResponse | null>(null);
  const [code, setCode] = useState("");
  const [ticket, setTicket] = useState("");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const requestCode = async () => {
    setBusy(true);
    setError("");
    try {
      setChallenge(
        await api<OtpChallengeResponse>("/auth/otp/request/", {
          method: "POST",
          body: JSON.stringify({ identifier, purpose: "PASSWORD_RESET" }),
        }),
      );
      setCode("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send a code");
    } finally {
      setBusy(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (!challenge) {
        await requestCode();
      } else if (!ticket) {
        const result = await api<{ reset_ticket: string }>("/auth/otp/verify/", {
          method: "POST",
          body: JSON.stringify({
            challenge_id: challenge.challenge_id,
            code,
            purpose: "PASSWORD_RESET",
          }),
        });
        setTicket(result.reset_ticket);
      } else {
        await api("/auth/password/reset/confirm/", {
          method: "POST",
          body: JSON.stringify({ reset_ticket: ticket, new_password: password }),
        });
        setNotice("Password reset. You can now sign in.");
        setTicket("");
        setChallenge(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Password reset failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="login-form" onSubmit={submit}>
      <div className="login-form-kicker">Drona Logitech</div>
      <h2>Reset password</h2>
      {notice && <div className="notice">{notice}</div>}
      {error && <div className="notice error">{error}</div>}
      {!challenge && (
        <div className="field">
          <label htmlFor="reset-identifier">Email or WhatsApp number</label>
          <input id="reset-identifier" className="input" required value={identifier}
            onChange={(event) => setIdentifier(event.target.value)} />
        </div>
      )}
      {challenge && !ticket && (
        <OtpCodeStep challenge={challenge} code={code} onCodeChange={setCode} onResend={requestCode} busy={busy} />
      )}
      {ticket && (
        <div className="field">
          <label htmlFor="reset-password">New password</label>
          <input id="reset-password" type="password" className="input" required minLength={12}
            value={password} onChange={(event) => setPassword(event.target.value)} />
        </div>
      )}
      <button className="button primary" disabled={busy}>
        {busy ? "Working…" : !challenge ? "Send code" : !ticket ? "Verify code" : "Reset password"}
      </button>
      <button type="button" className="button" onClick={onBack}>
        Back to sign in
      </button>
    </form>
  );
}
```

- [ ] **Step 5: Reduce the page to mode selection**

Replace the body of `apps/web/app/login/page.tsx` so it keeps the `login-visual` section verbatim and renders one of the three forms. Delete the `reset_uid`/`reset_token` `useEffect` and every state variable now owned by a child.

```tsx
"use client";

import { useState } from "react";
import { BrandLogo } from "@/components/BrandLogo";
import { ForgotPassword } from "@/components/auth/ForgotPassword";
import { OtpSignIn } from "@/components/auth/OtpSignIn";
import { PasswordSignIn } from "@/components/auth/PasswordSignIn";

type Mode = "password" | "otp" | "forgot";

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>("password");

  return (
    <div className="login-page">
      <section className="login-visual">
        <div className="login-brand">
          <BrandLogo priority />
          <span>Transport operations platform</span>
        </div>
        <div>
          <div className="eyebrow login-eyebrow">Operations command</div>
          <h1>Every trip, approval and payment—traceable.</h1>
          <p>
            Coordinate deployments, approve transporter advances, allocate payments trip by trip, and keep the complete
            audit trail in one controlled workspace.
          </p>
        </div>
        <small className="login-footnote">Secure role-based access · INR financial controls · Asia/Kolkata</small>
      </section>
      <section className="login-form-wrap">
        {mode === "password" && (
          <PasswordSignIn onForgot={() => setMode("forgot")} onUseOtp={() => setMode("otp")} />
        )}
        {mode === "otp" && <OtpSignIn onBack={() => setMode("password")} />}
        {mode === "forgot" && <ForgotPassword onBack={() => setMode("password")} />}
      </section>
    </div>
  );
}
```

- [ ] **Step 6: Verify types, lint and the existing e2e login helper**

Run: `cd apps/web && npm run lint && npm run typecheck`
Expected: clean.

Run: `cd apps/web && npm run test:e2e -- e2e/smoke.spec.ts`
Expected: passes — this proves `loginAs` still finds `Username`, `Password` and `Sign in securely` after the split.

- [ ] **Step 7: Commit**

```bash
git add apps/web/app/login apps/web/components/auth
git commit -m "Split the login page and add OTP sign-in and code-based recovery"
```

---

### Task 8: Integrations settings, e2e coverage and schema

**Files:**
- Modify: `apps/web/app/integrations/page.tsx:75-81`
- Create: `apps/web/e2e/otp-login.spec.ts`
- Modify: `apps/api/schema.yml` (regenerated)
- Modify: `docs/api.md`

**Interfaces:**
- Consumes: the connect-endpoint keys from Task 4 and the UI from Task 7.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Add the two template fields**

In `apps/web/app/integrations/page.tsx`, extend the `whatsAppTemplates` state — the form already renders one labelled input per entry, so no JSX change is needed:

```tsx
    login_otp_template_name: "vms_login",
    password_recovery_template_name: "password_recovery",
```

And add the matching languages to the `connectWhatsApp` body:

```tsx
          login_otp_template_language: whatsAppLanguage,
          password_recovery_template_language: whatsAppLanguage,
```

- [ ] **Step 2: Write the e2e spec**

Create `apps/web/e2e/otp-login.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

const challenge = {
  challenge_id: "11111111-1111-4111-8111-111111111111",
  channel: "WHATSAPP",
  destination_masked: "+91 98****1111",
  expires_in: 300,
};

test("otp sign-in walks from identifier to code to authenticator", async ({ page }) => {
  await page.context().clearCookies();
  await page.route("**/api/auth/otp/request/", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(challenge) }),
  );
  await page.route("**/api/auth/otp/verify/", (route) =>
    route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({ detail: "A valid authenticator code is required", mfa_required: true }),
    }),
  );

  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in with a code instead" }).click();
  await page.getByLabel("Email or WhatsApp number").fill("919811111111");
  await page.getByRole("button", { name: "Send code" }).click();

  await expect(page.getByText("+91 98****1111")).toBeVisible();
  await expect(page.getByRole("button", { name: /Resend code in \d+s/ })).toBeDisabled();

  await page.getByLabel("Verification code").fill("123456");
  await page.getByRole("button", { name: "Verify and sign in" }).click();
  await expect(page.getByLabel("Authenticator code")).toBeVisible();
});

test("forgot password asks for an identifier then a code", async ({ page }) => {
  await page.context().clearCookies();
  await page.route("**/api/auth/otp/request/", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(challenge) }),
  );

  await page.goto("/login");
  await page.getByRole("button", { name: "Forgot password?" }).click();
  await page.getByLabel("Email or WhatsApp number").fill("member@drona.test");
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByLabel("Verification code")).toBeVisible();
});
```

- [ ] **Step 3: Regenerate the OpenAPI schema**

Run: `cd apps/api && python manage.py spectacular --file schema.yml --validate --fail-on-warn`
Expected: exit 0, and `schema.yml` now contains `/api/auth/otp/request/` and `/api/auth/otp/verify/` and no longer contains `/api/auth/password/reset/` without the `confirm` suffix.

- [ ] **Step 4: Document the endpoints**

In `docs/api.md`, add the two OTP endpoints beside the existing auth routes and correct the password-reset entry to the `{reset_ticket, new_password}` body. Note that `/api/auth/password/reset/` was removed.

- [ ] **Step 5: Run everything**

```bash
cd apps/api && pytest && ruff check .
cd ../web && npm run lint && npm run typecheck && npm run test:e2e
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add apps/web apps/api/schema.yml docs/api.md
git commit -m "Expose OTP template settings, e2e coverage and API schema"
```

---

## Verification

After Task 8, confirm against a real WhatsApp connection before calling this done:

1. Connect WhatsApp in Integrations with `login_otp_template_name = vms_login`.
2. Request a login code for an account whose `whatsapp_phone` is a test number; confirm the message arrives rendering `OTP Code: NNNNNN. This is your OTP code for Drona Logitech VMS.`
3. Request a password recovery code. If Meta rejects it with a template-component error, set `password_reset_button_type` to `copy_code` on the connection and retry — this is the case the spec anticipated. Record the working value in `.env.example`.
4. In Integrations, open the outbox and confirm neither OTP row displays a code.
