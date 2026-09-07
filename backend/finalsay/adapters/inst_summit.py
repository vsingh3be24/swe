"""Summit College adapter (fixtures). Held-out institution in the eval split."""

from __future__ import annotations

from finalsay.adapters.base import FixtureAdapter


class SummitAdapter(FixtureAdapter):
    slug = "summit"
    name = "Summit College"
    base_url = "https://notices.summit.edu"
