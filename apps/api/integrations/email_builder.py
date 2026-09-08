"""Turn the plain-text body of any outbound email into a branded HTML version.

Every email in this codebase is queued as plain text (see DEFAULT_TEMPLATES in
integrations.services, the vendor bodies in approvals/payments, and the OTP copy
in accounts.otp). Rather than rewrite each call site, this module reads the text
that is already being sent and infers its structure, so a new email added later
is styled without any extra work. The plain-text part is still sent unchanged as
the multipart/alternative fallback.
"""

import re

from .email_layout import AMBER, BRAND_RED, GREEN, render_document

# A friendlier heading than the raw subject, which carries reference prefixes.
EVENT_TITLES = {
    "APPROVAL_REQUESTED": "Approval requested",
    "APPROVAL_COMPLETED": "Approval completed",
    "APPROVAL_REJECTED": "Approval rejected",
    "CHANGES_REQUESTED": "Changes requested",
    "FINANCE_READY": "Ready for payment",
    "PAYMENT_COMPLETED": "Payment completed",
    "PAYMENT_FAILED": "Payment notification failed",
    "SETTLEMENT_PENDING": "Settlement pending",
    "MENTION": "You were mentioned",
    "LOGIN_OTP": "Your sign-in code",
    "PASSWORD_RESET_OTP": "Password recovery code",
}

EVENT_ACCENTS = {
    "APPROVAL_COMPLETED": GREEN,
    "PAYMENT_COMPLETED": GREEN,
    "APPROVAL_REQUESTED": AMBER,
    "FINANCE_READY": AMBER,
    "SETTLEMENT_PENDING": AMBER,
    "CHANGES_REQUESTED": AMBER,
}

EVENT_BUTTONS = {
    "APPROVAL_REQUESTED": "Review approval",
    "FINANCE_READY": "Open in finance",
    "APPROVAL_COMPLETED": "View approval",
    "APPROVAL_REJECTED": "View approval",
    "CHANGES_REQUESTED": "View approval",
    "PAYMENT_COMPLETED": "View payment",
    "SETTLEMENT_PENDING": "View trip",
}

OTP_EVENTS = {"LOGIN_OTP", "PASSWORD_RESET_OTP"}
OTP_LEADS = {
    "LOGIN_OTP": "Use this code to finish signing in.",
    "PASSWORD_RESET_OTP": "Use this code to reset your password.",
}

URL_RE = re.compile(r"https?://\S+")
REFERENCE_RE = re.compile(r"\b(?:PA|PAY|TRIP|TR|INV)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
OTP_CODE_RE = re.compile(r"\b(\d{4,8})\b")
# Split on sentence-ending punctuation followed by a space, so a decimal amount
# such as "2,47,500.00" is never mistaken for the end of a sentence.
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
# "UTR: ABC123" is a fact; "Payment PAY-1 processed on 2026-01-01" is a sentence.
FACT_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 /_-]{0,28}):\s*(\S.*)$")
# "Gross 1200.00" inside a pipe-delimited line item.
METRIC_RE = re.compile(r"^([A-Za-z][A-Za-z ]{0,18}?)\s+([-+]?[\d,]+(?:\.\d+)?|\S+)$")


def _sentences(text):
    return [part.strip() for part in SENTENCE_RE.split(text.strip()) if part.strip()]


def _split_line_item(line):
    cells = [cell.strip() for cell in line.split("|")]
    cells = [cell for cell in cells if cell]
    if len(cells) < 2:
        return None
    metrics = []
    body_cells = []
    for cell in cells[1:]:
        match = METRIC_RE.match(cell)
        if match:
            metrics.append((match.group(1).strip(), match.group(2).strip()))
        else:
            body_cells.append(cell)
    return {"title": cells[0], "subtitle": " · ".join(body_cells), "metrics": metrics}


