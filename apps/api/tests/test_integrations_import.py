from io import BytesIO

import pytest
from openpyxl import Workbook

from accounts.models import User
from approvals.services import create_approval_batch
from imports.services import LEGACY_COLUMNS, preview_legacy_workbook
from integrations.models import IntegrationMessage
from integrations.services import ingest_email_reply


def test_excel_import_preview_handles_dates_formulas_and_duplicates():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(LEGACY_COLUMNS)
    row = [1, "Sonipat", "Delhi", 45500, "LTRS", 10, 20000, 50000, 2500, "=H2*90%", "=J2+I2", "Demo Vendor", "HR 10 AB 1234", "Demo Driver", "0000000000", "32 FT", 45501]
    sheet.append(row)
    duplicate = list(row)
    duplicate[0] = 2
    sheet.append(duplicate)
    output = BytesIO()
    workbook.save(output)
    preview = preview_legacy_workbook(output.getvalue())
    assert preview["valid_count"] == 2
    assert preview["rows"][0]["normalized"]["deployment_date"] == "2024-07-27"
    assert preview["rows"][0]["normalized"]["calculated_advance"] == "45000.00"
    assert any("Possible duplicate" in warning for warning in preview["rows"][1]["warnings"])


@pytest.mark.django_db
def test_email_reply_mapping_is_idempotent(trip_factory, users):
    trip = trip_factory(1)
    trip.vendor.email = "manager@example.test"
    trip.vendor.save(update_fields=["email", "updated_at"])
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    message = ingest_email_reply(
        external_message_id="email-1",
        external_thread_id="thread-1",
        subject=f"Re: [{batch.approval_no}] Please approve",
        body="Approved after checking the attachment.",
        sender="manager@example.test",
    )
    duplicate = ingest_email_reply(
        external_message_id="email-1",
        external_thread_id="thread-1",
        subject=f"Re: [{batch.approval_no}] Please approve",
        body="Ignored duplicate",
        sender="manager@example.test",
    )
    assert message.pk == duplicate.pk
    assert IntegrationMessage.objects.count() == 1
    from approvals.models import Comment

    assert Comment.objects.filter(object_type="approval", object_id=str(batch.pk)).count() == 1


def legacy_workbook(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(LEGACY_COLUMNS)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def sample_row(index, *, vehicle="HR10AB1234", vendor="Demo Vendor"):
    return [index, "Sonipat", "Delhi", 45500, "LTRS", 10, 20000, 50000, 2500, 45000, 47500, vendor, vehicle, "Demo Driver", "0000000000", "32 FT", 45501]


def test_legacy_preview_rejects_more_than_1000_rows():
    with pytest.raises(ValueError, match="1,000"):
        preview_legacy_workbook(legacy_workbook([sample_row(index) for index in range(1, 1002)]))


@pytest.mark.django_db
def test_legacy_confirm_reports_vehicle_owned_by_another_vendor(users):
    from imports.models import ImportJob
    from imports.services import confirm_import
    from operations.models import Client, Vehicle, Vendor

    client = Client.objects.create(code="NPL", name="NPL")
    other = Vendor.objects.create(vendor_code="OTHER", legal_name="Other", display_name="Other Transport")
    Vehicle.objects.create(registration_no="HR10AB1234", vendor=other, vehicle_type="32 FT")
    preview = preview_legacy_workbook(legacy_workbook([sample_row(1, vendor="New Transport")]))
    job = ImportJob.objects.create(
        uploaded_by=users[User.Role.OPERATIONS], original_filename="legacy.xlsx", source_hash="vehicle-owner-test",
        summary=preview, row_count=preview["row_count"], valid_count=preview["valid_count"], error_count=preview["error_count"],
    )
    job = confirm_import(job=job, actor=users[User.Role.OPERATIONS], client_id=client.pk, create_missing=True)
    assert job.status == "VALIDATION_FAILED"
    assert "another vendor" in job.result["errors"][0]["error"]
