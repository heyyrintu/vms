# Configurable Masters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace free-text branches, vehicle types and enum charge types with admin-managed, validated master tables, without breaking existing data, importers or reports.

**Architecture:** Three lookup models in the `core` app; the existing string columns stay and are validated against active master codes by a shared resolver; `TripCharge` gains a foreign key to `ChargeType` and inherits defaults from it. The frontend reads all three lists from `/api/choices/` and manages them from a new Settings panel.

**Tech Stack:** Django 5.2, DRF 3.18, pytest-django, Next.js 16, TanStack Query 5, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-07-configurable-masters-design.md`

## Global Constraints

- Work on branch `feat/configurable-masters` off `main`.
- Backend commands run from `apps/api` with `.venv/Scripts/python` (Windows) or `.venv/bin/python`.
- After every backend task: `ruff check .`, `python manage.py makemigrations --check --dry-run`, and `python -m pytest -q -p no:cacheprovider -p no:warnings` must pass.
- After every frontend task: `npm run lint && npm run typecheck && npm run format:check && npm run build` from `apps/web`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Fixtures: `users` (dict by `User.Role`, no TRANSPORTER entry) and `trip_factory(index=1, vendor=None, rate=..., unloading=...)` from `tests/conftest.py`; `client_for(user)` from `tests/test_lifecycle_regressions.py`.
- Strict validation: unknown or inactive codes are rejected everywhere except imports with `create_missing=True`.

---

### Task 1: Master models, code normaliser and seed migration

**Files:**
- Modify: `apps/api/core/models.py` (append models), `apps/api/core/masters.py` (create)
- Create: `apps/api/core/migrations/0004_masters.py` (auto), `apps/api/core/migrations/0005_seed_masters.py`
- Test: `apps/api/tests/test_masters.py` (create)

**Interfaces:**
- Produces: `core.models.Branch`, `core.models.VehicleType`, `core.models.ChargeType` (fields per spec); `core.masters.normalise_code(value) -> str`; `core.masters.seed_charge_types()`; `ChargeType.DEFAULTS` dict keyed by code with `(direction, advance_eligible, tds_eligible)`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_masters.py
import pytest

from core.masters import normalise_code


def test_normalise_code_collapses_case_and_whitespace():
    assert normalise_code("  32 ft   mxl ") == "32 FT MXL"
    assert normalise_code("") == ""


@pytest.mark.django_db
def test_seed_creates_charge_types_with_todays_defaults():
    from core.models import ChargeType

    unloading = ChargeType.objects.get(code="UNLOADING")
    assert unloading.direction == "ADD"
    assert unloading.default_advance_eligible is True
    assert unloading.default_tds_eligible is False
    assert ChargeType.objects.get(code="DEDUCTION").direction == "DEDUCT"
    assert ChargeType.objects.filter(active=True).count() == 8
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_masters.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: core.masters`.

- [ ] **Step 3: Add the normaliser and models**

```python
# apps/api/core/masters.py
"""Shared helpers for the branch, vehicle type and charge type masters."""
from rest_framework import serializers


def normalise_code(value):
    return " ".join(str(value or "").split()).upper()


def resolve_master(model, value, *, field, allow_blank=False):
    """Return the canonical active code for ``value`` or raise a field error."""
    code = normalise_code(value)
    if not code:
        if allow_blank:
            return ""
        raise serializers.ValidationError({field: f"{model._meta.verbose_name} is required"})
    if not model.objects.filter(code=code, active=True).exists():
        raise serializers.ValidationError({field: f"'{value}' is not an active {model._meta.verbose_name}"})
    return code


def resolve_or_create_master(model, value, *, create_missing, name=None):
    """Importer variant: create the master when allowed, otherwise return None for a preflight error."""
    code = normalise_code(value)
    if not code:
        return ""
    record = model.objects.filter(code=code).first()
    if record:
        return code if record.active else None
    if not create_missing:
        return None
    model.objects.create(code=code, name=(name or str(value)).strip()[:100])
    return code
```

Append to `apps/api/core/models.py`:

```python
class MasterRecord(models.Model):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["code"]

    def save(self, *args, **kwargs):
        from .masters import normalise_code

        self.code = normalise_code(self.code)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}"


class Branch(MasterRecord):
    default_cost_center = models.CharField(max_length=100, blank=True)

    class Meta(MasterRecord.Meta):
        verbose_name = "branch"
        verbose_name_plural = "branches"


class VehicleType(MasterRecord):
    capacity_hint = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)

    class Meta(MasterRecord.Meta):
        verbose_name = "vehicle type"


class ChargeType(MasterRecord):
    class Direction(models.TextChoices):
        ADD = "ADD", "Add"
        DEDUCT = "DEDUCT", "Deduct"

    # code: (direction, default_advance_eligible, default_tds_eligible, sort_order)
    DEFAULTS = {
        "FREIGHT": ("ADD", False, True, 10),
        "UNLOADING": ("ADD", True, False, 20),
        "LOADING": ("ADD", False, False, 30),
        "DETENTION": ("ADD", False, False, 40),
        "TOLL": ("ADD", False, False, 50),
        "REIMBURSEMENT": ("ADD", False, False, 60),
        "OTHER": ("ADD", False, False, 70),
        "DEDUCTION": ("DEDUCT", False, False, 80),
    }

    code = models.CharField(max_length=30, unique=True)
    direction = models.CharField(max_length=10, choices=Direction.choices, default=Direction.ADD)
    default_advance_eligible = models.BooleanField(default=False)
    default_tds_eligible = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=100)

    class Meta(MasterRecord.Meta):
        verbose_name = "charge type"
        ordering = ["sort_order", "code"]
```

