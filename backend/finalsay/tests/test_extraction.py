"""Extraction tests: field extraction, redaction, and OCR graceful degradation."""

from __future__ import annotations

import pytest

from finalsay.services import extraction
from finalsay.services.extraction import OcrUnavailable

SAMPLE = (
    "Office of the Registrar\n"
    "Attention: all first-year students\n"
    "The mid-term exam is postponed to 22 Sept 2024.\n"
    "Deadline: submit forms by 20 Sept 2024.\n"
    "Contact Dr. Jane Smith at jane.smith@northgate.edu or +1 415 555 2671.\n"
    "Roll number 21CS0456 must re-register.\n"
    "Name: Robert Brown\n"
)


def test_fields_extracted():
    result = extraction.extract(text=SAMPLE)
    fields = result.fields
    assert set(["issuer", "date", "deadline", "audience", "action"]).issubset(
        fields.keys()
    )
    # issuer picked up from the "Office of" marker.
    assert fields["issuer"][0] is not None
    # a date is recognized.
    assert fields["date"][0] is not None
    # action clause mentions the postponement.
    assert "postpon" in (fields["action"][0] or "").lower()
    # confidences are in [0, 1].
    for value, conf in fields.values():
        assert 0.0 <= conf <= 1.0


def test_redaction_masks_pii():
    redacted = extraction.redact(SAMPLE)
    # Email removed.
    assert "jane.smith@northgate.edu" not in redacted
    assert "[REDACTED_EMAIL]" in redacted
    # Phone removed.
    assert "555 2671" not in redacted
    assert "[REDACTED_PHONE]" in redacted
    # Roll number removed.
    assert "21CS0456" not in redacted
    assert "[REDACTED_ID]" in redacted
    # Names removed.
    assert "Jane Smith" not in redacted
    assert "Robert Brown" not in redacted
    assert "[REDACTED_NAME]" in redacted


def test_extract_returns_only_redacted_text():
    result = extraction.extract(text=SAMPLE)
    # The returned text must not contain any original PII.
    assert "jane.smith@northgate.edu" not in result.redacted_text
    assert "21CS0456" not in result.redacted_text
    assert "Robert Brown" not in result.redacted_text
    # Fields extracted from redacted text must not leak PII either.
    for value, _conf in result.fields.values():
        if value:
            assert "jane.smith@northgate.edu" not in value
            assert "21CS0456" not in value


def test_ocr_unavailable_raises_typed_error(monkeypatch):
    # Force "no tesseract engine available".
    monkeypatch.setattr(extraction, "_tesseract_available", lambda: None)
    with pytest.raises(OcrUnavailable):
        extraction.acquire_text(image_bytes=b"\x89PNG\r\n\x1a\n fake image bytes")


def test_pasted_text_path_works_without_ocr(monkeypatch):
    monkeypatch.setattr(extraction, "_tesseract_available", lambda: None)
    # Pasted text must work even when no OCR engine exists.
    result = extraction.extract(text="Exam on 15 Sept.")
    assert "15 Sept" in result.redacted_text
