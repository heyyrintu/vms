import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import User
from operations.models import Driver, Vendor


def pdf(name):
    return SimpleUploadedFile(name, b"%PDF-1.4\n% secure test document\n", content_type="application/pdf")


@pytest.mark.django_db
def test_operations_can_onboard_vendor_bank_and_kyc(users, tmp_path):
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])
    vendor = Vendor.objects.create(vendor_code="KYC-01", legal_name="KYC Vendor Pvt Ltd", display_name="KYC Vendor")

    bank_response = client.post(
        "/api/vendor-bank-accounts/",
        {
            "vendor": vendor.pk,
            "bank_name": "HDFC Bank",
            "account_holder": "KYC Vendor Pvt Ltd",
            "account_number": "1234 5678 9012",
            "ifsc_code": "hdfc0001234",
        },
        format="json",
    )
    assert bank_response.status_code == 201
    assert bank_response.data["masked_account_number"] == "•••• 9012"
    assert bank_response.data["ifsc_code"] == "HDFC0001234"
    assert "account_number" not in bank_response.data
    bank_id = bank_response.data["id"]

    with override_settings(MEDIA_ROOT=tmp_path):
        aadhaar_response = client.post(
            "/api/documents/",
            {"file": pdf("vendor-aadhaar.pdf"), "kind": "AADHAAR", "object_type": "vendor", "object_id": vendor.pk},
            format="multipart",
        )
        cheque_response = client.post(
            "/api/documents/",
            {"file": pdf("cancelled-cheque.pdf"), "kind": "CANCELLED_CHEQUE", "object_type": "vendor_bank_account", "object_id": bank_id},
            format="multipart",
        )

    assert aadhaar_response.status_code == 201
    assert cheque_response.status_code == 201
    refreshed = client.get(f"/api/vendor-bank-accounts/{bank_id}/")
    assert refreshed.data["cancelled_cheque_uploaded"] is True
    vendor_detail = client.get(f"/api/vendors/{vendor.pk}/")
    assert vendor_detail.data["bank_accounts"][0]["masked_account_number"] == "•••• 9012"


@pytest.mark.django_db
def test_driver_accepts_only_driver_identity_document_kinds(users, tmp_path):
    vendor = Vendor.objects.create(vendor_code="DRV-01", legal_name="Driver Vendor", display_name="Driver Vendor")
    driver = Driver.objects.create(name="Verified Driver", phone="919876543210", vendor=vendor)
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])

    with override_settings(MEDIA_ROOT=tmp_path):
        licence = client.post(
            "/api/documents/",
            {"file": pdf("licence.pdf"), "kind": "DRIVING_LICENSE", "object_type": "driver", "object_id": driver.pk},
            format="multipart",
        )
        invalid = client.post(
            "/api/documents/",
            {"file": pdf("wrong.pdf"), "kind": "CANCELLED_CHEQUE", "object_type": "driver", "object_id": driver.pk},
            format="multipart",
        )
        disguised = client.post(
            "/api/documents/",
            {"file": pdf("disguised.pdf"), "kind": "AADHAAR", "object_type": "trip", "object_id": "999999"},
            format="multipart",
        )

    assert licence.status_code == 201
    assert invalid.status_code == 400
    assert disguised.status_code == 400


@pytest.mark.django_db
def test_approver_cannot_read_vendor_kyc_document(users, tmp_path):
    vendor = Vendor.objects.create(vendor_code="PRIVATE-01", legal_name="Private Vendor", display_name="Private Vendor")
    operations = APIClient()
    operations.force_authenticate(users[User.Role.OPERATIONS])
    with override_settings(MEDIA_ROOT=tmp_path):
        uploaded = operations.post(
            "/api/documents/",
            {"file": pdf("private-pan.pdf"), "kind": "PAN", "object_type": "vendor", "object_id": vendor.pk},
            format="multipart",
        )
        assert uploaded.status_code == 201
        approver = APIClient()
        approver.force_authenticate(users[User.Role.APPROVER])
        listing = approver.get(f"/api/documents/?object_type=vendor&object_id={vendor.pk}")
        download = approver.get(f"/api/documents/{uploaded.data['id']}/download/")

    assert listing.status_code == 200
    assert listing.data["count"] == 0
    assert download.status_code == 404


