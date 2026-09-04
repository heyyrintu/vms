import os
import socket
from urllib.parse import urlparse

import boto3
import redis
from botocore.config import Config
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

PLACEHOLDERS = ("change-me", "changeme", "example", "replace-me", "unsafe")


class Command(BaseCommand):
    help = "Validate the production configuration and its private dependencies"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-connectivity",
            action="store_true",
            help="Validate configuration without contacting PostgreSQL, Redis, S3, or ClamAV",
        )

    def handle(self, *args, **options):
        errors: list[str] = []

        def require(name: str, *, secret: bool = False) -> str:
            value = os.getenv(name, "").strip()
            if not value:
                errors.append(f"{name} is required")
            elif secret and any(marker in value.lower() for marker in PLACEHOLDERS):
                errors.append(f"{name} still contains a placeholder value")
            return value

        if settings.DEBUG:
            errors.append("DJANGO_DEBUG must be false")
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
            errors.append("DATABASE_URL must use PostgreSQL")
        if "*" in settings.ALLOWED_HOSTS:
            errors.append("DJANGO_ALLOWED_HOSTS must not contain *")
        if not getattr(settings, "SECURE_SSL_REDIRECT", False):
            errors.append("SECURE_SSL_REDIRECT must be true")
        if getattr(settings, "SECURE_HSTS_SECONDS", 0) < 31_536_000:
            errors.append("SECURE_HSTS_SECONDS must be at least 31536000")

        web_origin = require("WEB_ORIGIN")
        parsed_origin = urlparse(web_origin)
        if parsed_origin.scheme != "https" or not parsed_origin.hostname:
            errors.append("WEB_ORIGIN must be one HTTPS origin")
        elif parsed_origin.hostname not in settings.ALLOWED_HOSTS:
            errors.append("WEB_ORIGIN host must be present in DJANGO_ALLOWED_HOSTS")
        if web_origin and web_origin not in settings.CSRF_TRUSTED_ORIGINS:
            errors.append("WEB_ORIGIN must be present in CSRF_TRUSTED_ORIGINS")

        require("DJANGO_SECRET_KEY", secret=True)
        field_key = require("FIELD_ENCRYPTION_KEY", secret=True)
        if field_key:
            try:
                Fernet(field_key.encode())
            except (TypeError, ValueError):
                errors.append("FIELD_ENCRYPTION_KEY must be a valid Fernet key")

        if os.getenv("USE_S3_STORAGE", "").lower() != "true":
            errors.append("USE_S3_STORAGE must be true")
        if settings.INTEGRATION_DELIVERY_MODE != "async":
            errors.append("INTEGRATION_DELIVERY_MODE must be async")
        if os.getenv("EMAIL_PROVIDER", "").lower() != "smtp":
            errors.append("EMAIL_PROVIDER must be smtp")
        if os.getenv("WHATSAPP_PROVIDER", "").lower() != "whatsapp":
            errors.append("WHATSAPP_PROVIDER must be whatsapp")

        require("REDIS_URL", secret=True)
        require("AWS_STORAGE_BUCKET_NAME")
        require("AWS_S3_ENDPOINT_URL")
        require("AWS_ACCESS_KEY_ID", secret=True)
        require("AWS_SECRET_ACCESS_KEY", secret=True)
        require("CLAMAV_HOST")
        require("SMTP_HOST")
        smtp_username = os.getenv("SMTP_USERNAME", "").strip()
        if smtp_username:
            require("SMTP_PASSWORD", secret=True)
        require("SMTP_FROM_EMAIL")
        if os.getenv("SMTP_USE_TLS", "true").lower() == "true" and os.getenv(
            "SMTP_USE_SSL", "false"
        ).lower() == "true":
            errors.append("SMTP_USE_TLS and SMTP_USE_SSL cannot both be true")
        require("EMAIL_WEBHOOK_TOKEN", secret=True)
        require("WHATSAPP_ACCESS_TOKEN", secret=True)
        require("WHATSAPP_PHONE_NUMBER_ID", secret=True)
        require("WHATSAPP_VERIFY_TOKEN", secret=True)
        require("WHATSAPP_APP_SECRET", secret=True)

        if errors:
            raise CommandError("Production configuration is invalid:\n- " + "\n- ".join(errors))

        if not options["skip_connectivity"]:
            self._check_dependencies()

        self.stdout.write(self.style.SUCCESS("Production configuration and dependencies are ready"))

    def _check_dependencies(self) -> None:
        failures: list[str] = []
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as exc:  # pragma: no cover - exercised by deployment
            failures.append(f"PostgreSQL: {exc}")

        try:
            redis.Redis.from_url(os.environ["REDIS_URL"], socket_timeout=5).ping()
        except Exception as exc:  # pragma: no cover - exercised by deployment
            failures.append(f"Redis: {exc}")

        try:
            boto3.client(
                "s3",
                endpoint_url=os.environ["AWS_S3_ENDPOINT_URL"],
                aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
                region_name=os.getenv("AWS_S3_REGION_NAME", "us-east-1"),
                config=Config(s3={"addressing_style": "path"}),
            ).head_bucket(Bucket=os.environ["AWS_STORAGE_BUCKET_NAME"])
        except Exception as exc:  # pragma: no cover - exercised by deployment
            failures.append(f"Object storage: {exc}")

        try:
            with socket.create_connection(
                (os.environ["CLAMAV_HOST"], int(os.getenv("CLAMAV_PORT", "3310"))),
                timeout=5,
            ) as scanner:
                scanner.sendall(b"zPING\0")
                if b"PONG" not in scanner.recv(32):
                    raise RuntimeError("unexpected PING response")
        except Exception as exc:  # pragma: no cover - exercised by deployment
            failures.append(f"ClamAV: {exc}")

        if failures:
            raise CommandError("Production dependencies are unavailable:\n- " + "\n- ".join(failures))
