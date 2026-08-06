# Datasheet: Dell-EMC Synthetic PMI Corpus (dellemc_vcio) v1.0

Follows the structure of *Datasheets for Datasets* (Gebru et al.). Written because this
corpus is a **permanent, versioned, citable dataset** — a decision made explicitly (see
"Two decisions to take before starting", `corpus_integration_plan.md`), not a disposable
test fixture — so it needs the documentation a thesis committee or a reviewer would expect
before treating a result built on it as evidence.

## Motivation

**For what purpose was the dataset created?** To evaluate whether an agentic PMI-reporting
system detects cross-source disagreement, escalates rather than silently resolves it, and
degrades honestly on corrupted or contradictory input — the coordination-and-steering claim
this project's thesis argues for (see `docs/evaluation_study_design.md` §1). No existing
public dataset pairs a realistic PMI document set with machine-scorable ground truth for
exactly this: cross-document conflicts and injected data-quality errors, both with known
correct answers.

**Who created it and on whose behalf?** Generated programmatically (`generators/case.py`
and the `generators/g2_*.py` renderers) for this thesis project, not commissioned by or
affiliated with Dell Technologies, EMC Corporation, or Deloitte.

## Composition

**What do the instances represent?** 21 documents simulating one reporting week (W3,
26-30 September 2016, "day 22" after close) of a Value Creation Integration Office
tracking the real Dell-EMC merger — a masterplan-style deck, weekly minutes, a signed
SteerCo minutes PDF, an integration tracker workbook, a RAID log, a synergy tracker, a
risk-dashboard screenshot, a RACI wiki page, an escalation e-mail thread, role cards, an
org chart, and a merger-terms summary. Two variants: `clean/` (21 files) and
`with_errors/` (the same 21, 5 content-altered + 1 renamed — see Integrity, below).

**What is real and what is invented?** Every fact is tagged in `generators/case.py` as
one of:
- `[PUBLIC]` — verifiable in three sources: EMC Corp's Form 8-K Exhibit 99.1 (SEC EDGAR,
  filed 7 September 2016), Deloitte Global's published case study *"Dell, EMC, and
  Deloitte create the next tech icon"*, and Dell's 7 September 2016 press release. This
  covers the deal itself: parties, value, structure, close date, the VCIO's existence and
  its two named co-leads, the seven workstreams, headline company statistics.
- `[SYNTHETIC]` — every operational detail: task owners, meeting statements, risks,
  synergy figures, dates, and the two named individuals who chair governance (Michael
  Dell, Rory Read, Howard Elias, and the lead advisory partner) appear **only** in their
  documented public roles. No statement, decision, action, risk, or escalation anywhere
  in the corpus is attributed to a real named person. This invariant is deliberate and
  load-bearing — it is what makes the corpus usable without becoming a claim about what
  Dell, EMC, or Deloitte actually did internally, and it must survive any future version.

**Is any information missing?** Weeks 1-2 of the integration are not generated (only W3),
so no week-over-week trend data exists yet — noted in `BACKLOG.md` as a v1.1 candidate.
No adversarial documents (off-topic file, scan-only OCR-only PDF, wrong-language content)
exist yet either. Two document formats named in the original spec (`.msg`/`.eml`,
`.mpp`) are not represented.

