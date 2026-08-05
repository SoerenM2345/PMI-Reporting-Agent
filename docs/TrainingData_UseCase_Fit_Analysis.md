# ECTSum vs. QMSum Against H2 Reporting Use Case Requirements

Compiled 2026-07-18. Companion to `TrainingData_Decision.md` and
`DataIngestion_CriticalReview.md`. Requirements sourced from: the "H2 Automated Reporting:
Requirements & Potentials" slide (Deloitte deck, this session), `H2_Reporting_Requirements.docx`
(R1 to R6), and `UC2_V2_SingleAgent_Definition.md` §5 (Gap 1, Gap 2).

## 1. Dataset properties (as verified)

| Property | ECTSum | QMSum |
|---|---|---|
| Citation | Mukherjee et al. (2022), EMNLP Main Conference, arXiv:2210.12467 | Zhong et al. (2021), NAACL 2021, arXiv:2104.05938 |
| Total pairs | 2,425 | 1,808 query-summary pairs over 232 meetings |
| Split (verified) | 1,681 / 249 / 495, exact match to paper's split | 1,257 / 272 / 279, combined general+specific, matches paper |
| Split (project's narrower claim) | n/a | ~950/~200/~210 specific + 162/35/35 general. Plausible sub-split, not independently verified against the paper's own breakdown table. Treat as an estimate, not a confirmed count |
| License | GPL-3.0 | MIT |
| Source register | Earnings call transcripts (external, investor facing) | General meeting transcripts (academic committee, product, board style meetings) |
| Summary structure | Single tier: numeric bullet points, "so what" style | Two tiers: general query (whole meeting overview) and specific query (topic targeted segment) |
| Domain match to PMI | Financial/status numeric content close to SteerCo reporting register | Meeting format close to PMI status meetings, content register not PMI specific |
| Data format | Plain text, `.txt`. One transcript file plus one ground-truth-summary file per pair, matched by filename (e.g. `AAP_q1_2021.txt` in both `ects/` and `gt_summaries/`) | JSON. Per official repo (`Yale-LILY/QMSum`, `README.md`, checked this session): one JSON object per meeting with four fields, `topic_list`, `general_query_list`, `specific_query_list` (each query/answer pair, specific queries also carry `relevant_text_span`), and `meeting_transcripts` (ordered list of `{speaker, content}` turns). Offered in both `.jsonl` and per-split `.json`, split across `data/ALL` (combined) and `data/Academic`/`data/Product`/`data/Committee` (single domain) |
| Local path / source | Confirmed present in this repo: `PMI-Reporting-Agent/data/ectsum/{train,val,test}/{ects,gt_summaries}/*.txt`, file counts match the verified 1,681/249/495 split | **Not found locally.** Searched this project folder and the `PMI-Reporting-Agent` repo tree (including `origin/katja`): no `qmsum` directory, no matching JSON files exist anywhere. `TrainingData_Decision.md`'s claim of "Downloaded & verified (local, 102 MB)" is not reflected in the actual repo state, the same pattern `DataIngestion_CriticalReview.md` already flagged for the `katja-dataset` branch. Source of truth for now is the upstream repo: https://github.com/Yale-LILY/QMSum (`data/ALL`, `data/Academic`, `data/Committee`, `data/Product`) |

## 2. Requirements pulled from the slide and the docs

**Baseline specific requirements** (infrastructure, not data shape): Excel/Confluence/Jira/MS
Project integration, native Office output (Excel, PowerPoint), standardized status schema across
workstreams, notification/push (email, Teams, Slack), tracker update discipline, defined cadence
and format standards.

**Potentials and pain points** (capabilities to build): automated multi tier reporting, task
integration (meeting summary to Jira), smart prioritization (overdue flagging, weekly task list),
KPI benchmarking, qualitative/sentiment insights, legacy Office compatibility.

**Exemplary reworked UC3** (highest demand, per interviews): status collection directly from
workstream leads via form, Jira, or transcript; meeting summary generation with automatic task
entry into Jira; auto generated prioritized weekly task list; overdue task flagging with automatic
escalation.

**Formal requirements** (`H2_Reporting_Requirements.docx`): R1 data source integration, R2
transcripts as structured async input, R3 upfront defined templates, R4 non-IT workstream
onboarding, R5 tiered audience-specific reports from one data source, R6 mandatory human review
gate.

**Known uncovered gaps** (`TrainingData_Decision.md` / UC2_V2 §5): Gap 1, multi-format structured
extraction (Excel/PPTX/Word/PDF/HTML into one schema). Gap 2, cross-source conflict resolution
(e.g. "Excel 82% vs. PowerPoint 75%").

## 3. Comparison against requirements

| Requirement / dimension | ECTSum | QMSum | Verdict |
|---|---|---|---|
| Audience tiering (R5, multi tier reporting) | Covers one tier: executive/SteerCo style bullet summary | Covers two tiers: general query maps to SteerCo overview, specific query maps to workstream lead detail | Together cover 2 of 3 tiers. Neither produces a Functional Manager digest (workstream subset) tier |
| Transcript as input (R2, baseline UC3's live example) | Input is a call transcript, format matches | Input is a meeting transcript, closest format match of the two | Both match the transcript modality, contingent on D1 (see section 4) |
| Task/action item extraction with owner attribution (Task Integration, exemplary UC3 point 2, R2) | Not covered, no task structure in the corpus | Not covered, QMSum is summarization only, no action item or owner labels | Gap. Neither dataset teaches this skill, this is AMI's role, currently blocked per `OPEN_POINTS.md` #6 |
| Overdue flagging and escalation (Smart Prioritization, exemplary UC3 point 4) | Not covered | Not covered | Gap. No dataset candidate identified. Likely a deterministic/rule based feature, not a learned one (see section 5) |
| KPI benchmarking | Not covered | Not covered | Gap. No proxy corpus identified |
| Qualitative/sentiment/cultural signals | Weak, monologue style earnings calls carry little dialogue level sentiment | Weak but marginally better, multi speaker dialogue at least contains some tone signal, no labeled sentiment | Neither is fit for purpose. Would need a dedicated sentiment/discourse corpus if the team wants this learned rather than prompted |
| Numeric/budget variance fidelity (R5, traffic light status) | Strong, ECTSum's own evaluation emphasizes factual/numerical faithfulness in financial bullets | Weak, QMSum summaries are narrative, not numeric | ECTSum is the stronger fit for this specific sub-requirement |
| Standardized cross-workstream schema (baseline requirement 3, R1, R4) | Not covered, single transcript to single summary, no workstream tagging | Not covered, same structure | Gap. Neither corpus originates from multiple sources or carries a workstream schema |
| Multi-format extraction into schema (Gap 1) | Not covered, plain text only | Not covered, plain text only | Confirmed gap, unaffected by this comparison. SEC EDGAR remains the recommended source per `TrainingData_Decision.md` |
| Cross-source conflict detection (Gap 2) | Not covered | Not covered | Confirmed gap, needs synthetic conflict injection regardless of which generation corpus is used |
| Native Office output rendering (Legacy Compatibility, baseline requirement 2) | Not applicable, this is a templating/rendering step (python-pptx/openpyxl), not a text generation skill either corpus can teach | Not applicable, same reasoning | No dataset action needed, already handled by existing rendering scripts |
| License risk for thesis deliverables | GPL-3.0, fine for internal fine-tuning/eval, re-check before redistributing weights or repackaged data | MIT, permissive, no redistribution restriction | If the thesis package ever ships a model or repackaged eval set publicly, QMSum carries less license risk than ECTSum |
| Verification status (project's own rigor standard) | Fully verified, split sums and matches paper exactly, already checked into repo | Total confirmed against the paper. The project's own narrower specific/general sub-split (~950/~200/~210 + 162/35/35) is flagged as an estimate, not yet checked against the paper's breakdown table | ECTSum is closed on this point. QMSum has one open verification item |

## 4. A scope conflict the comparison surfaces

The slide's "Potentials & Pain Points" section and its live interview quote ("Hey Claude, zieh
dir doch mal das Transkript...") describe a transcript-in, Jira-task-out pipeline as the
highest-value, already-working example of this use case. `H2_Reporting_Requirements.docx`'s R2
formalizes this as a requirement. But `UC2_V2_SingleAgent_Definition.md` §5 states Version 2's
literal input list is Excel/PowerPoint/PDF/Word/HTML, with no transcripts, and `OPEN_POINTS.md`
#3 (D1) already logs this as an open, unresolved team decision that gates QMSum's (and AMI's)
relevance entirely.

This matters here because it is upstream of the dataset comparison itself: if D1 resolves to "no
transcripts in V2 scope," QMSum's applicability drops to zero regardless of how well it otherwise
maps to the audience tiering requirement, and the slide's own headline example (UC3, baseline,
not V2) would need to be marked explicitly out of scope for the current build, or D1 would need
to be reopened. This is not a new finding, it is the same D1 item already on the open list, but
this comparison is a second, independent path to the same conflict, worth noting per the
project's rule that catching things twice, independently, is what the formal process is for.

## 5. Action item plan

**Either/or (blocks on D1):**

- If D1 resolves "yes, transcripts stay in V2 scope": keep the current hybrid plan, ECTSum for
  the executive/SteerCo tier, QMSum for the workstream-detail tier, and proceed to fix the QMSum
  verification gap below before using QMSum's numbers in any deliverable.
- If D1 resolves "no, V2 drops transcripts": drop QMSum (and AMI) from the V2 training plan
  entirely, keep ECTSum only for the executive tier, and formally mark the slide's transcript
  based exemplary UC3 example as a V1/baseline reference case, not a V2 build target, so it stops
  reading as an implicit V2 requirement.

**Mitigation and adjustments to the existing plan:**

- Verify QMSum's claimed 950/200/210 specific plus 162/35/35 general sub-split against the
  paper's own breakdown table before it appears in any slide or decision doc as a confirmed
  number. Currently an estimate, per `DataIngestion_CriticalReview.md`.
- **Actually download QMSum before treating it as available.** This session's search of the
  local project folder and repo found no `qmsum` data anywhere, contradicting
  `TrainingData_Decision.md`'s "downloaded, local, 102 MB" claim, the ECTSum precedent for how
  this should look (`data/ectsum/` in the repo, file counts verified). Pull from
  `https://github.com/Yale-LILY/QMSum` (`data/ALL` for the combined split, or the three
  domain-specific folders if a per-domain split is preferred) and check it into
  `PMI-Reporting-Agent/data/qmsum/` the same way ECTSum was checked in, before D1 execution
  starts, not after.
- Resolve D1 before investing further build time in QMSum or AMI layers, per `OPEN_POINTS.md` #3.
  This comparison independently confirms D1 as the correct blocking decision, not a nice to have.
- Do not treat "audience tiering covered" as fully satisfied even in the transcripts-in-scope
  case. ECTSum plus QMSum cover 2 of 3 tiers (SteerCo, workstream lead). The Functional Manager
  digest tier (a workstream subset view) has no corpus coverage from either source and would need
  to be derived by filtering/subsetting the workstream-lead tier's output, not trained separately.

**Additions (fill the confirmed gaps, none of which this pair of datasets can fix):**

- Action item extraction with owner attribution: source from AMI (Carletta et al. 2005,
  partitioned per Rennard et al. 2022, CC BY 4.0), already identified in `TrainingData_Decision.md`
  and currently blocked on manual download per `OPEN_POINTS.md` #6. No change to that
  recommendation, just reconfirming it is the only path for this specific requirement.
- Overdue flagging, escalation, and KPI benchmarking: no academic proxy corpus was identified for
  either. Recommend scoping these as deterministic, rule based logic (date threshold comparisons,
  benchmark lookup tables) rather than sourcing training data for them, since they are structurally
  closer to business logic than to a text generation or extraction skill.
- Qualitative/sentiment/cultural signal enrichment: neither corpus is fit for purpose. If the team
  wants this learned rather than handled via prompting a general purpose model, it needs a
  dedicated research pass (a fourth `pmi-deep-research` run), not an extension of the current two
  corpora.
- Gap 1 (multi-format extraction) and Gap 2 (conflict resolution): unaffected by this comparison,
  already correctly flagged in `TrainingData_Decision.md` with SEC EDGAR XBRL/HTML/Ex-99.1 as the
  recommended real-data source for Gap 1, and synthetic conflict injection for Gap 2. Keep both
  funded as first-class pipeline rows per `OPEN_POINTS.md` #10, this analysis found no reason to
  change that recommendation.

## 6. Deep-research addendum: is there a closer-fit open dataset than ECTSum/QMSum?

Run via `pmi-deep-research` (Xiao and Watson 2017 eight-step protocol), 2026-07-18.

**Step 1-2: Research question and protocol.** Concrete decision: is there an open-source,
academically rigorous dataset whose register is closer to internal, recurring, structured
project/program status reporting (tasks, milestones, RAID log, budget/KPI variance,
audience-tiered output) than ECTSum's earnings-call register or QMSum's general-meeting
register. Databases searched: general web search standing in for Google Scholar/Semantic Scholar
signal, arXiv, ACL Anthology, Hugging Face dataset cards. Search terms run: "GovReport dataset
long report summarization," "open source project status report summarization dataset PMO task
milestone," "MeetingBank city council meeting summarization dataset," "multi-tier audience
summarization dataset executive summary detailed report," "software issue tracking bug report
summarization dataset Jira GitHub," "Multi-LexSum civil rights lawsuits multiple granularities."
Inclusion: named author/title/year, peer-reviewed or NeurIPS/ACL/NAACL Datasets and Benchmarks
track, speaks directly to report-or-meeting-to-summary generation (not just adjacent), 2020 or
later. Exclusion: vendor/tooling pages with no dataset attached (PMO report templates, Broadcom/
OpenProject docs), issue-tracker datasets with no paired gold summary (Eclipse bug reports,
Spring Jira Bug Dataset, an IEEE DataPort listing), generic multi-document news summarization
with no report/status register (NewsSumm, MultiNews).

**Step 3-4: Search and screening.** The PMO/status-report search returned zero citable academic
datasets, only commercial tooling documentation, confirming this project's own earlier finding
(`TrainingData_Decision.md` §2, "no PMI-specific reporting dataset exists"). The issue-tracking
search returned real, citable datasets (Eclipse bug corpus, Spring Jira Bug Dataset, an
alternative public-Jira-repo dataset) but all were excluded: they carry no gold-standard summary
or report text, only issue metadata, so none would teach a generation skill, only classification/
localization, a different task. Three candidates survived screening: GovReport, Multi-LexSum,
MeetingBank.

**1. GovReport** — *Huang, L., Cao, S., Parulian, N., Ji, H., and Wang, L. (2021), "Efficient
Attentions for Long Document Summarization," NAACL 2021 Main Conference*
- **Evidence tier:** Peer-reviewed, NAACL main conference. Recognition signal: adopted as a
  standard component of multiple later long-context benchmarks found independently during this
  search (SCROLLS, LongBench, L-Eval), which is a stronger, more durable recognition signal than
  a raw citation count.
- **Type:** Empirically validated, the paper's own summarization models are benchmarked against
  it with ROUGE.
- **What it actually claims or does:** 19,466 real reports from the U.S. Congressional Research
  Service and Government Accountability Office paired with expert-written summaries. Confirmed
  this session directly from the dataset host (`ccdv/govreport-summarization` on Hugging Face):
  17,517 train / 973 val / 973 test, CC BY 4.0 license, plain report-string to summary-string
  JSON/parquet format. A companion release, GovReport-QS (Cao and Wang, 2022, HIBRIDS, arXiv
  2203.10741), adds question-summary hierarchies over the same reports, i.e. an explicit outline
  structure, not a separate dataset for this comparison's purposes.
- **Fit to this project's constraint:** the closest register match found. GAO/CRS reports are
  formal, structured program and policy assessments (budget review, performance audit, compliance
  status) written for a governance audience, summarized down to an executive-readable brief, the
  same generation shape as SteerCo reporting (long structured status in, short audience-tiered
  summary out), and the source content itself is often numeric/programmatic (budget figures,
  performance metrics), closer to R5's "traffic-light status, budget variances" than ECTSum's
  investor-facing earnings narrative or QMSum's generic meeting talk.

**2. Multi-LexSum** — *Shen, Z., Lo, K., Yu, L., Dahlberg, N., Schlanger, M., and Downey, D.
(2022), "Multi-LexSum: Real-World Summaries of Civil Rights Lawsuits at Multiple Granularities,"
NeurIPS 2022 Datasets and Benchmarks Track, arXiv:2206.10883*
- **Evidence tier:** Peer-reviewed, NeurIPS Datasets and Benchmarks track, a top-tier ML venue
  specifically for dataset contributions.
- **Type:** Empirically validated, and uniquely among all datasets considered in this project so
  far, expert-authored rather than (semi-)automatically curated: lawyers and law students wrote
  the summaries against a guideline, with a second-expert review pass.
- **What it actually claims or does:** 9,280 case summaries, each with up to three target
  summaries at different granularities (tiny/one-sentence, short/one-paragraph, long/
  multi-paragraph) for the same underlying case, confirmed via the dataset's own Hugging Face
  card (train 3,177 cases / test 908 / dev 454, 70/20/10 split). License: source documents public
  domain, case summaries and metadata CC BY-NC (non-commercial), code Apache 2.0.
- **Fit to this project's constraint:** the strongest structural fit found for R5's explicit
  three-tier audience requirement specifically. ECTSum offers one tier, QMSum offers two
  (general/specific), Multi-LexSum is the only candidate built from the ground up as one source
  with three parallel target summaries of increasing depth, which is a closer structural analog
  to CEO 3-pager / workstream digest / functional-manager subset than anything else found. Domain
  register (civil rights litigation case narratives) is not close to PMI status reporting at all,
  weaker than GovReport on register, and the CC BY-NC license needs a check against how this
  project's academic use is framed before relying on it beyond internal thesis work.

**3. MeetingBank** — *Hu, Y., Ganter, T., Deilamsalehy, H., Dernoncourt, F., Foroosh, H., and
Liu, F. (2023), "MeetingBank: A Benchmark Dataset for Meeting Summarization," ACL 2023 Main
Conference, arXiv:2305.17529*
- **Evidence tier:** Peer-reviewed, ACL main conference.
- **Type:** Empirically validated, includes both professionally written official minutes and
  model-generated summaries for comparison.
- **What it actually claims or does:** 1,366 real city council meetings across 6 major US cities,
  transcripts plus professionally written official meeting minutes as gold summaries, 6,892
  segment-level summarization instances, split 5,169 train / 861 val / 862 test (confirmed via
  the dataset's Hugging Face card this session). License CC BY-NC-SA 4.0.
- **Fit to this project's constraint:** the closest match found for *recurring institutional
  governance cadence* specifically, the same governing body meets repeatedly over time and
  produces a structured, official record each time, structurally closer to a standing SteerCo's
  meeting rhythm than QMSum's one-off, domain-mixed meetings. Register (civic/public governance)
  is not PMI-specific, and the license is the most restrictive of the three (NC and ShareAlike
  both apply), a real constraint to check before use.

**Recommendation (Step 7).** GovReport is the strongest single addition: closer register (formal
structured report to executive summary, numeric/programmatic content) than either existing
candidate, a fully permissive CC BY 4.0 license (better than ECTSum's GPL-3.0), and durable
recognition via inclusion in standard long-context benchmarks. It does not replace ECTSum, ECTSum
remains the closer match for numeric earnings-style fidelity specifically (Section 3), but
GovReport is recommended as a third generation-skill source targeting the executive/SteerCo tier
specifically, strengthening exactly the tier this project's own evaluation plan already prioritizes.
Multi-LexSum is the strongest answer to a narrower question, if the team wants the audience-tiering
skill (R5) trained on data explicitly built for multi-granularity output rather than inferred from
QMSum's two-tier structure, at the cost of a weaker domain register and a non-commercial license
condition to verify. MeetingBank is the weakest fit of the three for register purposes here, it is
included because the search found it and it is real, rigorous, and well-recognized, not because it
beats QMSum, per this project's honesty rule, it does not clearly do so, its main value is the
recurring-cadence structural analogy, not content register. **Honest bottom line:** no candidate
found beats ECTSum/QMSum outright, none is PMI-specific (confirming `TrainingData_Decision.md`'s
original finding that no such dataset exists), but GovReport is a genuine, concrete improvement to
add alongside the existing pair, not a replacement for the D2 (Gap 1/2) decision, which remains
unaffected by this search.

### Sources for Section 6

- Huang, L., Cao, S., Parulian, N., Ji, H., and Wang, L. (2021). "Efficient Attentions for Long
  Document Summarization." NAACL 2021. https://aclanthology.org/2021.naacl-main.112/
- Cao, S., and Wang, L. (2022). "HIBRIDS: Attention with Hierarchical Biases for Structure-aware
  Long Document Summarization." arXiv:2203.10741
- Shen, Z., Lo, K., Yu, L., Dahlberg, N., Schlanger, M., and Downey, D. (2022). "Multi-LexSum:
  Real-World Summaries of Civil Rights Lawsuits at Multiple Granularities." NeurIPS 2022 Datasets
  and Benchmarks Track. https://arxiv.org/abs/2206.10883
- Hu, Y., Ganter, T., Deilamsalehy, H., Dernoncourt, F., Foroosh, H., and Liu, F. (2023).
  "MeetingBank: A Benchmark Dataset for Meeting Summarization." ACL 2023.
  https://aclanthology.org/2023.acl-long.906/
- Dataset cards checked directly: https://huggingface.co/datasets/ccdv/govreport-summarization,
  https://huggingface.co/datasets/allenai/multi_lexsum,
  https://huggingface.co/datasets/huuuyeah/meetingbank
- GovReport license and citation: https://gov-report-data.github.io/

## 7. D1 resolved as "keep both": usage plan and coding-agent demands

Per team direction, D1 is treated here as resolved to "yes, transcripts stay in scope, keep both
ECTSum and QMSum." This section gives a concrete plan for using them to maximize requirement
fulfillment beyond raw text-in, text-out generation, plus the Section 5 additions restated as an
implementation-ready spec.

### 7.1 Split-to-format rendering plan

Section 3 established that ECTSum and QMSum's raw text pairs exercise the report-generation step
only. They currently touch none of Gap 1 (multi-format extraction), Office rendering, or the
vision/image extraction subsystem, which `DataIngestion_CriticalReview.md` (finding 7) flags as
"the biggest subsystem" per `MASTER.md`'s own description, with zero data-layer coverage anywhere
in the project. The proposal below reuses a portion of the existing gold summaries, not to teach
the model anything new, but to manufacture end-to-end pipeline integration fixtures against real
narrative content instead of only synthetic (`make_sample_data.py`-style) content.

**Caveat, carried over honestly, not glossed over:** this does not fix Gap 1's real finding.
Real business documents have structural noise (merged cells, inconsistent headers, cross-format
numeric contradictions) that a rendering script cannot invent from clean prose, exactly the
limitation `DataIngestion_CriticalReview.md` finding (a) already identified for this style of
reshaping. This plan increases the return on two datasets already in hand and adds partial,
synthetic-structure coverage to the extraction and vision layers; it is not a substitute for the
SEC EDGAR real-document plan already recommended for Gap 1.

| Split | Purpose | Rendered | Target format | Rationale |
|---|---|---|---|---|
| ECTSum train (1,681) | Generation fine-tuning/prompting corpus | 0%, stays raw `.txt` | n/a | Rendering adds nothing the generation step needs to learn |
| ECTSum val (249) | Stage-3 generation eval, plus a cloned extraction-fixture pool | 100% stays raw for generation eval; an additional 15% (about 37 pairs) is cloned, not removed, into pptx SteerCo-shell decks | pptx | Tests the ingestion-to-generation roundtrip: can the pipeline re-extract what it just generated |
| ECTSum test (495) | Ticker-disjoint (per D4) held-out benchmark, plus extraction/vision fixtures | 100% stays raw for the benchmark; an additional 20% (about 99 pairs) cloned: 12% (about 60) to pptx, 8% (about 39) to KPI-chart images (`matplotlib`, already a project dependency) | pptx + jpg | The jpg allocation is the only source in this plan that gives the vision/image extraction subsystem anything, even synthetic-structure, real-narrative charts, to run against |
| QMSum general-query | SteerCo-tier generation signal, same role as ECTSum | Train stays raw; 15% of val/test cloned to pptx | pptx | Enlarges the SteerCo-tier rendering pool without touching QMSum's specific-query role |
| QMSum specific-query | Workstream-lead-tier generation signal | Train stays raw; 15% of val/test cloned to docx | docx | Closest target format to R5's "workstream digest with full task list" tier |

**Timing:** rendering happens once, at held-out fixture build time, the same moment
`TrainingData_Decision.md`'s Stage 0 freezes the 15 to 30 real PMI examples, not repeated per
training epoch. Rendered files land in a new, versioned `data/rendered_fixtures/` tree and are
consumed only by integration tests (7.3, Demand 3), kept fully separate from the raw val/test
files used for Stage-3 ROUGE/BERTScore scoring, so no single example serves both the generation-
eval role and the extraction-fixture role, the project's Exclusiveness rule applied to data reuse.

### 7.2 Note on the percentages

The 15% and 20% figures above are a starting proposal for the team to tune, not an empirically
derived optimum, stated plainly so they are not mistaken for a validated number the way QMSum's
sub-split estimate was flagged in Section 1. They are sized to be large enough to give the
extraction/vision layers a non-trivial fixture pool without materially shrinking the generation
eval sets they are cloned from (cloned, not moved, specifically so Stage-3 scoring is unaffected).

### 7.3 Section 5 additions, restated as coding-agent demands

**Demand 1, fill the QMSum data gap.** Create `PMI-Reporting-Agent/data/qmsum/`, pull from
`https://github.com/Yale-LILY/QMSum` (`data/ALL/jsonl/{train,val,test}.jsonl`). Acceptance: file
or record counts match the paper's 1,257/272/279 combined split; add a `data/README.md` entry in
the same format as the existing `ectsum/` entry.

**Demand 2, build the split-to-format renderer.** New file `scripts/render_generation_fixtures.py`,
modeled on the existing `scripts/make_sample_data.py`. Input: ECTSum val/test pairs, QMSum val/test
general- and specific-query pairs. Output: `data/rendered_fixtures/{pptx,docx,jpg}/` using the
existing `app/generators/pptx_report.py` for pptx, a new `app/generators/docx_report.py` (only
`pptx_report.py` and `xlsx_dashboard.py` exist today, confirmed this session) for docx, and
`matplotlib` (already in `requirements.txt`) for the jpg KPI charts. Percentages from 7.1
implemented as named constants (e.g. `ECTSUM_VAL_RENDER_PCT = 0.15`), not hardcoded inline, so the
team can retune without a code change. Deterministic given a fixed random seed. Output includes a
manifest CSV mapping each rendered file back to its source split and id.

**Demand 3, wire the extraction roundtrip test.** Extend `tests/test_pipeline.py`: for each file in
`data/rendered_fixtures/`, run it through the matching `app/extractors/*.py` module and assert the
extracted text has nontrivial overlap (e.g. ROUGE-1) with the gold summary it was rendered from, a
low bar that only catches gross extraction failures, not a full quality gate. The test must fail
loudly, not silently skip, if a fixture directory is empty, the same "claimed but not present"
failure mode already caught twice in this project (QMSum's missing local data, the `katja-dataset`
branch's missing scripts).

**Demand 4, AMI acquisition.** Not a coding demand, per `OPEN_POINTS.md` #6 the host blocks
scripted download; flag to Sören for manual acquisition specifically. Once obtained, place at
`data/ami/`; check `app/models/pmi.py`'s task schema for owner-attribution fields before adding
new ones, to avoid duplicating an existing field.

**Demand 5, deterministic overdue/escalation and KPI-benchmark logic.** New or extended file,
likely `app/agent/standardize.py` or a new `app/agent/prioritization.py`. Behavior: overdue is
`due_date < today AND status != "Done"`; escalation triggers on a configurable N-day-past-due
threshold; KPI benchmarking is a static lookup table keyed by workstream type, sourced from the
team's own domain knowledge, not a dataset. Explicit instruction to the coding agent: this is
deterministic business logic per Section 5's own finding, do not attempt to train or prompt-tune
it as a generation task.

**Demand 6, Gap 1/Gap 2, no change.** Listed here only for completeness of this demand set. No new
coding action beyond what `TrainingData_Decision.md` and `OPEN_POINTS.md` #10 already specify
(SEC EDGAR XBRL/HTML pipeline for Gap 1, synthetic conflict injection for Gap 2); this analysis
found no reason to change that recommendation.

## Sources

- Mukherjee et al. (2022), ECTSum, EMNLP, https://aclanthology.org/2022.emnlp-main.748/
- Zhong et al. (2021), QMSum, NAACL, https://arxiv.org/abs/2104.05938
- `H2_Reporting_Requirements.docx` (this project)
- `TrainingData_Decision.md`, `DataIngestion_CriticalReview.md`, `OPEN_POINTS.md`,
  `UC2_V2_SingleAgent_Definition.md` §5 (this project)
- "H2 Automated Reporting: Requirements & Potentials" slide, Deloitte deck (provided this session)
- Section 6 sources listed separately above, covering GovReport, Multi-LexSum, and MeetingBank