Check the existing behaviour of FREIGHT before keeping `default_tds_eligible=True` for it: `grep -n "FREIGHT" apps/api -r --include=*.py`. If nothing creates FREIGHT charges with `tds_eligible=True`, set it to `False` to match today's implicit default.

- [ ] **Step 4: Generate the schema migration and write the seed migration**

Run: `cd apps/api && .venv/Scripts/python manage.py makemigrations core -n masters`

Then create `apps/api/core/migrations/0005_seed_masters.py` (adjust the dependency number to the file makemigrations produced):

```python
from django.db import migrations


def normalise(value):
    return " ".join(str(value or "").split()).upper()


def seed(apps, schema_editor):
    Branch = apps.get_model("core", "Branch")
    VehicleType = apps.get_model("core", "VehicleType")
    ChargeType = apps.get_model("core", "ChargeType")
    Client = apps.get_model("operations", "Client")
    Indent = apps.get_model("operations", "Indent")
    Vehicle = apps.get_model("operations", "Vehicle")
    Trip = apps.get_model("operations", "Trip")

    defaults = {
        "FREIGHT": ("ADD", False, False, 10),
        "UNLOADING": ("ADD", True, False, 20),
        "LOADING": ("ADD", False, False, 30),
        "DETENTION": ("ADD", False, False, 40),
        "TOLL": ("ADD", False, False, 50),
        "REIMBURSEMENT": ("ADD", False, False, 60),
        "OTHER": ("ADD", False, False, 70),
        "DEDUCTION": ("DEDUCT", False, False, 80),
    }
    for code, (direction, advance, tds, order) in defaults.items():
        ChargeType.objects.get_or_create(
            code=code,
            defaults={"name": code.title(), "direction": direction, "default_advance_eligible": advance,
                      "default_tds_eligible": tds, "sort_order": order},
        )

    def collect(model, *sources):
        seen = {}
        for source_model, field in sources:
            for raw in source_model.objects.exclude(**{field: ""}).values_list(field, flat=True).distinct():
                code = normalise(raw)
                if code and code not in seen:
                    seen[code] = str(raw).strip()[:100]
        for code, name in seen.items():
            model.objects.get_or_create(code=code, defaults={"name": name})

    collect(Branch, (Client, "default_branch"), (Indent, "branch"), (Trip, "branch"))
    collect(VehicleType, (Vehicle, "vehicle_type"), (Indent, "required_vehicle_type"), (Trip, "vehicle_type_snapshot"))

    for model, fields in ((Client, ["default_branch"]), (Indent, ["branch", "required_vehicle_type"]),
                          (Vehicle, ["vehicle_type"]), (Trip, ["branch", "vehicle_type_snapshot"])):
        for row in model.objects.all().only("pk", *fields):
            changed = {field: normalise(getattr(row, field)) for field in fields if getattr(row, field)}
            if any(getattr(row, field) != value for field, value in changed.items()):
                model.objects.filter(pk=row.pk).update(**changed)


class Migration(migrations.Migration):
    dependencies = [("core", "0004_masters"), ("operations", "0005_indent_registration_and_multi_indent_trips")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
```

- [ ] **Step 5: Run the tests and the suite**

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python manage.py makemigrations --check --dry-run && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass. The seed test passes because pytest-django applies migrations to the test database.

- [ ] **Step 6: Commit**

```bash
git add apps/api/core apps/api/tests/test_masters.py
git commit -m "Add branch, vehicle type and charge type masters with seed migration"
```

---

### Task 2: TripCharge foreign key and default inheritance

**Files:**
- Modify: `apps/api/operations/models.py` (`TripCharge`), `apps/api/operations/serializers.py:238-242` (`TripChargeSerializer`), `:364-380` (`TripSerializer.create`)
- Create: `apps/api/operations/migrations/0006_tripcharge_charge_type_ref.py`
- Test: `apps/api/tests/test_masters.py`

