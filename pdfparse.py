"""Extract fine + location from a Seattle citation PDF via OCR.

The citation PDF's first page is a SCANNED IMAGE of the paper ticket; the fine
amount and infraction location exist only as pixels there (the PDF text layer
has no dollar amounts and no address). So we rasterize the first couple of
pages with pypdfium2 and OCR them with pytesseract (tesseract binary required
on the host).

Everything degrades gracefully: any failure (missing tesseract, unreadable
scan, unexpected layout) returns None for the affected field so the report can
fall back to the PDF link rather than crashing the run.
"""

from __future__ import annotations

import io
import re

# Pages to OCR. Page 1 (index 0) is the ticket face with fine + location.
# Page 2 sometimes carries overflow; OCR both to be safe.
_OCR_PAGES = (0, 1)
_RENDER_DPI = 200

# "Fine: $65.00"
_FINE_RE = re.compile(r"Fine\s*[:\-]?\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
# Fallback: any dollar amount if the "Fine:" label OCRs badly.
_DOLLAR_RE = re.compile(r"\$\s*([\d,]+\.\d{2})")
# "INFRACTION LOCATION:\n314 1ST AVE W"
_LOCATION_RE = re.compile(
    r"INFRACTION\s+LOCATION\s*[:\-]?\s*\n?\s*(.+)", re.IGNORECASE
)


def _ocr_text(pdf_bytes):
    """Rasterize the first pages and return concatenated OCR text, or ''.

    Imports are done lazily so the rest of the tool works even if the OCR
    stack isn't installed (the caller treats an empty string as "no data").
    """
    try:
        import pypdfium2 as pdfium
        import pytesseract
    except Exception:
        return ""

    try:
        doc = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    except Exception:
        return ""

    chunks = []
    try:
        n = len(doc)
        for idx in _OCR_PAGES:
            if idx >= n:
                break
            try:
                page = doc[idx]
                pil = page.render(scale=_RENDER_DPI / 72).to_pil()
                chunks.append(pytesseract.image_to_string(pil))
            except Exception:
                continue
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return "\n".join(chunks)


def _clean_location(raw):
    """Trim an OCR'd location line to something address-like."""
    line = raw.strip()
    # Cut at obvious next-field labels if OCR ran lines together.
    for stop in ("REGISTRATION", "License", "VIOLATION", "SMC", "Public"):
        i = line.upper().find(stop.upper())
        if i > 0:
            line = line[:i]
    line = line.strip(" .:-")
    # Sanity: must contain a digit or look like a street.
    if not line or len(line) > 120:
        return None
    return line


def parse_citation_pdf(pdf_bytes):
    """Return {'fine': str|None, 'location': str|None, 'ocr_ok': bool}.

    - fine: dollar amount as a string like "65.00" (no $), or None.
    - location: infraction location line, or None.
    - ocr_ok: True if we got any OCR text at all (lets caller distinguish
      "OCR unavailable" from "OCR ran but found nothing").

    Note: escalation is NOT derived from the PDF — every ticket's page 2
    carries boilerplate describing tow/impound consequences, so it's not a
    signal. Escalation is detected structurally in state.py (new hearings/
    judgments, changed docket entries).
    """
    result = {"fine": None, "location": None, "ocr_ok": False}
    text = _ocr_text(pdf_bytes)
    if not text:
        return result
    result["ocr_ok"] = True

    m = _FINE_RE.search(text)
    if not m:
        m = _DOLLAR_RE.search(text)
    if m:
        result["fine"] = m.group(1).replace(",", "")

    m = _LOCATION_RE.search(text)
    if m:
        result["location"] = _clean_location(m.group(1))

    return result
