# AGENTS.md — parking-ticket-tracker

Orientation for an AI agent (or a human) picking this repo up cold.

## What this is
An unattended weekly cron job that emails a rich-HTML digest of **open** Seattle
parking citations for one or more plates. Pure Python 3 stdlib + a small OCR
stack. No framework, no database — state is per-plate JSON files.

## Module map
- `track.py` — entry point / orchestrator. argparse (`--plate` and `--email-to`
  are both `nargs='+'`; `--state-dir`, `--dry-run`, `--no-pdf`). `enrich_plate()`
  builds a ticket dict per citation; `run()` diffs, reports, mails, saves state.
- `seattle.py` — API client (stdlib `urllib`). Centralized browser `HEADERS`
  (real Firefox UA + Origin/Referer — the site is CORS-gated and may filter
  bots; **do not** let it fall back to urllib's default UA). Retry/backoff,
  gzip handling. Knows the endpoint chain (see below).
- `pdfparse.py` — OCR the citation PDF for **fine + location** (they exist only
  as a scanned image on page 1; the PDF text layer has neither). `pypdfium2`
  renders, `pytesseract` OCRs, regex pulls `Fine: $NN.NN` and `INFRACTION
  LOCATION:`. Returns `{fine, location, ocr_ok}`; all failures → None (graceful).
- `state.py` — per-plate snapshot load/save (atomic write) + `diff()` →
  (new_set, escalated_set). Escalation is **structural** (hearings/judgments
  appear, docket grows, or keyword hit), NOT from the PDF (its page-2 boilerplate
  always mentions tow/impound, so it's not a signal).
- `report.py` — `build_html`, `build_text`, `build_subject`. NEW=amber row,
  ESCALATED=red row + badges; per-plate summary with total fines.
- `mailer.py` — Gmail via stdlib `smtplib.SMTP_SSL` + `EmailMessage`. Creds from
  `~/.netrc` (`machine smtp.gmail.com`) via stdlib `netrc`. No curl.
- `setup.sh` — creates `.venv` without sudo (`venv --without-pip` + `get-pip.py`)
  and installs `requirements.txt`. Idempotent.

## API endpoint chain (all verified live; court UUID = 68f021c4-...af13)
1. Open citations for a plate:
   `GET /courts/cms/citations?defendantParty.partyActorInstance.displayName={PLATE}`
   `&defendantParty.partyActorInstance.displayNameSearchType=300054`
   `&caseHeader.closedFlag=false&caseHeader.courtID={COURT}&size=100&sort=violationDate,desc`
   → `_embedded.results[]` with `citationNumber`, `violationDate`,
     `caseHeader.caseInstanceUUID`.
2. Per case, base `/courts/{COURT}/cms/cases/{CUID}`:
   `/charges` (statuteDescription = the violation), `/docketentries`
   (officer notes; the Complaint entry with `documentCount>0` anchors the PDF),
   `/parties`, `/hearings`, `/judgments` (last two usually empty = escalation
   signals when non-empty).
3. Citation PDF:
   - `GET /courts/cms/docketentrydocumentsaccess?...&docketEntryUUID={DEUID}&caseHeader.caseInstanceUUID={CUID}`
     → `documentLinkUUID`.
   - `GET /courts/{COURT}/cms/case/{CUID}/docketentrydocuments/{documentLinkUUID}`
     → the PDF. **courtID in this path is the UUID, not the short "1".**

## Gotchas
- **UA/headers matter** — strip them and the API may 403. Keep the full set.
- **Fine/location are OCR-only.** No dollar amount or address exists anywhere in
  the JSON. Don't waste time re-searching the JSON for them.
- PDF page 1 & 2 are scanned images (0 text chars); page 3+ is officer
  certification text. OCR pages 0–1 only.
- **Escalation** has no dedicated API field. It's inferred. If Seattle ever adds
  a financial/collections endpoint, wire it into `enrich_plate` + `state.diff`.
- State is written **only after a successful send** so a send failure doesn't
  eat the NEW flags next run. `--dry-run` never writes state.
- Cron must call `.venv/bin/python3` by absolute path (no venv activation).

## Deploy (host: snowball, user cbongiorno)
```
cd ~/dev/mine && git clone <repo> parking-ticket-tracker && cd parking-ticket-tracker
sudo apt install tesseract-ocr        # one-time, needs a human (sudo pw)
bash setup.sh
.venv/bin/python3 track.py --dry-run --plate BYP5855 --email-to christian.bongiorno@gmail.com
```
Then add the weekly crontab line (see README).

## Testing without spamming
`--dry-run` prints text + HTML and skips send/state. Use a throwaway
`--state-dir /tmp/xyz` to exercise NEW/ESCALATED diffing.
