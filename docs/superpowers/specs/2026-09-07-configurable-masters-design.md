# Configurable Masters Design

Date: 2026-09-07
Status: approved in conversation, awaiting implementation

## Problem

PRD section 14.12 lists branch or cost centre, vehicle types and charge types as settings. Today branch and vehicle type are free-text columns on `Client`, `Indent`, `Vehicle` and `Trip`, and charge types are a fixed `TextChoices` enum on `TripCharge`. Values drift ("32 FT MXL", "32ft MXL", "32 FT"), reports group inconsistently, and adding a charge type needs a release.

## Decisions

- Masters are lookup tables. Existing string columns stay and are validated against active master codes. Only `TripCharge` gains a foreign key.
- Validation is strict: an unknown or inactive value is rejected on create and update. Existing data is migrated into the masters first so nothing already stored becomes invalid.
- Charge types replace the enum and carry defaults for direction, advance eligibility and TDS eligibility. Per-line overrides remain.
- Cost centre stays free text with an optional default on the branch.
- Deactivating a master never rewrites history; it only blocks new use.

## Data model (app `core`)

| Model | Fields |
|---|---|
| `Branch` | `code` (unique, uppercase, max 40), `name` (max 100), `default_cost_center` (max 100, blank), `active` (default true), timestamps |
| `VehicleType` | `code` (unique, uppercase, max 40), `name` (max 100), `capacity_hint` (decimal 12,3, null), `active`, timestamps |
| `ChargeType` | `code` (unique, uppercase, max 30), `name` (max 100), `direction` (ADD or DEDUCT), `default_advance_eligible` (bool), `default_tds_eligible` (bool), `sort_order` (int, default 100), `active`, timestamps |

Codes are normalised with `normalise_code(value) = " ".join(value.split()).upper()`.

`operations.TripCharge` gains `charge_type_ref = ForeignKey(ChargeType, on_delete=PROTECT, related_name="charges")`. The existing `charge_type` string column is kept as the denormalised code so reports, importers and the MIS export keep working. The `TripCharge.ChargeType` enum remains only as the seed list.

## Migrations

1. `core`: create the three tables.
2. `core` data migration: seed `ChargeType` from the enum with today's implicit defaults (UNLOADING: ADD, advance-eligible, not TDS-eligible; DEDUCTION: DEDUCT; every other code: ADD, not advance-eligible, not TDS-eligible). Seed `Branch` from distinct non-blank `Client.default_branch`, `Indent.branch`, `Trip.branch`. Seed `VehicleType` from distinct non-blank `Vehicle.vehicle_type`, `Indent.required_vehicle_type`, `Trip.vehicle_type_snapshot`. Values are normalised; the first spelling seen becomes `name`. Duplicates that differ only by case or whitespace collapse into one record.
3. `operations`: add `charge_type_ref` nullable, populate from `charge_type`, then alter to non-null. Existing string columns on `Client`, `Indent`, `Vehicle` and `Trip` are rewritten to their normalised code in the same migration so validation passes on the next edit.

## Validation

`core/masters.py` exposes `resolve_master(model, value, *, field, allow_blank)`: normalises, looks up an active record by code, returns the canonical code, or raises `serializers.ValidationError({field: "... is not an active <master>"})`.

- `ClientSerializer.default_branch`, `IndentSerializer.branch` and `required_vehicle_type`, `TripSerializer.branch`, `VehicleSerializer.vehicle_type` call it (blank allowed where the model allows blank).
- `TripChargeSerializer` accepts `charge_type` as a code, resolves it to `charge_type_ref`, and fills `direction`, `advance_eligible` and `tds_eligible` from the master when the request omits them.
- `TripSerializer.create` builds the unloading advance line through the same path.
- Importers: the legacy, indent and MIS importers resolve branch and vehicle type through `resolve_or_create_master(model, value, create_missing)`. With `create_missing` false an unknown value is a preflight error; with it true the master is created inactive-free (active) with the raw value as name.

## API

- `GET/POST/PATCH /api/branches/`, `/api/vehicle-types/`, `/api/charge-types/`. Read requires `masters.read` (every role has it); write requires `masters.write` (Operations, Admin). No DELETE; `active=false` is the only way to retire a record.
- `GET /api/choices/` adds `branch`, `vehicle_type` and `charge_type` lists of active records, each `{value: code, label: name}` plus, for charge types, `direction`, `default_advance_eligible`, `default_tds_eligible`.

## Frontend

- `components/MastersPanel.tsx` on the Settings page (Operations and Admin): three tables with an inline add form and an activate or deactivate toggle, following the approval-rules panel pattern.
- Trip form and indent form: branch and vehicle type become selects fed by `/api/choices/`; the trip register and indent register branch and vehicle-type filters become selects.
- Fleet page: vehicle type select.
- Trip detail: a small "Add charge" form (charge type select, amount, description) posting to the existing `/api/trips/{id}/charges/` endpoint, shown while the trip has no active approval snapshot.

## Testing

Backend: migration seeding collapses "32 ft mxl" and "32 FT MXL" into one record; each serializer rejects an unknown or inactive code; charge defaults are inherited and overridable; legacy importer creates missing masters only with `create_missing`; choices endpoint stays within four queries. Frontend: a Playwright test adds a vehicle type in Settings and selects it in the new-trip form.

## Out of scope

Foreign keys on the string columns, cost-centre master, vendor or driver masters, bulk import of masters.
