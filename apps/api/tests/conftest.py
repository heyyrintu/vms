from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import User
from core.models import OrganizationSettings
from operations.models import Client, Driver, Indent, Trip, TripCharge, Vehicle, Vendor


@pytest.fixture
def users(db):
    return {
        role: User.objects.create_user(username=role.lower(), password="StrongPass123!", role=role)
        for role in (
            User.Role.OPERATIONS,
            User.Role.APPROVER,
            User.Role.FINANCE,
            User.Role.MANAGEMENT,
            User.Role.ADMIN,
        )
    }


@pytest.fixture
def organization(db):
    return OrganizationSettings.objects.create(
        name="Test Logistics",
        default_advance_percent=Decimal("90.00"),
        default_tds_rate=Decimal("1.00"),
        default_tds_policy="PER_PAYMENT_TAXABLE_AMOUNT",
    )


@pytest.fixture
def trip_factory(db, organization, users):
    client = Client.objects.create(code="NPL", name="NPL")

    def create(index=1, vendor=None, rate="50000.00", unloading="2500.00"):
        vendor = vendor or Vendor.objects.create(
            vendor_code=f"V-{index:03d}", legal_name=f"Vendor {index} Pvt Ltd", display_name=f"Vendor {index}"
        )
        vehicle = Vehicle.objects.create(
            registration_no=f"HR10TEST{index:02d}", vendor=vendor, vehicle_type="32 FT MXL"
        )
        driver = Driver.objects.create(name=f"Driver {index}", phone=f"+910000000{index:03d}", vendor=vendor)
        indent = Indent.objects.create(
            indent_no=f"IND-{index:04d}",
            client=client,
            indent_date=timezone.localdate(),
            origin="Sonipat",
            destination="Ghaziabad",
        )
        trip = Trip.objects.create(
            indent=indent,
            client=client,
            origin=indent.origin,
            destination=indent.destination,
            deployment_date=timezone.localdate(),
            expected_delivery_date=timezone.localdate() + timedelta(days=1),
            vendor=vendor,
            vehicle=vehicle,
            driver=driver,
            vendor_freight_rate=Decimal(rate),
        )
        if Decimal(unloading):
            TripCharge.objects.create(
                trip=trip,
                charge_type=TripCharge.ChargeType.UNLOADING,
                amount=Decimal(unloading),
                advance_eligible=True,
                tds_eligible=False,
                created_by=users[User.Role.OPERATIONS],
            )
        return trip

    return create

