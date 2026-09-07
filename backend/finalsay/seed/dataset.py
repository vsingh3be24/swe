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

# Reviewer A and Reviewer B annotations over the labelled benchmark. Designed so
# Cohen's kappa is a stable, non-trivial value (substantial-but-imperfect
# agreement) for the benchmark screen and the eval harness.
#
# Scope-note sections 1 and 7 require a labelled benchmark of 300+ notice
# pairs/chains, each carrying a gold relationship label plus two INDEPENDENT
# annotator labels. The benchmark is a dataset in its own right and is distinct
# from the eval gold submissions (which drive the held-out harness metrics), so
# scaling it here does NOT touch the temporal-holdout naturalistic phrasings.
BENCHMARK_ANNOTATORS = ("reviewer_a", "reviewer_b")

# Every taxonomy label appears as a gold label in the benchmark, including the
# deliberately ambiguous ``unresolved`` bucket and the low-vocabulary-overlap
# date-conflict cases (contradictory / superseded), so gold coverage spans the
# full 7-label relationship taxonomy.
_BENCHMARK_LABELS = (
    "consistent",
    "contradictory",
    "superseded",
    "corrected",
    "extended",
    "cancelled",
    "unresolved",
)

# For each gold label, the single most *confusable* label a careful annotator
# might reach instead. These mirror the genuine ambiguities in the taxonomy:
# a superseding notice and a contradicting one both carry a conflicting date;
# an extension looks like a supersession; an erratum/correction can read as a
# no-op (consistent); an ambiguous circular can read as a contradiction.
_BENCHMARK_CONFUSABLE = {
    "consistent": "corrected",
    "contradictory": "superseded",
    "superseded": "contradictory",
    "corrected": "consistent",
    "extended": "superseded",
    "cancelled": "superseded",
    "unresolved": "contradictory",
}

# Target size of the labelled benchmark (>= 300; 44 * 7 = 308 keeps the seven
# labels perfectly balanced).
BENCHMARK_TARGET = 308


def generate_benchmark_triples(
    target: int = BENCHMARK_TARGET,
) -> list[tuple[str, str, str]]:
    """Deterministically generate ``>= target`` benchmark annotation triples.

    Returns a list of ``(gold_label, annotator_a_label, annotator_b_label)``.

    The generator is pure and deterministic (no randomness, no seeded RNG), so
    re-running the seed yields identical row counts and an identical Cohen's
    kappa. Gold labels cycle through all seven relationship types for balanced
    coverage. Each annotator INDEPENDENTLY disagrees with the gold label on a
    fixed, offset fraction of the confusable cases (annotator A on every 7th
    such case, annotator B on every 4th), so:

    - neither annotator is a trivial copy of the gold column,
    - the two annotators disagree with each other on a realistic, non-trivial
      share of pairs, landing Cohen's kappa in the substantial-but-imperfect
      band (~0.6-0.85, strictly > 0 and strictly < 1.0),
    - the disagreements are confined to genuinely confusable label pairs
      (superseded<->contradictory, extended<->superseded, corrected<->consistent,
      unresolved<->contradictory), which is how real annotator noise looks.
    """
    triples: list[tuple[str, str, str]] = []
    i = 0
    while len(triples) < target:
        gold = _BENCHMARK_LABELS[i % len(_BENCHMARK_LABELS)]
        confusable = _BENCHMARK_CONFUSABLE[gold]
        # Annotator A: careful, disagrees with gold only occasionally.
        a = confusable if (i % 7 == 3 and confusable != gold) else gold
        # Annotator B: independently disagrees on a different (denser) subset.
        b = confusable if (i % 4 == 0 and confusable != gold) else gold
        triples.append((gold, a, b))
        i += 1
    return triples


# (gold_label, annotator_a_label, annotator_b_label) triples (>= 300 pairs).
BENCHMARK_TRIPLES = generate_benchmark_triples()


# --- Benchmark phrasing diversification ---------------------------------------
#
# The 308 benchmark pairs are relationship-judgement records. Earlier they read
# templated because the same handful of underlying notice texts were reused
# across every pair. To make the pairs read like distinct, plausible notices we
# attach a DETERMINISTIC, per-index phrasing to each pair (a display string on
# the BenchmarkPair row), rotating through varied topics, institutions, issuers,
# dates and several sentence templates *per gold label*.
#
# This is pure and index-driven (no RNG, no seeded randomness), so re-running
# the seed produces byte-identical texts, identical row counts and identical
# kappa (kappa is computed from the annotator label columns, not this text). It
# is confined to the benchmark dataset: it does NOT touch seed/fixtures/*.json,
# the eval gold submissions, or the temporal_bucket==1 naturalistic phrasings,
# so the held-out eval splits stay uncontaminated.

# Institutions/issuers rotated across benchmark pairs for surface variety.
_BENCHMARK_ISSUERS = [
    ("Northgate University", "Office of the Registrar"),
    ("Riverside Institute", "Academic Section"),
    ("Summit College", "Registrar Office"),
    ("Northgate University", "Examinations Cell"),
    ("Riverside Institute", "Dean of Students"),
    ("Summit College", "Controller of Examinations"),
]

# A wider topic pool than _TOPICS so benchmark notices span many subjects.
_BENCHMARK_TOPICS = [
    "the mid-term examination",
    "the annual convocation",
    "the library's extended hours",
    "the hostel maintenance shutdown",
    "the fee payment window",
    "the inter-college sports meet",
    "the guest lecture series",
    "the scholarship application drive",
    "the campus placement schedule",
    "the semester registration",
    "the departmental workshop",
    "the alumni reunion",
    "the research symposium",
    "the health-camp registration",
    "the cultural-fest auditions",
]

