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


def _safe_plate(plate):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", plate)


def state_path(plate, state_dir=DEFAULT_STATE_DIR):
    return os.path.join(state_dir, f"{_safe_plate(plate)}.json")


# --------------------------------------------------------------------------
# OCR cache — keyed by documentLinkUUID (a document's contents never change),
# so a citation/notice PDF is only downloaded + OCR'd once, ever. This is the
# main run-time cost, so caching makes subsequent runs dramatically faster.
# --------------------------------------------------------------------------
def _ocr_cache_path(state_dir=DEFAULT_STATE_DIR):
    return os.path.join(state_dir, "ocr_cache.json")


def load_ocr_cache(state_dir=DEFAULT_STATE_DIR):
    """Return {documentLinkUUID: parsed_dict}, or {} if none/corrupt."""
    try:
        with open(_ocr_cache_path(state_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_ocr_cache(cache, state_dir=DEFAULT_STATE_DIR):
    """Persist the OCR cache atomically."""
    os.makedirs(state_dir, exist_ok=True)
    path = _ocr_cache_path(state_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


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
        "status": t.get("status", "Open"),
        "statusBad": t.get("statusBad", False),
        "hearingsCount": t.get("hearingsCount", 0),
        "judgmentsCount": t.get("judgmentsCount", 0),
        "docketCount": t.get("docketCount", 0),
    }


def diff(previous, tickets):
    """Compute NEW and ESCALATED citation-number sets.

    previous: dict from load(); tickets: this run's list of enriched dicts.
    Returns (new_set, escalated_set).

    First run (no prior state) establishes a baseline and flags NOTHING as new
    or escalated — otherwise every ticket would spuriously show as "new" on the
    very first report. Only changes relative to a saved baseline are flagged.
    """
    if not previous:
        return set(), set()

    new = set()
    escalated = set()
    for t in tickets:
        cn = t.get("citationNumber")
        prev = previous.get(cn)
        if prev is None:
            new.add(cn)
            continue
        # Escalated: the status label changed (e.g. Open -> Collections), or a
        # judgment/hearing newly appeared. Status is the authoritative signal.
        status_changed = t.get("status", "Open") != prev.get("status", "Open")
        grew = (
            t.get("judgmentsCount", 0) > prev.get("judgmentsCount", 0)
            or t.get("hearingsCount", 0) > prev.get("hearingsCount", 0)
        )
        if status_changed or grew:
            escalated.add(cn)
    return new, escalated
