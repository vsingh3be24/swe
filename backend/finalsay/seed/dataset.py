"""Synthetic dataset generator for the seed script and eval harness (R7.3).

Produces, deterministically (no randomness, so re-running is stable):

- Three fictional institutions (Northgate, Riverside, Summit).
- ~40 official notices per institution.
- ~60 student submissions, each paired with an official notice and a *gold*
  relationship label covering EVERY taxonomy label: consistent, contradictory,
  superseded, corrected, extended, cancelled, unresolved. Includes deliberately
  ambiguous pairs (gold ``unresolved``) and low-lexical-overlap date conflicts
  (e.g. "22 Sept" vs "15 Sept").
- Gold field values per notice for extraction-F1 scoring.

Two phrasing styles are produced per gold label:

- ``cue`` phrasings (used for the early/training rounds) spell out the rule cue
  the default :class:`MockComparisonModel` keys on, so the seeded reviewer
  console and demo show every taxonomy label deterministically.
- ``naturalistic`` phrasings (used for the *held-out* evaluation rounds) express
  the same gold relationship the way a real notice might, WITHOUT guaranteeing
  the exact mock cue fires. This makes the evaluation honest: relationship F1 on
  the held-out splits reflects how the model actually generalises rather than
  measuring text that was reverse-engineered from its own rules. Metrics on the
  held-out splits are therefore genuine and need not be perfect.
"""

from __future__ import annotations

from dataclasses import dataclass, field

INSTITUTIONS = [
    {"slug": "northgate", "name": "Northgate University", "source_url": "https://notices.northgate.edu"},
    {"slug": "riverside", "name": "Riverside Institute", "source_url": "https://notices.riverside.edu"},
    {"slug": "summit", "name": "Summit College", "source_url": "https://notices.summit.edu"},
]

# The held-out institution for the eval "institution" split.
HELD_OUT_SLUG = "summit"

# A rotating set of topics used to synthesize plausible official notices.
_TOPICS = [
    ("Mid-term examination", "exam"),
    ("Library extended hours", "library"),
    ("Hostel maintenance", "hostel"),
    ("Fee payment window", "fees"),
    ("Convocation ceremony", "convocation"),
    ("Sports meet", "sports"),
    ("Guest lecture series", "lecture"),
    ("Scholarship applications", "scholarship"),
    ("Campus placement drive", "placement"),
    ("Semester registration", "registration"),
]

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class OfficialSpec:
    external_id: str
    institution_slug: str
    text: str
    issuer: str
    date: str
    deadline: str | None
    audience: str
    action: str
    source_url: str


@dataclass
class SubmissionSpec:
    key: str
    institution_slug: str
    text: str
    gold_label: str
    official_external_id: str
    gold_fields: dict = field(default_factory=dict)
    # Used to build a temporal split: 0 = early, 1 = late (held out in temporal split).
    temporal_bucket: int = 0


def _issuer_for(slug: str) -> str:
    return {
        "northgate": "Office of the Registrar, Northgate University",
        "riverside": "Academic Section, Riverside Institute",
        "summit": "Registrar Office, Summit College",
    }[slug]


def _official_text(issuer: str, topic: str, date: str, deadline: str, audience: str, action: str) -> str:
    lines = [
        f"Issued by: {issuer}",
        f"Subject: {topic}",
        f"Date: {date}",
        f"To all {audience}.",
        action,
    ]
    if deadline:
        lines.append(f"Deadline: {deadline}.")
    lines.append("For queries contact the office during working hours.")
    return "\n".join(lines)


def generate_officials() -> list[OfficialSpec]:
    """Generate ~40 official notices per institution (deterministic)."""
    officials: list[OfficialSpec] = []
    for inst in INSTITUTIONS:
        slug = inst["slug"]
        issuer = _issuer_for(slug)
        base_url = inst["source_url"]
        # 40 notices per institution.
        for i in range(40):
            topic_name, topic_key = _TOPICS[i % len(_TOPICS)]
            day = (i % 27) + 1
            month = _MONTHS[i % 12]
            date = f"{day} {month}"
            audience = "students" if i % 2 == 0 else "first-year students"
            deadline = f"{min(day + 7, 28)} {month}" if topic_key in {"fees", "scholarship", "registration", "placement"} else ""
            action = f"The {topic_name.lower()} is scheduled on {date} for all {audience}."
            ext_id = f"{slug}-{topic_key}-{i:02d}"
            officials.append(
                OfficialSpec(
                    external_id=ext_id,
                    institution_slug=slug,
                    text=_official_text(issuer, topic_name, date, deadline, audience, action),
                    issuer=f"Issued by: {issuer}",
                    date=date,
                    deadline=(f"{deadline}." if deadline else None),
                    audience=f"all {audience}",
                    action=action,
                    source_url=f"{base_url}/notices/{ext_id}",
                )
            )
    return officials


