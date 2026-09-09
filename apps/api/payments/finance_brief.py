"""The payout brief that the FINANCE_READY notification carries.

Final approval used to tell finance only that an approval was ready and hand
them a link, so whoever had to release the money still had to open the app to
find the payee, the verified bank account and the evidence behind each trip.
This module renders the same facts the finance queue already assembles
(payments.views.FinancePendingView) as the plain text those notifications are
built from; integrations.email_builder turns that text into the branded layout.

Full account numbers stay out of it on purpose. They are stored encrypted and
the finance screen only ever shows the masked form, so a notification - which
lands in a mailbox nobody had to authenticate into - must not widen that
exposure. The masked number, holder and IFSC are enough to recognise the payee;
the transfer itself is still made from the finance queue.
"""

import os
import re
from decimal import Decimal

from django.db.models import Prefetch, Q

from approvals.models import PaymentApprovalItem
from operations.models import Document, Trip, VendorBankAccount

from .models import PaymentAllocation
from .services import paid_totals

DOCUMENT_LABELS = dict(Document.Kind.choices)
# The evidence finance looks for before releasing money against a trip.
TRIP_EVIDENCE = (Document.Kind.POD, Document.Kind.LR, Document.Kind.VENDOR_INVOICE)

# Payment-critical evidence first, so a tight budget still attaches what finance
# needs to release the money rather than an arbitrary slice of the pack.
ATTACHMENT_PRIORITY = (
    Document.Kind.CANCELLED_CHEQUE,
    Document.Kind.VENDOR_INVOICE,
    Document.Kind.POD,
    Document.Kind.LR,
    Document.Kind.PAN,
    Document.Kind.AADHAAR,
)
DEFAULT_ATTACHMENT_LIMIT_MB = 15
UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _amount(value):
    return f"{Decimal(value or 0):,.2f}"


def _labels(documents):
    """Deduplicated document kinds, in the order they were uploaded."""
    seen = []
    for document in documents:
        label = DOCUMENT_LABELS.get(document.kind, document.kind)
        if label not in seen:
            seen.append(label)
    return seen


def _payable_items(batch):
    """Approved lines that still owe money, mirroring the finance queue filter."""
    items = (
        batch.items.filter(item_status=PaymentApprovalItem.Status.APPROVED)
        .exclude(
            trip__status__in=[
                Trip.Status.CANCELLED,
                Trip.Status.CANCELLED_WITH_PAYMENT,
                Trip.Status.SETTLED,
            ]
        )
        .select_related("vendor", "trip")
        .prefetch_related(
            Prefetch("allocations", queryset=PaymentAllocation.objects.select_related("payment"))
        )
        .order_by("vendor__display_name", "id")
    )
    payable = []
    for item in items:
        paid = paid_totals(item)
        if item.gross_requested - paid["gross"] > 0:
            payable.append((item, paid))
    return payable


def _documents_by_owner(vendor_ids, trip_ids, driver_ids, bank_ids):
    documents = Document.objects.filter(scan_status="CLEAN").filter(
        Q(object_type="vendor", object_id__in=[str(value) for value in vendor_ids])
        | Q(object_type="trip", object_id__in=[str(value) for value in trip_ids])
        | Q(object_type="driver", object_id__in=[str(value) for value in driver_ids])
        | Q(object_type="vendor_bank_account", object_id__in=[str(value) for value in bank_ids])
    )
    owned = {}
    for document in documents:
        owned.setdefault((document.object_type, document.object_id), []).append(document)
    return owned


