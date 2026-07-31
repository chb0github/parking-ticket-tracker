#!/usr/bin/env python3
"""Seattle parking-ticket weekly tracker.

Fetches OPEN parking citations for one or more license plates from the Seattle
Municipal Court public records API, enriches each with charge / officer note /
fine / location (the last two OCR'd from the citation PDF image), diffs against
last run to flag NEW and ESCALATED tickets, and emails a rich-HTML digest.

Usage:
  track.py --plate BYP5855 [ABC1234 ...] \\
           --email-to me@example.com [you@example.com ...] \\
           [--state-dir DIR] [--dry-run] [--no-pdf]

Designed to run unattended from cron. Invoke with the venv interpreter by
absolute path (cron does not activate venvs):
  /path/to/.venv/bin/python3 /path/to/track.py --plate ... --email-to ...
"""

from __future__ import annotations

import argparse
import sys
import traceback

import seattle
import pdfparse
import state as statemod
import report
import mailer

DEFAULT_RECIPIENT = "christian.bongiorno@gmail.com"


def _officer_note(docket_entries):
    """Join the officer's notes/comments docket entries into one string."""
    notes = []
    for e in docket_entries:
        sub = (e.get("docketEntrySubType") or "")
        desc = (e.get("docketEntryDescription") or "").strip()
        if desc and desc.upper() not in ("N.A", "N.A.", "NA") and "Officer" in sub:
            notes.append(desc)
    return " / ".join(notes)


def _docket_text(docket_entries):
    return " ".join(
        (e.get("docketEntryDescription") or "") + " " + (e.get("docketEntryName") or "")
        for e in docket_entries
    )


def _delinquent_entry(docket_entries):
    """The 'Mail Vendor - Parking-Camera Delinquent' docket entry, if any.

    This is the authoritative structured signal that a citation has escalated
    to a delinquency/collections notice (a notice was mailed to the owner).
    """
    for e in docket_entries:
        if e.get("docketEntryType") == "Mail Vendor" and "Delinquent" in (
            e.get("docketEntrySubType") or ""
        ):
            return e
    return None


def _resolve_status(docket, hearings_count, judgments_count):
    """Return (status_label, is_bad, source_entry).

    Status is derived from STRUCTURED signals (docket entry types / counts),
    not fuzzy keyword matches. source_entry is the docket entry that
    establishes the status (so the report can link to that exact document for
    attribution), or None.

    Note on "Delinquent": the mailed "Parking-Camera Delinquent" notice warns
    the ticket *may* go to collections if unpaid by a due date — it does not
    itself mean the case is already in collections. We label it "Delinquent"
    and link the notice so the reader can verify.
    """
    if judgments_count > 0:
        return "Judgment", True, None
    delinquent = _delinquent_entry(docket)
    if delinquent is not None:
        return "Delinquent", True, delinquent
    if hearings_count > 0:
        return "Hearing set", False, None
    return "Open", False, None


