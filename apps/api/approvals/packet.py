import hashlib
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from operations.models import Document

BRAND_RED = colors.HexColor("#D71920")
BRAND_ORANGE = colors.HexColor("#F7941D")
INK = colors.HexColor("#2B201D")
MUTED = colors.HexColor("#716662")
LINE = colors.HexColor("#EADFD9")
SOFT = colors.HexColor("#FFF8F0")


def _amount(value):
    return f"INR {value:,.2f}"


def _paragraph(value, style):
    return Paragraph(str(value or "-"), style)


def build_approval_packet_pdf(batch):
    batch = (
        batch.__class__.objects.select_related("client", "requested_by")
        .prefetch_related("items__trip", "items__vendor")
        .get(pk=batch.pk)
    )
    buffer = BytesIO()
    page_size = landscape(A4)
    document = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=13 * mm,
        rightMargin=13 * mm,
        topMargin=24 * mm,
        bottomMargin=17 * mm,
        title=f"Drona Logitech approval {batch.approval_no}",
        author="Drona Logitech",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="PacketTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=18, leading=21, textColor=INK, spaceAfter=3 * mm))
    styles.add(ParagraphStyle(name="PacketBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=8, leading=10, textColor=INK))
    styles.add(ParagraphStyle(name="PacketSmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=7, leading=8.5, textColor=MUTED))
    styles.add(ParagraphStyle(name="PacketHeader", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7, leading=8.5, textColor=colors.white))
    styles.add(ParagraphStyle(name="PacketMoney", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=INK, alignment=TA_RIGHT))

    def page_chrome(canvas, doc):
        width, height = page_size
        canvas.saveState()
        canvas.setFillColor(BRAND_RED)
        canvas.rect(0, height - 7 * mm, width, 7 * mm, fill=1, stroke=0)
        canvas.setFillColor(BRAND_ORANGE)
        canvas.rect(0, height - 8.5 * mm, width, 1.5 * mm, fill=1, stroke=0)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(13 * mm, 8 * mm, f"Approval packet {batch.approval_no} - confidential operational record")
        canvas.drawRightString(width - 13 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    story = []
    logo_path = Path(settings.BASE_DIR).parents[1] / "drona-logo.png"
    if logo_path.exists():
        logo = Image(str(logo_path), width=49 * mm, height=14 * mm)
        logo.hAlign = "LEFT"
        story.append(logo)
    story.append(Paragraph("Payment approval review", styles["PacketTitle"]))

    submitted = timezone.localtime(batch.submitted_at or batch.created_at).strftime("%d %b %Y, %I:%M %p %Z")
    summary = Table(
        [
            ["Approval", batch.approval_no, "Client", batch.client.name, "Purpose", batch.purpose.replace("_", " ").title()],
            ["Requested by", batch.requested_by.get_full_name() or batch.requested_by.username, "Submitted", submitted, "Revision", str(batch.revision_no)],
        ],
        colWidths=[22 * mm, 38 * mm, 20 * mm, 54 * mm, 20 * mm, 38 * mm],
    )
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTNAME", (4, 0), (4, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([summary, Spacer(1, 5 * mm)])

    headers = ["Trip", "Route", "Vendor", "Vehicle / driver", "Freight 100%", "Advance", "Balance", "Charges", "TDS", "Net request"]
    rows = [[_paragraph(header, styles["PacketHeader"]) for header in headers]]
    for item in batch.items.select_related("trip", "vendor").order_by("id"):
        trip = item.trip
        balance = item.freight_rate_snapshot - item.freight_advance_gross
        rows.append([
            _paragraph(f"<b>{trip.trip_no}</b><br/>{trip.deployment_date:%d %b %Y}", styles["PacketBody"]),
            _paragraph(f"{trip.origin}<br/>to {trip.destination}", styles["PacketBody"]),
            _paragraph(item.vendor.display_name, styles["PacketBody"]),
            _paragraph(f"{trip.vehicle_registration_snapshot}<br/>{trip.driver_name_snapshot}", styles["PacketBody"]),
            _paragraph(_amount(item.freight_rate_snapshot), styles["PacketMoney"]),
            _paragraph(f"{_amount(item.freight_advance_gross)}<br/>{item.advance_percent}%", styles["PacketMoney"]),
            _paragraph(_amount(balance), styles["PacketMoney"]),
            _paragraph(_amount(item.advance_eligible_charges - item.advance_stage_deductions), styles["PacketMoney"]),
            _paragraph(_amount(item.tds_this_request), styles["PacketMoney"]),
            _paragraph(_amount(item.net_requested), styles["PacketMoney"]),
        ])
    trip_table = Table(rows, repeatRows=1, colWidths=[31 * mm, 31 * mm, 27 * mm, 31 * mm, 26 * mm, 27 * mm, 25 * mm, 23 * mm, 21 * mm, 27 * mm])
    trip_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FCFAF8")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([trip_table, Spacer(1, 5 * mm)])

    totals = Table(
        [["Total gross requested", _amount(batch.gross_requested), "TDS", _amount(batch.tds_requested), "Net payable", _amount(batch.net_requested)]],
        colWidths=[35 * mm, 37 * mm, 18 * mm, 32 * mm, 27 * mm, 38 * mm],
        hAlign="RIGHT",
    )
    totals.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT),
        ("BOX", (0, 0), (-1, -1), 0.8, BRAND_ORANGE),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("ALIGN", (3, 0), (3, 0), "RIGHT"),
        ("ALIGN", (5, 0), (5, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([totals, Spacer(1, 4 * mm), Paragraph("Review the trip lines and totals above. Use the Approve or Reject button in the WhatsApp message. Decisions are authenticated, timestamped and recorded in the audit trail.", styles["PacketSmall"])])
    document.build(story, onFirstPage=page_chrome, onLaterPages=page_chrome)
    return buffer.getvalue()


def ensure_approval_packet(batch, uploaded_by):
    existing = Document.objects.filter(
        object_type="approval",
        object_id=str(batch.pk),
        kind=Document.Kind.APPROVAL_PACKET,
        scan_status="CLEAN",
    ).first()
    if existing:
        return existing
    content = build_approval_packet_pdf(batch)
    filename = f"{batch.approval_no}-approval-packet.pdf"
    return Document.objects.create(
        object_type="approval",
        object_id=str(batch.pk),
        kind=Document.Kind.APPROVAL_PACKET,
        file=ContentFile(content, name=filename),
        original_name=filename,
        content_type="application/pdf",
        size=len(content),
        uploaded_by=uploaded_by,
        sha256=hashlib.sha256(content).hexdigest(),
        scan_status="CLEAN",
        scan_detail="Generated by Drona Logitech",
    )
