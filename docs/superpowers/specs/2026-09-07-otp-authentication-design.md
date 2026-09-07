# WhatsApp and Email OTP Authentication Design

Date: 2026-09-07
Status: approved in conversation, awaiting implementation

## Problem

Sign-in is username plus password, optionally hardened by a TOTP authenticator (`accounts.LoginView`). Users who forget a password receive an emailed magic link carrying `reset_uid` and `reset_token` (`accounts.PasswordResetRequestView`), which the login page consumes from the query string. Two gaps follow. Operations and transporter staff work from phones and do not reliably keep a password; and the reset link is email-only even though `User.whatsapp_phone` and a working `WhatsAppProvider` already exist.

Two approved Meta templates are available:

- `vms_login` (id `1738923667316316`) — `OTP Code: {{1}}. This is your OTP code for {{2}}. For your security, do not share this code.`
- `password_recovery` (id `1639963370986997`) — `{{1}} is your password recovery code. For your security, do not share this code.`

## Decisions

- OTP sign-in is an **alternative** to password sign-in, not a replacement. `LoginView` and the password form are unchanged.
- The user types an **email address or a WhatsApp number** as the identifier. Its shape selects the channel: an email goes to email, a number goes to WhatsApp. There is no channel picker.
- Because the identifier must resolve to exactly one account, `User.email` and `User.whatsapp_phone` become **unique**. Blank values are excluded from the constraints.
- **TOTP is still enforced.** A user with `mfa_enabled` must supply an authenticator code to complete an OTP login. OTP proves possession of a phone or mailbox; it does not stand in for the second factor.
- Forgot-password becomes a **six-digit code on both channels**. The emailed magic link is removed, not kept alongside.
- Delivered codes are **redacted from the message log**. `IntegrationMessageSerializer` excludes only `payload_encrypted`, so `subject` and `body_summary` are returned by `GET /api/messages/`; an unredacted body would let any user holding the `*` capability read a live code and sign in as its owner.
- Challenge state lives in a **table**, not a signed token. Single-use, attempt counting and revocation are the controls that make a six-digit secret safe, and none of them work statelessly.

## Data model (app `accounts`)

`OtpChallenge`, primary key `id = UUIDField(primary_key=True, default=uuid4, editable=False)`. The id is the opaque handle the browser holds between request and verify.

| Field | Definition |
|---|---|
| `user` | `ForeignKey(User, on_delete=PROTECT, related_name="otp_challenges")` |
| `purpose` | `LOGIN` or `PASSWORD_RESET` (`TextChoices`, max 20) |
| `channel` | `WHATSAPP` or `EMAIL` (`TextChoices`, max 20) |
| `code_hash` | `CharField(max_length=64)` — hex HMAC-SHA256 keyed by `SECRET_KEY` over `f"{id}:{code}"` |
| `destination_masked` | `CharField(max_length=120)` — `+91 87****0172`, `r***@dronalogitech.com` |
| `expires_at` | `DateTimeField(db_index=True)` |
| `attempts` | `PositiveSmallIntegerField(default=0)` |
| `consumed_at` | `DateTimeField(null=True, blank=True)` — set when the challenge stops being usable, whether it was redeemed or superseded by a newer one |
| `request_ip` | `GenericIPAddressField(null=True, blank=True)` |
| `created_at` | `DateTimeField(auto_now_add=True)` |

Index on `(user, purpose, -created_at)`.

Constants in `accounts/otp.py`: `CODE_TTL = timedelta(minutes=5)`, `MAX_ATTEMPTS = 5`, `RESEND_COOLDOWN = timedelta(seconds=60)`, `MAX_PER_HOUR = 5`, `RESET_TICKET_MAX_AGE = 600`.

Codes are `f"{secrets.randbelow(1_000_000):06d}"`. The plaintext code exists only in the outbound message payload and the HTTP request cycle; it is never written to `OtpChallenge`. Issuing a challenge marks every other live challenge for the same `(user, purpose)` consumed, so only the newest code works.

`User` gains two constraints in `Meta.constraints`:

- `UniqueConstraint(Lower("email"), condition=~Q(email=""), name="accounts_user_unique_email_ci")`
- `UniqueConstraint("whatsapp_phone", condition=~Q(whatsapp_phone=""), name="accounts_user_unique_whatsapp_phone")`

Both are partial, so any number of accounts may leave a field blank. Partial unique indexes are supported by SQLite 3.8+ and PostgreSQL, so development and production enforce identically. `User.clean()` already normalises `whatsapp_phone` to digits, so the constraint compares normalised values.

## Migrations

