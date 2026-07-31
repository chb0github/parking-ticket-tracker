# parking-ticket-tracker

Weekly digest of **open** Seattle parking citations for one or more license
plates, emailed to you as rich HTML. Runs unattended from cron — no AI in the
loop.

For each open ticket it reports: ticket #, violation date, charge type, **fine**,
**location**, the citing officer's note, and a link to the citation PDF. It
diffs against the previous run to flag **NEW** and **ESCALATED** tickets.

## How it works

Data comes from the Seattle Municipal Court public records API
(`courtrecords-api.seattle.gov`, unauthenticated). Most fields are JSON, but the
**fine amount and infraction location live only in the scanned ticket image**
(page 1 of the citation PDF), so those two are obtained via OCR
(`pypdfium2` render + `tesseract`). Everything degrades gracefully: if OCR is
unavailable or a scan misreads, the fine/location show `—` and the PDF link is
still included.

Pipeline: list open citations for a plate → per case pull charges / docket /
parties / hearings / judgments → download + OCR the citation PDF for fine +
location → diff vs saved state → build HTML → email via Gmail SMTP.

## Requirements

- Python 3.10+
- `tesseract` binary on the host (Ubuntu: `sudo apt install tesseract-ocr`)
- Python packages (installed into a local `.venv` by `setup.sh`):
  `pypdfium2`, `pytesseract`, `Pillow`
- A `~/.netrc` entry for Gmail SMTP:
  ```
  machine smtp.gmail.com
      login your.address@gmail.com
      password <gmail app password>
  ```

## Setup

```
bash setup.sh
```
Creates `.venv` (bootstrapping pip without sudo if needed) and installs
requirements. Verify: `.venv/bin/python3 -c "import pytesseract, pypdfium2"`.

## Usage

```
.venv/bin/python3 track.py --plate BYP5855 --email-to you@example.com
```

Both flags accept multiple values:
```
.venv/bin/python3 track.py --plate BYP5855 ABC1234 --email-to you@example.com spouse@example.com
```

Options:
- `--dry-run` — print the report instead of emailing; does not update state
- `--no-pdf` — skip PDF/OCR (no fine/location); faster for testing
- `--state-dir DIR` — where per-plate snapshots live (default
  `~/.local/state/parking-tickets`)

## Cron (weekly)

Use the venv interpreter by absolute path (cron doesn't activate venvs):
```
7 8 * * 1 /home/you/parking-ticket-tracker/.venv/bin/python3 /home/you/parking-ticket-tracker/track.py --plate BYP5855 --email-to you@example.com >> /tmp/parking_tickets.log 2>&1
```

## Notes / limitations

- Only **open** cases are tracked (the API filters `closedFlag=false`).
- There is no structured "in collections / impounded" field in the API today.
  Escalation is inferred structurally: a hearing or judgment appearing, the
  docket growing, or docket/charge text matching escalation keywords
  (impound, tow, warrant, default judgment, …). See `state.py`.
- Fine/location are OCR'd — verify against the linked PDF if a value looks off.