def _find_official(officials: list[OfficialSpec], slug: str, topic_key: str, index: int) -> OfficialSpec:
    matches = [o for o in officials if o.institution_slug == slug and topic_key in o.external_id]
    return matches[index % len(matches)]


def generate_submissions(officials: list[OfficialSpec]) -> list[SubmissionSpec]:
    """Generate ~60 gold-labeled submissions covering every taxonomy label.

    Early rounds (``temporal_bucket == 0``) use cue phrasings that the mock rule
    engine reproduces deterministically, so the seeded demo shows every label.
    The last round (``temporal_bucket == 1``, held out by the temporal split)
    uses naturalistic phrasings NOT engineered around the rule cues, so the eval
    harness measures real discrimination rather than the fixtures.
    """
    subs: list[SubmissionSpec] = []

    # Distribution across the three institutions and the seven labels. We build
    # roughly 3 examples per (label) per institution -> ~60 total, plus extras.
    labels_plan = [
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved",
    ]

    counter = 0
    for inst in INSTITUTIONS:
        slug = inst["slug"]
        for round_idx in range(3):  # 3 rounds * 7 labels * 3 inst = 63 submissions
            for label in labels_plan:
                official = _find_official(officials, slug, "exam", counter)
                bucket = 1 if round_idx == 2 else 0  # last round is "late" (temporal holdout)
                # Held-out round (bucket 1) uses naturalistic phrasing not built
                # around the mock cues, so eval on the temporal split is honest.
                naturalistic = bucket == 1
                sub = _make_submission(
                    slug, label, official, counter, bucket, naturalistic
                )
                subs.append(sub)
                counter += 1

    # Add two spotlight low-overlap date-conflict cases ("22 Sept" vs "15 Sept").
    for slug in ("northgate", "riverside"):
        official = _find_official(officials, slug, "exam", 0)
        subs.append(
            SubmissionSpec(
                key=f"{slug}-spotlight-2215",
                institution_slug=slug,
                text="Mid-term exam moved. It is postponed to 22 Sep from the earlier date.",
                gold_label="superseded",
                official_external_id=official.external_id,
                gold_fields={"date": "22 Sep", "action": "postponed to 22 Sep"},
                temporal_bucket=0,
            )
        )
    return subs


def _naturalistic_text(label: str, base_topic: str, audience: str) -> tuple[str, dict]:
    """Return realistic phrasing for ``label`` that is NOT engineered around the
    mock rule cues, plus its gold field values.

    These are the held-out evaluation phrasings. Some will be classified
    correctly by the mock engine (genuine skill), others may be gated to
    ``unresolved`` or missed — which is the honest signal the harness reports.
    """
    # These retain the *genuine* structure a real notice would carry (dates,
    # negations, overlap) so the model's real reasoning can partially succeed,
    # but they drop the reverse-engineered exact keyword cues (e.g. the words
    # "postponed"/"cancelled"/"erratum"/"extended to") that previously made the
    # score a round-trip check. Some are correctly classified (real skill),
    # others are missed or gated to unresolved (the honest signal).
    if label == "consistent":
        text = (
            f"Just confirming that {base_topic} is going ahead as announced for "
            f"{audience}; the schedule I received matches the official one exactly "
            f"and remains unchanged."
        )
        return text, {"action": "confirmed as scheduled"}
    if label == "superseded":
        # A later date replaces an earlier one; the word "postponed" is absent,
        # so the model must reason from the conflicting dates alone.
        text = (
            f"Heads up: {base_topic} originally set for 15 Sep will now take "
            f"place on 22 Sep instead."
        )
        return text, {"date": "22 Sep", "action": "now on 22 Sep"}
    if label == "extended":
        # Deadline shifts later without the literal "extended to" cue.
        text = (
            f"The registration window for {base_topic}, first closing on 14 Oct, "
            f"now runs through 28 Oct to give everyone more time."
        )
        return text, {"deadline": "28 Oct", "action": "window now runs to 28 Oct"}
    if label == "contradictory":
        # Two conflicting dates plus an explicit negation, but no postpone cue.
        text = (
            f"The date I was told for {base_topic} is 3 Nov, which is not the "
            f"15 Sep printed on the official notice."
        )
        return text, {"date": "3 Nov", "action": "date given as 3 Nov"}
    if label == "corrected":
        text = (
            f"Please note a revised venue for {base_topic}: it will be held in "
            f"Hall B; everything else stays the same."
        )
        return text, {"action": "revised venue to Hall B"}
    if label == "cancelled":
        text = (
            f"We regret to inform {audience} that {base_topic} will no longer be "
            f"taking place this term."
        )
        return text, {"action": "no longer taking place"}
    # unresolved
    text = (
        "There seems to be some confusion about the recent circular; the timing "
        "and venue details are not entirely clear to me."
    )
    return text, {"action": None}