**Interfaces:**
- Produces: `TripCharge.charge_type_ref` (non-null FK); `TripChargeSerializer` accepts `charge_type` code and fills defaults; `operations.models.charge_defaults(code) -> dict(direction, advance_eligible, tds_eligible)`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_charge_inherits_master_defaults_and_allows_override(trip_factory, users):
    from tests.test_lifecycle_regressions import client_for
    trip = trip_factory()
    client = client_for(users[User.Role.OPERATIONS])
    created = client.post(f"/api/trips/{trip.pk}/charges/", {"charge_type": "unloading", "amount": "500"}, format="json")
    assert created.status_code == 201, created.data
    assert created.data["advance_eligible"] is True and created.data["tds_eligible"] is False
    overridden = client.post(f"/api/trips/{trip.pk}/charges/", {"charge_type": "UNLOADING", "amount": "1", "advance_eligible": False}, format="json")
    assert overridden.data["advance_eligible"] is False
    unknown = client.post(f"/api/trips/{trip.pk}/charges/", {"charge_type": "BRIBE", "amount": "1"}, format="json")
    assert unknown.status_code == 400
```

Add `from accounts.models import User` to the test module imports.

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_masters.py -q -p no:cacheprovider`
Expected: the new test fails; lowercase `unloading` is rejected by the enum choices.

- [ ] **Step 3: Model and migration**

In `operations/models.py`, inside `TripCharge`, after `charge_type = ...` add:

```python
    charge_type_ref = models.ForeignKey("core.ChargeType", on_delete=models.PROTECT, related_name="charges")
```

and remove `choices=ChargeType.choices` from `charge_type` (keep `max_length=30`). Add module-level helper below the class:

```python
def charge_defaults(code):
    from core.models import ChargeType

    record = ChargeType.objects.filter(code=code, active=True).first()
    if record is None:
        raise ValueError(f"'{code}' is not an active charge type")
    return {
        "charge_type_ref": record,
        "charge_type": record.code,
        "direction": record.direction,
        "advance_eligible": record.default_advance_eligible,
        "tds_eligible": record.default_tds_eligible,
    }
```

Create `apps/api/operations/migrations/0006_tripcharge_charge_type_ref.py`:

```python
import django.db.models.deletion
from django.db import migrations, models


def link(apps, schema_editor):
    TripCharge = apps.get_model("operations", "TripCharge")
    ChargeType = apps.get_model("core", "ChargeType")
    by_code = {row.code: row.pk for row in ChargeType.objects.all()}
    for charge in TripCharge.objects.all().only("pk", "charge_type"):
        code = " ".join(str(charge.charge_type or "OTHER").split()).upper()
        TripCharge.objects.filter(pk=charge.pk).update(charge_type=code, charge_type_ref_id=by_code.get(code, by_code["OTHER"]))


class Migration(migrations.Migration):
    dependencies = [("operations", "0005_indent_registration_and_multi_indent_trips"), ("core", "0005_seed_masters")]
    operations = [
        migrations.AlterField(model_name="tripcharge", name="charge_type", field=models.CharField(max_length=30)),
        migrations.AddField(model_name="tripcharge", name="charge_type_ref",
                            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="charges", to="core.chargetype")),
        migrations.RunPython(link, migrations.RunPython.noop),
        migrations.AlterField(model_name="tripcharge", name="charge_type_ref",
                              field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="charges", to="core.chargetype")),
    ]
```

- [ ] **Step 4: Serializer**

Replace `TripChargeSerializer`:

```python
class TripChargeSerializer(serializers.ModelSerializer):
    charge_type = serializers.CharField(max_length=30)

    class Meta:
        model = TripCharge
        fields = "__all__"
        read_only_fields = ["created_by", "charge_type_ref"]
        extra_kwargs = {"direction": {"required": False}, "advance_eligible": {"required": False}, "tds_eligible": {"required": False}}

    def validate(self, attrs):
        from operations.models import charge_defaults

        try:
            defaults = charge_defaults(normalise_code(attrs["charge_type"]))
        except ValueError as exc:
            raise serializers.ValidationError({"charge_type": str(exc)}) from exc
        for key, value in defaults.items():
            attrs.setdefault(key, value)
        attrs["charge_type"] = defaults["charge_type"]
        attrs["charge_type_ref"] = defaults["charge_type_ref"]
        return attrs
```

Add `from core.masters import normalise_code, resolve_master` to the serializer imports. In `TripSerializer.create`, replace the `TripCharge.objects.create(...)` block with:

```python
        if unloading:
            TripCharge.objects.create(
                trip=trip, description="Unloading advance", amount=unloading,
                source=TripCharge.Source.INITIAL, created_by=self.context["request"].user,
                **charge_defaults("UNLOADING"),
            )
```

and import `charge_defaults` from `.models`. Update the three other creators of UNLOADING charges the same way: `imports/services.py:282`, `imports/mis.py:441`, `core/management/commands/seed_demo.py:110` (replace `charge_type=TripCharge.ChargeType.UNLOADING, direction=..., advance_eligible=True, tds_eligible=False` with `**charge_defaults("UNLOADING")`). `imports/services.py:318` compares `charge.charge_type == TripCharge.ChargeType.UNLOADING`; change it to `== "UNLOADING"`.

- [ ] **Step 5: Run the suite**

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python manage.py makemigrations --check --dry-run && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass. If `makemigrations --check` reports a pending change to `charge_type`, copy the exact `AlterField` it prints into the migration.

- [ ] **Step 6: Commit**

