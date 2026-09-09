"""Branded HTML shell for every outbound email.

Email clients strip <style> blocks, ignore flexbox and drop external CSS, so the
layout here is table-based with inline styles. The <style> block only carries the
mobile and dark-mode overrides that inline styles cannot express.
"""

import os
from html import escape

from django.conf import settings

# Mirrors apps/web/app/globals.css so mail matches the product.
INK = "#2b201d"
MUTED = "#716662"
LINE = "#eadfd9"
CANVAS = "#f8f5f2"
PAPER = "#ffffff"
BRAND_RED = "#d71920"
BRAND_DARK = "#241817"
AMBER = "#f7941d"
GREEN = "#1f7a4d"

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"
CARD_WIDTH = 600


def brand():
    """Branding is env-driven so a deployment can rebrand without a code change."""
    return {
        "name": os.getenv("EMAIL_BRAND_NAME", "Drona Logitech"),
        "tagline": os.getenv("EMAIL_BRAND_TAGLINE", "Vehicle Management System"),
        "logo_url": os.getenv("EMAIL_LOGO_URL", "").strip(),
        "support_email": os.getenv("EMAIL_SUPPORT_EMAIL", "").strip(),
        "address": os.getenv("EMAIL_BRAND_ADDRESS", "").strip(),
        "web_origin": getattr(settings, "WEB_ORIGIN", "").rstrip("/"),
        "primary": os.getenv("EMAIL_PRIMARY_COLOR", BRAND_RED).strip() or BRAND_RED,
    }


def _cell(content, *, padding="0 32px"):
    return (
        f'<tr><td class="dl-pad" style="padding:{padding};font-family:{FONT};">'
        f"{content}</td></tr>"
    )


def _paragraph(text):
    return (
        f'<p class="dl-text" style="margin:0 0 14px;font-family:{FONT};font-size:15px;'
        f'line-height:1.62;color:{INK};">{escape(text)}</p>'
    )


def _note(text):
    return (
        f'<p class="dl-muted" style="margin:0 0 14px;font-family:{FONT};font-size:13px;'
        f'line-height:1.6;color:{MUTED};">{escape(text)}</p>'
    )


def _section(text):
    """A rule plus a bold label, so one email can carry several payout blocks."""
    return (
        f'<div class="dl-title dl-rule" style="margin:20px 0 12px;padding-top:16px;'
        f'border-top:1px solid {LINE};font-family:{FONT};font-size:15px;font-weight:700;'
        f'color:{INK};">{escape(text)}</div>'
    )


def _code(payload):
    code = escape(str(payload.get("code", "")))
    note = payload.get("note", "")
    block = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:4px 0 16px;"><tr>'
        f'<td class="dl-panel" align="center" style="padding:22px 16px;background:{CANVAS};'
        f'border:1px dashed {LINE};border-radius:10px;">'
        f'<div class="dl-title" style="font-family:{MONO};font-size:32px;font-weight:700;'
        f'letter-spacing:8px;color:{INK};line-height:1;">{code}</div>'
        "</td></tr></table>"
    )
    return block + (_note(note) if note else "")


def _facts(rows):
    cells = []
    for label, value in rows:
        cells.append(
            f'<tr><td class="dl-muted" style="padding:9px 0;font-family:{FONT};font-size:13px;'
            f'color:{MUTED};border-bottom:1px solid {LINE};white-space:nowrap;">{escape(label)}</td>'
            f'<td class="dl-text" align="right" style="padding:9px 0;font-family:{FONT};'
            f'font-size:14px;font-weight:600;color:{INK};border-bottom:1px solid {LINE};">'
            f"{escape(value)}</td></tr>"
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:2px 0 18px;">{"".join(cells)}</table>'
    )