def vendor_payouts(batch):
    """Group the payable lines of a batch into one payout block per vendor."""
    payable = _payable_items(batch)
    if not payable:
        return []

    vendor_ids = {item.vendor_id for item, _paid in payable}
    accounts = list(
        VendorBankAccount.objects.filter(vendor_id__in=vendor_ids).order_by(
            "vendor_id", "-active", "id"
        )
    )
    documents = _documents_by_owner(
        vendor_ids,
        {item.trip_id for item, _paid in payable},
        {item.trip.driver_id for item, _paid in payable},
        {account.pk for account in accounts},
    )

    groups = {}
    for item, paid in payable:
        group = groups.setdefault(
            item.vendor_id,
            {
                "vendor": item.vendor,
                "accounts": [],
                "kyc": _labels(documents.get(("vendor", str(item.vendor_id)), [])),
                "gross": Decimal("0.00"),
                "tds": Decimal("0.00"),
                "net": Decimal("0.00"),
                "trips": [],
                # Every evidence row behind this payout, kept alongside the filename
                # prefix that tells two vendors' scan.pdf apart in one mailbox.
                "documents": [
                    (document, item.vendor.vendor_code)
                    for document in documents.get(("vendor", str(item.vendor_id)), [])
                ],
            },
        )
        gross = item.gross_requested - paid["gross"]
        tds = item.tds_this_request - paid["tds"]
        net = item.net_requested - paid["net"]
        group["gross"] += gross
        group["tds"] += tds
        group["net"] += net
        trip_documents = documents.get(("trip", str(item.trip_id)), []) + documents.get(
            ("driver", str(item.trip.driver_id)), []
        )
        evidence = _labels(trip_documents)
        group["documents"].extend(
            (document, item.trip.trip_no) for document in trip_documents
        )
        group["trips"].append(
            {
                "trip": item.trip,
                "gross": gross,
                "tds": tds,
                "net": net,
                "evidence": evidence,
                "missing": [
                    DOCUMENT_LABELS[kind]
                    for kind in TRIP_EVIDENCE
                    if DOCUMENT_LABELS[kind] not in evidence
                ],
            }
        )

    for account in accounts:
        group = groups.get(account.vendor_id)
        if not group or not account.active:
            continue
        cheques = documents.get(("vendor_bank_account", str(account.pk)), [])
        group["documents"].extend(
            (document, group["vendor"].vendor_code) for document in cheques
        )
        group["accounts"].append(
            {"account": account, "cancelled_cheque": bool(cheques)}
        )
    return list(groups.values())


def attachment_limit_bytes():
    """Total budget for one finance email, overridable per deployment."""
    try:
        megabytes = int(os.getenv("FINANCE_EMAIL_ATTACHMENT_LIMIT_MB", "") or DEFAULT_ATTACHMENT_LIMIT_MB)
    except ValueError:
        megabytes = DEFAULT_ATTACHMENT_LIMIT_MB
    return max(0, megabytes) * 1024 * 1024


def _attachment_filename(document, prefix):
    """`V-900-PAN-scan.pdf` - two vendors can both have uploaded `scan.pdf`."""
    name = UNSAFE_FILENAME_RE.sub("-", f"{prefix}-{document.kind}-{document.original_name}")
    return name.strip("-")[:180] or f"document-{document.pk}"


def _attachment_rank(entry):
    document, _prefix = entry
    # Driver KYC ranks below every vendor and trip document of the same kind.
    scope = 1 if document.object_type == "driver" else 0
    try:
        kind = ATTACHMENT_PRIORITY.index(document.kind)
    except ValueError:
        kind = len(ATTACHMENT_PRIORITY)
    return (scope, kind, document.pk)


def attachment_plan(groups, *, limit_bytes=None):
    """Pick the evidence that fits in one mailbox, in payment-critical order.

    Chosen at queue time rather than at delivery so the body can name what is
    attached and what was left behind; `Document.size` is on the row, so nothing
    is opened to weigh it.
    """
    budget = attachment_limit_bytes() if limit_bytes is None else limit_bytes
    entries = []
    seen = set()
    for group in groups:
        for document, prefix in group.get("documents", []):
            if document.pk in seen:
                continue
            seen.add(document.pk)
            entries.append((document, prefix))
    entries.sort(key=_attachment_rank)

    specs = []
    skipped = []
    used = 0
    for document, prefix in entries:
        size = document.size or 0
        if used + size > budget:
            # Keep scanning: a small POD should still travel when one oversized
            # invoice has eaten most of the budget.
            skipped.append(f"{DOCUMENT_LABELS.get(document.kind, document.kind)} ({prefix})")
            continue
        used += size
        specs.append({"id": document.pk, "filename": _attachment_filename(document, prefix)})
    return specs, skipped


def _account_lines(entry, *, index=0):
    account = entry["account"]
    lines = [f"Bank account {index}:"] if index else []
    lines.append(f"Bank: {account.bank_name}")
    lines.append(f"Account holder: {account.account_holder}")
    lines.append(f"Account number: {account.masked_account_number}")
    lines.append(f"IFSC: {account.ifsc_code}")
    lines.append(f"Cancelled cheque: {'On file' if entry['cancelled_cheque'] else 'Not uploaded'}")
    return lines


