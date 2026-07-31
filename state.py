"""Per-plate snapshot persistence and run-over-run diffing.

Each plate gets one JSON file under the state dir, keyed by citationNumber.
Comparing this run's tickets to the saved snapshot yields:
  - NEW:       citation numbers not seen last run
  - ESCALATED: citations whose escalation-relevant signals changed
               (hearings/judgments appeared, docket-entry count grew, or a
               docket/charge text now matches escalation keywords)

State is advisory: a missing/corrupt file just means "everything is new",
which is safe (a slightly noisy email) rather than harmful.
"""

from __future__ import annotations

import json
import os
import re

DEFAULT_STATE_DIR = os.path.expanduser("~/.local/state/parking-tickets")

# Structural escalation signals in docket/charge free text.
_ESCALATION_RE = re.compile(
    r"impound|immobiliz|\btow(ed|ing)?\b|collection|warrant|"
    r"default judgment|failure to (respond|appear)|penalty added",
    re.IGNORECASE,
)


def _safe_plate(plate):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", plate)


def state_path(plate, state_dir=DEFAULT_STATE_DIR):
    return os.path.join(state_dir, f"{_safe_plate(plate)}.json")


def load(plate, state_dir=DEFAULT_STATE_DIR):
    """Return the saved snapshot dict {citationNumber: record}, or {} if none."""
    path = state_path(plate, state_dir)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("tickets", {}) if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save(plate, tickets, state_dir=DEFAULT_STATE_DIR):
    """Persist this run's tickets (list of dicts) keyed by citationNumber.

    Atomic write (temp + rename) so a crash mid-write can't corrupt state.
    """
    os.makedirs(state_dir, exist_ok=True)
    keyed = {t["citationNumber"]: _snapshot_record(t) for t in tickets}
    payload = {"plate": plate, "tickets": keyed}
    path = state_path(plate, state_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _snapshot_record(t):
    """The subset of a ticket worth persisting for diffing."""
    return {
        "citationNumber": t.get("citationNumber"),
        "violationDate": t.get("violationDate"),
        "charge": t.get("charge"),
        "fine": t.get("fine"),
        "location": t.get("location"),
        "hearingsCount": t.get("hearingsCount", 0),
        "judgmentsCount": t.get("judgmentsCount", 0),
        "docketCount": t.get("docketCount", 0),
        "escalationHit": t.get("escalationHit", False),
    }


def escalation_hit(ticket):
    """True if any docket/charge free text matches escalation keywords."""
    haystack = " ".join(
        str(ticket.get(k, "")) for k in ("charge", "officerNote", "docketText")
    )
    return bool(_ESCALATION_RE.search(haystack))


def diff(previous, tickets):
    """Compute NEW and ESCALATED citation-number sets.

    previous: dict from load(); tickets: this run's list of enriched dicts.
    Returns (new_set, escalated_set).
    """
    new = set()
    escalated = set()
    for t in tickets:
        cn = t.get("citationNumber")
        prev = previous.get(cn)
        if prev is None:
            new.add(cn)
            continue
        # Escalation: a structural signal grew or a keyword newly appears.
        grew = (
            t.get("hearingsCount", 0) > prev.get("hearingsCount", 0)
            or t.get("judgmentsCount", 0) > prev.get("judgmentsCount", 0)
            or t.get("docketCount", 0) > prev.get("docketCount", 0)
        )
        newly_flagged = t.get("escalationHit", False) and not prev.get("escalationHit", False)
        if grew or newly_flagged:
            escalated.add(cn)
    return new, escalated
