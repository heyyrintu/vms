import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import User


@pytest.mark.django_db
def test_trip_register_combines_search_date_branch_and_vehicle_filters(trip_factory, users):
    matching = trip_factory(1)
    matching.branch = "Sonipat"
    matching.vehicle_type_snapshot = "32 FT MXL"
    matching.save(update_fields=["branch", "vehicle_type_snapshot", "updated_at"])
    other = trip_factory(2)
    other.branch = "Delhi"
    other.vehicle_type_snapshot = "Tanker"
    other.save(update_fields=["branch", "vehicle_type_snapshot", "updated_at"])
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])

    response = client.get(
        "/api/trips/",
        {
            "search": matching.vendor.display_name,
            "branch": "Sonipat",
            "vehicle_type": "32 FT",
            "date_from": matching.deployment_date.isoformat(),
            "date_to": matching.deployment_date.isoformat(),
        },
    )

    assert response.status_code == 200
    assert [row["id"] for row in response.data["results"]] == [matching.pk]


@pytest.mark.django_db
def test_comment_mentions_replies_edits_and_uploaded_attachment_are_returned(trip_factory, users, tmp_path):
    trip = trip_factory(1)
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])

    candidates = client.get("/api/comments/mention-candidates/")
    assert candidates.status_code == 200
    assert {row["id"] for row in candidates.data} >= {
        users[User.Role.APPROVER].pk,
        users[User.Role.FINANCE].pk,
    }

    root = client.post(
        "/api/comments/",
        {
            "object_type": "trip",
            "object_id": str(trip.pk),
            "body": "Please verify this trip.",
            "visibility": "INTERNAL",
            "mentions": [users[User.Role.APPROVER].pk],
        },
        format="json",
    )
    assert root.status_code == 201, root.data
    reply = client.post(
        "/api/comments/",
        {
            "object_type": "trip",
            "object_id": str(trip.pk),
            "body": "Verification attached.",
            "visibility": "INTERNAL",
            "parent": root.data["id"],
        },
        format="json",
    )
    assert reply.status_code == 201, reply.data
    edited = client.patch(
        f"/api/comments/{reply.data['id']}/",
        {"body": "Verification document attached."},
        format="json",
    )
    assert edited.status_code == 200
    assert len(edited.data["edit_history"]) == 1

    with override_settings(MEDIA_ROOT=tmp_path):
        uploaded = client.post(
            "/api/documents/",
            {
                "file": SimpleUploadedFile("verification.pdf", b"%PDF-1.4\n% test\n", content_type="application/pdf"),
                "kind": "OTHER",
                "object_type": "comment",
                "object_id": reply.data["id"],
            },
            format="multipart",
        )
        assert uploaded.status_code == 201, uploaded.data
        listing = client.get("/api/comments/", {"object_type": "trip", "object_id": trip.pk})

    assert listing.status_code == 200
    saved_reply = next(row for row in listing.data["results"] if row["id"] == reply.data["id"])
    assert saved_reply["parent"] == root.data["id"]
    assert saved_reply["attachments"][0]["original_name"] == "verification.pdf"
