# Evaluation Study Design

*Written from the position of the evaluation agent: how to assess agents X, Y and Z with
enough rigour that the result survives a supervisor, a reviewer, and — the harder test — a
Deloitte practitioner who disagrees with the conclusion.*

This document specifies **what would count as a result**, the parameters that must be fixed
and logged, and the documentation set that has to exist alongside it. It sits on top of the
existing `evaluation_plan.md` (which defines good metrics but no study) and the corpus
described in [`corpus_integration_plan.md`](corpus_integration_plan.md).

---

## 1 · The claim under test, and the one that would falsify it

The project's research question is whether Agentic AI improves **coordination and steering**
across PMI activities. The corpus can speak to three of the five hypotheses and, importantly,
**not to the other two** — stating that plainly is worth more than overclaiming.

| Hypothesis | Can this corpus test it? | Why |
|---|---|---|
| H1 Project setup | **No** | Setup quality is an organisational outcome over weeks; a document corpus cannot observe it |
| **H2 Reporting** | **Yes, directly** | Manual effort in producing a status report is exactly what the pipeline replaces, and the transcript→minutes pair gives a second, cleaner instance |
| **H3 Risk management** | **Partly** | Detection of an emerging risk is testable (C5: a risk escalated in chat that never reached the register). *Recommending* mitigations is not, without a practitioner panel |
| H4 Synergy realisation | **No** | Requires longitudinal financial outcomes |
| **H5 People alignment** | **Partly** | Ownership gaps are testable (C3 role collision, C6 reassignment, E-03, E-09). Cross-workstream *facilitation* is not |

**The falsifying result, stated in advance.** If the agent produces a report that reads well,
contains no detectable fabrication, and yet **fails to escalate C5 or C6**, the central claim
fails — because those two are precisely the coordination gaps the thesis argues Agentic AI
closes. A fluent report that silently resolves a stale register is *worse* than no report: it
launders a coordination failure into an apparently authoritative figure. This should be
written into the protocol before any run, so it cannot be reinterpreted afterwards.

---

## 2 · Design: what X, Y and Z should be

"Agent X, Y, Z" only produces a defensible result if the conditions differ along **one
dimension at a time**. Two designs are worth running; they answer different questions.

### Design A — Ablation (primary; answers "does the architecture matter?")

| Condition | Description | Isolates |
|---|---|---|
| **Z — Deterministic baseline** | Extractors + consistency engine + template renderer. **No LLM** (`null_client`, deterministic fallbacks — the repo already supports this and runs keyless) | The floor. What rule-based coordination achieves alone |
| **Y — LLM without the consistency layer** | LLM reads the files and writes the report. Conflict detection and escalation **disabled** | Whether a capable model alone closes the coordination gap |
| **X — Full agent** | Extractors + consistency engine + escalation (409) + LLM narrative | The contribution being claimed |

This is the design that produces the thesis result, because Y is what a reader will otherwise
assume is sufficient — *"why not just give the files to a good model?"* — and Z establishes
that the improvement is not merely automation of clerical work. **Z runs with no API key**,
so it costs nothing and is perfectly reproducible.

### Design B — Model swap (secondary; answers "does the model matter?")

X held constant, provider varied across the models the repo already abstracts (Anthropic /
OpenAI, exact IDs pinned per §21.10). Answers a practical question, not a research one.
Report it, do not build the thesis on it — model IDs change and the finding decays.

**Do not run both factors crossed** unless n permits. 3 conditions × 2 corpora × 5 repeats =
30 runs is tractable. Adding 3 models makes it 90 and adds little.

### Conditions per agent

| Corpus | Purpose |
|---|---|
| `clean` | Detection and escalation of genuine disagreement; report quality |
| `with_errors` | Robustness. Both sets are live here (6 designed + 10 injected = **16**) |

---

## 3 · Unit of analysis and sampling

- **Unit of analysis:** one *run* — one corpus condition processed end to end by one agent
  configuration.
- **Unit of observation for detection metrics:** one *finding* (conflict or error). n = 6
  (clean) or 16 (with_errors) per run. **This is small**, and the analysis plan in §6 is built
  around that fact rather than pretending otherwise.
- **Repeats:** ≥ 5 per cell even at temperature 0. LLM pipelines are not deterministic in
  practice (tool ordering, retries, truncation). *Reporting a single run is the most common
  methodological failure in this literature and the easiest to avoid.* Report mean, SD, min,
  max — never a single number.
- **Power:** with n = 16 findings, only large effects are detectable. Be explicit: this is a
  **feasibility and characterisation study**, not a powered comparison. Frame findings as
  existence proofs and effect estimates with intervals, never as significance claims about
  small differences.