def _items(rows):
    """Line items render as stacked cards; a five-column table is unreadable on a phone."""
    cards = []
    for row in rows:
        title = escape(row.get("title", ""))
        subtitle = escape(row.get("subtitle", ""))
        metrics = "".join(
            f'<td class="dl-stack" style="padding:0 18px 0 0;font-family:{FONT};">'
            f'<span class="dl-muted" style="display:block;font-size:11px;letter-spacing:0.6px;'
            f'text-transform:uppercase;color:{MUTED};">{escape(label)}</span>'
            f'<span class="dl-text" style="display:block;font-size:14px;font-weight:600;'
            f'color:{INK};padding-top:2px;">{escape(value)}</span></td>'
            for label, value in row.get("metrics", [])
        )
        body = (
            f'<div class="dl-text" style="font-family:{FONT};font-size:14px;font-weight:700;'
            f'color:{INK};">{title}</div>'
        )
        if subtitle:
            body += (
                f'<div class="dl-muted" style="font-family:{FONT};font-size:13px;color:{MUTED};'
                f'padding-top:2px;">{subtitle}</div>'
            )
        if metrics:
            body += (
                '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                f'style="margin-top:10px;"><tr>{metrics}</tr></table>'
            )
        cards.append(
            f'<tr><td class="dl-panel" style="padding:14px 16px;background:{CANVAS};'
            f'border:1px solid {LINE};border-radius:8px;">{body}</td></tr>'
            '<tr><td style="height:8px;line-height:8px;font-size:0;">&nbsp;</td></tr>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:2px 0 12px;">{"".join(cards)}</table>'
    )


def _button(payload, accent):
    raw_url = payload.get("url", "")
    url = escape(raw_url, quote=True)
    label = escape(payload.get("label", "Open"))
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:6px 0 18px;"><tr>'
        f'<td align="center" bgcolor="{accent}" style="border-radius:8px;">'
        "<!--[if mso]>&nbsp;<![endif]-->"
        f'<a href="{url}" target="_blank" rel="noopener" '
        f'style="display:inline-block;padding:13px 30px;font-family:{FONT};font-size:15px;'
        'font-weight:600;line-height:1;color:#ffffff;text-decoration:none;border-radius:8px;">'
        f"{label}</a>"
        "<!--[if mso]>&nbsp;<![endif]-->"
        "</td></tr></table>"
        f'<p class="dl-muted" style="margin:0 0 14px;font-family:{FONT};font-size:12px;'
        f'line-height:1.5;color:{MUTED};word-break:break-all;">'
        "If the button does not work, paste this link into your browser:<br>"
        f"{escape(raw_url)}</p>"
    )


BLOCK_RENDERERS = {
    "paragraph": lambda value, accent: _paragraph(value),
    "note": lambda value, accent: _note(value),
    "section": lambda value, accent: _section(value),
    "code": lambda value, accent: _code(value),
    "facts": lambda value, accent: _facts(value),
    "items": lambda value, accent: _items(value),
    "button": _button,
}


def _header(info, accent):
    if info["logo_url"]:
        mark = (
            f'<img src="{escape(info["logo_url"], quote=True)}" width="132" '
            f'alt="{escape(info["name"])}" '
            'style="display:block;border:0;height:auto;max-width:132px;">'
        )
    else:
        mark = (
            f'<div style="font-family:{FONT};font-size:19px;font-weight:700;letter-spacing:1.6px;'
            f'text-transform:uppercase;color:#ffffff;line-height:1.2;">{escape(info["name"])}</div>'
        )
    return (
        f'<tr><td style="height:4px;line-height:4px;font-size:0;background:{accent};">&nbsp;</td></tr>'
        f'<tr><td class="dl-pad" style="padding:24px 32px;background:{BRAND_DARK};">{mark}'
        f'<div style="font-family:{FONT};font-size:12px;letter-spacing:0.8px;'
        'text-transform:uppercase;color:#b9a9a4;padding-top:6px;">'
        f'{escape(info["tagline"])}</div></td></tr>'
    )


