import os

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "Create or update the production administrator from environment variables"

    def add_arguments(self, parser):
        parser.add_argument("--username", default=os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin"))
        parser.add_argument("--email", default=os.getenv("BOOTSTRAP_ADMIN_EMAIL", ""))
        parser.add_argument("--password-env", default="BOOTSTRAP_ADMIN_PASSWORD")

    def handle(self, *args, **options):
        password = os.getenv(options["password_env"], "")
        if len(password) < 12:
            raise CommandError(
                f"{options['password_env']} must contain a password of at least 12 characters"
            )
        user, created = User.objects.get_or_create(username=options["username"])
        user.email = options["email"] or user.email
        user.role = User.Role.ADMIN
        user.vendor = None
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.full_clean()
        user.save()
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} administrator {user.username}"))