---

## 4 · Metrics

The existing `evaluation_plan.md` already argues the right split — honesty over capability.
This adds operational definitions, ranks them, and adds the summarisation arm.

### Primary — honesty (a failure here invalidates the run)

| # | Metric | Definition | Target | Corpus |
|---|---|---|---|---|
| P1 | **Critical-conflict escalation** | Conflicts with `must_escalate: true` surfaced to the user ÷ present | **100%** | clean, errors |
| P2 | **Stale-register flagging** | C5, C6 correctly flagged as *register out of date* rather than resolved to a value | **100%** | both |
| P3 | **Fabrication rate** | Numeric claims in output with no `stated_in` source and no valid derivation, after adjudication | **0** | both |
| P4 | **Silent-loss rate** | Files or rows contributing nothing and **not** reported as such. Includes E-01 | **0** | errors |
| P5 | **Unreadable-file honesty** | E-01 reported as unreadable, not skipped | **pass/fail** | errors |

P1–P5 are **gates**, not scores. Any failure is reported as a defect, not averaged away.

### Secondary — capability

| # | Metric | Definition | Target |
|---|---|---|---|
| S1 | Extraction recall | Entities extracted ÷ present in ground truth, per type and per format | ≥ 90% tabular; report images separately |
| S2 | Conflict detection recall | Findings detected ÷ planted (6 or 16) | ≥ 90% |
| S3 | Conflict precision | True ÷ reported, with `unplanted_true_positive` adjudicated separately | ≥ 95% |
| S4 | Resolution correctness | Where ground truth has a `correct` value, agent's resolution matches | report, no target |
| S5 | Output validity | Every artefact re-opens in python-pptx / openpyxl / PIL | 100% |
| S6 | Confidence calibration | Image findings: accuracy vs. stated confidence; ECE + reliability diagram | report |

### Tertiary — the summarisation arm (transcript → minutes)

The strongest single instance in the corpus, and it maps to established method. Given the
transcript, can the agent reproduce the signed minutes?

| # | Metric | Definition |
|---|---|---|
| T1 | Decision recall | 4 minuted decisions recovered |
| T2 | Action recall + owner accuracy | 4 actions, with correct owner and due date |
| T3 | **Decision precision** | Decisions asserted that were **not** taken — the dangerous direction |
| T4 | Faithfulness | Human-rated, per §7 |

Use automatic overlap metrics (ROUGE and similar) **only as a descriptive secondary**. They
correlate poorly with faithfulness, which is the property that matters here; T1–T3 are
element-level and directly meaningful.

### Cost and effort (needed for the H2 claim)

Wall-clock, tokens, cost per run, and human resolution time (number of conflict cards, time to
clear). H2 claims *reduced manual effort*: without a baseline of how long this takes a human,
the claim is unfalsifiable. **Measure it, or drop the effort claim.**

---

## 5 · Parameters that must be fixed and logged

Everything below goes into `run.json`. If it is not logged, the run is not reproducible and
does not count.

**Fixed across all runs:** corpus version + manifest hash · git SHA · prompt-file hashes ·
temperature 0 · seeds where the API supports them · retry and timeout policy · upload order
(fix it; do not let filesystem order vary) · resolution policy applied from ground truth ·
adjudication rubric version.

**Varied and recorded:** agent configuration (X/Y/Z) · provider and **exact** model ID
(never "the latest") · corpus condition · repeat index.

**Recorded as outcome:** every API status code — the 409 above all · full conflict payload
pre- and post-resolution · quality report · token counts, cost, wall-clock · every LLM
fallback fired (the repo already records these; they are a confound if unlogged).

---

## 6 · Analysis plan

Written before data collection. Deviations get reported as deviations.

- **Descriptive first.** Per cell: mean, SD, min, max over repeats. A table of raw per-run
  values in the appendix — with n this small, the reader should see every observation.
- **Comparisons.** Paired by finding, since X, Y and Z see identical inputs.
  - Binary detection outcomes (detected / not) across two conditions: **McNemar's test**.
  - Continuous scores across three conditions: **Friedman**, then Wilcoxon signed-rank
    post-hoc with Holm correction.
  - Report **effect sizes with bootstrap confidence intervals**, not p-values alone. With
    n = 16 a p-value is close to uninformative; an interval is honest about that.
- **Never** average a gate metric. P1–P5 are reported as counts of runs that passed.
- **Pre-register** §1's falsification criterion, the metric set and this analysis plan in a
  timestamped file in the repo before the first scored run. Not a formality — it is what stops
  metric selection drifting toward whatever produced a good result.

---

## 7 · Human evaluation

