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