def _footer(info, footer_note):
    bits = [escape(f"{info['name']} - {info['tagline']}")]
    if info["address"]:
        bits.append(escape(info["address"]))
    if info["support_email"]:
        bits.append(
            f'Questions? <a href="mailto:{escape(info["support_email"], quote=True)}" '
            f'style="color:{MUTED};">{escape(info["support_email"])}</a>'
        )
    lines = "<br>".join(bits)
    note = (
        f'<p class="dl-muted" style="margin:0 0 8px;font-family:{FONT};font-size:12px;'
        f'line-height:1.6;color:{MUTED};">{escape(footer_note)}</p>'
        if footer_note
        else ""
    )
    return (
        f'<tr><td class="dl-pad" style="padding:20px 32px 28px;border-top:1px solid {LINE};">'
        f"{note}"
        f'<p class="dl-muted" style="margin:0;font-family:{FONT};font-size:12px;line-height:1.6;'
        f'color:{MUTED};">{lines}</p></td></tr>'
    )


HEAD_STYLE = (
    ":root{color-scheme:light dark;supported-color-schemes:light dark;}"
    "body,table,td,a{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}"
    "img{-ms-interpolation-mode:bicubic;}"
    "@media only screen and (max-width:620px){"
    ".dl-card{width:100%!important;border-radius:0!important;"
    "border-left:0!important;border-right:0!important;}"
    ".dl-pad{padding-left:20px!important;padding-right:20px!important;}"
    ".dl-stack{display:block!important;width:100%!important;padding:0 0 10px 0!important;}}"
    "@media (prefers-color-scheme:dark){"
    ".dl-body{background:#171010!important;}"
    f".dl-card{{background:{BRAND_DARK}!important;border-color:#3d2c29!important;}}"
    ".dl-text,.dl-title{color:#f7efe9!important;}"
    ".dl-muted{color:#b3a29c!important;}"
    ".dl-panel{background:#30221f!important;border-color:#463330!important;}"
    ".dl-rule{border-top-color:#463330!important;}}"
)


def render_document(document):
    """Turn a structured document (see email_builder) into a full HTML email."""
    info = brand()
    accent = document.get("accent") or info["primary"]
    rows = [_header(info, accent)]

    heading = ""
    if document.get("eyebrow"):
        heading += (
            f'<div style="font-family:{FONT};font-size:11px;font-weight:700;letter-spacing:1.4px;'
            f'text-transform:uppercase;color:{accent};padding-bottom:8px;">'
            f'{escape(document["eyebrow"])}</div>'
        )
    heading += (
        f'<h1 class="dl-title" style="margin:0 0 16px;font-family:{FONT};font-size:23px;'
        f'line-height:1.3;font-weight:700;color:{INK};">'
        f'{escape(document.get("title", ""))}</h1>'
    )
    rows.append(_cell(heading, padding="30px 32px 0"))

    body = "".join(
        BLOCK_RENDERERS[kind](value, accent)
        for kind, value in document.get("blocks", [])
        if kind in BLOCK_RENDERERS
    )
    rows.append(_cell(body, padding="0 32px 6px"))
    rows.append(_footer(info, document.get("footer_note", "")))

    return (
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
        '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">'
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="x-apple-disable-message-reformatting">'
        '<meta name="color-scheme" content="light dark">'
        f'<title>{escape(document.get("title", ""))}</title>'
        f"<style>{HEAD_STYLE}</style></head>"
        f'<body class="dl-body" style="margin:0;padding:0;background:{CANVAS};">'
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">'
        f'{escape(document.get("preheader", ""))}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{CANVAS};"><tr><td align="center" style="padding:28px 12px;">'
        f'<table role="presentation" class="dl-card" width="{CARD_WIDTH}" cellpadding="0" '
        f'cellspacing="0" border="0" style="width:{CARD_WIDTH}px;max-width:{CARD_WIDTH}px;'
        f'background:{PAPER};border:1px solid {LINE};border-radius:12px;overflow:hidden;">'
        f'{"".join(rows)}</table></td></tr></table></body></html>'
    )
