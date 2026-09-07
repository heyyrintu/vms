import pytest
from django.db import IntegrityError, transaction

from accounts.management.commands.check_login_identifiers import find_conflicts
from accounts.models import User


@pytest.mark.django_db
def test_email_is_unique_case_insensitively():
    User.objects.create_user(username="one", email="Ops@Drona.test")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create_user(username="two", email="ops@drona.test")


@pytest.mark.django_db
def test_whatsapp_phone_is_unique():
    User.objects.create_user(username="one", whatsapp_phone="919811111111")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create_user(username="two", whatsapp_phone="919811111111")


@pytest.mark.django_db
def test_blank_identifiers_do_not_collide():
    User.objects.create_user(username="one", email="", whatsapp_phone="")
    User.objects.create_user(username="two", email="", whatsapp_phone="")
    assert User.objects.filter(email="").count() == 2


def test_find_conflicts_reports_colliding_usernames():
    """Pure logic, no database.

    Once the migration in this task has run, the database itself refuses to
    hold a conflict, so this detector can only be exercised over rows passed
    in. That is also how it earns its keep: it runs against an *old* database
    before the constraints exist.
    """
    rows = [
        ("alpha", "a@x.test", ""),
        ("beta", "A@X.test", ""),
        ("gamma", "g@x.test", "919811111111"),
        ("delta", "d@x.test", "919811111111"),
        ("epsilon", "", ""),
        ("zeta", "", ""),
    ]
    assert find_conflicts(rows) == [
        ("email", "a@x.test", ["alpha", "beta"]),
        ("whatsapp_phone", "919811111111", ["delta", "gamma"]),
    ]


def test_find_conflicts_is_quiet_on_clean_data():
    assert find_conflicts([("alpha", "a@x.test", "919811111111"), ("beta", "", "")]) == []


@pytest.mark.django_db
def test_check_login_identifiers_command_passes_on_clean_data(capsys):
    from django.core.management import call_command

    User.objects.create_user(username="alpha", email="a@x.test")
    call_command("check_login_identifiers")
    assert "No duplicate login identifiers" in capsys.readouterr().out