def _make_submission(
    slug: str,
    label: str,
    official: OfficialSpec,
    idx: int,
    bucket: int,
    naturalistic: bool = False,
) -> SubmissionSpec:
    """Craft a submission for ``label``.

    When ``naturalistic`` is set the text uses realistic phrasing not engineered
    around the mock rule cues (held-out evaluation data); otherwise it uses cue
    phrasing the mock model reproduces deterministically (demo/training data).
    """
    base_topic = "the mid-term examination"
    audience = "all students"
    key = f"{slug}-{label}-{idx:02d}"

    if naturalistic:
        text, fields = _naturalistic_text(label, base_topic, audience)
        return SubmissionSpec(
            key=key,
            institution_slug=slug,
            text=text,
            gold_label=label,
            official_external_id=official.external_id,
            gold_fields=fields,
            temporal_bucket=bucket,
        )

    if label == "consistent":
        # High lexical overlap, no conflicting facts -> consistent.
        text = official.text + "\nThis matches the official schedule and remains unchanged."
        fields = {"date": official.date, "action": "confirmed as scheduled"}
    elif label == "superseded":
        # Conflicting dates + postpone cue -> superseded.
        text = (
            f"Notice: {base_topic} for {audience} has been postponed and rescheduled "
            f"to 22 Sep, moving away from the earlier 15 Sep date."
        )
        fields = {"date": "22 Sep", "action": "postponed to 22 Sep"}
    elif label == "extended":
        # Conflicting dates + extend cue -> extended.
        text = (
            f"The deadline for {base_topic} registration has been extended to 28 Oct, "
            f"beyond the original 14 Oct cutoff."
        )
        fields = {"deadline": "28 Oct", "action": "deadline extended to 28 Oct"}
    elif label == "contradictory":
        # Conflicting dates, no postpone/extend cue -> contradictory.
        text = (
            f"According to this notice, {base_topic} is on 3 Nov, whereas the official "
            f"notice states 15 Sep."
        )
        fields = {"date": "3 Nov", "action": "claimed on 3 Nov"}
    elif label == "corrected":
        # Correction/erratum cue -> corrected.
        text = (
            f"Correction: an erratum has been issued for {base_topic}. The corrected "
            f"venue is Hall B; all other details remain."
        )
        fields = {"action": "correction issued for venue"}
    elif label == "cancelled":
        # Cancellation cue -> cancelled.
        text = (
            f"This is to inform {audience} that {base_topic} has been cancelled "
            f"until further notice."
        )
        fields = {"action": "cancelled until further notice"}
    else:  # unresolved
        # Deliberately ambiguous, low-overlap, no strong cue -> unresolved (gated).
        text = (
            "Kindly clarify the arrangement mentioned in the circular; the details "
            "appear unclear regarding venue and timing."
        )
        fields = {"action": None}

    return SubmissionSpec(
        key=key,
        institution_slug=slug,
        text=text,
        gold_label=label,
        official_external_id=official.external_id,
        gold_fields=fields,
        temporal_bucket=bucket,
    )


# --- Benchmark annotations (two annotators) -----------------------------------

# Reviewer A and Reviewer B annotations over a fixed set of pairs. Designed so
# Cohen's kappa is a stable, non-trivial value (substantial-but-imperfect
# agreement) for the benchmark screen and the eval harness.
BENCHMARK_ANNOTATORS = ("reviewer_a", "reviewer_b")

# (gold_label, annotator_a_label, annotator_b_label) triples for 14 pairs.
BENCHMARK_TRIPLES = [
    ("consistent", "consistent", "consistent"),
    ("consistent", "consistent", "consistent"),
    ("superseded", "superseded", "superseded"),
    ("superseded", "superseded", "contradictory"),
    ("contradictory", "contradictory", "contradictory"),
    ("contradictory", "contradictory", "superseded"),
    ("corrected", "corrected", "corrected"),
    ("cancelled", "cancelled", "cancelled"),
    ("extended", "extended", "extended"),
    ("extended", "extended", "superseded"),
    ("unresolved", "unresolved", "unresolved"),
    ("unresolved", "unresolved", "contradictory"),
    ("consistent", "consistent", "consistent"),
    ("cancelled", "cancelled", "cancelled"),
]

# --- Demo users (known passwords, documented in HANDOFF/README) ---------------

DEMO_USERS = [
    {"email": "student@finalsay.demo", "password": "student123", "role": "student", "display_name": "Demo Student"},
    {"email": "reviewer@finalsay.demo", "password": "reviewer123", "role": "reviewer", "display_name": "Demo Reviewer"},
    {"email": "admin@finalsay.demo", "password": "admin123", "role": "admin", "display_name": "Demo Admin"},
    {"email": "issuer@finalsay.demo", "password": "issuer123", "role": "issuer", "display_name": "Demo Issuer"},
]
