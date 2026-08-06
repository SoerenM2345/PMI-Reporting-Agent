# Critical Review — MASTER.md "Dataset Augmentation Plan" (Data Ingestion Layer)

Reviewed: 2026-07-18. Scope: the "Dataset augmentation plan (in progress — branch
`katja-dataset`)" section of the `MASTER.md` supplied for review, cross-checked against
the actual state of the `PMI-Reporting-Agent` repository (`main`, and `origin/katja`
fetched live from GitHub), `data/README.md`, `OPEN_POINTS.md`, `docs/TrainingData_Decision.md`,
`../UC2_V2_SingleAgent_Definition.md`, and `origin/katja`'s own `docs/evaluation_plan.md`.
Citations (ECTSum, QMSum, AMI, SEC EDGAR rate limits) independently verified by search,
not taken on faith.

**Headline finding before the four questions:** the supplied `MASTER.md` is not a
description of the code you have checked out. It describes an architecture — `image.py`
extractor, `config.py`, `llm/` provider abstraction, `models/entities.py` + `source.py` +
`quality.py`, three LangGraph graphs, 32+ consistency checks, 136 tests, a frontend — that
exists only on `origin/katja` (fetched live: it is real, and substantially more complete
than `main`). Your local `main` checkout has 13 tests, one `consistency.py`, one `llm.py`,
no image/vision code, and no `config.py`. This matters for the review below because the
dataset plan's own feasibility depends on infrastructure that isn't in your working
branch.

**Second headline finding:** the "Dataset augmentation plan" section itself — including
the `katja-dataset` branch name, the M0–M6 status table, and the named scripts
(`scripts/dataset/prep_ectsum.py`, `render_to_pmi_formats.py`) — does not exist in
`origin/katja`'s own `MASTER.md` (checked directly: zero matches for "Dataset
augmentation", "katja-dataset", "QMSum", "AMI" in that file). It also doesn't exist as a
branch on GitHub (`git ls-remote` shows only `main`, `katja`, `soeren`) and none of the
named scripts exist in any branch. The plan's "Status so far" table claims M0 is done
(branch checked out, sample script re-verified) and M1 is "in progress, paused mid-build"
— none of that is reflected in any accessible repository state as of this review.

---

## a. Is it technically feasible?

**Partially, and only for one of the two skills it's meant to serve.**

The mechanical part is feasible and cheap: ECTSum/QMSum are plain-text transcript→summary
pairs; rendering summary text into a `.pptx`/`.xlsx` shell is a normal use of the
`python-pptx`/`openpyxl` stack already in the repo. AMI is real, CC BY 4.0, and its
download page (`groups.inf.ed.ac.uk/ami/download/`) does require manual signal selection
through a "chooser" UI rather than a scriptable bulk endpoint — this corroborates the
project's own claim ("host blocks automation") in `OPEN_POINTS.md` #6, so treat that
specific constraint as confirmed, not just asserted.

What is not straightforwardly feasible is the underlying premise: turning real dialogue
content into "PMI-shaped files" that exercise the extractors the way real PMI documents
do. ECTSum/QMSum have no cell references, no multi-sheet structure, no percentage-vs-text
disagreement across formats — those have to be invented during rendering. So the
*narrative content* would be real, but the *structural/schema layer* the extractors and
`matching.py`/`consistency.py` actually operate on (file/sheet/cell/slide/page/region,
`SourceReference`, cross-format numeric conflicts) would still be synthesized by the
rendering script, same as `make_sample_data.py` already does. That's a real result, but
it is not the "real, externally validated content" the plan's own rationale paragraph
promises as the fix for the tautology problem — the rendering step reintroduces exactly
the "we test what we generated" risk it was proposed to escape, just one layer removed.

No code for any of this exists yet, on either branch, so feasibility is currently
untested rather than proven.

## b. Is it backed by an academic, research-based approach to data ingestion from open sources?

**The data sources are real and correctly cited. The reshaping methodology is not
grounded in a cited approach, and the project's own governance step for this decision has
not been run.**

Verified independently:
- **ECTSum** — Mukherjee et al. (2022), *ECTSum: A New Benchmark Dataset for Bullet
  Point Summarization of Long Earnings Call Transcripts*, EMNLP 2022 Main Conference,
  arXiv:2210.12467. Confirmed: 2,425 total pairs, GPL-3.0. The repo's claimed 1,681/249/495
  split sums to 2,425 and is consistent with the paper's exact split (not just a rounded
  70/10/20). Citation is accurate.
