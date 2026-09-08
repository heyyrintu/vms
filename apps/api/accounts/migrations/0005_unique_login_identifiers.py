from django.db import migrations
from django.db.models import Q, UniqueConstraint
from django.db.models.functions import Lower


def reject_duplicate_identifiers(apps, schema_editor):
    from collections import defaultdict

    User = apps.get_model("accounts", "User")
    problems = []
    for field, key in (("email", lambda value: value.lower()), ("whatsapp_phone", lambda value: value)):
        buckets = defaultdict(list)
        for username, value in User.objects.values_list("username", field):
            if value:
                buckets[key(value)].append(username)
        problems.extend(
            f"{field} {value} is shared by {', '.join(sorted(names))}"
            for value, names in sorted(buckets.items())
            if len(names) > 1
        )
    if problems:
        raise RuntimeError(
            "Cannot add unique login identifiers until these are resolved:\n  "
            + "\n  ".join(problems)
            + "\nRun: python manage.py check_login_identifiers"
        )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_user_whatsapp_phone")]

    operations = [
        migrations.RunPython(reject_duplicate_identifiers, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="user",
            constraint=UniqueConstraint(
                Lower("email"), condition=~Q(email=""), name="accounts_user_unique_email_ci"
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=UniqueConstraint(
                fields=["whatsapp_phone"],
                condition=~Q(whatsapp_phone=""),
                name="accounts_user_unique_whatsapp_phone",
            ),
        ),
    ]