```bash
git add apps/api/operations apps/api/imports apps/api/core/management apps/api/tests/test_masters.py
git commit -m "Link trip charges to the charge type master and inherit its defaults"
```

---

### Task 3: Validate branch and vehicle type on clients, indents, vehicles and trips

**Files:**
- Modify: `apps/api/operations/serializers.py` (`ClientSerializer`, `VehicleSerializer`, `IndentSerializer.validate`, `TripSerializer.validate`)
- Test: `apps/api/tests/test_masters.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_vehicle_type_and_branch_must_be_active_masters(trip_factory, users):
    from core.models import Branch, VehicleType
    from tests.test_lifecycle_regressions import client_for
    trip = trip_factory()
    Branch.objects.create(code="SONIPAT", name="Sonipat")
    VehicleType.objects.create(code="32 FT MXL", name="32 ft multi axle")
    client = client_for(users[User.Role.OPERATIONS])
    ok = client.post("/api/vehicles/", {"registration_no": "HR10ZZ9999", "vendor": trip.vendor_id, "vehicle_type": "32 ft mxl"}, format="json")
    assert ok.status_code == 201, ok.data
    assert ok.data["vehicle_type"] == "32 FT MXL"
    bad = client.post("/api/vehicles/", {"registration_no": "HR10ZZ9998", "vendor": trip.vendor_id, "vehicle_type": "Rocket"}, format="json")
    assert bad.status_code == 400 and "vehicle_type" in bad.data
    branch_bad = client.patch(f"/api/trips/{trip.pk}/", {"branch": "Nowhere"}, format="json")
    assert branch_bad.status_code == 400 and "branch" in branch_bad.data
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_masters.py -q -p no:cacheprovider`
Expected: FAIL, "Rocket" is accepted.

- [ ] **Step 3: Add field validators**

```python
# in ClientSerializer
    def validate_default_branch(self, value):
        from core.models import Branch
        return resolve_master(Branch, value, field="default_branch", allow_blank=True)

# in VehicleSerializer
    def validate_vehicle_type(self, value):
        from core.models import VehicleType
        return resolve_master(VehicleType, value, field="vehicle_type")

# in IndentSerializer, at the top of validate(self, attrs)
        from core.models import Branch, VehicleType
        if "branch" in attrs:
            attrs["branch"] = resolve_master(Branch, attrs["branch"], field="branch", allow_blank=True)
        if "required_vehicle_type" in attrs:
            attrs["required_vehicle_type"] = resolve_master(VehicleType, attrs["required_vehicle_type"], field="required_vehicle_type", allow_blank=True)

# in TripSerializer.validate, at the top
        from core.models import Branch
        if "branch" in attrs:
            attrs["branch"] = resolve_master(Branch, attrs["branch"], field="branch", allow_blank=True)
```

`resolve_master` raises `ValidationError({field: ...})`; inside a `validate_<field>` method DRF re-keys it, so return the resolved code and let it raise.

- [ ] **Step 4: Fix the test fixtures that use free-text types**

`tests/conftest.py` creates vehicles with `vehicle_type="32 FT MXL"` and indents with `required_vehicle_type`; they bypass serializers so they still work. Any API-level test that posts a vehicle type or branch not in the masters now needs a `VehicleType`/`Branch` row; run the suite and add the row in those tests (`tests/test_vendor_driver_kyc.py`, `tests/test_completion_workflows.py` are the likely ones).

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/operations/serializers.py apps/api/tests
git commit -m "Validate branch and vehicle type against active masters"
```

---

### Task 4: Master API, permissions and choices

**Files:**
- Create: `apps/api/core/master_views.py`, `apps/api/core/master_serializers.py`
- Modify: `apps/api/config/urls.py` (router registrations + imports), `apps/api/core/views.py` (`ChoicesView`)
- Test: `apps/api/tests/test_masters.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_masters_api_create_toggle_and_choices(users):
    from tests.test_lifecycle_regressions import client_for
    ops = client_for(users[User.Role.OPERATIONS])
    created = ops.post("/api/vehicle-types/", {"code": "20 ft", "name": "20 ft container"}, format="json")
    assert created.status_code == 201 and created.data["code"] == "20 FT"
    assert ops.delete(f"/api/vehicle-types/{created.data['id']}/").status_code == 405
    approver = client_for(users[User.Role.APPROVER])
    assert approver.post("/api/vehicle-types/", {"code": "X", "name": "x"}, format="json").status_code == 403
    assert approver.get("/api/vehicle-types/").status_code == 200
    ops.patch(f"/api/vehicle-types/{created.data['id']}/", {"active": False}, format="json")
    choices = ops.get("/api/choices/").data
    assert "20 FT" not in [row["value"] for row in choices["vehicle_type"]]
    assert any(row["value"] == "UNLOADING" and row["default_advance_eligible"] for row in choices["charge_type"])
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_masters.py -q -p no:cacheprovider`
Expected: FAIL with 404 on `/api/vehicle-types/`.

- [ ] **Step 3: Serializers, viewsets, routes, choices**

```python
# apps/api/core/master_serializers.py
from rest_framework import serializers

