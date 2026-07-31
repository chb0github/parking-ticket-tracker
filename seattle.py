"""Client for the Seattle Municipal Court public records API.

Stdlib only (urllib) so it runs on a bare Python 3.10 install. The API is
unauthenticated but CORS-gated: it inspects Origin/Referer and may filter
non-browser User-Agents, so every request carries a full browser header set
(see HEADERS). urllib's default "Python-urllib/x.y" UA is explicitly
overridden.

Endpoint chain (verified against live data):
  1. list_open_citations(plate)        -> open citations for a plate
  2. per case (caseInstanceUUID):
       get_charges / get_docketentries / get_parties / get_hearings / get_judgments
  3. citation PDF:
       find_complaint_document(...) -> documentLinkUUID
       download_pdf(...)            -> PDF bytes
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.parse
import urllib.request
import urllib.error

API_ROOT = "https://courtrecords-api.seattle.gov"

# Seattle Municipal Court. The list/search endpoint wants this UUID as
# caseHeader.courtID; note the PDF endpoint ALSO uses this UUID in its path
# (not the short courtID "1" that appears inside case payloads).
COURT_UUID = "68f021c4-6a44-4735-9a76-5360b2e8af13"

# displayNameSearchType observed in the site's own requests (exact-ish match
# on the cited vehicle's display name / plate).
DISPLAY_NAME_SEARCH_TYPE = "300054"

# Full browser header set. The site may filter bots, so we present as Firefox
# and include the Origin/Referer the CORS-gated API checks.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) "
        "Gecko/20100101 Firefox/152.0"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US",
    "Accept-Encoding": "gzip, deflate",
    "Origin": "https://courtrecords.seattle.gov",
    "Referer": "https://courtrecords.seattle.gov/",
    "Connection": "keep-alive",
}

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
BACKOFF_BASE = 1.5


class SeattleAPIError(RuntimeError):
    pass


def _request(url, accept=None, expect="json"):
    """GET a URL with browser headers, retry/backoff, and gzip handling.

    Returns parsed JSON (expect="json") or raw bytes (expect="bytes").
    """
    headers = dict(HEADERS)
    if accept:
        headers["Accept"] = accept

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                elif resp.headers.get("Content-Encoding") == "deflate":
                    import zlib
                    raw = zlib.decompress(raw)
                if expect == "bytes":
                    return raw
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 4xx are not worth retrying (except 429); surface them.
            if e.code == 429 and attempt < MAX_RETRIES:
                last_err = e
            elif 500 <= e.code < 600 and attempt < MAX_RETRIES:
                last_err = e
            else:
                raise SeattleAPIError(f"HTTP {e.code} for {url}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
        if attempt < MAX_RETRIES:
            time.sleep(BACKOFF_BASE ** attempt)
    raise SeattleAPIError(f"request failed after {MAX_RETRIES} tries: {url}: {last_err}")


def _results(payload):
    """Extract the _embedded.results[] list from a HAL-style payload."""
    if not isinstance(payload, dict):
        return []
    return (payload.get("_embedded") or {}).get("results") or []


def _case_base(case_uuid):
    return f"{API_ROOT}/courts/{COURT_UUID}/cms/cases/{case_uuid}"


# --------------------------------------------------------------------------
# 1. Open citations for a plate
# --------------------------------------------------------------------------
def list_open_citations(plate, size=100):
    """Return (results, total) of OPEN citations for a plate.

    Server-side filters closedFlag=false, so every result is an open case.
    """
    params = {
        "defendantParty.partyActorInstance.displayName": plate,
        "defendantParty.partyActorInstance.displayNameSearchType": DISPLAY_NAME_SEARCH_TYPE,
        "caseHeader.closedFlag": "false",
        "caseHeader.courtID": COURT_UUID,
        "page": "0",
        "size": str(size),
        "sort": "violationDate,desc",
    }
    url = f"{API_ROOT}/courts/cms/citations?" + urllib.parse.urlencode(params)
    payload = _request(url)
    total = ((payload.get("page") or {}).get("totalElements")) if isinstance(payload, dict) else None
    return _results(payload), total


# --------------------------------------------------------------------------
# 2. Per-case sub-resources
# --------------------------------------------------------------------------
def get_charges(case_uuid):
    return _results(_request(f"{_case_base(case_uuid)}/charges?page=0&size=50"))


def get_docketentries(case_uuid):
    return _results(_request(f"{_case_base(case_uuid)}/docketentries?page=0&size=50&sort=filedDate,desc"))


def get_parties(case_uuid):
    return _results(_request(f"{_case_base(case_uuid)}/parties?page=0&size=50"))


def get_hearings(case_uuid):
    return _results(_request(f"{_case_base(case_uuid)}/hearings?page=0&size=50"))


def get_judgments(case_uuid):
    return _results(_request(f"{_case_base(case_uuid)}/judgments?page=0&size=50"))


# --------------------------------------------------------------------------
# 3. Citation PDF
# --------------------------------------------------------------------------
def find_complaint_document(case_uuid, docket_entry_uuid):
    """Resolve the documentLinkUUID for a docket entry's attached PDF.

    Returns the first document dict (with documentLinkUUID, documentInfo, ...)
    or None if the entry has no accessible document.
    """
    params = {
        "page": "0",
        "size": "10",
        "sort": "documentName,asc",
        "caseHeader.courtID": COURT_UUID,
        "docketEntryUUID": docket_entry_uuid,
        "caseHeader.caseInstanceUUID": case_uuid,
    }
    url = f"{API_ROOT}/courts/cms/docketentrydocumentsaccess?" + urllib.parse.urlencode(params)
    results = _results(_request(url))
    return results[0] if results else None


def download_pdf(case_uuid, document_link_uuid):
    """Download the citation PDF bytes. courtID in the path is the UUID."""
    url = (
        f"{API_ROOT}/courts/{COURT_UUID}/cms/case/{case_uuid}"
        f"/docketentrydocuments/{document_link_uuid}"
    )
    return _request(url, accept="application/pdf,*/*", expect="bytes")


def pdf_url(case_uuid, document_link_uuid):
    """The direct, clickable PDF URL (for including in the report)."""
    return (
        f"{API_ROOT}/courts/{COURT_UUID}/cms/case/{case_uuid}"
        f"/docketentrydocuments/{document_link_uuid}"
    )


def complaint_docket_entry(docket_entries):
    """Pick the docket entry that carries the citation PDF.

    Prefers a Complaint entry with documentCount > 0; falls back to any entry
    with documentCount > 0.
    """
    def has_doc(e):
        try:
            return int(e.get("documentCount", "0")) > 0
        except (TypeError, ValueError):
            return False

    complaints = [e for e in docket_entries if e.get("docketEntryType") == "Complaint" and has_doc(e)]
    if complaints:
        return complaints[0]
    withdoc = [e for e in docket_entries if has_doc(e)]
    return withdoc[0] if withdoc else None