- **QMSum** — Zhong et al. (2021), NAACL 2021, arXiv:2104.05938, MIT license. Confirmed:
  1,808 total query-summary pairs over 232 meetings, split 1,257/272/279 across
  general+specific queries combined. `TrainingData_Decision.md`'s narrower
  "~950/~200/~210 specific + 162/35/35 general" figures are a plausible sub-split (specific
  queries outnumber general queries per meeting) but were not independently verified
  against the paper's own breakdown table — flag as an estimate, not a verified count.
- **AMI** — Carletta et al. (2005); scenario partition per Rennard et al. (2022),
  CC BY 4.0. Confirmed real and license-clear.
- **SEC EDGAR** rate-limit claim (10 req/s, fair-access) — confirmed accurate.

What's missing is any citation for the *reshaping methodology itself*: how to
responsibly convert open dialogue-summarization corpora into a structurally different
target schema (multi-format business documents with per-field provenance) for agent
evaluation. `UC2_V2_SingleAgent_Definition.md` §5 names the actually-relevant academic
analogs for this — document-information-extraction benchmarks (FUNSD, DocVQA,
PubTables-1M) — as "the closest generic analogs for gap 1... not yet researched to the
same rigor" as the three survivor corpora. Those are absent from `MASTER.md`'s pipeline
table entirely. The one methodology citation in play (Long et al. 2024, on synthetic-data
risk) is a caution about a *different* option (Option A), not a positive grounding for
the reshaping approach actually being executed.

More importantly, by this project's own stated rule: `TrainingData_Decision.md`'s D3
explicitly asks whether this decision should be run through `pmi-deep-research`'s full
Xiao & Watson 8-step protocol "before treating it as settled." Per this project's prior
experience (`PROJECT_MEMORY.md`, 2026-07-08 entry — the informal pass on the LLM-provider
decision missed a real factual error that the formal 8-step pass caught), skipping that
step is exactly the situation where errors survive unnoticed. That step has not been run
for D2 (synthetic vs. proxy vs. hybrid). So: real datasets, uncited reshaping method, and
the project's own mandated rigor check still outstanding.

## c. Is it complete — would it produce a functional data layer to learn/train/test on?

**No.** Walking the plan's own five-layer table:

| Layer | Status | Assessment |
|---|---|---|
| Executive/SteerCo digest (ECTSum+QMSum) | M1, paused, unverified | Tests report-*generation* only |
| Workstream-detail (QMSum specific) | Not started | — |
| Action-item extraction (AMI) | Blocked, not started | Scope conflict (see below) |
| Conflict probes | Not started | Perturbs already-synthetic renderings |
| Gold set (15–30 real/anonymized) | Not started, no owner | Called "non-negotiable" by the plan's own recommendation |

Two structural problems on top of the status gaps:

1. **Zero coverage of Gap 1** (multi-format structured extraction — `excel.py`,
   `word.py`, `powerpoint.py`, `pdf.py`, `html.py`, `matching.py`), which both
   `TrainingData_Decision.md` and `UC2_V2_SingleAgent_Definition.md` independently flag as
   the sub-skill with *no existing proxy candidate at all*, and for which
   `TrainingData_Decision.md` recommends SEC EDGAR (XBRL tags as free ground-truth labels
   against real HTML/PDF filings) as the near-free solution. SEC EDGAR does not appear
   anywhere in `MASTER.md`'s pipeline table. This is the largest gap in the plan: the
   extractors are the bulk of the actual codebase and the source of most bugs fixed from
   v1 (`MASTER.md`'s own table), yet the dataset plan as scoped would never exercise them
   against real documents — only against LLM-generated report text.
2. **Scope inconsistency on transcripts.** `UC2_V2_SingleAgent_Definition.md` §5 states
   plainly that Version 2's literal input list is Excel/PowerPoint/PDF/Word/HTML — no
   transcripts — and that AMI's relevance "drops specifically because V2's input list
   excludes meeting transcripts entirely." `OPEN_POINTS.md` #3 lists this as an open team
   decision (D1). Building the AMI/QMSum layers before D1 is resolved risks building data
   for an input type the current spec doesn't ingest.

Even if M1–M6 were fully executed as written, the resulting data layer would train/test
report generation and, weakly, conflict-probe detection on synthetic-schema documents. It
would not provide anything to validate the extraction layer against real-world formatting
noise — the one thing this repo's own bug-fix history (`MASTER.md`'s "Bugs fixed from v1"
table: header-matching, number-locale parsing, path traversal) shows is the actual source
of defects.

## d. What's missing, concretely

