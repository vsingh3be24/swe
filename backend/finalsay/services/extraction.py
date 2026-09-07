"""Extraction (module 2, design.md section 5).

Pipeline: text acquisition (PDF via pypdf, image via pytesseract only when a
Tesseract binary is available, pasted text used directly) -> field extraction
(issuer, date, deadline, audience, action with per-field confidence) -> a
redaction pass that masks emails, phone numbers, roll/registration numbers and
name patterns.

GC-5 / R2.4: only redacted text and extracted fields are ever returned. This
module never returns or persists the unredacted original text.
"""

from __future__ import annotations

import io
import re
import shutil
from dataclasses import dataclass, field

from finalsay.config import get_settings


class OcrUnavailable(RuntimeError):
    """Raised when image OCR is requested but no Tesseract engine is available.

    The API layer surfaces this as HTTP 422 asking the user to paste text
    instead (graceful degradation for R2.1).
    """


@dataclass
class ExtractionResult:
    """Result of the extraction pipeline.

    ``redacted_text`` is the only textual artifact that should be stored or
    returned to callers. ``fields`` maps each field name to a
    ``(value, confidence)`` tuple.
    """

    redacted_text: str
    fields: dict[str, tuple[str | None, float]] = field(default_factory=dict)

    def field_value(self, name: str) -> str | None:
        pair = self.fields.get(name)
        return pair[0] if pair else None


# --- Redaction patterns (applied before storage, GC-5) ------------------------

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Phone numbers: optional +country, separators, 7+ digits total.
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3}[\s.-]?\d{3,4}(?!\w)"
)
# Roll / registration numbers, e.g. 21CS0456 (two digits, two letters, 4+ digits).
_ROLL_RE = re.compile(r"\b\d{2}[A-Z]{2}\d{4,}\b")
# Honorific names: Mr./Ms./Mrs./Dr. Firstname [Lastname]
_HONORIFIC_NAME_RE = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
)
# "Name: John Doe" style labelled names.
_LABELLED_NAME_RE = re.compile(
    r"\bName\s*[:\-]\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*"
)

_EMAIL_MASK = "[REDACTED_EMAIL]"
_PHONE_MASK = "[REDACTED_PHONE]"
_ROLL_MASK = "[REDACTED_ID]"
_NAME_MASK = "[REDACTED_NAME]"


def redact(text: str) -> str:
    """Mask personal data (emails, phones, roll numbers, names) in ``text``.

    Order matters: emails and roll numbers are masked before phone numbers so
    the broader phone pattern cannot partially consume them.
    """
    redacted = _EMAIL_RE.sub(_EMAIL_MASK, text)
    redacted = _ROLL_RE.sub(_ROLL_MASK, redacted)
    redacted = _HONORIFIC_NAME_RE.sub(_NAME_MASK, redacted)
    redacted = _LABELLED_NAME_RE.sub(f"Name: {_NAME_MASK}", redacted)
    redacted = _PHONE_RE.sub(_PHONE_MASK, redacted)
    return redacted


# --- Text acquisition ---------------------------------------------------------

def _tesseract_available() -> str | None:
    """Return a usable tesseract command path, or None if no engine is present."""
    settings = get_settings()
    configured = settings.tesseract_cmd
    if configured and configured != "auto":
        return configured if shutil.which(configured) or _is_file(configured) else None
    return shutil.which("tesseract")


def _is_file(path: str) -> bool:
    import os

    return os.path.isfile(path)