from .models import Branch, ChargeType, VehicleType


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ["id", "code", "name", "default_cost_center", "active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class VehicleTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleType
        fields = ["id", "code", "name", "capacity_hint", "active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class ChargeTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChargeType
        fields = ["id", "code", "name", "direction", "default_advance_eligible", "default_tds_eligible", "sort_order", "active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]
```

```python
# apps/api/core/master_views.py
from rest_framework import viewsets

from accounts.permissions import RolePermission
from audit.models import record_audit

from .master_serializers import BranchSerializer, ChargeTypeSerializer, VehicleTypeSerializer
from .models import Branch, ChargeType, VehicleType


class MasterPermission(RolePermission):
    read_capability = "masters.read"
    write_capability = "masters.write"


class MasterViewSet(viewsets.ModelViewSet):
    permission_classes = [MasterPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_create(self, serializer):
        record = serializer.save()
        record_audit(actor=self.request.user, action="MASTER_CREATED", instance=record, after=serializer.data, request_id=getattr(self.request, "request_id", ""))

    def perform_update(self, serializer):
        before = {"active": serializer.instance.active, "name": serializer.instance.name}
        record = serializer.save()
        record_audit(actor=self.request.user, action="MASTER_UPDATED", instance=record, before=before, after=serializer.data, request_id=getattr(self.request, "request_id", ""))


class BranchViewSet(MasterViewSet):
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer


class VehicleTypeViewSet(MasterViewSet):
    queryset = VehicleType.objects.all()
    serializer_class = VehicleTypeSerializer


class ChargeTypeViewSet(MasterViewSet):
    queryset = ChargeType.objects.all()
    serializer_class = ChargeTypeSerializer
```

In `config/urls.py` add `from core.master_views import BranchViewSet, ChargeTypeViewSet, VehicleTypeViewSet` and, after the `clients` registration:

```python
router.register("branches", BranchViewSet, basename="branch")
router.register("vehicle-types", VehicleTypeViewSet, basename="vehicle-type")
router.register("charge-types", ChargeTypeViewSet, basename="charge-type")
```

In `core/views.py` `ChoicesView.get`, extend the response dict:

```python
                "branch": [{"value": row.code, "label": row.name} for row in Branch.objects.filter(active=True)],
                "vehicle_type": [{"value": row.code, "label": row.name} for row in VehicleType.objects.filter(active=True)],
                "charge_type": [
                    {"value": row.code, "label": row.name, "direction": row.direction,
                     "default_advance_eligible": row.default_advance_eligible, "default_tds_eligible": row.default_tds_eligible}
                    for row in ChargeType.objects.filter(active=True)
                ],
```

with `from .models import Branch, ChargeType, VehicleType` inside the method.

- [ ] **Step 4: Run the suite and schema validation**

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python manage.py spectacular --file schema.ci.yml --validate --fail-on-warn && rm schema.ci.yml && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/core apps/api/config/urls.py apps/api/tests/test_masters.py
git commit -m "Expose branch, vehicle type and charge type masters through the API and choices"
```

---

### Task 5: Importers resolve or create masters

**Files:**
- Modify: `apps/api/imports/services.py` (preflight loop and create loop), `apps/api/imports/indents.py` (`confirm_indent_import`), `apps/api/imports/mis.py` (`_resolve_trip`)
- Test: `apps/api/tests/test_integrations_import.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_legacy_confirm_creates_vehicle_type_master_only_when_allowed(users):
    from core.models import VehicleType
    from imports.models import ImportJob
    from imports.services import confirm_import
    from operations.models import Client

    client = Client.objects.create(code="NPL", name="NPL")
    for allow, expected_status in ((False, "VALIDATION_FAILED"), (True, "COMPLETED")):
        preview = preview_legacy_workbook(legacy_workbook([sample_row(1, vehicle=f"HR10AB{int(allow)}234")]))
        job = ImportJob.objects.create(
            uploaded_by=users[User.Role.OPERATIONS], original_filename="legacy.xlsx", source_hash=f"vt-{allow}",
            summary=preview, row_count=1, valid_count=1, error_count=0,
        )
        job = confirm_import(job=job, actor=users[User.Role.OPERATIONS], client_id=client.pk, create_missing=allow)
        assert job.status == expected_status, job.result
    assert VehicleType.objects.filter(code="32 FT").exists()
```

`sample_row` writes vehicle type "32 FT". Ensure no earlier test in the module already seeded it, or use a distinct value.

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_integrations_import.py -q -p no:cacheprovider`
Expected: the `create_missing=False` pass completes instead of failing validation.

- [ ] **Step 3: Wire the resolver**

In `imports/services.py` preflight loop (the one that appends to `preflight_errors`), after the vehicle checks add:

```python
        from core.masters import resolve_or_create_master
        from core.models import VehicleType

        if values["vehicle_type"] and resolve_or_create_master(VehicleType, values["vehicle_type"], create_missing=False) is None and not create_missing:
            preflight_errors.append({"row_no": row["row_no"], "error": f"Vehicle type '{values['vehicle_type']}' is not an active master"})
            continue
```

In the create loop, before `Vehicle.objects.get_or_create(...)`:

```python
        vehicle_type_code = resolve_or_create_master(VehicleType, values["vehicle_type"] or "UNSPECIFIED", create_missing=True) or "UNSPECIFIED"
```

and use `vehicle_type_code` in the `defaults` and in `required_vehicle_type=` on the indent. Apply the same two-line pattern in `imports/mis.py::_resolve_trip` around `Vehicle.objects.create` and `Indent.objects.create` (both `create_missing` values come from the function argument), and in `imports/indents.py::confirm_indent_import` for `branch` (with `Branch`) and `required_vehicle_type` is not set there, so only branch applies: resolve with `create_missing=True` since indent imports are operations-driven.

Note the preflight for `create_missing=False` must run before any row is created; it already does because preflight is a separate loop.

- [ ] **Step 4: Run the suite**

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/imports apps/api/tests/test_integrations_import.py
git commit -m "Resolve or create branch and vehicle type masters during imports"
```

---

### Task 6: Masters panel in Settings

**Files:**
- Create: `apps/web/components/MastersPanel.tsx`
- Modify: `apps/web/app/settings/page.tsx:156` (mount), `apps/web/lib/types.ts` (types)
- Test: `apps/web/e2e/core-flow.spec.ts`

- [ ] **Step 1: Write the failing e2e test**

```ts
test("operations adds a vehicle type in settings and can pick it on a new trip", async ({ page }) => {
  await loginAs(page, "operations");
  await page.goto("/settings");
  const code = `E2E ${Date.now().toString().slice(-6)}`;
  await page.getByLabel("Vehicle type code").fill(code);
  await page.getByLabel("Vehicle type name").fill("E2E type");
  await page.getByRole("button", { name: "Add vehicle type" }).click();
  await expect(page.getByRole("cell", { name: code.toUpperCase() })).toBeVisible();
  await page.goto("/trips/new");
  await expect(page.getByLabel("Vehicle type").locator("option", { hasText: "E2E type" })).toHaveCount(1);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/web && npx playwright test e2e/core-flow.spec.ts -g "vehicle type in settings"` (servers running as in CI)
Expected: FAIL, no "Vehicle type code" label.

- [ ] **Step 3: Types and panel**

Append to `lib/types.ts`:

```ts
export type MasterRow = { id: number; code: string; name: string; active: boolean; direction?: string; default_advance_eligible?: boolean; default_tds_eligible?: boolean; default_cost_center?: string; capacity_hint?: string | null };
export type ChoiceRow = { value: string; label: string; direction?: string; default_advance_eligible?: boolean; default_tds_eligible?: boolean };
export type Choices = { trip_status: ChoiceRow[]; document_kind: ChoiceRow[]; billing_status: ChoiceRow[]; payment_status: ChoiceRow[]; branch: ChoiceRow[]; vehicle_type: ChoiceRow[]; charge_type: ChoiceRow[] };
```

```tsx
// apps/web/components/MastersPanel.tsx
"use client";

import { FormEvent, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiAll } from "@/lib/api";
import type { MasterRow } from "@/lib/types";
import { ErrorNotice, StatusBadge } from "@/components/UI";

type MasterKind = { path: string; label: string; singular: string; extra?: "charge" | "branch" | "vehicle" };

const KINDS: MasterKind[] = [
  { path: "/branches/", label: "Branches", singular: "Branch", extra: "branch" },
  { path: "/vehicle-types/", label: "Vehicle types", singular: "Vehicle type", extra: "vehicle" },
  { path: "/charge-types/", label: "Charge types", singular: "Charge type", extra: "charge" },
];

function MasterTable({ kind }: { kind: MasterKind }) {
  const queryClient = useQueryClient();
  const rows = useQuery({ queryKey: ["masters", kind.path], queryFn: () => apiAll<MasterRow>(kind.path) });
  const [form, setForm] = useState({ code: "", name: "", direction: "ADD", default_advance_eligible: false, default_tds_eligible: false, default_cost_center: "" });
  const [error, setError] = useState<unknown>();
  const refresh = () => Promise.all([queryClient.invalidateQueries({ queryKey: ["masters", kind.path] }), queryClient.invalidateQueries({ queryKey: ["choices"] })]);
  const add = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    const body: Record<string, unknown> = { code: form.code, name: form.name };
    if (kind.extra === "charge") Object.assign(body, { direction: form.direction, default_advance_eligible: form.default_advance_eligible, default_tds_eligible: form.default_tds_eligible });
    if (kind.extra === "branch") body.default_cost_center = form.default_cost_center;
    try {
      await api(kind.path, { method: "POST", body: JSON.stringify(body) });
      setForm({ ...form, code: "", name: "", default_cost_center: "" });
      await refresh();
    } catch (reason) {
      setError(reason);
    }
  };
  const toggle = async (row: MasterRow) => {
    try {
      await api(`${kind.path}${row.id}/`, { method: "PATCH", body: JSON.stringify({ active: !row.active }) });
      await refresh();
    } catch (reason) {
      setError(reason);
    }
  };
  const idBase = kind.singular.toLowerCase().replace(/\s+/g, "-");
  return (
    <section className="panel">
      <div className="panel-head"><h2>{kind.label}</h2><span className="eyebrow">Validated on every save</span></div>
      {Boolean(error) && <div className="panel-body"><ErrorNotice error={error} /></div>}
      <form className="panel-body form-grid" onSubmit={add}>
        <div className="field"><label htmlFor={`${idBase}-code`}>{kind.singular} code</label><input id={`${idBase}-code`} required className="input" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></div>
        <div className="field span-2"><label htmlFor={`${idBase}-name`}>{kind.singular} name</label><input id={`${idBase}-name`} required className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
        {kind.extra === "branch" && <div className="field"><label htmlFor={`${idBase}-cc`}>Default cost centre</label><input id={`${idBase}-cc`} className="input" value={form.default_cost_center} onChange={(e) => setForm({ ...form, default_cost_center: e.target.value })} /></div>}
        {kind.extra === "charge" && (
          <>
            <div className="field"><label htmlFor={`${idBase}-direction`}>Direction</label><select id={`${idBase}-direction`} className="input" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })}><option>ADD</option><option>DEDUCT</option></select></div>
            <label className="field" style={{ flexDirection: "row", alignItems: "center" }}><input type="checkbox" className="checkbox" checked={form.default_advance_eligible} onChange={(e) => setForm({ ...form, default_advance_eligible: e.target.checked })} /> Advance eligible by default</label>
            <label className="field" style={{ flexDirection: "row", alignItems: "center" }}><input type="checkbox" className="checkbox" checked={form.default_tds_eligible} onChange={(e) => setForm({ ...form, default_tds_eligible: e.target.checked })} /> TDS eligible by default</label>
          </>
        )}
        <div className="field"><label>&nbsp;</label><button className="button primary">Add {kind.singular.toLowerCase()}</button></div>
      </form>
      <div className="table-wrap"><table>
        <thead><tr><th>Code</th><th>Name</th>{kind.extra === "charge" && <th>Defaults</th>}<th>Status</th><th></th></tr></thead>
        <tbody>{rows.data?.map((row) => (
          <tr key={row.id}>
            <td><strong>{row.code}</strong></td>
            <td>{row.name}</td>
            {kind.extra === "charge" && <td>{row.direction} · {row.default_advance_eligible ? "advance" : "no advance"} · {row.default_tds_eligible ? "TDS" : "no TDS"}</td>}
            <td><StatusBadge value={row.active ? "ACTIVE" : "INACTIVE"} /></td>
            <td><button type="button" className="button small" onClick={() => toggle(row)}>{row.active ? "Deactivate" : "Activate"}</button></td>
          </tr>
        ))}</tbody>
      </table></div>
    </section>
  );
}

export function MastersPanel() {
  return <>{KINDS.map((kind) => <MasterTable kind={kind} key={kind.path} />)}</>;
}
```

In `settings/page.tsx`, import `MastersPanel` and render `{(admin || me.data?.role === "OPERATIONS") && <MastersPanel />}` next to the `AdminSettings` mount.

- [ ] **Step 4: Verify**

Run: `cd apps/web && npx prettier --write components/MastersPanel.tsx lib/types.ts app/settings/page.tsx && npm run lint && npm run typecheck && npm run format:check && npm run build`
Expected: all pass. The e2e test still fails until Task 7 replaces the trip form input with a select.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/MastersPanel.tsx apps/web/lib/types.ts apps/web/app/settings/page.tsx apps/web/e2e/core-flow.spec.ts
git commit -m "Manage branch, vehicle type and charge type masters from Settings"
```

---

### Task 7: Selects in the trip, indent and vehicle forms and register filters

**Files:**
- Modify: `apps/web/app/trips/new/page.tsx:344-352`, `apps/web/app/indents/page.tsx:380-396`, `apps/web/app/fleet/page.tsx:139`, `apps/web/app/trips/page.tsx` (branch and vehicle-type filter inputs), `apps/web/app/indents/page.tsx` (branch filter)
- Create: `apps/web/lib/useChoices.ts`

- [ ] **Step 1: Hook**

```ts
// apps/web/lib/useChoices.ts
"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Choices } from "@/lib/types";

export function useChoices() {
  return useQuery({ queryKey: ["choices"], queryFn: () => api<Choices>("/choices/"), staleTime: 60_000 });
}
```

- [ ] **Step 2: Replace inputs with selects**

In each form, call `const choices = useChoices();` near the other queries, then replace the text inputs. Trip form branch (line 344):

```tsx
<label htmlFor="trip-branch">Branch</label>
<select id="trip-branch" className="input" value={form.branch} onChange={(e) => change("branch", e.target.value)}>
  <option value="">No branch</option>
  {choices.data?.branch.map((row) => <option key={row.value} value={row.value}>{row.label}</option>)}
</select>
```

Trip form vehicle type (line 351) uses `id="trip-vehicle-type"`, label text "Vehicle type", `choices.data?.vehicle_type`, first option "Any vehicle type". Indent form: same two selects bound to `form.branch` and `form.required_vehicle_type`. Fleet vehicle form: select bound to `vehicle.vehicle_type` with `required` and a "Select type" empty option. Trip register filters (`branch`, `vehicleType`) and the indent register `branch` filter become selects with an "All" empty option; keep their existing state setters.

When a form is editing a record whose value is inactive (not in choices), append `<option value={form.branch}>{form.branch} (inactive)</option>` so the current value stays selectable; do this only when `form.branch` is non-empty and absent from `choices.data.branch`.

- [ ] **Step 3: Verify**

Run: `cd apps/web && npx prettier --write app lib && npm run lint && npm run typecheck && npm run format:check && npm run build && npx playwright test e2e/core-flow.spec.ts`
Expected: all pass, including the Task 6 test. Existing e2e tests that type free text into these fields (`smoke.spec.ts` onboarding test) must select an existing option instead; update them.

- [ ] **Step 4: Commit**

```bash
git add apps/web
git commit -m "Pick branch and vehicle type from masters in forms and filters"
```

---

### Task 8: Add-charge form on the trip detail page

**Files:**
- Modify: `apps/web/app/trips/[id]/page.tsx` (add a panel below "Cost & advance breakdown")

- [ ] **Step 1: Implement**

Add state and handler inside `TripDetailPage`:

```tsx
const choices = useChoices();
const [charge, setCharge] = useState({ charge_type: "UNLOADING", amount: "", description: "" });
const addCharge = async (event: FormEvent) => {
  event.preventDefault();
  await run(() => api(`/trips/${id}/charges/`, { method: "POST", body: JSON.stringify(charge) }));
  setCharge({ ...charge, amount: "", description: "" });
};
```

Render, only when `!t.active_approval`:

```tsx
<form className="panel" onSubmit={addCharge}>
  <div className="panel-head"><h2>Add charge</h2><span className="eyebrow">Defaults from the charge type master</span></div>
  <div className="panel-body form-grid">
    <div className="field"><label htmlFor="charge-type">Charge type</label><select id="charge-type" className="input" value={charge.charge_type} onChange={(e) => setCharge({ ...charge, charge_type: e.target.value })}>{choices.data?.charge_type.map((row) => <option key={row.value} value={row.value}>{row.label} ({row.direction.toLowerCase()})</option>)}</select></div>
    <div className="field"><label htmlFor="charge-amount">Amount</label><input id="charge-amount" required type="number" min="0" step="0.01" className="input" value={charge.amount} onChange={(e) => setCharge({ ...charge, amount: e.target.value })} /></div>
    <div className="field span-2"><label htmlFor="charge-description">Description</label><input id="charge-description" className="input" value={charge.description} onChange={(e) => setCharge({ ...charge, description: e.target.value })} /></div>
    <div className="field"><label>&nbsp;</label><button className="button" disabled={busy}>Add charge</button></div>
  </div>
</form>
```

Import `useChoices` and make sure `FormEvent` and `useState` are already imported (they are).

- [ ] **Step 2: Verify and commit**

Run: `cd apps/web && npx prettier --write "app/trips/[id]/page.tsx" && npm run lint && npm run typecheck && npm run format:check && npm run build`

```bash
git add "apps/web/app/trips/[id]/page.tsx"
git commit -m "Add charges to a trip from the detail page using the charge type master"
```

---

### Task 9: Documentation and pull request

**Files:**
- Modify: `docs/architecture.md` (masters section), `docs/implementation-status.md` (mark masters delivered), `PRD.md` section 14.12 (note that branch, vehicle type and charge type are now masters)

- [ ] **Step 1: Docs**

Add to `docs/architecture.md`:

```markdown
## Masters

Branch, vehicle type and charge type are lookup tables in the `core` app (`/api/branches/`, `/api/vehicle-types/`, `/api/charge-types/`). Operational records keep string columns but every create or update is validated against active master codes; `TripCharge` references `ChargeType` directly and inherits its direction and eligibility defaults. Masters are deactivated, never deleted, so history keeps its labels. Importers create missing masters only when the user ticks "create missing".
```

- [ ] **Step 2: Full verification**

```bash
cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python manage.py makemigrations --check --dry-run && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings
cd ../web && npm run lint && npm run typecheck && npm run format:check && npm run build && npx playwright test
```

- [ ] **Step 3: Push and open the PR**

```bash
git add docs PRD.md
git commit -m "Document the configurable masters"
git push -u origin feat/configurable-masters
gh pr create --base main --title "Configurable branch, vehicle type and charge type masters" --body "Implements docs/superpowers/specs/2026-09-07-configurable-masters-design.md. See the plan in docs/superpowers/plans/2026-09-07-configurable-masters.md for task-by-task detail. Migrations seed masters from existing data and link every trip charge to its charge type."
```
