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
       color: #1a1a1a; line-height: 1.25; font-size: 12px; margin: 0; padding: 12px; }
h1 { font-size: 15px; margin: 0 0 2px; }
h2 { font-size: 13px; margin: 14px 0 3px; }
.summary { color: #555; font-size: 11px; margin: 0 0 6px; }
table { border-collapse: collapse; width: 100%; font-size: 12px; }
th, td { text-align: left; padding: 3px 8px; border-bottom: 1px solid #ebebeb; white-space: nowrap; }
th { background: #f5f6f8; font-weight: 600; border-bottom: 1px solid #ccc; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.new td { background: #fff8e1; }
tr.total td { font-weight: 700; border-top: 2px solid #ccc; background: #f5f6f8; }
a { color: #1155cc; text-decoration: none; }
a.st-bad { color: #c5221f; font-weight: 700; }
a.st-warn { color: #b06a00; font-weight: 600; }
.new-dot { color: #b06a00; font-weight: 700; }
.footer { color: #999; font-size: 10px; margin-top: 14px; }
"""

_TABLE_HEADERS = [
    ("Ticket #", ""), ("Violation", ""), ("Charge", ""),
    ("Fine", "num"), ("Total", "num"), ("Status", ""), ("Link", ""),
]


def _status_cell(t):
    """Status text linking to the OFFICIAL source of that status.

    For a Collections/Judgment status the link points at the document that
    establishes it (e.g. the mailed delinquency notice). Falls back to plain
    text if no source URL was resolved. Color signals severity.
    """
    label = t.get("status", "Open")
    is_bad = t.get("statusBad", False)
    url = t.get("statusUrl")
    cls = "st-bad" if is_bad else ("st-warn" if label == "Hearing set" else "")
    if url:
        return f'<a class="{cls}" href="{_esc(url)}">{_esc(label)}</a>'
    span_cls = f' class="{cls}"' if cls else ""
    return f"<span{span_cls}>{_esc(label)}</span>"


def _row_html(t, is_new):
    cls = "new" if is_new else ""
    fv = _fine_value(t)
    fine_cell = _money(fv) if fv is not None else "—"
    total_cell = _money(fv + PROCESSING_FEE) if fv is not None else "—"
    tick = _esc(t.get("citationNumber"))
    if is_new:
        tick = f'<span class="new-dot">●</span> {tick}'
    ticket_url = t.get("ticketUrl")
    link_cell = f'<a href="{_esc(ticket_url)}">ticket</a>' if ticket_url else "—"
    return (
        f'<tr class="{cls}">'
        f"<td>{tick}</td>"
        f"<td>{_esc(_fmt_date(t.get('violationDate')))}</td>"
        f'<td>{_esc(t.get("charge") or "—")}</td>'
        f'<td class="num">{_esc(fine_cell)}</td>'
        f'<td class="num">{_esc(total_cell)}</td>'
        f"<td>{_status_cell(t)}</td>"
        f"<td>{link_cell}</td>"
        f"</tr>"
    )


def _total_row_html(tickets):
    fine_sum, _, grand, all_known = _totals(tickets)
    approx = "" if all_known else "+"
    return (
        '<tr class="total">'
        '<td></td><td></td>'
        f'<td>Total ({len(tickets)})</td>'
        f'<td class="num">{_esc(_money(fine_sum) + approx)}</td>'
        f'<td class="num">{_esc(_money(grand) + approx)}</td>'
        '<td></td><td></td></tr>'
    )


def _plate_section_html(plate, tickets, new_set, esc_set):
    n_new = len(new_set)
    n_esc = len(esc_set)
    summary = f"{len(tickets)} open · +{_money(PROCESSING_FEE)} fee/ticket"
    if n_new:
        summary += f" · {n_new} new"
    if n_esc:
        summary += f" · {n_esc} escalated"

    if not tickets:
        body = "<p>No open tickets. 🎉</p>"
    else:
        rows = "\n".join(
            _row_html(t, t.get("citationNumber") in new_set) for t in tickets
        )
        header = "".join(
            f'<th class="{c}">{h}</th>' if c else f"<th>{h}</th>" for (h, c) in _TABLE_HEADERS
        )
        body = (
            "<table><thead><tr>" + header + "</tr></thead><tbody>"
            + rows + _total_row_html(tickets) + "</tbody></table>"
        )
    return f"<h2>Plate {_esc(plate)}</h2>\n<p class='summary'>{_esc(summary)}</p>\n{body}"


def _official_page(per_plate):
    for entry in per_plate:
        for t in entry[1]:
            if t.get("officialStatusPage"):
                return t["officialStatusPage"]
    return None


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
    official = _official_page(per_plate)
    official_link = (
        f' Official status: <a href="{_esc(official)}">{_esc(official)}</a>.'
        if official else ""
    )
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><style>{_STYLE}</style></head>"
        f"<body><h1>Seattle Parking Ticket Report</h1><p class='summary'>{_esc(sub)}</p>{sections}"
        f"<p class='footer'>Source: Seattle Municipal Court public records. "
        f"<b>Status</b> links to the exact document it was read from (red = "
        f"Delinquent/Judgment); &ldquo;Delinquent&rdquo; means a notice was mailed warning the "
        f"ticket may go to collections if unpaid — not that it is already in collections."
        f"{official_link} <b>Link</b> opens the citation PDF. Fine is OCR'd and may misread. "
        f"Total includes a {_money(PROCESSING_FEE)} fee per ticket.</p>"
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
            label = t.get("status", "Open")
            status_src = f" [status: {t['statusUrl']}]" if t.get("statusUrl") else ""
            ticket_src = f" [ticket: {t['ticketUrl']}]" if t.get("ticketUrl") else ""
            lines.append(
                f"  #{t.get('citationNumber')}{flag} {_fmt_date(t.get('violationDate'))} "
                f"{t.get('charge') or '—'} | fine {fine_s} + fee {_money(PROCESSING_FEE)} = {total_s} "
                f"| {label}{status_src}{ticket_src}"
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