1. `accounts` — create `OtpChallenge`.
2. `accounts` — a `RunPython` guard that runs **before** the constraints are added. It groups active users by `Lower(email)` and by `whatsapp_phone`, ignoring blanks, and raises `RuntimeError` naming every colliding username and value if any group has more than one member. This turns a partially-applied migration into a refusal to start.
3. `accounts` — add the two `UniqueConstraint`s.

`python manage.py check_login_identifiers` runs the same grouping read-only and prints the conflicts, so the check can be run against production before the deploy rather than discovered by it. It exits non-zero when conflicts exist.

The seeded demo users in `core/management/commands/seed_demo.py` do not set `whatsapp_phone`, so no fixture change is needed; local databases where a number was entered by hand will surface in the pre-check.

## Delivery

`accounts/otp.py` exposes `issue_challenge(user, *, purpose, channel, request)` and `verify_challenge(challenge_id, code)`.

Sending reuses `integrations.services.queue_message` so codes inherit idempotency, retry, the outbox sweep and the audit trail. `queue_message` gains one optional keyword, `summary=None`, defaulting to today's `body[:1000]`; every existing caller is unaffected. OTP sends pass `summary="Sign-in code sent (code redacted)"` (or `"Password recovery code sent (code redacted)"`), keeping the code inside `payload_encrypted` only.

Call shape: `idempotency_key=f"otp:{challenge.id}"`, `object_type="account"`, `object_id=str(user.pk)`, `user=user`, `event_key` of `LOGIN_OTP` or `PASSWORD_RESET_OTP`, `recipient` of `user.email` or `user.whatsapp_phone`. Subjects never contain the code: `"Your Drona Logitech sign-in code"` and `"Your Drona Logitech password recovery code"`.

WhatsApp template settings resolve through the existing `_whatsapp_template_setting(configuration_key, environment_key, default)` helper:

| Purpose | Configuration key | Environment key | Default | `body_parameters` |
|---|---|---|---|---|
| `LOGIN` | `login_otp_template_name` | `WHATSAPP_LOGIN_OTP_TEMPLATE_NAME` | `vms_login` | `[code, OTP_APP_LABEL]` |
| `PASSWORD_RESET` | `password_recovery_template_name` | `WHATSAPP_PASSWORD_RECOVERY_TEMPLATE_NAME` | `password_recovery` | `[code]` |

`OTP_APP_LABEL` is a setting defaulting to `"Drona Logitech VMS"`, so `vms_login` renders `OTP Code: 123456. This is your OTP code for Drona Logitech VMS.` Matching `_template_language` keys default to `en`. `IntegrationConnectionViewSet.whatsapp_connect` adds all four keys to `template_defaults` under the existing `[a-z0-9_]{1,512}` validation. The matching inputs appear in `app/integrations/page.tsx`, whose form already renders one field per entry of its `whatsAppTemplates` state object, so adding the two keys is sufficient.

`WhatsAppProvider.send` gains an `otp_button_type` option, one of `none` (default), `copy_code` or `url`, appending respectively nothing, `{"type": "button", "sub_type": "copy_code", "index": "0", "parameters": [{"type": "coupon_code", "coupon_code": code}]}`, or the existing url-button component. `vms_login` takes two variables and is therefore a utility-category template that sends with `none`. `password_recovery` reads as Meta's authentication category, which rejects sends that omit the OTP button component; making the button a setting means a rejected first send is fixed by changing configuration rather than by shipping a corrected guess. The chosen value is stored in `IntegrationConnection.configuration` as `password_recovery_button_type`.

Email bodies are plain text carrying the code; the SMTP path needs no change.

## API

```
POST /api/auth/otp/request/            {identifier, purpose}
                                       -> {challenge_id, channel, destination_masked, expires_in}
POST /api/auth/otp/verify/             {challenge_id, code, otp?}
                                       -> LOGIN:          session cookie + UserSerializer
                                       -> PASSWORD_RESET: {reset_ticket}
POST /api/auth/password/reset/confirm/ {reset_ticket, new_password} -> {status}
```

`identifier` is trimmed; a value containing `@` is treated as an email and matched case-insensitively, otherwise it is normalised by `re.sub(r"[\s()+-]", "", value)` and matched against `whatsapp_phone`. Only `is_active` users match. `expires_in` is seconds.

Two different one-time codes meet on `otp/verify/` and must not be confused. `code` is the six digits delivered over WhatsApp or email by this feature. `otp` is the TOTP authenticator code, named to match the existing `LoginSerializer` field rather than renamed for local clarity; a request may need both.