def text_from_pdf(data: bytes) -> str:
    """Extract embedded text from PDF bytes using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(parts).strip()


def text_from_image(data: bytes) -> str:
    """OCR image bytes via pytesseract, or raise OcrUnavailable if no engine."""
    cmd = _tesseract_available()
    if cmd is None:
        raise OcrUnavailable(
            "No Tesseract OCR engine is available. Please paste the notice text instead."
        )
    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = cmd
    image = Image.open(io.BytesIO(data))
    return pytesseract.image_to_string(image).strip()


def acquire_text(
    *,
    text: str | None = None,
    pdf_bytes: bytes | None = None,
    image_bytes: bytes | None = None,
) -> str:
    """Return raw text from exactly one of pasted text, PDF bytes or image bytes.

    Raises OcrUnavailable for image input when no OCR engine exists.
    """
    if text is not None:
        return text.strip()
    if pdf_bytes is not None:
        return text_from_pdf(pdf_bytes)
    if image_bytes is not None:
        return text_from_image(image_bytes)
    raise ValueError("acquire_text requires one of: text, pdf_bytes, image_bytes")


# --- Field extraction ---------------------------------------------------------

_MONTHS = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)"
)
# e.g. "15 Sept", "22 September 2024", "September 15, 2024", "2024-09-15", "15/09/2024"
_DATE_RE_SRC = (
    rf"\b(?:\d{{1,2}}\s+{_MONTHS}(?:\s+\d{{4}})?"
    rf"|{_MONTHS}\s+\d{{1,2}}(?:,?\s+\d{{4}})?"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}/\d{1,2}/\d{2,4})\b"
)
_DATE_RE = re.compile(_DATE_RE_SRC, re.IGNORECASE)

_ISSUER_RE = re.compile(
    r"(?:^|\n)\s*(?:From|Issued by|Issuer|Office of|Department of)\s*[:\-]?\s*(.+)",
    re.IGNORECASE,
)
# Deadline cue words. Anchored so the generic "by <date>" cue only fires when a
# date actually follows, and never on the word "by" inside "Issued by:" (the
# issuer line) which previously drove the harness deadline F1 to ~0.0.
# Explicit cues (deadline / due / last date / closes on / cutoff / register by /
# submit by / extended to) capture the trailing clause; a plain "by" or
# "extended to" must be immediately followed by a date to count.
_DEADLINE_EXPLICIT_RE = re.compile(
    r"(?:deadline|due date|due|last date(?:\s+of\s+\w+)?|closes?(?:\s+on)?|cutoff)"
    r"\s*(?:is|:|-)?\s*(.+?)(?:\.|\n|$)",
    re.IGNORECASE,
)
# "by <date>" / "extended to <date>" / "before <date>" — but NOT "Issued by".
_DEADLINE_BY_RE = re.compile(
    rf"(?<!issued )(?:extended\s+to|register\s+by|submit\s+by|before|by)\s+"
    rf"({_DATE_RE_SRC})",
    re.IGNORECASE,
)
_AUDIENCE_RE = re.compile(
    r"(?:to all|attention|for(?:\s+all)?|audience)\s*[:\-]?\s*"
    r"([A-Za-z][A-Za-z\s,]{2,60}?students?[A-Za-z\s,]{0,40})",
    re.IGNORECASE,
)
_ACTION_VERBS = (
    "postponed",
    "rescheduled",
    "cancelled",
    "canceled",
    "extended",
    "corrected",
    "advanced",
    "moved",
    "will be held",
    "is scheduled",
    "must",
    "required to",
)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _extract_deadline(text: str) -> tuple[str | None, float]:
    """Extract the deadline as a date near a deadline cue.

    Strategy (in priority order):
    1. A "<cue> <date>" phrase (``register by``/``submit by``/``extended to``/
       ``before``/bare ``by``) that is immediately followed by a date. The bare
       ``by`` cue explicitly excludes the ``Issued by:`` issuer line, which was
       the source of the harness deadline-F1 regression. Returns just the date.
    2. An explicit deadline cue word (``deadline``/``due``/``last date``/
       ``closes``/``cutoff``); the first date inside the captured clause is
       preferred, otherwise the trimmed clause itself.

    Returns ``(value, confidence)`` or ``(None, 0.0)`` when no deadline is found.
    """
    by_match = _DEADLINE_BY_RE.search(text)
    if by_match:
        return (by_match.group(1).strip(), 0.85)

    explicit = _DEADLINE_EXPLICIT_RE.search(text)
    if explicit:
        clause = explicit.group(1).strip()
        date_in_clause = _DATE_RE.search(clause)
        if date_in_clause:
            return (date_in_clause.group(0).strip(), 0.8)
        # No date in the clause: keep a short trimmed value only, avoiding
        # runaway multi-clause captures.
        short = clause.split(",")[0].strip()
        return (short or None, 0.5) if short else (None, 0.0)

    return (None, 0.0)


def extract_fields(text: str) -> dict[str, tuple[str | None, float]]:
    """Rule/regex based extractor for issuer, date, deadline, audience, action.

    Returns a mapping ``field_name -> (value, confidence)``; missing fields get
    ``(None, 0.0)``.
    """
    fields: dict[str, tuple[str | None, float]] = {}

    # issuer: explicit marker, else fall back to first non-empty line.
    issuer_match = _ISSUER_RE.search(text)
    if issuer_match:
        fields["issuer"] = (issuer_match.group(1).strip(), 0.8)
    else:
        first = _first_line(text)
        fields["issuer"] = (first or None, 0.4 if first else 0.0)

    # date: the first recognizable date.
    date_match = _DATE_RE.search(text)
    fields["date"] = (
        (date_match.group(0).strip(), 0.85) if date_match else (None, 0.0)
    )

    # deadline: prefer a "<cue> <date>" match (register/submit by, extended to,
    # before, or a bare "by" that is NOT the "Issued by:" issuer line) which
    # yields just the date; otherwise fall back to an explicit deadline phrase
    # and pull the first date out of its clause.
    fields["deadline"] = _extract_deadline(text)

    # audience: e.g. "all first-year students".
    audience_match = _AUDIENCE_RE.search(text)
    fields["audience"] = (
        (audience_match.group(1).strip(), 0.6) if audience_match else (None, 0.0)
    )

    # action: the sentence/clause containing a known action verb.
    action_value: str | None = None
    for verb in _ACTION_VERBS:
        idx = text.lower().find(verb)
        if idx != -1:
            # take the enclosing sentence.
            start = text.rfind(".", 0, idx) + 1
            end = text.find(".", idx)
            end = end if end != -1 else len(text)
            action_value = text[start:end].strip()
            break
    fields["action"] = (
        (action_value, 0.7) if action_value else (None, 0.0)
    )

    return fields


def extract(
    *,
    text: str | None = None,
    pdf_bytes: bytes | None = None,
    image_bytes: bytes | None = None,
) -> ExtractionResult:
    """Run the full pipeline and return only redacted text + extracted fields.

    Fields are extracted from the redacted text so no personal data leaks into
    stored field values either.
    """
    raw = acquire_text(text=text, pdf_bytes=pdf_bytes, image_bytes=image_bytes)
    redacted_text = redact(raw)
    fields = extract_fields(redacted_text)
    return ExtractionResult(redacted_text=redacted_text, fields=fields)
