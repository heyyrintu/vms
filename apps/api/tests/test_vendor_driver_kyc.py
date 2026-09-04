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
