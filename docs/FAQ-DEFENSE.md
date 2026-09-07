# FinalSay - Defense FAQ

The ten hardest questions a reviewer could ask, answered honestly. Where a number
appears it comes from the committed `docs/eval-results.md` (which wins on any
disagreement) or `docs/postgres-verification.md`. Weaknesses are stated as
weaknesses, not spun.

### 1. Where is the ML, really?

ML is used for the semantic comparison of institutional notices: given a student's
forwarded notice and a verified official notice, the model predicts whether they
are consistent, contradictory, superseded, or unrelated - a relationship a keyword
match can't reliably tell apart, since "exam postponed to 22 Sept" and "exam on 15
Sept" share almost no vocabulary but are directly related. Being fully honest about
the current state: the **default** comparison model in this prototype is a
deterministic rule engine (`MockComparisonModel`) so the demo runs offline with no
setup, and the extraction, redaction, and provenance layers are rule-based and
cryptographic, not learned. The genuine ML path is `HFComparisonModel`
(`facebook/bart-large-mnli` zero-shot NLI), which we did run and evaluate. So the
ML is real and evaluated, but in the shipped default it is opt-in rather than
the always-on classifier.

### 2. Why is your real model worse than your mock?

On the institution split FinalSay scores relationship F1 **0.739 with the mock
model but only 0.289 with the real HF model** - genuinely worse, and below the
`nli` (0.385) and `prompted_llm` (0.524) baselines on that split. We are not going
to dress that up. Two honest reasons: the mock rule engine was authored against
this taxonomy and its cues, so it fits the corpus well, whereas an off-the-shelf
NLI model applied **zero-shot** has never seen this domain; and the HF model
copes with uncertainty by routing far more cases to `unresolved` (0.714 vs the
mock's 0.286/0.190), which protects the false-confirmation rate (0.000 for both)
but costs recall. The takeaway is not "the mock is good" - it is that zero-shot
NLI is insufficient here and fine-tuning is the open question.

### 3. 1.5x isn't much - is this worth building?

Measured honestly, the time-to-identify saving is **1.457x on the temporal split
and 1.894x on the institution split** - not the ~19x an earlier, over-idealized
version of the harness implied. We deliberately replaced the "assume perfect
retrieval" cost of 1.0 with the measured retrieval rank, and we charge retrieval
misses the full institution-feed scan cost rather than dropping them
(recall@5 is 0.714 / 0.810). So on speed alone the case is modest. The stronger
argument for building it is not scan time - it is the **safety property**: FinalSay
is the only system in our evaluation with a **0.000 false-confirmation rate**,
where every baseline confirms wrong or superseded notices 14–43% of the time.
Avoiding a confidently-wrong "this notice is valid" is the point; the scan-time
saving is secondary.

### 4. Your data is synthetic, so what does the benchmark prove?

Fair - the corpus, the submissions, and the annotator disagreement are all
deterministically generated, so the benchmark cannot claim to measure real-world
accuracy. What it does prove is more limited and still useful: it exercises the
full 7-label taxonomy including deliberately ambiguous `unresolved` cases and
low-vocabulary-overlap date conflicts, it enforces a **held-out institution**
(Summit) and a **temporal holdout** with naturalistic phrasing that was *not*
engineered around the rule engine's cues, and it lets us compare FinalSay against
four baselines on identical inputs. So it demonstrates relative behavior and the
generalization gap (e.g. HF underperforming on unseen institutions) rather than an
absolute accuracy claim. Replacing the synthetic corpus with real, redacted
institutional notices is required future work.

### 5. Why blockchain at all?

The goal is tamper-evident provenance: a student (or a reviewer) should be able to
prove an official notice has not been altered since it was ingested. We hash each
notice, combine the day's hashes into a Merkle root, and anchor only that root, so
a single anchor covers a whole day of notices and no personal data ever leaves the
system. Honestly, a blockchain is not strictly necessary for this - a trusted
timestamping authority or an append-only log would also work, and our **default
anchor is a local append-only hash chain**, not a chain at all. The optional
Polygon Amoy anchor adds a publicly-verifiable, no-single-owner record, which is
the only property a purely local log lacks. So blockchain is a defensible choice
for public verifiability, but we are not claiming it is the only way to achieve
tamper-evidence.

### 6. What happens if the chain is down?

The anchor is behind an interface (`Anchor` ABC) with two implementations. The
default `LocalHashChainAnchor` has no external dependency and never blocks. The
opt-in `PolygonAmoyAnchor` catches any failure - RPC down, no credentials, network
error - and downgrades to the local anchor so ingestion never stalls. The honest
cost of that design: if the external chain is unavailable, that day's root is only
recorded locally, so you lose the public, third-party verifiability for those
notices until the chain path recovers; the notices are still internally
tamper-checkable against the local root, but "anyone can independently verify it on
a public ledger" degrades to "the operator's own log says so."

### 7. How do you know the held-out evaluation isn't contaminated?

The `institution` split holds out **Summit College entirely** - none of Summit's
officials or submissions are seen during any fitting. The `temporal` split holds
out the latest round of submissions, and critically that held-out round uses
**naturalistic phrasing generated by a separate code path** (`_naturalistic_text`)
that deliberately drops the exact cue words the rule engine keys on, so the
held-out text is not reverse-engineered from the model's own rules. We also kept
the benchmark-scaling work (going from 14 to 308 pairs, and the cosmetic phrasing
diversification) strictly separate from the eval gold submissions and the
temporal-holdout phrasings - the fixtures under `seed/fixtures/*.json` were not
touched - so scaling the benchmark did not leak into the held-out metrics. The
visible evidence that it is not contaminated is the honest low score: FinalSay's
temporal-split F1 is ~0.05 with the mock model, not a round-trip 1.0.

### 8. Kappa is synthetic - why should I trust the labels?

You should not trust the kappa of **0.625** as a measurement of real human
agreement, and we do not present it that way. The two annotator label columns are
produced by a deterministic generator in which each annotator independently
disagrees with the gold label on a fixed fraction of *genuinely confusable* pairs
(superseded↔contradictory, extended↔superseded, corrected↔consistent,
unresolved↔contradictory). The kappa is therefore a plausible, stable stand-in for
"substantial but imperfect agreement," useful for exercising and demonstrating the
benchmark and kappa machinery, not evidence that real annotators would agree at
that rate. Real dual annotation by humans is required before the kappa can be
treated as a genuine reliability figure.

### 9. The scope note says PostgreSQL but you run SQLite.

Correct - the default demo runs **SQLite**, which is a deviation from the scope
note's PostgreSQL default. The reason is environmental: the sandbox reaps
background daemons between steps and wipes `/tmp`, so a persistent Postgres server
is not reliable for a bare one-command demo, and SQLite over the same SQLAlchemy
models keeps the architecture faithful (temporal relations are still relational
edge rows). We did not leave Postgres as an unverified claim: we brought up a real
`postgres:16-alpine` container, created the schema, seeded it twice with identical
counts (idempotent), and ran a submit/classify + provenance build/verify smoke
against it - all recorded in `docs/postgres-verification.md`. Two honest caveats
there: "migrations" means SQLAlchemy `create_all`, not Alembic (the app has no
Alembic setup), and the default pytest suite stays SQLite-pinned by `conftest.py`,
so real Postgres behavior was proven by a targeted script rather than the full
suite.

### 10. What would you do differently with another semester?

The single biggest change: **fine-tune the comparison model on the benchmark's
training split** instead of relying on zero-shot NLI - the HF-vs-mock
institution-split result (0.289 vs 0.739) is direct evidence that zero-shot is not
enough for this domain. Second, **replace the synthetic corpus and synthetic
annotations with real, redacted institutional notices and genuine dual human
annotation**, so the benchmark and the kappa measure something real. Third,
**make the ML path the default** rather than shipping a rule engine as the default
classifier, once the model is good enough to trust. And on process: we would
settle the still-open questions early - the final choice of the three institutions
and which one is held out, the task split across the four team members, and the
mapping of components onto the 17-week schedule.