**Enumeration.** `otp/request/` always returns `200` with the same body shape. An identifier that matches no active user yields a random UUID with no database row and a mask derived from the submitted text; `otp/verify/` then fails with the same `"Invalid or expired code"` as a wrong code. Response timing is not equalised — the design accepts that, since the account list is administrator-managed rather than self-service.

**Verify.** Rejects a challenge that is consumed, past `expires_at`, or already at `MAX_ATTEMPTS`. A wrong code increments `attempts` and returns 400. Comparison uses `hmac.compare_digest`. A correct code sets `consumed_at` inside the same `select_for_update` transaction that read it, so a code cannot be redeemed twice concurrently.

**MFA.** For `purpose=LOGIN`, once the code verifies, a user with `mfa_enabled` must also pass `otp` (the authenticator code) through `verify_code(decrypt_value(user.mfa_secret_encrypted), otp)`. Failure returns `{"detail": "A valid authenticator code is required", "mfa_required": true}` with status 400, mirroring `LoginView`, and does **not** consume the challenge — otherwise a user with MFA could never complete a login. It does increment `attempts`, so an authenticator code cannot be brute-forced against a challenge whose delivered code is already known; the challenge dies at `MAX_ATTEMPTS` and the user requests a new one. The challenge is consumed only on full success.

**Reset ticket.** `TimestampSigner().sign_object({"user": user.pk, "challenge": str(challenge.id)})`, checked with `max_age=RESET_TICKET_MAX_AGE` and rejected unless the named challenge is consumed, has `purpose=PASSWORD_RESET` and belongs to that user. `PasswordResetConfirmView` accepts `{reset_ticket, new_password}`, runs `password_validation.validate_password`, and drops the `uid`/`token` branch. `PasswordResetRequestView`, `PasswordResetRequestSerializer` and the `uid`/`token` fields of `PasswordResetConfirmSerializer` are deleted along with the `/api/auth/password/reset/` route.

**Throttling.** New `DEFAULT_THROTTLE_RATES` scopes `otp_request` at `5/hour` and `otp_verify` at `20/hour`, applied by `throttle_scope`. Because `AnonRateThrottle` keys on IP and would let a distributed caller flood one person's WhatsApp, `issue_challenge` additionally refuses when the user has a challenge newer than `RESEND_COOLDOWN` or more than `MAX_PER_HOUR` in the last hour, returning 429 with a generic message. The per-user check runs only for identifiers that resolved, so it cannot be used to probe for existing accounts.

**Audit.** `record_audit` fires on issue, successful verify, exhausted attempts and completed reset, with the `OtpChallenge` as `instance` and never the code in `before`/`after`.

## Frontend

`app/login/page.tsx` already carries sign-in, reset-request and reset-confirm in one component; two more flows would make it unworkable. It is split so the page owns only mode selection:

- `components/auth/PasswordSignIn.tsx` — today's username, password and authenticator fields, unchanged in behaviour.
- `components/auth/OtpSignIn.tsx` — identifier, then code, then the authenticator field when `mfa_required` comes back.
- `components/auth/ForgotPassword.tsx` — identifier, then code, then new password.
- `components/auth/OtpCodeStep.tsx` — the shared step: masked-destination line, six-digit `inputMode="numeric"` field with `autoComplete="one-time-code"`, a resend button disabled by a 60-second countdown, and the visible expiry.

The `reset_uid` / `reset_token` `useEffect` is removed with the magic link.

## Testing

`apps/api/tests/test_otp_auth.py`:

- Happy path across both channels and both purposes.
- Expired code, wrong code, attempt lockout at `MAX_ATTEMPTS`, single-use rejection of a replayed code.
- Unknown identifier returns the same body shape and the same verify failure as a wrong code.
- `mfa_enabled` login is refused without the authenticator code, the challenge survives that refusal, and succeeds with it.
- The queued `IntegrationMessage` has the code absent from `subject` and `body_summary` and present in the decrypted `payload_encrypted`.
- Resend cooldown and hourly cap return 429.
- Reset ticket is rejected when forged, when expired, and when its challenge was never consumed.
- Constraints: duplicate email differing only by case is rejected, duplicate phone is rejected, multiple blanks are allowed.
- `check_login_identifiers` exits non-zero and names both colliding usernames.

`apps/web/e2e/otp-login.spec.ts` intercepts `/api/auth/otp/*` and asserts the UI transitions: identifier to code step with the mask shown, resend disabled then enabled, wrong code surfacing an error, `mfa_required` revealing the authenticator field. No test-only endpoint exposes a live code; that would be an authentication bypass shipped in the codebase. Cryptographic and flow correctness is covered by the Django tests, which decrypt the payload directly.
