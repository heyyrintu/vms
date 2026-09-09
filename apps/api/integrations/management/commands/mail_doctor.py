"""Answer "why did that email not arrive?" from inside the running container.

Checks the four places an outbound email can silently stop: configuration, the
recipient lookup, the SMTP relay itself, and the outbox. Run it where the app
actually runs -- the answer is usually different from a developer laptop.
"""

import os
import smtplib
import ssl
import traceback

from django.conf import settings
from django.core.management.base import BaseCommand

OK = "PASS"
BAD = "FAIL"


class Command(BaseCommand):
    help = "Diagnose why outbound email (including OTP) is not arriving"

    def add_arguments(self, parser):
        parser.add_argument(
            "identifier",
            nargs="?",
            help="Email address to test the OTP recipient lookup against",
        )
        parser.add_argument(
            "--send",
            action="store_true",
            help="Actually issue and send a login OTP to that identifier",
        )

    def line(self, status, label, detail=""):
        style = self.style.SUCCESS if status == OK else self.style.ERROR
        self.stdout.write(f"{style(status):8} {label}" + (f"  {detail}" if detail else ""))

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("\n1. Configuration"))
        mode = settings.INTEGRATION_DELIVERY_MODE
        self.line(
            OK if mode == "sync" else BAD,
            f"INTEGRATION_DELIVERY_MODE = {mode}",
            "" if mode == "sync" else "async needs a live Celery worker",
        )
        provider = os.getenv("EMAIL_PROVIDER", "")
        self.line(
            OK if provider == "smtp" else BAD,
            f"EMAIL_PROVIDER = {provider or '(unset)'}",
            "" if provider == "smtp" else "'fake' or unset means nothing is really sent",
        )
        host = os.getenv("SMTP_HOST", "")
        port = os.getenv("SMTP_PORT", "587")
        self.stdout.write(f"         relay: {host}:{port}  from={os.getenv('SMTP_FROM_EMAIL', '')}")
        from_name = os.getenv("SMTP_FROM_NAME", "")
        if from_name and ("@" in from_name or any(c.isdigit() for c in from_name[-6:])):
            self.line(BAD, f"SMTP_FROM_NAME = {from_name!r}", "looks like an address, not a name")

        self.stdout.write(self.style.MIGRATE_HEADING("\n2. SMTP relay reachability"))
        if not host:
            self.line(BAD, "SMTP_HOST is empty", "nothing to connect to")
        else:
            try:
                use_ssl = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
                client_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
                kwargs = {"host": host, "port": int(port), "timeout": 15}
                if use_ssl:
                    kwargs["context"] = ssl.create_default_context()
                with client_class(**kwargs) as client:
                    client.ehlo()
                    if not use_ssl and os.getenv("SMTP_USE_TLS", "true").lower() == "true":
                        client.starttls(context=ssl.create_default_context())
                        client.ehlo()
                    username = os.getenv("SMTP_USERNAME", "")
                    if username:
                        client.login(username, os.getenv("SMTP_PASSWORD", ""))
                        self.line(OK, "connect + STARTTLS + login")
                    else:
                        self.line(OK, "connect + STARTTLS (no auth configured)")
            except Exception as exc:
                self.line(BAD, f"{type(exc).__name__}: {str(exc)[:160]}")
                self.stdout.write(
                    "         A timeout here usually means the host blocks outbound "
                    "SMTP ports. Try port 2525, or ask the provider to unblock 587."
                )

        identifier = options["identifier"]
        if identifier:
            self.stdout.write(self.style.MIGRATE_HEADING("\n3. Recipient lookup"))
            from accounts import otp as otp_service

            user, channel = otp_service.resolve_identifier(identifier)
            if user is None:
                self.line(BAD, f"no active user matches {identifier}",
                          "the API returns a FAKE success for this and sends nothing")
            elif channel == "EMAIL" and not user.email:
                self.line(BAD, f"{user.username} has no email address")
            else:
                self.line(OK, f"{identifier} -> {user.username} via {channel}")

        self.stdout.write(self.style.MIGRATE_HEADING("\n4. Recent outbound email"))
        from integrations.models import IntegrationMessage

        rows = IntegrationMessage.objects.filter(channel="EMAIL").order_by("-created_at")[:10]
        if not rows:
            self.stdout.write("         no EMAIL messages have ever been queued here")
        for row in rows:
            status = OK if row.status in {"SENT", "DELIVERED"} else BAD
            self.line(
                status,
                f"{row.created_at:%m-%d %H:%M} {row.event_key or '-':20} {row.status:9} "
                f"-> {row.recipient[:32]}",
                (row.last_error or "")[:120],
            )

        if options["send"] and identifier:
            self.stdout.write(self.style.MIGRATE_HEADING("\n5. Live OTP send"))
            from accounts import otp as otp_service
            from accounts.models import OtpChallenge

            user, channel = otp_service.resolve_identifier(identifier)
            if user is None:
                self.line(BAD, "cannot send: no such user")
                return
            try:
                challenge, code = otp_service.issue_challenge(
                    user, purpose=OtpChallenge.Purpose.LOGIN, channel=channel
                )
                message = otp_service.send_challenge(challenge, code)
                message.refresh_from_db()
                self.line(
                    OK if message.status in {"SENT", "DELIVERED"} else BAD,
                    f"status={message.status} to={message.recipient}",
                    (message.last_error or "")[:200],
                )
            except Exception:
                self.line(BAD, "send raised")
                self.stdout.write(traceback.format_exc()[-1200:])
