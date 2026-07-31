"""Build the HTML (and plain-text) weekly digest email body.

One section per plate, laid out like a spreadsheet: a row per open ticket
(Ticket #, Violation date, Charge, Fine, Fee, Total, PDF) and a grand-total
row at the bottom. A flat processing fee is added to every ticket.
NEW rows are highlighted; ESCALATED rows get a badge.
"""

from __future__ import annotations

import datetime
import html

import seattle

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
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
       color: #26272d; line-height: 1.4; font-size: 13px; margin: 0; padding: 0;
       background: #eef1f6; }
.wrap { max-width: 820px; margin: 0 auto; padding: 20px 14px 32px; }
.card { background: #ffffff; border: 1px solid #d9e0ea; border-radius: 8px;
        overflow: hidden; box-shadow: 0 1px 3px rgba(0,70,173,.08); margin-bottom: 18px; }
.hdr { background: #0046ad; color: #fff; padding: 16px 18px; }
.hdr h1 { font-size: 18px; margin: 0; font-weight: 600; letter-spacing: .2px; }
.hdr .sub { color: #cfe0ff; font-size: 12px; margin-top: 3px; }
h2 { font-size: 14px; margin: 0; padding: 14px 16px 0; font-weight: 600; }
h2 a { color: #003da5; }
.summary { color: #5b6472; font-size: 12px; margin: 2px 0 0; padding: 0 16px 10px; }
table { border-collapse: collapse; width: 100%; font-size: 12.5px; table-layout: fixed; }
th, td { text-align: left; padding: 8px 10px; vertical-align: top;
         overflow-wrap: break-word; word-break: break-word; }
th { background: #003da5; color: #eaf1ff; font-weight: 600; font-size: 10.5px;
     text-transform: uppercase; letter-spacing: .3px; }
td { border-bottom: 1px solid #eef1f5; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.nowrap { white-space: nowrap; }
tr.total td { font-weight: 700; border-top: 2px solid #c3d2ea; background: #e1ecfe; color: #003da5; }
a { color: #0046ad; text-decoration: none; }
a:hover { text-decoration: underline; }
a.st-bad { color: #e4002b; font-weight: 700; }
a.st-warn { color: #b06a00; font-weight: 600; }
.new-dot { color: #0046ad; font-weight: 700; margin-right: 2px; }
.footer { color: #8a93a3; font-size: 10.5px; margin: 0; padding: 4px 16px 16px; line-height: 1.5; }
"""

_TABLE_HEADERS = [
    ("Ticket #", "nowrap"), ("Violation", "nowrap"), ("Charge", ""),
    ("Fine", "num"), ("Total", "num"), ("Status", "nowrap"), ("To Collections", "nowrap"),
]

# Column widths for fixed layout (must sum ~100%).
_COL_WIDTHS = ["13%", "11%", "27%", "9%", "10%", "13%", "17%"]


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


def _row_html(t, is_new, idx):
    # Zebra striping via inline bg (email-safe; :nth-child is unreliable in mail
    # clients). NEW rows get a soft blue tint + left accent instead of a stripe.
    if is_new:
        bg = "#eef4ff"
        first_td_style = ' style="border-left:3px solid #3b6fd4"'
    else:
        bg = "#ffffff" if idx % 2 == 0 else "#f4f6f9"
        first_td_style = ""
    fv = _fine_value(t)
    fine_cell = _money(fv) if fv is not None else "—"
    total_cell = _money(fv + PROCESSING_FEE) if fv is not None else "—"
    tick = _esc(t.get("citationNumber"))
    case_url = t.get("caseReportUrl")
    if case_url:
        tick = f'<a href="{_esc(case_url)}">{tick}</a>'
    if is_new:
        tick = f'<span class="new-dot">●</span> {tick}'
    # Charge text hyperlinks to the citation PDF (the original ticket).
    charge_text = _esc(t.get("charge") or "—")
    ticket_url = t.get("ticketUrl")
    charge_cell = f'<a href="{_esc(ticket_url)}">{charge_text}</a>' if ticket_url else charge_text
    pay_by = t.get("payBy") or "—"
    return (
        f'<tr style="background:{bg}">'
        f'<td class="nowrap"{first_td_style}>{tick}</td>'
        f'<td class="nowrap">{_esc(_fmt_date(t.get("violationDate")))}</td>'
        f"<td>{charge_cell}</td>"
        f'<td class="num">{_esc(fine_cell)}</td>'
        f'<td class="num">{_esc(total_cell)}</td>'
        f'<td class="nowrap">{_status_cell(t)}</td>'
        f'<td class="nowrap">{_esc(pay_by)}</td>'
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
        summary += f" · {n_new} new (● = new since last week)"
    if n_esc:
        summary += f" · {n_esc} escalated"

    if not tickets:
        body = "<p style='padding:0 16px 16px;color:#5b6472'>No open tickets. 🎉</p>"
    else:
        rows = "\n".join(
            _row_html(t, t.get("citationNumber") in new_set, i)
            for i, t in enumerate(tickets)
        )
        header = "".join(
            f'<th class="{c}">{h}</th>' if c else f"<th>{h}</th>" for (h, c) in _TABLE_HEADERS
        )
        colgroup = "<colgroup>" + "".join(f'<col style="width:{w}">' for w in _COL_WIDTHS) + "</colgroup>"
        body = (
            "<table>" + colgroup + "<thead><tr>" + header + "</tr></thead><tbody>"
            + rows + _total_row_html(tickets) + "</tbody></table>"
        )
    search_url = seattle.citations_search_url(plate)
    heading = f'<a href="{_esc(search_url)}">{_esc(plate)}</a>'
    return (
        f'<div class="card"><h2>Plate {heading}</h2>'
        f"<p class='summary'>{_esc(summary)}</p>{body}</div>"
    )


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
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<style>{_STYLE}</style></head><body><div class='wrap'>"
        f"<div class='card'><div class='hdr'>"
        f"<table role='presentation' cellpadding='0' cellspacing='0'><tr>"
        f"<td style='padding-right:10px;vertical-align:middle'>"
        f"<img src='cid:smclogo' width='34' height='34' alt='' "
        f"style='display:block;border-radius:4px'></td>"
        f"<td style='vertical-align:middle'>"
        f"<h1>Seattle Parking Ticket Report</h1>"
        f"<div class='sub'>{_esc(sub)}</div></td></tr></table></div>"
        f"<p class='footer'>Source: Seattle Municipal Court public records. "
        f"<b>Ticket #</b> opens the case report; <b>Status</b> links to the exact document it "
        f"was read from (red = Delinquent/Judgment). &ldquo;Delinquent&rdquo; means a notice was "
        f"mailed warning the ticket may go to collections if unpaid — not that it is already in "
        f"collections. &ldquo;Goes to collections on&rdquo; is the pay-by deadline from that "
        f"notice.{official_link} The <b>Charge</b> links to the citation PDF (original ticket). "
        f"Fine is OCR'd and may misread. Total includes a {_money(PROCESSING_FEE)} fee per ticket.</p>"
        f"</div>{sections}</div></body></html>"
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
        lines.append(f"   search: {seattle.citations_search_url(plate)}")
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
            pay_by = f" collections-on {t['payBy']}" if t.get("payBy") else ""
            status_src = f" [status: {t['statusUrl']}]" if t.get("statusUrl") else ""
            ticket_src = f" [ticket: {t['ticketUrl']}]" if t.get("ticketUrl") else ""
            lines.append(
                f"  #{t.get('citationNumber')}{flag} {_fmt_date(t.get('violationDate'))} "
                f"{t.get('charge') or '—'} | fine {fine_s} + fee {_money(PROCESSING_FEE)} = {total_s} "
                f"| {label}{pay_by}{status_src}{ticket_src}"
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