Two of the most important properties — faithfulness and decision-usefulness — are not
machine-checkable. The repo already has `uat_questionnaire.md`; this makes it a rating study.

- **Raters:** ≥ 3, PMI or consulting experience. The interview participants are the natural
  pool and already have context.
- **Blinding:** condition-blind. Reports stripped of any tell that identifies X, Y or Z, and
  presented in randomised order. This is the arm most often skipped and most often fatal to a
  claim.
- **Instrument:** 5-point Likert on **faithfulness** (every claim traceable), **completeness**
  (nothing material omitted), **actionability** (a SteerCo could decide from it), **trust**
  (would you put your name on it) — plus one free-text field for *the thing that would stop
  you sending it*, which reliably surfaces more than the scale does.
- **Agreement:** report **Krippendorff's α** (handles >2 raters and ordinal data). If α < 0.67,
  the rubric is the problem — fix and re-rate rather than reporting a mean over noise.
- **Anchoring:** include the human-authored ground-truth minutes as an unlabelled ceiling
  condition. Without a ceiling, a mean of 3.8 has no interpretation.

---

## 8 · Threats to validity

Stated with mitigations. The first one is fatal if left unaddressed and the repo has already
named it — that honesty should be preserved, not quietly dropped.

| Threat | Severity | Mitigation |
|---|---|---|
| **Construct — the tautology.** The same team authored the corpus, the conflicts and the rules that detect them. `MASTER.md` already calls this "our rules testing our rules" | **High** | (a) Report clean and error corpora separately — the 10 injected errors were authored *after* the detection logic and are closer to held-out; (b) hold back a slice never used for tuning; (c) triangulate against **externally validated** material (QMSum / AMI / ECTSum) per the existing dataset plan; (d) state the limitation prominently rather than in a footnote |
| **External — one deal, one week, one language pair** | High | Frame as a characterisation study on one instance. Do not generalise to PMI programmes. Weeks 1–2 and a second deal are the obvious extension |
| **Construct — synthetic ≠ real messiness** | Medium | Real documents are worse than these: inconsistent templates, half-finished tables, scans. Corpus v1.1 should add an off-topic file, a scan-only PDF, and a corrupted archive |
| **Internal — LLM non-determinism** | Medium | ≥ 5 repeats, temperature 0, log every fallback |
| **Internal — adjudication bias** | Medium | Fabrication and `unplanted_true_positive` adjudicated blind to condition, by two people, disagreements recorded |
| **Conclusion — small n** | High | No significance claims on small differences; intervals and effect sizes only; report every raw observation |
| **Ethical / legal — real-company anchoring** | Low but real | Every document already carries the synthetic disclaimer and no statement is attributed to a real named individual. **Keep that invariant; it is doing real work** |

---

## 9 · Documentation set

What must exist for the result to be assessable. Six of these do not exist yet.

| Artefact | Status | Purpose |
|---|---|---|
| `DATASHEET.md` (Datasheets-for-Datasets structure) | **missing** | What the corpus is, how built, what it does not represent |
| `ground_truth.json` + `error_key.json` | **missing** (key exists as xlsx) | Machine-scorable truth |
| `PROTOCOL.md` — pre-registered design, metrics, analysis plan, falsification criterion | **missing** | Stops post-hoc metric selection |
| `MANIFEST.sha256` | **missing** | Corpus integrity |
| Run manifests (`run.json` per run) | **missing** | Reproducibility |
| Model card per configuration (provider, exact ID, temperature, prompts, fallbacks) | **missing** | Configuration provenance |
| `results/` — raw per-run CSV + analysis notebook | **missing** | Reader recomputes from raw |
| Adjudication rubric + log | **missing** | Makes the human judgements auditable |
| `evaluation_plan.md` | exists | Metric rationale |
| `known_limitations.md` | exists | Keep updated as the limitation register |
| `uat_questionnaire.md` | exists | Extend to the blinded rating instrument (§7) |

---

## 10 · Execution sequence

| Phase | Work | Output |
|---|---|---|
| 0 | Corpus integration steps 1–3 | Versioned corpus + ground truth |
| 1 | Write and commit `PROTOCOL.md` **before any scored run** | Pre-registration |
| 2 | Harness + scorer (steps 4–5) | Runnable pipeline |
| 3 | **Z only** — keyless, free, fully deterministic | Baseline + harness debugging at zero cost |
| 4 | X and Y, 5 repeats × 2 corpora | Primary result |
| 5 | Adjudication (fabrication, unplanted positives) | Adjudicated metrics |
| 6 | Blinded human rating | Faithfulness, actionability, trust |
| 7 | Analysis + limitation register | Thesis chapter |

Phase 3 is deliberately first: it exercises the whole harness for free and finds the plumbing
bugs before any paid run.

