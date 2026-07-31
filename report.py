"""Build the HTML (and plain-text) weekly digest email body.

One section per plate: a summary line plus a table of open tickets
(Ticket #, Violation date, Charge, Fine, Location, Officer note, PDF link).
NEW rows are highlighted; ESCALATED rows get a badge.
"""

from __future__ import annotations

import datetime
import html


def _fmt_date(iso):
    """2026-07-18T18:18:00.000+00:00 -> 2026-07-18 (or the raw string)."""
    if not iso:
        return "—"
    try:
        return iso[:10]
    except Exception:
        return str(iso)


def _fmt_fine(fine):
    if not fine:
        return "—"
    return f"${fine}"


def _money_total(tickets):
    total = 0.0
    any_known = False
    for t in tickets:
        try:
            total += float(t["fine"])
            any_known = True
        except (TypeError, ValueError, KeyError):
            pass
    return total, any_known


def _esc(s):
    return html.escape(str(s)) if s is not None else ""


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------
_STYLE = """
body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       color: #1a1a1a; line-height: 1.4; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 24px 0 6px; }
.summary { color: #444; font-size: 13px; margin: 0 0 10px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 7px 9px; border-bottom: 1px solid #e3e3e3;
         vertical-align: top; }
th { background: #f5f6f8; font-weight: 600; border-bottom: 2px solid #d0d3d8; }
tr.new td { background: #fff8e1; }
tr.escalated td { background: #fdecea; }
.badge { display: inline-block; font-size: 10px; font-weight: 700; padding: 1px 6px;
         border-radius: 10px; margin-right: 4px; vertical-align: middle; }
.badge-new { background: #ffca28; color: #4a3b00; }
.badge-esc { background: #d93025; color: #fff; }
.note { color: #555; font-size: 12px; max-width: 320px; }
.fine { font-variant-numeric: tabular-nums; white-space: nowrap; }
a { color: #1155cc; }
.footer { color: #888; font-size: 11px; margin-top: 22px; }
"""

_TABLE_HEADERS = ["", "Ticket #", "Violation", "Charge", "Fine", "Location", "Officer note", "PDF"]


def _row_html(t, is_new, is_esc):
    cls = "escalated" if is_esc else ("new" if is_new else "")
    badges = ""
    if is_new:
        badges += '<span class="badge badge-new">NEW</span>'
    if is_esc:
        badges += '<span class="badge badge-esc">ESCALATED</span>'
    pdf = t.get("pdfUrl")
    pdf_cell = f'<a href="{_esc(pdf)}">view</a>' if pdf else "—"
    return (
        f'<tr class="{cls}">'
        f"<td>{badges}</td>"
        f'<td>{_esc(t.get("citationNumber"))}</td>'
        f"<td>{_esc(_fmt_date(t.get('violationDate')))}</td>"
        f'<td>{_esc(t.get("charge") or "—")}</td>'
        f'<td class="fine">{_esc(_fmt_fine(t.get("fine")))}</td>'
        f'<td>{_esc(t.get("location") or "—")}</td>'
        f'<td class="note">{_esc(t.get("officerNote") or "—")}</td>'
        f"<td>{pdf_cell}</td>"
        f"</tr>"
    )


def _plate_section_html(plate, tickets, new_set, esc_set):
    total, any_known = _money_total(tickets)
    n_new = len(new_set)
    n_esc = len(esc_set)
    money = f"${total:,.2f}" + ("" if any_known else "+") if tickets else "$0.00"
    summary = f"{len(tickets)} open ticket(s) · total fines {money}"
    if n_new:
        summary += f" · {n_new} new"
    if n_esc:
        summary += f" · {n_esc} escalated"

    rows = "\n".join(
        _row_html(t, t.get("citationNumber") in new_set, t.get("citationNumber") in esc_set)
        for t in tickets
    )
    if not tickets:
        body = "<p>No open tickets. 🎉</p>"
    else:
        body = (
            "<table><thead><tr>"
            + "".join(f"<th>{h}</th>" for h in _TABLE_HEADERS)
            + "</tr></thead><tbody>"
            + rows
            + "</tbody></table>"
        )
    return f"<h2>Plate {_esc(plate)}</h2>\n<p class='summary'>{_esc(summary)}</p>\n{body}"


def build_html(per_plate, generated_at=None):
    """per_plate: list of (plate, tickets, new_set, esc_set)."""
    when = (generated_at or datetime.datetime.now()).strftime("%A %Y-%m-%d %H:%M")
    sections = "\n".join(
        _plate_section_html(p, tk, nw, es) for (p, tk, nw, es) in per_plate
    )
    total_new = sum(len(nw) for (_, _, nw, _) in per_plate)
    total_esc = sum(len(es) for (_, _, _, es) in per_plate)
    headline = "Seattle Parking Ticket Report"
    sub = f"Generated {when}"
    if total_new or total_esc:
        sub += f" · {total_new} new · {total_esc} escalated across all plates"
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><style>{_STYLE}</style></head>"
        f"<body><h1>{headline}</h1><p class='summary'>{_esc(sub)}</p>{sections}"
        f"<p class='footer'>Source: Seattle Municipal Court public records. "
        f"Fine &amp; location are OCR'd from the citation image and may occasionally misread — "
        f"click the PDF link to verify.</p></body></html>"
    )


# --------------------------------------------------------------------------
# Plain text fallback
# --------------------------------------------------------------------------
def build_text(per_plate, generated_at=None):
    when = (generated_at or datetime.datetime.now()).strftime("%A %Y-%m-%d %H:%M")
    lines = ["Seattle Parking Ticket Report", f"Generated {when}", ""]
    for plate, tickets, new_set, esc_set in per_plate:
        total, any_known = _money_total(tickets)
        money = f"${total:,.2f}" + ("" if any_known else "+")
        lines.append(f"== Plate {plate}: {len(tickets)} open, total {money} ==")
        for t in tickets:
            flags = []
            if t.get("citationNumber") in new_set:
                flags.append("NEW")
            if t.get("citationNumber") in esc_set:
                flags.append("ESCALATED")
            flag = (" [" + ",".join(flags) + "]") if flags else ""
            lines.append(
                f"  #{t.get('citationNumber')}{flag} "
                f"{_fmt_date(t.get('violationDate'))} "
                f"{t.get('charge') or '—'} "
                f"{_fmt_fine(t.get('fine'))} @ {t.get('location') or '—'}"
            )
            if t.get("pdfUrl"):
                lines.append(f"      PDF: {t['pdfUrl']}")
        lines.append("")
    return "\n".join(lines)


def build_subject(per_plate):
    total = sum(len(tk) for (_, tk, _, _) in per_plate)
    total_new = sum(len(nw) for (_, _, nw, _) in per_plate)
    total_esc = sum(len(es) for (_, _, _, es) in per_plate)
    plates = ", ".join(p for (p, _, _, _) in per_plate)
    subj = f"Parking tickets [{plates}]: {total} open"
    if total_new:
        subj += f", {total_new} new"
    if total_esc:
        subj += f", {total_esc} ESCALATED"
    return subj
