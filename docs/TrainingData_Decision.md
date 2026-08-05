# Training Data Concept — Status, Bottleneck, Decision & Evaluation

Compiled 2026-07-09. Sources: Google Doc "H2 — Deep Dive: ECTSum Addition +
Training Data Concept" (compiled 2026-07-08), `H2 Reporting - Relevant
Databases & Papers.docx`, `UC2_V2_SingleAgent_Definition.md` §5, and web
research on SEC EDGAR (2026-07-09). Companion slide:
`../TrainingData_Decision_Slide.pptx` (in the shared PMI folder).

## 1. Where the concept stands (line-up)

Three verified proxy corpora, mapped to sub-skills (per the Deep Dive doc's
core principle: *don't flatten sources into one training set — they test
different sub-skills*):

| Sub-skill | Corpus | Status | Split |
|---|---|---|---|
| Executive/SteerCo digest generation | **ECTSum** (Mukherjee et al. 2022, EMNLP, arXiv:2210.12467, GPL-3.0) + QMSum general-query | Downloaded & verified; in repo `data/ectsum/` | 1681/249/495 (+162/35/35) |
| Workstream-detail reports | **QMSum** specific-query (Zhong et al. 2021, NAACL, arXiv:2104.05938, MIT) | Downloaded & verified (local, 102 MB) | ~950/~200/~210 pairs |
| Action-item extraction | **AMI** (Carletta et al. 2005; partition per Rennard et al. 2022, CC BY 4.0) | **Blocked** — manual download required | 98/20/20 meetings |

Prep decisions already made in the concept: temperature-based multi-task
sampling (T≈2–3) so ECTSum doesn't drown the smaller corpora; ECTSum
"paraphrase" variant for natural report style; AMI filtered to
decision/action dialogue acts.

## 2. The bottleneck — still there

**No PMI-specific reporting dataset exists** (confirmed by search, Deep Dive
§2). Every corpus above is a proxy domain. On top of that, V2's own workflow
added **two sub-skills none of the three corpora cover at all**
(UC2_V2 §5):

- **Gap 1 — multi-format structured extraction**: Excel/PPTX/Word/PDF/HTML →
  one Pydantic PMI schema. All three corpora are summarization-from-dialogue
  sets; none teach schema-normalization from heterogeneous business documents.
- **Gap 2 — cross-source consistency & conflict resolution**: detect
  "Excel 82% vs PowerPoint 75%" and resolve. No existing corpus contains
  multiple conflicting representations of the same fact *by design*.

Secondary bottlenecks: AMI not yet obtained; QMSum/AMI relevance conditional
on the open transcript-scope decision; ECTSum 310-ticker train/test overlap
unresolved.

## 3. Decision questions

1. **D1 — Scope:** Is transcript ingestion in V2? (Gates QMSum + AMI entirely.)
2. **D2 — Gap data:** Fill gaps 1–2 with **synthetic** data, a **proxy**
   corpus (SEC EDGAR), or a **hybrid**? — **Reframed by §8 (2026-07-24):** the
   underlying premise (a fine-tuning-style train/test split over labeled
   proxy data) doesn't match this agent's actual architecture, which has no
   training loop at all. See §8 for the revised recommendation.
3. **D3 — Rigor:** Run D2 through the full `pmi-deep-research` 8-step protocol
   (Xiao & Watson 2017) before treating it as settled? — **Resolved
   2026-07-24, see §8.**
4. **D4 — Split hygiene:** Accept ECTSum ticker overlap or re-split
   ticker-disjoint for a stricter generalization test? — Still applies to any
   ECTSum-based benchmark number specifically; superseded as the *primary*
   evaluation question by §8's prequential/rolling-origin finding for the
   continuously-growing SM-review corpus.
5. **D5 — License gate:** ECTSum is GPL-3.0 — internal fine-tuning/eval OK;
   re-check before redistributing weights or repackaged data.

## 4. Option A — Synthetic data

**Context:** gap 2 is a narrow, mechanical skill on a schema we own; the repo
already generates seeded-conflict test files (`scripts/make_sample_data.py`,
82%-vs-75%) and the pytest suite consumes them.

**Pro**
- Exact fit to our Pydantic schema and the Excel > Word/PDF > PPT > HTML rule;
  conflict patterns and gold labels exist *by construction*.
- Unlimited volume, zero license risk, near-zero cost; pipeline already built.
- Only practical way to get *guaranteed* conflicts — real business documents
  rarely contradict each other on purpose.

**Con**
- Circularity risk: we test what we generated — validates the mechanism, not
  real-world robustness.
- Known risks of LLM-generated data: distribution bias, and model collapse if
  synthetic data replaces (rather than accumulates alongside) real data —
  Long et al. (2024), ACL Findings, arXiv:2406.15126; arXiv:2510.01631.
- Weak external validity as thesis evidence (project rule: empirical > constructed).

## 5. Option B — Proxy corpus via SEC EDGAR

**Context:** EDGAR is the SEC's free filings database — no API key, JSON REST
APIs (`data.sec.gov`), full-text search (`efts.sec.gov`), ~10 req/s fair-use
limit. The decisive property: **the same financial fact appears in multiple
formats per company-quarter** — XBRL structured tags (machine-readable ground
truth), 10-K/10-Q HTML tables, 8-K Exhibit 99.1 press-release narrative +
tables, PDF investor presentations. M&A-adjacent registers exist too (8-K
merger announcements, S-4, DEFM14A merger proxies).

**Pro**
- Gap 1 nearly solved for free: XBRL tags = ground-truth labels for extraction
  from real HTML/PDF documents — no manual annotation.
- Real-world formatting noise (the thing synthetic data can't fake).
- Auditability and citability for the thesis; domain-adjacent
  (financial status reporting, same register ECTSum already covers).
- Free, stable, well-documented government source.

**Con**
- Register mismatch: regulated filings ≠ internal PMI status reports
  (vocabulary drift, same caveat as QMSum).
- Genuine *conflicts* are rare — filings are checked for internal consistency,
  so gap 2 still needs conflict *injection* (i.e., a synthetic step) even on
  EDGAR documents. Exception: Ex-99.1 non-GAAP figures vs XBRL GAAP figures
  differ systematically — a realistic "same-metric-different-value" pattern.
- Prep effort: format alignment, XBRL-to-text matching, US-listed companies only.

## 6. Recommendation (for team decision, not decided)

**Hybrid, per sub-skill:** ECTSum (+QMSum if D1=yes) for generation;
EDGAR XBRL↔HTML/Ex-99.1 pairs for extraction (gap 1); synthetic conflict
injection — into both sample files and EDGAR documents — for gap 2;
and, non-negotiable regardless of option (Deep Dive §2, "the step that
matters most"): **15–30 manually written or anonymized real PMI examples as a
fully held-out target-domain test set.**

## 7. Evaluation process — how to know the choice was right

**Stage 0 — Freeze test sets before anything else.** The 15–30 real PMI
examples (never seen in training/prompting), plus a ticker-disjoint ECTSum
test subset (resolves D4 conservatively).

**Stage 1 — Extraction (gap 1).** Field-level precision/recall/F1 per entity
type (tasks, risks, budget, KPIs, owners, dates, status) against gold schema;
numerical accuracy as a separate line (a wrong number is worse than a missed
field in SteerCo reporting).

**Stage 2 — Consistency & conflict (gap 2).** Detection recall on seeded
conflicts; resolution accuracy vs. the source-priority rule and vs. human
gold decisions; false-positive rate on conflict-free document sets.

**Stage 3 — Generation.** ROUGE-1/2/L + BERTScore against reference
summaries, plus numerical precision of generated bullets (ECTSum's own
evaluation emphasizes factual/numerical faithfulness); blinded human rating
(audience fit, 1–5) by team members acting as SM reviewers.

**Stage 4 — The success metric that decides.** *Transfer gap* = proxy-domain
score − held-out-PMI score. Acceptance: PMI held-out performance within a
team-set tolerance (suggest ≤10–15% relative) of proxy performance, and
Stage-1 numerical accuracy above a hard floor (suggest ≥95%). If the transfer
gap exceeds tolerance → the proxy choice failed for that sub-skill: add
PMI-register synthetic data or reconsider (loop back to D2). In production,
track SM-review correction rate per report as the ongoing metric.

## 8. D3 executed — pmi-deep-research 8-step protocol on the data-utilization strategy (2026-07-24)

**Trigger:** user linked `H2_Dataset_Comparison` (Google Sheet), which extends §1–§7's ECTSum/QMSum
comparison to 5 corpora (adds GovReport, Multi-LexSum, MeetingBank) and shows **every one Gap on
all six PMI-specific rows** (task/action-item extraction, overdue flagging, KPI benchmarking,
cross-workstream schema, multi-format extraction, cross-source conflict detection). User proposed
unsupervised/statistical pattern-finding with continuous learning as an alternative to forcing
supervised training onto weak-fit labels, and asked whether a fixed split, k-fold, or one pooled
dataset is the right evaluation scheme — researched via the full 8-step protocol, explicitly
instructed not to weight this project's own prior conclusions above neutral external research.

**Reframing:** this agent has no training loop (`MASTER.md`: LLM only classifies/words, never
invents numbers) — the real decision is data-utilization + evaluation methodology, not a
train/test split for model fine-tuning.

**Top 3, ranked by fit to short-timeframe + current architecture:**
1. **RAG / in-context learning** — Lewis et al. (2020), NeurIPS, arXiv:2005.11401 (7,453 citations)
   + Gao et al. (2023/24) survey, arXiv:2312.10997. Matches the *current* architecture exactly (no
   training loop); retrieve SM-approved past reports as few-shot exemplars instead of relying on
   zero-shot judgment. No new infrastructure beyond an embeddings index.
2. **Human-in-the-loop active learning / data flywheel** — Settles (2009) canonical survey, 6,623
   citations; "Agent-in-the-Loop" (2025, arXiv:2510.06674) as an applied case study (trend/adoption
   tier, not yet peer-reviewed-confirmed). The mandatory SM-review gate (`OPEN_POINTS.md` #7)
   *already* generates real, gold, target-domain examples as a byproduct — turns an existing
   compliance requirement into the data mechanism, rather than adding one.
3. **Weak/programmatic supervision** — Ratner et al. (2017), Snorkel, PVLDB, 479 citations, deployed
   at Google/Intel/Apple/IBM. Reuses the extractors already in `app/extractors/base.py` as labeling
   functions over real unlabeled documents. Right second-stage move if the team later wants a
   smaller trained extraction model instead of an LLM API call indefinitely.

**Screened out, explicitly:** pure unsupervised pattern-finding (clustering/autoencoding raw
documents) as a standalone solution. No literature found treating it as viable for structured
business-document extraction — the schema (task owner, % progress, risk vs. milestone) is imposed,
not a latent statistical pattern text alone reveals. Every credible label-scarce approach found
still injects some supervision signal (heuristic, human, or retrieved).

**Evaluation methodology (the split/k-fold/pool question):** k-fold assumes a fixed, i.i.d. dataset
— doesn't fit continuously-arriving SM-reviewed data. Gama, Žliobaitė, Bifet, Pechenizkiy &
Bouchachia (2014), "A survey on concept drift adaptation," *ACM Computing Surveys* 46(4), and a 2024
evaluation-standardization paper (arXiv:2204.13625) both point to **prequential ("test-then-train")
or rolling-origin evaluation** for streaming data instead. Pooling everything into one dataset with
no held-out set is what this literature argues against hardest. This **independently corroborates**
(not just repeats) §6's frozen 15–30-example held-out set — verified against external literature per
the user's explicit instruction not to over-weight prior internal conclusions.

**Recommendation:** combine candidates 1 and 2 — RAG at generation time, fed continuously by the
SM-review step, evaluated prequentially against the frozen gold set (§6, still stands, now
externally verified). Candidate 3 (Snorkel-style weak supervision) stays on the roadmap for a later
"train our own smaller model" phase, not the immediate pick. Full brief with all sources given to
user in chat 2026-07-24; not duplicated here in full to avoid file sprawl — see `PROJECT_MEMORY.md`
2026-07-24 entry for the complete writeup.

**New open decision surfaced:** does the team want to eventually train a specialized extraction
model (→ revisits candidate 3 / Gap-1 EDGAR data), or stay RAG/ICL-only indefinitely? Added to
`OPEN_POINTS.md`.

## Sources

- Google Doc: H2 — Deep Dive (doc id 1Giifm-klkodBr2vGkkHlxJC6Fx2VXosFnfoxj-ZcfiU), 2026-07-08
- Mukherjee et al. 2022, ECTSum, EMNLP — https://aclanthology.org/2022.emnlp-main.748/
- Zhong et al. 2021, QMSum, NAACL — https://arxiv.org/abs/2104.05938
- Carletta et al. 2005, AMI — https://groups.inf.ed.ac.uk/ami/corpus/
- Long et al. 2024, LLMs-Driven Synthetic Data: A Survey, ACL Findings — https://aclanthology.org/2024.findings-acl.658/
- Synthetic-data scaling/pitfalls — https://arxiv.org/html/2510.01631v1
- SEC EDGAR access & APIs — https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data ; https://www.sec.gov/about/developer-resources
- 8-K Exhibit 99 content characteristics — https://sec-api.io/datasets/form-8k-exhibit-99-content
- H2_Dataset_Comparison (Google Sheet) — https://docs.google.com/spreadsheets/d/1kDtgsEKNNPo5cKBKaUIP7ZFmq-Nr5_3oCeJINF5zRps/
- Ratner, A. et al. (2017), Snorkel, PVLDB 11(3) — https://dl.acm.org/doi/10.14778/3157794.3157797
- Settles, B. (2009), Active Learning Literature Survey, UW-Madison TR1648 — https://minds.wisconsin.edu/handle/1793/60660
- Agent-in-the-Loop (2025) — arXiv:2510.06674
- Lewis, P. et al. (2020), RAG, NeurIPS — arXiv:2005.11401
- Gao, Y. et al. (2023/24), RAG for LLMs: A Survey — arXiv:2312.10997
- Gama, J. et al. (2014), A survey on concept drift adaptation, ACM Computing Surveys 46(4) — https://dl.acm.org/doi/10.1145/2523813
- Standardized Evaluation of ML for Evolving Data Streams (2024) — arXiv:2204.13625
