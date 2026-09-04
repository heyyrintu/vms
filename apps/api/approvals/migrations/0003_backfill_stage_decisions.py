from django.db import migrations


def backfill_stage_decisions(apps, schema_editor):
    Batch = apps.get_model("approvals", "PaymentApprovalBatch")
    Decision = apps.get_model("approvals", "ApprovalStageDecision")
    for batch in Batch.objects.all().iterator():
        if Decision.objects.filter(batch_id=batch.pk).exists():
            continue
        snapshot = batch.approval_rule_snapshot or {}
        stages = snapshot.get("stages") or [
            {"sequence": 1, "role": "APPROVER", "label": "Manager approval"}
        ]
        decisions = []
        for stage in stages:
            sequence = int(stage.get("sequence", 1))
            status = "PENDING"
            if batch.status == "APPROVED" or sequence < batch.current_stage:
                status = "APPROVED"
            elif sequence == batch.current_stage and batch.status == "REJECTED":
                status = "REJECTED"
            elif sequence == batch.current_stage and batch.status == "CHANGES_REQUESTED":
                status = "CHANGES_REQUESTED"
            action = (
                batch.actions.filter(approval_stage=sequence)
                .order_by("-created_at", "-id")
                .first()
            )
            decisions.append(
                Decision(
                    batch_id=batch.pk,
                    sequence=sequence,
                    role=stage.get("role", "APPROVER"),
                    label=stage.get("label") or stage.get("role", "APPROVER"),
                    status=status,
                    decided_by_id=action.actor_id if action and status != "PENDING" else None,
                    decided_at=action.created_at if action and status != "PENDING" else None,
                    comment=action.comment if action and status != "PENDING" else "",
                )
            )
        Decision.objects.bulk_create(decisions)


class Migration(migrations.Migration):
    dependencies = [("approvals", "0002_alter_approvalrule_options_approvalrule_conditions_and_more")]

    operations = [migrations.RunPython(backfill_stage_decisions, migrations.RunPython.noop)]
