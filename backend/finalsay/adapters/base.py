"""InstitutionAdapter interface (module 1, design.md section 4).

``InstitutionAdapter.fetch() -> list[RawNotice]`` reads that institution's
fixture file (``seed/fixtures/<inst>_official.json``) and returns raw notices,
each carrying a ``source_url``. Adapters are independently replaceable behind
the ABC so a real HTTP scraper could drop in without touching ingestion.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# The fixtures directory lives next to the seed script (design.md section 1).
_FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "seed", "fixtures")


@dataclass
class RawNotice:
    """A raw (un-extracted) notice as returned by an adapter.

    ``text`` is the raw notice body (before redaction); ``source_url`` records
    where the notice was fetched from. Extraction/redaction runs downstream in
    the ingestion service, so the raw text is never persisted directly.
    """

    text: str
    source_url: str
    institution_slug: str
    external_id: str | None = None
    metadata: dict = field(default_factory=dict)


class InstitutionAdapter(ABC):
    """Interface for fetching an institution's official notices."""

    slug: str = "abstract"
    name: str = "Abstract Institution"
    base_url: str = "https://example.edu"

    @abstractmethod
    def fetch(self) -> list[RawNotice]:
        """Return the institution's current official notices as raw notices."""
        raise NotImplementedError


class FixtureAdapter(InstitutionAdapter):
    """Base adapter that reads ``seed/fixtures/<slug>_official.json``.

    The fixture is a JSON list of objects with at least a ``text`` field and
    optionally ``source_url``/``external_id``. Missing files yield an empty
    list so ingestion never crashes on a not-yet-seeded institution.
    """

    def fetch(self) -> list[RawNotice]:
        path = os.path.join(_FIXTURES_DIR, f"{self.slug}_official.json")
        if not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as handle:
            records = json.load(handle)

        notices: list[RawNotice] = []
        for record in records:
            external_id = record.get("external_id")
            source_url = record.get("source_url") or (
                f"{self.base_url.rstrip('/')}/notices/{external_id or ''}"
            )
            notices.append(
                RawNotice(
                    text=record["text"],
                    source_url=source_url,
                    institution_slug=self.slug,
                    external_id=external_id,
                    metadata={
                        k: v
                        for k, v in record.items()
                        if k not in {"text", "source_url", "external_id"}
                    },
                )
            )
        return notices


def get_adapters() -> list[InstitutionAdapter]:
    """Return the three fixture-backed institution adapters."""
    # Imported here to avoid a circular import at module load time.
    from finalsay.adapters.inst_northgate import NorthgateAdapter
    from finalsay.adapters.inst_riverside import RiversideAdapter
    from finalsay.adapters.inst_summit import SummitAdapter

    return [NorthgateAdapter(), RiversideAdapter(), SummitAdapter()]