def _vendor_lines(group, *, position, total):
    vendor = group["vendor"]
    heading = vendor.display_name
    if total > 1:
        heading = f"Payout {position} of {total} - {vendor.display_name}"
    lines = [f"{heading}:", f"Vendor code: {vendor.vendor_code}"]
    if vendor.legal_name and vendor.legal_name != vendor.display_name:
        lines.append(f"Legal name: {vendor.legal_name}")
    if vendor.tax_identifier:
        lines.append(f"PAN / GSTIN: {vendor.tax_identifier}")
    if vendor.payment_terms:
        lines.append(f"Payment terms: {vendor.payment_terms}")
    lines.append(f"Gross approved: {_amount(group['gross'])}")
    lines.append(f"TDS deducted: {_amount(group['tds'])}")
    lines.append(f"Net to transfer: {_amount(group['net'])}")
    lines.append(f"Vendor KYC: {', '.join(group['kyc']) if group['kyc'] else 'Not uploaded'}")

    accounts = group["accounts"]
    if not accounts:
        lines.append(
            f"No active bank account is on file for {vendor.display_name}. "
            "Add and verify one under Vendors before releasing this payout."
        )
    else:
        for index, entry in enumerate(accounts, start=1):
            lines.extend(_account_lines(entry, index=index if len(accounts) > 1 else 0))
        if len(accounts) > 1:
            lines.append(
                "More than one verified account is on file. "
                "Confirm the payee account in the finance queue before paying."
            )

    for row in group["trips"]:
        trip = row["trip"]
        lines.append(
            " | ".join(
                [
                    trip.trip_no,
                    f"{trip.origin} → {trip.destination}",
                    trip.vehicle_registration_snapshot or "Vehicle not recorded",
                    f"Docs: {', '.join(row['evidence']) if row['evidence'] else 'none uploaded'}",
                    f"Gross {_amount(row['gross'])}",
                    f"TDS {_amount(row['tds'])}",
                    f"Net {_amount(row['net'])}",
                ]
            )
        )

    missing = sorted({label for row in group["trips"] for label in row["missing"]})
    if missing:
        lines.append(f"Missing trip evidence: {', '.join(missing)}.")
    return lines


def _attachment_lines(groups, attachments, skipped):
    kinds = []
    by_id = {
        document.pk: document
        for group in groups
        for document, _prefix in group.get("documents", [])
    }
    for spec in attachments:
        document = by_id.get(spec["id"])
        label = DOCUMENT_LABELS.get(document.kind, document.kind) if document else "Document"
        if label not in kinds:
            kinds.append(label)
    lines = []
    if attachments:
        lines.append(f"Attached: {len(attachments)} file{'s' if len(attachments) != 1 else ''}")
    if kinds:
        lines.append(f"Attached documents: {', '.join(kinds)}")
    if skipped:
        count = "One document" if len(skipped) == 1 else f"{len(skipped)} documents"
        verb = "exceeds" if len(skipped) == 1 else "exceed"
        lines.append(
            f"{count} {verb} the email attachment limit and can be opened from the "
            f"finance queue: {', '.join(skipped)}."
        )
    return lines


def build_payout_brief(groups, *, attachments=None, skipped=None):
    """Per-vendor payout detail, or "" when nothing on the batch is payable."""
    if not groups:
        return ""
    lines = []
    for position, group in enumerate(groups, start=1):
        lines.extend(_vendor_lines(group, position=position, total=len(groups)))
    attachments = attachments or []
    skipped = skipped or []
    if attachments or skipped:
        lines.extend(_attachment_lines(groups, attachments, skipped))
    if attachments:
        lines.append(
            "The attached files are the evidence listed above; the finance queue "
            "holds the same documents and records the transfer."
        )
    else:
        lines.append(
            "The documents listed above are downloadable from the finance queue, "
            "where the transfer is recorded."
        )
    return "\n".join(lines)


def payout_summary(groups):
    """One line for the in-app feed and the outbound message log."""
    if not groups:
        return ""
    trips = sum(len(group["trips"]) for group in groups)
    net = sum((group["net"] for group in groups), Decimal("0.00"))
    vendor_label = f"{len(groups)} vendor{'s' if len(groups) != 1 else ''}"
    trip_label = f"{trips} trip{'s' if trips != 1 else ''}"
    return f"{vendor_label}, {trip_label}, net {_amount(net)}"