1. A real or EDGAR-grounded structured-extraction dataset for Gap 1, with field/cell-level
   ground truth — currently absent from the plan entirely, not merely "not started."
2. Resolution of **D1** (is transcript ingestion in scope for V2 at all?) before investing
   further in AMI/QMSum layers whose relevance is conditional on that answer.
3. Reconciliation of the "Status so far" table against actual git state — no
   `katja-dataset` branch, no `scripts/dataset/` directory, no named scripts exist on
   `main`, `origin/katja`, or `origin/soeren` as of 2026-07-18. Before trusting "M1 paused
   mid-build," confirm where that work actually lives (uncommitted local files elsewhere,
   or aspirational text).
4. An owner and timeline for the 15–30-example held-out gold set — currently the least
   resourced item despite being called non-negotiable.
5. Running D2 (synthetic vs. proxy vs. hybrid for gaps 1–2) through the full
   `pmi-deep-research` 8-step protocol, per the project's own D3 and prior track record of
   that step catching real errors.
6. A decision on **D4** (ECTSum's measured 310-ticker train/test overlap) before any
   ECTSum-based benchmark number is reported as valid.
7. Explicit acknowledgment that image/vision extraction — described in `MASTER.md` as
   "the biggest subsystem" — has zero data-layer coverage in this plan. The only artifact
   is one hand-authored fixture (`tests/fixtures/vision/risk_dashboard.json`, on
   `origin/katja`) already flagged in that branch's own docs as proving the plumbing, not
   that the model can read a heatmap.

---

## Meta-review: do a–d hold up, or does something need rethinking?

- **(a) Feasibility** — the conclusion is durable, but it depends on which branch is
  "current." If work continues from local `main`, the plan's own referenced
  infrastructure (`image.py`, `config.py`, `SourceReference`, three-graph agent) isn't
  present yet — that reconciliation is a prerequisite, not a detail.
- **(b) Academic grounding** — durable as stated, but cheaply fixable: the underlying
  corpora are legitimately cited; what's missing is running the actual reshaping decision
  through the project's own mandated rigor step. This is a process gap, not a dead end.
- **(c) Completeness** — this is the finding most likely to require rethinking the plan's
  *shape*, not just giving it more time. A dataset plan that never touches the extraction
  layer doesn't produce a "functional data layer" for this agent, because extraction is
  most of what the agent does. Recommend promoting a Gap-1 layer (SEC EDGAR XBRL↔HTML/
  Ex-99.1, or the FUNSD/DocVQA/PubTables-1M analogs UC2_V2 §5 already flagged) to a
  first-class row in the pipeline table, funded on the same footing as the ECTSum layer —
  not left as a future addendum.
- **(d) Missing items** — each has a clear next step already implied by existing
  `OPEN_POINTS.md` entries; the two new items this review adds are the Gap-1 layer and the
  branch/commit-status reconciliation.

**Overall verdict:** the plan is honest in tone — it explicitly names the tautology
problem it's trying to escape — but as currently scoped it only partially escapes it, and
it doesn't yet cover the part of the agent most likely to fail in the real world. Before
resourcing M2–M6 as written, resolve D1 (transcript scope, gates whether AMI/QMSum layers
are worth building at all) and add a funded Gap-1/extraction layer; without both, this
plan produces a data layer for the least risky part of the system (text generation) and
none for the parts its own bug history shows are actually fragile (multi-format
extraction, cross-source conflict detection). This is also the same honesty standard the
agent itself is built to enforce on its own users — per the `evaluation_plan.md`
committed on `origin/katja`: a confident status claim that turns out not to match the
underlying source is exactly the failure mode both the agent and this dataset plan need
to avoid making about themselves.

## Sources checked

- Repo state: `main` (local, clean, HEAD `0f9e6d5`), `origin/katja` (fetched live, HEAD
  `bf03922`), `git ls-remote origin` (branches: `main`, `katja`, `soeren` — no
  `katja-dataset`).
- `data/README.md`, `OPEN_POINTS.md`, `docs/TrainingData_Decision.md` (this repo, `main`).
- `origin/katja:docs/evaluation_plan.md`, `origin/katja:MASTER.md` (fetched, not merged).
- `../UC2_V2_SingleAgent_Definition.md` (PMI project root).
- Mukherjee et al. (2022) EMNLP — https://aclanthology.org/2022.emnlp-main.748/
- Zhong et al. (2021) NAACL — https://arxiv.org/abs/2104.05938
- AMI Corpus download page — https://groups.inf.ed.ac.uk/ami/download/
- SEC EDGAR rate limits — https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
