"""Build the HTML (and plain-text) weekly digest email body.

One section per plate, laid out like a spreadsheet: a row per open ticket
(Ticket #, Violation date, Charge, Fine, Fee, Total, PDF) and a grand-total
row at the bottom. A flat processing fee is added to every ticket.
NEW rows are highlighted; ESCALATED rows get a badge.
"""

from __future__ import annotations

import datetime
import html

# Flat processing fee added to every citation (dollars).
PROCESSING_FEE = 3.60


def _fmt_date(iso):
    """2026-07-18T18:18:00.000+00:00 -> 2026-07-18 (or the raw string)."""
    if not iso:
        return "—"
    try:
        return iso[:10]
    except Exception:
        return str(iso)


def _fine_value(t):
    """Ticket fine as float, or None if unknown."""
    try:
        return float(t["fine"])
    except (TypeError, ValueError, KeyError):
        return None


def _money(x):
    return f"${x:,.2f}"


def _totals(tickets):
    """Sum fines, fees, and grand total across tickets.

    Returns (fine_sum, fee_sum, grand_total, all_fines_known).
    Fees apply to every ticket regardless of whether its fine OCR'd.
    """
    fine_sum = 0.0
    all_known = True
    for t in tickets:
        fv = _fine_value(t)
        if fv is None:
            all_known = False
        else:
            fine_sum += fv
    fee_sum = PROCESSING_FEE * len(tickets)
    return fine_sum, fee_sum, fine_sum + fee_sum, all_known


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
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr.new td { background: #fff8e1; }
tr.escalated td { background: #fdecea; }
tr.total td { font-weight: 700; border-top: 2px solid #d0d3d8; background: #f5f6f8; }
.badge { display: inline-block; font-size: 10px; font-weight: 700; padding: 1px 6px;
         border-radius: 10px; margin-right: 4px; vertical-align: middle; }
.badge-new { background: #ffca28; color: #4a3b00; }
.badge-esc { background: #d93025; color: #fff; }
a { color: #1155cc; }
.footer { color: #888; font-size: 11px; margin-top: 22px; }
"""

_TABLE_HEADERS = [
    ("", ""), ("Ticket #", ""), ("Violation", ""), ("Charge", ""),
    ("Fine", "num"), ("Fee", "num"), ("Total", "num"), ("PDF", ""),
]


def _row_html(t, is_new, is_esc):
    cls = "escalated" if is_esc else ("new" if is_new else "")
    badges = ""
    if is_new:
        badges += '<span class="badge badge-new">NEW</span>'
    if is_esc:
        badges += '<span class="badge badge-esc">ESCALATED</span>'
    fv = _fine_value(t)
    fine_cell = _money(fv) if fv is not None else "—"
    total_cell = _money(fv + PROCESSING_FEE) if fv is not None else "—"
    pdf = t.get("pdfUrl")
    pdf_cell = f'<a href="{_esc(pdf)}">view</a>' if pdf else "—"
    return (
        f'<tr class="{cls}">'
        f"<td>{badges}</td>"
        f'<td>{_esc(t.get("citationNumber"))}</td>'
        f"<td>{_esc(_fmt_date(t.get('violationDate')))}</td>"
        f'<td>{_esc(t.get("charge") or "—")}</td>'
        f'<td class="num">{_esc(fine_cell)}</td>'
        f'<td class="num">{_esc(_money(PROCESSING_FEE))}</td>'
        f'<td class="num">{_esc(total_cell)}</td>'
        f"<td>{pdf_cell}</td>"
        f"</tr>"
    )


def _total_row_html(tickets):
    fine_sum, fee_sum, grand, all_known = _totals(tickets)
    approx = "" if all_known else "+"
    return (
        '<tr class="total">'
        '<td></td><td></td><td></td>'
        f'<td>Total ({len(tickets)})</td>'
        f'<td class="num">{_esc(_money(fine_sum) + approx)}</td>'
        f'<td class="num">{_esc(_money(fee_sum))}</td>'
        f'<td class="num">{_esc(_money(grand) + approx)}</td>'
        '<td></td></tr>'
    )


def _plate_section_html(plate, tickets, new_set, esc_set):
    n_new = len(new_set)
    n_esc = len(esc_set)
    summary = f"{len(tickets)} open ticket(s)"
    if n_new:
        summary += f" · {n_new} new"
    if n_esc:
        summary += f" · {n_esc} escalated"

    if not tickets:
        body = "<p>No open tickets. 🎉</p>"
    else:
        rows = "\n".join(
            _row_html(t, t.get("citationNumber") in new_set, t.get("citationNumber") in esc_set)
            for t in tickets
        )
        header = "".join(
            f'<th class="{c}">{h}</th>' if c else f"<th>{h}</th>" for (h, c) in _TABLE_HEADERS
        )
        body = (
            "<table><thead><tr>" + header + "</tr></thead><tbody>"
            + rows + _total_row_html(tickets) + "</tbody></table>"
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
    sub = f"Generated {when}"
    if total_new or total_esc:
        sub += f" · {total_new} new · {total_esc} escalated across all plates"
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><style>{_STYLE}</style></head>"
        f"<body><h1>Seattle Parking Ticket Report</h1><p class='summary'>{_esc(sub)}</p>{sections}"
        f"<p class='footer'>Source: Seattle Municipal Court public records. "
        f"Fine is OCR'd from the citation image and may occasionally misread — click the PDF "
        f"link to verify. A {_money(PROCESSING_FEE)} processing fee is added per ticket.</p>"
        f"</body></html>"
    )


# --------------------------------------------------------------------------
# Plain text fallback
# --------------------------------------------------------------------------
def build_text(per_plate, generated_at=None):
    when = (generated_at or datetime.datetime.now()).strftime("%A %Y-%m-%d %H:%M")
    lines = ["Seattle Parking Ticket Report", f"Generated {when}", ""]
    for plate, tickets, new_set, esc_set in per_plate:
        fine_sum, fee_sum, grand, all_known = _totals(tickets)
        approx = "" if all_known else "+"
        lines.append(f"== Plate {plate}: {len(tickets)} open ==")
        for t in tickets:
            flags = []
            if t.get("citationNumber") in new_set:
                flags.append("NEW")
            if t.get("citationNumber") in esc_set:
                flags.append("ESCALATED")
            flag = (" [" + ",".join(flags) + "]") if flags else ""
            fv = _fine_value(t)
            fine_s = _money(fv) if fv is not None else "—"
            total_s = _money(fv + PROCESSING_FEE) if fv is not None else "—"
            lines.append(
                f"  #{t.get('citationNumber')}{flag} {_fmt_date(t.get('violationDate'))} "
                f"{t.get('charge') or '—'} | fine {fine_s} + fee {_money(PROCESSING_FEE)} = {total_s}"
            )
        lines.append(
            f"  TOTAL ({len(tickets)}): fines {_money(fine_sum)}{approx} "
            f"+ fees {_money(fee_sum)} = {_money(grand)}{approx}"
        )
        lines.append("")
    return "\n".join(lines)


def build_subject(per_plate):
    total = sum(len(tk) for (_, tk, _, _) in per_plate)
    total_new = sum(len(nw) for (_, _, nw, _) in per_plate)
    total_esc = sum(len(es) for (_, _, _, es) in per_plate)
    grand = sum(_totals(tk)[2] for (_, tk, _, _) in per_plate)
    plates = ", ".join(p for (p, _, _, _) in per_plate)
    subj = f"Parking tickets [{plates}]: {total} open, {_money(grand)} due"
    if total_new:
        subj += f", {total_new} new"
    if total_esc:
        subj += f", {total_esc} ESCALATED"
    return subj