def png(name):
    return SimpleUploadedFile(name, b"\x89PNG\r\n\x1a\nfake-image-body", content_type="image/png")


def xlsx(name):
    return SimpleUploadedFile(
        name,
        b"PK\x03\x04fake-spreadsheet-body",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@pytest.mark.django_db
def test_preview_renders_pdfs_and_images_in_place(users, tmp_path, trip_factory):
    trip = trip_factory(21)
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])

    with override_settings(MEDIA_ROOT=tmp_path):
        pod = client.post(
            "/api/documents/",
            {"file": pdf("pod.pdf"), "kind": "POD", "object_type": "trip", "object_id": trip.pk},
            format="multipart",
        )
        lorry_receipt = client.post(
            "/api/documents/",
            {"file": png("lr.png"), "kind": "LR", "object_type": "trip", "object_id": trip.pk},
            format="multipart",
        )
        assert pod.status_code == 201
        assert lorry_receipt.data["preview_url"] == f"/api/documents/{lorry_receipt.data['id']}/preview/"
        pdf_preview = client.get(f"/api/documents/{pod.data['id']}/preview/")
        image_preview = client.get(f"/api/documents/{lorry_receipt.data['id']}/preview/")

        assert pdf_preview.status_code == 200
        assert pdf_preview["Content-Type"] == "application/pdf"
        assert pdf_preview["Content-Disposition"].startswith("inline")
        assert pdf_preview["X-Content-Type-Options"] == "nosniff"
        assert "sandbox" in pdf_preview["Content-Security-Policy"]
        assert image_preview["Content-Type"] == "image/png"
        assert image_preview["Content-Disposition"].startswith("inline")


@pytest.mark.django_db
def test_preview_forces_a_download_for_a_type_the_viewer_cannot_render(users, tmp_path, trip_factory):
    trip = trip_factory(22)
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])

    with override_settings(MEDIA_ROOT=tmp_path):
        sheet = client.post(
            "/api/documents/",
            {"file": xlsx("rates.xlsx"), "kind": "OTHER", "object_type": "trip", "object_id": trip.pk},
            format="multipart",
        )
        assert sheet.status_code == 201
        response = client.get(f"/api/documents/{sheet.data['id']}/preview/")

    # A spreadsheet must never be handed to an iframe as its own content type.
    assert response.status_code == 200
    assert response["Content-Type"] == "application/octet-stream"
    assert response["Content-Disposition"].startswith("attachment")
    assert response["X-Content-Type-Options"] == "nosniff"


@pytest.mark.django_db
def test_transporter_cannot_preview_another_vendors_document(users, tmp_path, trip_factory):
    trip = trip_factory(23)
    other_vendor = Vendor.objects.create(
        vendor_code="OTHER-01", legal_name="Other Vendor Ltd", display_name="Other Vendor"
    )
    outsider = User.objects.create_user(
        username="outside-transporter",
        password="StrongPass123!",
        role=User.Role.TRANSPORTER,
        vendor=other_vendor,
    )
    operations = APIClient()
    operations.force_authenticate(users[User.Role.OPERATIONS])

    with override_settings(MEDIA_ROOT=tmp_path):
        uploaded = operations.post(
            "/api/documents/",
            {"file": pdf("their-pod.pdf"), "kind": "POD", "object_type": "trip", "object_id": trip.pk},
            format="multipart",
        )
        assert uploaded.status_code == 201
        transporter = APIClient()
        transporter.force_authenticate(outsider)
        preview = transporter.get(f"/api/documents/{uploaded.data['id']}/preview/")
        owner_preview = operations.get(f"/api/documents/{uploaded.data['id']}/preview/")

    # preview goes through get_object(), so it inherits the queryset scoping.
    assert preview.status_code == 404
    assert owner_preview.status_code == 200