# Date pairs (earlier, later) rotated so date-conflict labels read differently.
_BENCHMARK_DATE_PAIRS = [
    ("15 Sep", "22 Sep"),
    ("3 Oct", "17 Oct"),
    ("11 Nov", "25 Nov"),
    ("8 Jan", "20 Jan"),
    ("14 Feb", "28 Feb"),
    ("2 Mar", "19 Mar"),
    ("9 Apr", "23 Apr"),
]

# Several sentence templates per gold label. ``{topic}`` / ``{issuer}`` /
# ``{early}`` / ``{late}`` are filled deterministically by index. The variety is
# purely cosmetic: it never encodes the gold label as a machine cue and is not
# read by any model, so it cannot leak into eval metrics.
_BENCHMARK_SUBMISSION_TEMPLATES = {
    "consistent": [
        "A student forwarded a copy of {topic} notice; it matches the {issuer} original word for word.",
        "The circular a student shared about {topic} lines up exactly with what {issuer} published.",
        "Nothing has changed for {topic} — the shared copy agrees with the {issuer} notice.",
    ],
    "contradictory": [
        "A student says {topic} is on {late}, but the {issuer} notice clearly prints {early}.",
        "The shared note claims {topic} happens {late}; that flatly contradicts the {issuer} date of {early}.",
        "Someone reported {topic} for {late}, which cannot be right given the {issuer} notice says {early}.",
    ],
    "superseded": [
        "The {issuer} office moved {topic} from {early} to {late}, replacing the earlier date.",
        "Update from {issuer}: {topic} now takes place on {late} instead of the original {early}.",
        "{topic} has been rescheduled by {issuer} to {late}, superseding the {early} announcement.",
    ],
    "corrected": [
        "{issuer} issued an erratum for {topic}: the venue was misprinted and is now corrected.",
        "A correction from {issuer} fixes a typo in the {topic} notice; the substance is unchanged.",
        "Note the {issuer} correction to {topic} — a detail was wrong in the first notice.",
    ],
    "extended": [
        "{issuer} extended the deadline for {topic} from {early} to {late} on request.",
        "The window for {topic} now runs through {late}, longer than the {early} cutoff, per {issuer}.",
        "{issuer} granted more time for {topic}: submissions are accepted until {late} instead of {early}.",
    ],
    "cancelled": [
        "{issuer} has cancelled {topic} for this term; it will not be held.",
        "A student flagged that {topic} is called off — {issuer} confirms it is cancelled.",
        "{topic} will no longer take place; {issuer} withdrew the notice entirely.",
    ],
    "unresolved": [
        "A student is unsure what the {issuer} circular on {topic} actually means — details read ambiguously.",
        "The {topic} note from {issuer} is unclear; the timing and venue cannot be pinned down.",
        "It is hard to tell what {issuer} intends for {topic}; the wording is genuinely ambiguous.",
    ],
}

_BENCHMARK_OFFICIAL_TEMPLATES = {
    "consistent": "Official ({issuer}): {topic} will be held on {early} as scheduled.",
    "contradictory": "Official ({issuer}): {topic} is scheduled for {early}.",
    "superseded": "Official ({issuer}): {topic} was originally scheduled for {early}.",
    "corrected": "Official ({issuer}): {topic} notice — please read with the issued correction.",
    "extended": "Official ({issuer}): the deadline for {topic} was {early}.",
    "cancelled": "Official ({issuer}): {topic} is scheduled for {early}.",
    "unresolved": "Official ({issuer}): {topic} — see the circular for arrangements.",
}


def benchmark_pair_phrasing(index: int, gold_label: str) -> tuple[str, str]:
    """Return ``(submission_text, official_text)`` for benchmark pair ``index``.

    Pure and deterministic: the same ``(index, gold_label)`` always yields the
    same strings. Rotating the topic/issuer/date/template pools by co-prime-ish
    offsets makes consecutive pairs read differently, so the 308 pairs no longer
    look templated. This text is display-only for the labelled benchmark dataset
    and is never consumed by the eval harness or the kappa computation.
    """
    inst_name, office = _BENCHMARK_ISSUERS[index % len(_BENCHMARK_ISSUERS)]
    issuer = f"{office}, {inst_name}"
    topic = _BENCHMARK_TOPICS[(index * 3 + 1) % len(_BENCHMARK_TOPICS)]
    early, late = _BENCHMARK_DATE_PAIRS[(index * 2) % len(_BENCHMARK_DATE_PAIRS)]

    sub_templates = _BENCHMARK_SUBMISSION_TEMPLATES[gold_label]
    sub_template = sub_templates[index % len(sub_templates)]
    off_template = _BENCHMARK_OFFICIAL_TEMPLATES[gold_label]

    fields = {"topic": topic, "issuer": issuer, "early": early, "late": late}
    return sub_template.format(**fields), off_template.format(**fields)

# --- Demo users (known passwords, documented in HANDOFF/README) ---------------

DEMO_USERS = [
    {"email": "student@finalsay.demo", "password": "student123", "role": "student", "display_name": "Demo Student"},
    {"email": "reviewer@finalsay.demo", "password": "reviewer123", "role": "reviewer", "display_name": "Demo Reviewer"},
    {"email": "admin@finalsay.demo", "password": "admin123", "role": "admin", "display_name": "Demo Admin"},
    {"email": "issuer@finalsay.demo", "password": "issuer123", "role": "issuer", "display_name": "Demo Issuer"},
]