---

## 11 · What this study cannot answer

Worth a paragraph in the thesis, because a reviewer will otherwise write it for you.

It cannot show that Agentic AI **accelerates value creation** or **reduces execution risk** in
a real programme — those are longitudinal organisational outcomes and this is a document-level
study on one simulated week. It cannot support H1 or H4 at all. It cannot establish that the
agent generalises beyond one deal, one reporting week and one language pair. And it cannot
fully escape the construct problem: the corpus is synthetic, and the strongest available
mitigation is triangulation against externally validated material, not elimination.

What it **can** establish, and what is worth claiming: that a system built this way detects
cross-source disagreement a human reviewer would plausibly miss, escalates rather than
resolves it, does not fabricate, and degrades honestly on corrupted input — and that an LLM
without the consistency layer does not.

That is a narrower claim than the research question. It is also one the evidence can carry.

---

## Methodological references

**Verified 2026-08-05** by web search against the ACL Anthology / MIS Quarterly / ACM /
publisher records (title, authors, venue, year each confirmed to exist and match the
claimed use below) — not the full Xiao & Watson eight-step / top-3-by-recognition
citation-count ranking the project rules call for, which needs a citation-index tool this
session didn't have access to (no `pmi-deep-research` skill exists in this repo or
elsewhere in this environment — confirmed, see `docs/PROTOCOL.md`). Treat this as "these
are real, correctly-attributed, on-topic papers," not "these are provably the top-3 most
recognised sources on each topic" — the latter still needs the proper tool pass before the
thesis cites them as such.

- **Design-science framing for an artefact evaluation:**
  Hevner, A. R., March, S. T., Park, J., & Ram, S. (2004). Design science in information
  systems research. *MIS Quarterly*, 28(1), 75–106.
  Peffers, K., Tuunanen, T., Rothenberger, M. A., & Chatterjee, S. (2007). A design science
  research methodology for information systems research. *Journal of Management
  Information Systems*, 24(3), 45–78.
- **Datasheets for datasets; model cards:**
  Gebru, T., Morgenstern, J., Vecchione, B., Vaughan, J. W., Wallach, H., Daumé III, H., &
  Crawford, K. (2021). Datasheets for datasets. *Communications of the ACM*, 64(12), 86–92.
  Mitchell, M., Wu, S., Zaldivar, A., Barnes, P., Vasserman, L., Hutchinson, B., Spitzer,
  E., Raji, I. D., & Gebru, T. (2019). Model cards for model reporting. *Proceedings of
  FAT\* '19*, 220–229.
- **Statistical significance testing practice for NLP-scale comparisons; score
  distributions over single scores:**
  Dror, R., Baumer, G., Shlomov, S., & Reichart, R. (2018). The hitchhiker's guide to
  testing statistical significance in natural language processing. *Proceedings of ACL
  2018*, 1383–1392.
  Reimers, N., & Gurevych, I. (2017). Reporting score distributions makes a difference:
  Performance study of LSTM-networks for sequence tagging. *Proceedings of EMNLP 2017*,
  338–348.
- **Bootstrap-based significance/comparison for NLP systems:**
  Berg-Kirkpatrick, T., Burkett, D., & Klein, D. (2012). An empirical investigation of
  statistical significance in NLP. *Proceedings of EMNLP-CoNLL 2012*, 995–1005.
- **Faithfulness and factuality in abstractive summarisation; pitfalls in human evaluation
  of summarisation:**
  Maynez, J., Narayan, S., Bohnet, B., & McDonald, R. (2020). On faithfulness and factuality
  in abstractive summarization. *Proceedings of ACL 2020*, 1906–1919.
  Fabbri, A. R., Kryściński, W., McCann, B., Xiong, C., Socher, R., & Radev, D. (2021).
  SummEval: Re-evaluating summarization evaluation. *Transactions of the ACL*, 9, 391–409.
- **Meeting-summarisation corpora as external anchors:**
  Zhong, M., Yin, D., Yu, T., Zaidi, A., Mutuma, M., Jha, R., Awadallah, A. H.,
  Celikyilmaz, A., Liu, Y., Qiu, X., & Radev, D. (2021). QMSum: A new benchmark for
  query-based multi-domain meeting summarization. *Proceedings of NAACL-HLT 2021*.
  Carletta, J., et al. (2005). The AMI meeting corpus: A pre-announcement. *Proceedings of
  MLMI 2005*.
- **Inter-rater agreement for ordinal data with >2 raters:**
  Krippendorff, K. (2011). Computing Krippendorff's alpha-reliability. Annenberg School for
  Communication Departmental Papers, University of Pennsylvania.
