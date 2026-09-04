from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from approvals.models import ApprovalAction, PaymentApprovalBatch
from approvals.services import create_approval_batch, decide_batch, submit_batch
from core.models import OrganizationSettings
from operations.models import Client, Driver, Indent, Trip, TripCharge, Vehicle, Vendor
from payments.services import create_paid_payment


class Command(BaseCommand):
    help = "Create idempotent, entirely synthetic demonstration data"

    def handle(self, *args, **options):
        settings = OrganizationSettings.load()
        settings.name = "Drona Logitech Operations"
        settings.default_advance_percent = Decimal("90.00")
        settings.default_tds_rate = Decimal("1.00")
        settings.save()

        client, _ = Client.objects.get_or_create(code="NPL", defaults={"name": "NPL", "default_branch": "Sonipat"})
        vendors = []
        for code, name, email in (
            ("VND-001", "Northline Carriers", "payments@example.test"),
            ("VND-002", "Blueway Logistics", "accounts@example.test"),
            ("VND-003", "Highroad Transport", "ops@example.test"),
        ):
            vendor, _ = Vendor.objects.get_or_create(
                vendor_code=code,
                defaults={"legal_name": f"{name} Private Limited", "display_name": name, "email": email},
            )
            vendors.append(vendor)

        users = {}
        for username, role in (
            ("operations", User.Role.OPERATIONS),
            ("approver", User.Role.APPROVER),
            ("finance", User.Role.FINANCE),
            ("management", User.Role.MANAGEMENT),
            ("admin", User.Role.ADMIN),
        ):
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"role": role, "email": f"{username}@example.test", "first_name": role.title()},
            )
            if created:
                user.set_password("ChangeMe123!")
                user.is_staff = role == User.Role.ADMIN
                user.is_superuser = role == User.Role.ADMIN
                user.save()
            users[username] = user
        transporter, created = User.objects.get_or_create(
            username="transporter",
            defaults={"role": User.Role.TRANSPORTER, "vendor": vendors[0], "email": "transporter@example.test"},
        )
        if created:
            transporter.set_password("ChangeMe123!")
            transporter.save()

        today = timezone.localdate()
        trips = []
        routes = [
            ("Sonipat", "Ghaziabad", Decimal("50000"), Decimal("2500")),
            ("Sonipat", "Delhi", Decimal("42000"), Decimal("1800")),
            ("Sonipat", "Moradabad", Decimal("58500"), Decimal("2200")),
        ]
        for index, (origin, destination, rate, unloading) in enumerate(routes, start=1):
            vendor = vendors[(index - 1) % len(vendors)]
            vehicle, _ = Vehicle.objects.get_or_create(
                registration_no=f"HR10DEMO{index:02d}",
                defaults={"vendor": vendor, "vehicle_type": "32 FT MXL", "capacity": Decimal("25000")},
            )
            driver, _ = Driver.objects.get_or_create(
                phone=f"+9100000000{index:02d}",
                defaults={"name": f"Demo Driver {index}", "vendor": vendor},
            )
            indent, _ = Indent.objects.get_or_create(
                indent_no=f"NPL-IND-DEMO-{index:03d}",
                defaults={
                    "client": client,
                    "indent_date": today,
                    "origin": origin,
                    "destination": destination,
                    "expected_delivery_date": today + timedelta(days=index),
                    "branch": "Sonipat",
                    "required_vehicle_type": "32 FT MXL",
                },
            )
            trip = Trip.objects.filter(indent=indent).first()
            if not trip:
                trip = Trip.objects.create(
                    indent=indent,
                    client=client,
                    origin=origin,
                    destination=destination,
                    deployment_date=today,
                    expected_delivery_date=today + timedelta(days=index),
                    vendor=vendor,
                    vehicle=vehicle,
                    driver=driver,
                    vendor_freight_rate=rate,
                    branch="Sonipat",
                )
                TripCharge.objects.create(
                    trip=trip,
                    charge_type=TripCharge.ChargeType.UNLOADING,
                    description="Synthetic unloading allowance",
                    amount=unloading,
                    advance_eligible=True,
                    tds_eligible=False,
                    created_by=users["operations"],
                )
            trips.append(trip)

        if not PaymentApprovalBatch.objects.exists():
            batch = create_approval_batch(actor=users["operations"], trips=trips[:2])
            submit_batch(batch=batch, actor=users["operations"])
            decide_batch(batch=batch, actor=users["approver"], decision=ApprovalAction.Action.APPROVE)
            first_item = batch.items.order_by("id").first()
            create_paid_payment(
                actor=users["finance"],
                vendor=first_item.vendor,
                payment_date=today,
                utr_reference="DEMO-UTR-0001",
                allocations=[
                    {
                        "approval_item_id": first_item.pk,
                        "gross_amount_allocated": first_item.gross_requested,
                        "tds_allocated": first_item.tds_this_request,
                        "net_cash_allocated": first_item.net_requested,
                    }
                ],
                remarks="Synthetic demonstration payment",
            )
            pending = create_approval_batch(actor=users["operations"], trips=[trips[2]])
            submit_batch(batch=pending, actor=users["operations"])

        self.stdout.write(self.style.SUCCESS("Synthetic demo data is ready."))