**The construct problem, stated plainly.** The same project that wrote the reporting
agent's conflict-detection rules also wrote the conflicts this corpus tests them against
— "our rules testing our rules" (`MASTER.md`'s own phrase, quoted in
`evaluation_study_design.md` §8). Mitigations: the 10 injected errors (`error_key.json`)
were authored *after* the detection logic and are closer to held-out than the 6 designed
conflicts; a slice should be held back from any tuning; and results should be
triangulated against externally validated summarisation corpora (QMSum, AMI, ECTSum —
see `MASTER.md`'s dataset-augmentation plan). This is a real limitation of the corpus and
is stated here rather than in a footnote.

## Ground truth

- **6 designed conflicts** (`ground_truth.json`, IDs C1-C6): genuine cross-document
  disagreements planted by construction — e.g. three documents reporting three different
  WS3 progress percentages, or a milestone forecast date that shifts across three sources
  as the story unfolds. Two of the six (C5, C6) have **no resolvable correct value by
  design** — the point under test is whether the finding is flagged as a stale or
  unreconciled register entry, not resolved to a number.
- **10 injected errors** (`error_key.json`, IDs E-01 to E-10), applied to a copy of the
  clean corpus: a truncated/corrupted PDF, a misleading filename, a duplicate role
  holder, three date-vs-plan discrepancies, an inconsistent milestone count, transposed
  digits in a headline figure, a task misattributed to the wrong workstream, and a risk
  score whose stated band no longer follows its own arithmetic.
- **Arithmetic that matters for scoring:** `with_errors/` is a *copy* of `clean/`, so it
  contains **16 findable issues (6 + 10), not 10** — any scorer that treats it as only 10
  will report the wrong precision figure (see `corpus_integration_plan.md` Part 2).
- Every claim's source document (and, for spreadsheets, its tab) is recorded in
  `ground_truth.json`/`error_key.json`, traced by hand against the `generators/g2_*.py`
  renderers rather than inferred from description text — see the file-mapping table at
  the top of `generators/export_ground_truth.py`.
- **Known gap:** full per-entity source provenance (`stated_in`, needed to score
  extraction recall per entity, metric S1) is not yet exported for the full entity set
  (milestones, tasks, risks, synergies, decisions, actions, dependencies, assumptions,
  issues) — only for the 16 findings above. Recorded in `ground_truth.json`'s own
  `known_gaps` field, not silently absent.

## Collection process

Generated, not collected: `generators/case.py` is the single fact base (every aggregate —
counts, percentages, sums — is computed from record lists, never typed twice, so the
rendered documents cannot drift apart except at the six deliberately planted points).
`generators/g2_*.py` render it into format-specific documents (docx/pptx/xlsx/pdf/html/
image via PIL, and one verbatim meeting transcript). `generators/audit.py` checks internal
consistency (130 checks at last run, 0 failures). `generators/inject_errors.py` then
copies the clean corpus and applies the 10 errors as deterministic patches (OOXML XML
string replacement, a byte truncation, an `openpyxl` cell edit, a filename rename), each
asserting its target exists first — so silent drift between the generator and the
document it describes fails loudly rather than going unnoticed.

## Preprocessing / cleaning / labelling

None beyond generation — there is no raw form to clean, the documents are the direct
output of the generators. "Labelling" is the ground-truth export
(`generators/export_ground_truth.py`), which reads `case.py`'s `PLANTED_CONFLICTS` and
`error_key.py`'s `ROWS` rather than re-typing them, specifically so the label can never
silently diverge from the artefact it labels.

## Uses

**What has it been used for?** Evaluating the PMI Reporting Agent in this thesis project
(`scripts/eval/run_corpus.py`, `scripts/eval/score.py`).

**What else might it be used for?** Any system claiming to detect cross-source
disagreement or degrade honestly on corrupted PMI documents could be scored against the
same ground truth. The transcript-to-minutes pair is independently useful as a small
faithfulness-evaluation instance for meeting summarisation.

**What should it *not* be used for?** As evidence about how Dell, EMC, or Deloitte
actually ran their integration — the operational content is invented. As a benchmark for
generalisable PMI-agent performance — this is one deal, one week, one language pair
(German/English), and `evaluation_study_design.md` §11 is explicit that the study built
on it cannot support that generalisation.

## Distribution

Distributed only within this repository; not a public release. No third-party IP is
reproduced — the `[PUBLIC]` facts are restated from public filings and a published case
study, not copied verbatim, and the one external asset (`generators/DeloitteMaster.pptx`,
a template) is a design asset, not corpus content.

## Maintenance

**Versioning.** `v1.0` is frozen: `MANIFEST.sha256` records a hash of every corpus,
ground-truth, and generator file, and `generators/corpus_integrity.py` (wired into
`tests/test_corpus_dellemc.py`, marker `corpus`) fails loudly if any of them changes
without a deliberate version bump. A change — including fixing a typo inside a rendered
document — makes a **new version** (`v1.1`, ...) with its own manifest and, if the ground
truth moves, its own `ground_truth.json`/`error_key.json`. Documentation prose
(`README_CORPUS.md`, `BACKLOG.md`, this file) is deliberately excluded from the manifest
and may be corrected without a version bump.

**Who maintains it, and how to propose a change?** Maintained within this repository;
propose changes as a new version per the versioning rule above, via the same generator
pipeline (`generators/case.py` → `g2_*.py` → `audit.py` → `inject_errors.py` →
`export_ground_truth.py` → `build_manifest.py`) so the "never typed twice" property is
preserved rather than hand-patched.

**Known planned extension (v1.1, not yet built):** weeks 1-2 (for week-over-week trend
testing), one adversarial document (off-topic, scan-only, or wrong-language), per
`BACKLOG.md`.
