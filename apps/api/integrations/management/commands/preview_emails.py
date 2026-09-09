from pathlib import Path

from django.core.management.base import BaseCommand

from integrations.email_builder import render_email_html

# One sample per outbound email this system actually sends, using the exact
# bodies produced by integrations.services, approvals, payments and accounts.otp.
SAMPLES = [
    {
        "slug": "login-otp",
        "event_key": "LOGIN_OTP",
        "object_type": "account",
        "subject": "Your Drona Logitech sign-in code",
        "body": (
            "OTP Code: 481902. This is your OTP code for Drona Logitech VMS. "
            "For your security, do not share this code. It expires in 5 minutes."
        ),
    },
    {
        "slug": "password-reset-otp",
        "event_key": "PASSWORD_RESET_OTP",
        "object_type": "account",
        "subject": "Your Drona Logitech password recovery code",
        "body": (
            "702514 is your password recovery code. For your security, do not share "
            "this code. It expires in 5 minutes."
        ),
    },
    {
        "slug": "approval-requested",
        "event_key": "APPROVAL_REQUESTED",
        "object_type": "approvals.paymentapprovalbatch",
        "subject": "Approval requested",
        "body": (
            "Approval PA-2026-000418 is waiting for your decision. Net payable: 2,47,500.00. "
            "Review securely: https://vms.dronalogitech.com/approvals/418"
        ),
    },
    {
        "slug": "finance-ready",
        "event_key": "FINANCE_READY",
        "object_type": "approvals.paymentapprovalbatch",
        "subject": "Payment ready",
        "body": (
            "Approved payable PA-2026-000418 is ready for finance. "
            "Payout: 2 vendors, 3 trips, net 2,47,500.00.\n"
            "Payout 1 of 2 - Sethi Carriers:\n"
            "Vendor code: VEN-0042\n"
            "Legal name: Sethi Carriers Pvt Ltd\n"
            "PAN / GSTIN: AACCS1429J\n"
            "Payment terms: Net 7\n"
            "Gross approved: 1,25,000.00\n"
            "TDS deducted: 1,250.00\n"
            "Net to transfer: 1,23,750.00\n"
            "Vendor KYC: PAN, Aadhaar\n"
            "Bank: HDFC Bank\n"
            "Account holder: Sethi Carriers Pvt Ltd\n"
            "Account number: •••• 4821\n"
            "IFSC: HDFC0001234\n"
            "Cancelled cheque: On file\n"
            "TRIP-2026-0091 | Bhiwandi → Hyderabad | MH04GT4417 | Docs: POD, LR | "
            "Gross 1,25,000.00 | TDS 1,250.00 | Net 1,23,750.00\n"
            "Payout 2 of 2 - Ravi Logistics:\n"
            "Vendor code: VEN-0117\n"
            "PAN / GSTIN: AAGCR8821K\n"
            "Gross approved: 1,25,000.00\n"
            "TDS deducted: 1,250.00\n"
            "Net to transfer: 1,23,750.00\n"
            "Vendor KYC: Not uploaded\n"
            "Bank: ICICI Bank\n"
            "Account holder: Ravi Logistics\n"
            "Account number: •••• 9037\n"
            "IFSC: ICIC0004412\n"
            "Cancelled cheque: Not uploaded\n"
            "TRIP-2026-0104 | Bhiwandi → Chennai | MH04GT9910 | Docs: none uploaded | "
            "Gross 62,500.00 | TDS 625.00 | Net 61,875.00\n"
            "TRIP-2026-0108 | Bhiwandi → Coimbatore | MH04GT2288 | Docs: POD | "
            "Gross 62,500.00 | TDS 625.00 | Net 61,875.00\n"
            "Missing trip evidence: LR, POD, Vendor invoice.\n"
            "Attached: 4 files\n"
            "Attached documents: Cancelled cheque, POD, LR, PAN\n"
            "One document exceeds the email attachment limit and can be opened from "
            "the finance queue: Vendor invoice (TRIP-2026-0091).\n"
            "The attached files are the evidence listed above; the finance queue "
            "holds the same documents and records the transfer.\n"
            "Open securely: https://vms.dronalogitech.com/finance?approval=418"
        ),
    },
    {
        "slug": "approval-completed-vendor",
        "event_key": "APPROVAL_COMPLETED",
        "object_type": "approval",
        "subject": "[PA-2026-000418] Drona Logitech payment approval",
        "body": (
            "Approval PA-2026-000418 accepted for processing.\n"
            "TRIP-2026-0091 | Bhiwandi -> Hyderabad | Gross 125000.00 | TDS 1250.00 | Net 123750.00\n"
            "TRIP-2026-0104 | Bhiwandi -> Chennai | Gross 125000.00 | TDS 1250.00 | Net 123750.00"
        ),
    },
    {
        "slug": "payment-completed-vendor",
        "event_key": "PAYMENT_COMPLETED",
        "object_type": "payment",
        "subject": "[PAY-2026-000212] Drona Logitech payment confirmation",
        "body": (
            "Payment PAY-2026-000212 processed on 2026-09-08.\n"
            "TRIP-2026-0091 | Bhiwandi -> Hyderabad | Gross 125000.00 | TDS 1250.00 | Net 123750.00\n"
            "UTR: HDFCN52026090812345"
        ),
    },
    {
        "slug": "approval-rejected",
        "event_key": "APPROVAL_REJECTED",
        "object_type": "approvals.paymentapprovalbatch",
        "subject": "Approval rejected",
        "body": (
            "Approval PA-2026-000418 has been rejected by finance.head. "
            "Review securely: https://vms.dronalogitech.com/approvals/418"
        ),
    },
    {
        "slug": "settlement-pending",
        "event_key": "SETTLEMENT_PENDING",
        "object_type": "trip",
        "subject": "Settlement pending",
        "body": (
            "Trip TRIP-2026-0091 is ready for final settlement. "
            "Review securely: https://vms.dronalogitech.com/trips/91"
        ),
    },
]


class Command(BaseCommand):
    help = "Render every outbound email template to HTML files for visual review"

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            default="tmp/email-preview",
            help="Directory to write the rendered previews into",
        )

    def handle(self, *args, **options):
        out = Path(options["out"])
        out.mkdir(parents=True, exist_ok=True)
        links = []
        for sample in SAMPLES:
            html = render_email_html(
                subject=sample["subject"],
                body=sample["body"],
                event_key=sample["event_key"],
                object_type=sample["object_type"],
            )
            path = out / f"{sample['slug']}.html"
            path.write_text(html, encoding="utf-8")
            links.append((sample["slug"], sample["subject"]))
            self.stdout.write(f"  {path}")

        index = "".join(
            f'<li><a href="{slug}.html">{slug}</a> &mdash; <code>{subject}</code></li>'
            for slug, subject in links
        )
        (out / "index.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>VMS email previews</title>"
            "<body style=\"font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;\">"
            f"<h1>VMS email previews</h1><ul>{index}</ul></body>",
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(f"Rendered {len(links)} previews to {out}"))