class _Document:
    """Collects blocks, keeping consecutive line items and facts grouped together."""

    def __init__(self):
        self.blocks = []
        self._items = []
        self._facts = []

    def _flush(self):
        if self._items:
            self.blocks.append(("items", self._items))
            self._items = []
        if self._facts:
            self.blocks.append(("facts", self._facts))
            self._facts = []

    def add_item(self, item):
        if self._facts:
            self._flush()
        self._items.append(item)

    def add_fact(self, label, value):
        if self._items:
            self._flush()
        self._facts.append((label, value))

    def add_block(self, kind, value):
        self._flush()
        self.blocks.append((kind, value))

    def add_text(self, text):
        """Route each sentence to a fact row or a paragraph."""
        for sentence in _sentences(text):
            fact = FACT_RE.match(sentence.rstrip("."))
            if fact and len(fact.group(1).split()) <= 4 and len(fact.group(2).split()) <= 6:
                self.add_fact(fact.group(1).strip(), fact.group(2).strip())
            else:
                self.add_block("paragraph", sentence)

    def result(self):
        self._flush()
        return self.blocks


def _parse_body(body, *, event_key):
    document = _Document()
    has_button = False

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        url_match = URL_RE.search(line)
        if url_match:
            url = url_match.group(0).rstrip(".,;)")
            leading = line[: url_match.start()].strip()
            # "Approval PA-1 is waiting. Review securely: <url>" keeps the first
            # sentence as body copy and uses only the trailing clause as a label.
            segments = _sentences(leading)
            lead_in = ""
            if segments and segments[-1].endswith(":"):
                lead_in = segments.pop().rstrip(":").strip()
            if segments:
                document.add_text(" ".join(segments))
            if not has_button:
                has_button = True
                document.add_block(
                    "button",
                    {"url": url, "label": EVENT_BUTTONS.get(event_key) or lead_in[:40] or "Open in VMS"},
                )
            trailing = line[url_match.end():].strip(" .,;)")
            if trailing:
                document.add_text(trailing)
            continue

        item = _split_line_item(line) if "|" in line else None
        if item:
            document.add_item(item)
            continue

        document.add_text(line)

    return document.result()


def _otp_blocks(body, event_key):
    """The code is the whole message, so lift it out and keep the warning below it."""
    match = OTP_CODE_RE.search(body)
    if not match:
        return [("paragraph", body.strip())]
    code = match.group(1)
    # Removing the code leaves a dangling fragment ("OTP Code: ." or
    # "is your password recovery code."); drop it and keep the real sentences.
    sentences = _sentences(body.replace(code, "", 1))
    while sentences:
        head = sentences[0]
        stripped = head.strip(" .:")
        if not stripped or stripped[0].islower() or stripped.lower().startswith("otp code"):
            sentences.pop(0)
            continue
        break
    blocks = []
    lead = OTP_LEADS.get(event_key)
    if lead:
        blocks.append(("paragraph", lead))
    blocks.append(("code", {"code": code, "note": " ".join(sentences)}))
    return blocks


def build_document(*, subject, body, event_key="", object_type=""):
    body = body or ""
    title = EVENT_TITLES.get(event_key) or subject or "Notification"

    if event_key in OTP_EVENTS:
        blocks = _otp_blocks(body, event_key)
        eyebrow = "Security"
        footer_note = (
            "You received this because someone asked to sign in to your account. "
            "If that was not you, ignore this email and your account stays unchanged."
        )
    else:
        blocks = _parse_body(body, event_key=event_key)
        reference = REFERENCE_RE.search(subject or "") or REFERENCE_RE.search(body)
        eyebrow = reference.group(0) if reference else ""
        footer_note = (
            "You received this because you are listed on this record. "
            "Replying to this email adds your reply as a comment on the record."
            if object_type in {"approval", "payment", "trip"}
            else "You received this because you are listed on this record."
        )

    return {
        "title": title,
        "eyebrow": eyebrow,
        "accent": EVENT_ACCENTS.get(event_key) or BRAND_RED,
        "preheader": " ".join(body.split())[:140],
        "blocks": blocks,
        "footer_note": footer_note,
    }


def render_email_html(*, subject, body, event_key="", object_type=""):
    return render_document(
        build_document(subject=subject, body=body, event_key=event_key, object_type=object_type)
    )