def enrich_plate(plate, do_pdf=True, log=print):
    """Fetch + enrich all open tickets for a plate. Returns list of dicts."""
    citations, total = seattle.list_open_citations(plate)
    log(f"[{plate}] {total} open citation(s)")
    tickets = []
    for c in citations:
        cn = c.get("citationNumber")
        header = c.get("caseHeader") or {}
        cuid = header.get("caseInstanceUUID")
        ticket = {
            "citationNumber": cn,
            "violationDate": c.get("violationDate"),
            "caseInstanceUUID": cuid,
            "caseNumber": header.get("caseNumber"),
            "charge": None,
            "officerNote": None,
            "fine": None,
            "location": None,
            "ticketUrl": None,     # citation PDF
            "caseReportUrl": None,  # human-facing portal case report page
            "status": "Open",
            "statusBad": False,
            "statusUrl": None,     # source doc the status was read from (e.g. delinquency notice)
            "officialStatusPage": None,  # official public "check my tickets" page
            "payBy": None,         # date the ticket may go to collections (from delinquency notice)
            "hearingsCount": 0,
            "judgmentsCount": 0,
            "docketCount": 0,
            "docketText": "",
        }
        if not cuid:
            tickets.append(ticket)
            continue
        ticket["caseReportUrl"] = seattle.case_report_url(cuid)
        try:
            charges = seattle.get_charges(cuid)
            if charges:
                ticket["charge"] = charges[0].get("statuteDescription")
            docket = seattle.get_docketentries(cuid)
            ticket["docketCount"] = len(docket)
            ticket["officerNote"] = _officer_note(docket) or None
            ticket["docketText"] = _docket_text(docket)
            hc = len(seattle.get_hearings(cuid))
            jc = len(seattle.get_judgments(cuid))
            ticket["hearingsCount"] = hc
            ticket["judgmentsCount"] = jc

            # Structural status + link to the exact document it was read from.
            status, is_bad, source_entry = _resolve_status(docket, hc, jc)
            ticket["status"] = status
            ticket["statusBad"] = is_bad
            ticket["officialStatusPage"] = seattle.OFFICIAL_STATUS_PAGE
            # Attribution: link the status to the specific source document
            # (e.g. the mailed delinquency notice) so it can be verified.
            if source_entry is not None:
                try:
                    sdoc = seattle.find_complaint_document(cuid, source_entry["docketEntryUUID"])
                    if sdoc and sdoc.get("documentLinkUUID"):
                        sdlu = sdoc["documentLinkUUID"]
                        ticket["statusUrl"] = seattle.pdf_url(cuid, sdlu)
                        # OCR the delinquency notice for the "Pay by" escalation date.
                        if do_pdf and status == "Delinquent":
                            try:
                                notice = seattle.download_pdf(cuid, sdlu)
                                dparsed = pdfparse.parse_delinquency_pdf(notice)
                                ticket["payBy"] = dparsed.get("payBy")
                            except Exception as e:
                                log(f"[{plate}] #{cn}: delinquency-notice OCR failed: {e}")
                except Exception as e:
                    log(f"[{plate}] #{cn}: could not resolve status source doc: {e}")

            if do_pdf:
                entry = seattle.complaint_docket_entry(docket)
                if entry:
                    doc = seattle.find_complaint_document(cuid, entry["docketEntryUUID"])
                    if doc and doc.get("documentLinkUUID"):
                        dlu = doc["documentLinkUUID"]
                        ticket["ticketUrl"] = seattle.pdf_url(cuid, dlu)
                        try:
                            pdf_bytes = seattle.download_pdf(cuid, dlu)
                            parsed = pdfparse.parse_citation_pdf(pdf_bytes)
                            ticket["fine"] = parsed.get("fine")
                            ticket["location"] = parsed.get("location")
                            if not parsed.get("ocr_ok"):
                                log(f"[{plate}] #{cn}: OCR unavailable/failed; fine+location left blank")
                        except Exception as e:
                            log(f"[{plate}] #{cn}: PDF fetch/parse failed: {e}")
        except Exception as e:
            log(f"[{plate}] #{cn}: enrichment error: {e}")

        ticket["escalationHit"] = ticket.get("statusBad", False)
        tickets.append(ticket)
    # Sort by violation date ascending (oldest first); missing dates sort last.
    tickets.sort(key=lambda t: t.get("violationDate") or "9999")
    return tickets


def run(plates, recipients, state_dir, do_pdf=True, dry_run=False, log=print):
    per_plate = []
    for plate in plates:
        tickets = enrich_plate(plate, do_pdf=do_pdf, log=log)
        previous = statemod.load(plate, state_dir)
        new_set, esc_set = statemod.diff(previous, tickets)
        if new_set:
            log(f"[{plate}] NEW: {sorted(new_set)}")
        if esc_set:
            log(f"[{plate}] ESCALATED: {sorted(esc_set)}")
        per_plate.append((plate, tickets, new_set, esc_set))

    html_body = report.build_html(per_plate)
    text_body = report.build_text(per_plate)
    subject = report.build_subject(per_plate)

    if dry_run:
        log("--- DRY RUN: not sending email ---")
        log("Subject: " + subject)
        print(text_body)
        print("\n[HTML body follows]\n")
        print(html_body)
    else:
        mailer.send(recipients, subject, html_body, text_body)
        log(f"Sent report to {', '.join(recipients)}: {subject}")
        # Only persist state after a successful send, so a send failure
        # doesn't silently swallow "new" flags on the next run.
        for plate, tickets, _, _ in per_plate:
            statemod.save(plate, tickets, state_dir)
        log("State saved.")

    return per_plate


def main(argv=None):
    ap = argparse.ArgumentParser(description="Seattle parking-ticket weekly tracker")
    ap.add_argument("--plate", nargs="+", required=True, metavar="PLATE",
                    help="One or more license plates to track")
    ap.add_argument("--email-to", nargs="+", default=[DEFAULT_RECIPIENT], metavar="ADDR",
                    help=f"One or more recipient emails (default: {DEFAULT_RECIPIENT})")
    ap.add_argument("--state-dir", default=statemod.DEFAULT_STATE_DIR,
                    help=f"Where to store per-plate state (default: {statemod.DEFAULT_STATE_DIR})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the report instead of emailing; do not update state")
    ap.add_argument("--no-pdf", action="store_true",
                    help="Skip PDF download/OCR (no fine/location); faster for testing")
    args = ap.parse_args(argv)

    try:
        run(
            plates=args.plate,
            recipients=args.email_to,
            state_dir=args.state_dir,
            do_pdf=not args.no_pdf,
            dry_run=args.dry_run,
        )
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
