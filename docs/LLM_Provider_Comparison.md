# OpenAI vs Claude for the PMI Reporting Agent — Pricing, Quality, Decision Parameters

Compiled 2026-07-09 from vendor pricing pages and third-party benchmark
comparisons (all web-checked today; benchmark sources are industry blogs, not
peer-reviewed — treat scores as directional, see caveats).

## 1. What the LLM actually does in our pipeline

Scope matters for both cost and quality: the LLM (a) classifies the user
request (output type + audience) and (b) writes summary bullets from the
already-extracted, already-validated data model. **It never extracts or
invents numbers** — extraction is deterministic. So the relevant quality axes
are instruction-following, structured (JSON) output reliability, faithfulness
to provided numbers, and business-document understanding — *not* raw
knowledge or coding benchmarks.

## 2. Pricing (standard API, USD per 1M tokens, July 2026)

| Model | Input | Output | Cached input | Batch |
|---|---|---|---|---|
| OpenAI GPT-5.5 (spec's choice) | $5.00 | $30.00 | $0.50 | $2.50 / $15.00 |
| OpenAI GPT-5.5 long-context (>272K in) | 2× in | 1.5× out | — | — |
| Claude Opus 4.8 | $5.00 | $25.00 | −90% | −50% |
| Claude Sonnet 5 (intro to 2026-08-31) | $2.00 | $10.00 | −90% | −50% |
| Claude Sonnet 5 (from 2026-09-01) | $3.00 | $15.00 | −90% | −50% |
| Claude Haiku 4.5 | $1.00 | $5.00 | −90% | −50% |

Both vendors bill purely per token (input + output); there is no per-call fee.
Both offer ~90% caching discounts and ~50% batch discounts.

**Cost per report for our workload** (typical run: ~10–20K input tokens of
serialized data model + prompts, ~1–2K output tokens):

| Model | Est. cost / report | ~Reports per 20 EUR/month (spec budget) |
|---|---|---|
| GPT-5.5 | $0.08–0.16 | ~130–250 |
| Claude Opus 4.8 | $0.08–0.15 | ~140–260 |
| Claude Sonnet 5 (intro) | $0.02–0.06 | ~350–1000 |
| Claude Haiku 4.5 | $0.01–0.03 | ~700–2000 |

At flagship tier the two are effectively price-equal for our workload (Claude
marginally cheaper on output). The real cost lever is tiering down: our
LLM tasks are narrow enough that Sonnet 5 / Haiku 4.5 likely suffice, at
3–10× lower cost. OpenAI's comparable lever is gpt-5.5 batch/flex mode
(halved, but async — awkward for an interactive UI).

## 3. Quality evidence for this use case

- **Office-document / structured understanding:** the largest reported gap in
  current head-to-heads is OfficeQA Pro: **Claude Opus 4.8 66.2% vs GPT-5.5
  54.1%** — the single most task-relevant benchmark for a
  business-document-reporting agent (CodingFleet, DataCamp).
- **Agentic/tool-use throughput:** GPT-5.5 slightly ahead on agentic suites
  (81.5 vs 80.1) and materially faster/cheaper per completed agentic task on
  some evals (~2× faster; $6.61 vs $12.58 per DeepSWE task) (CodingFleet,
  Requesty). Less relevant for us: our graph makes 2 short LLM calls per run.
- **Calibration / hallucination:** multiple 2026 hallucination studies find
  GPT-5.5 answers more questions correctly but fabricates confidently when it
  doesn't know (attempt rate ~86% on unknown questions vs ~36% for Claude,
  which abstains). With extended thinking both drop to ~4–5% hallucination
  rates (DigitalApplied, CometAPI, MindStudio). For numbers-forward SteerCo
  reporting behind a Senior-Manager review gate, **calibrated abstention is
  worth more than raw coverage** — a confidently wrong figure is the worst
  failure mode. Our deterministic-numbers design mitigates this for both.
- **Long context:** both handle our payloads (≤20K tokens) trivially;
  GPT-5.5's long-context surcharge and Claude's large windows are moot here.

**Caveats:** all named benchmarks come from third-party blogs/aggregators
(CodingFleet, DataCamp, BenchLM, Artificial Analysis, etc.), not peer review;
none evaluates PMI report generation specifically; scores move monthly. The
correct final arbiter is our own Stage 1–4 evaluation harness
(`TrainingData_Decision.md` §7) run against both providers — the mock/real
LLM switch in `app/agent/llm.py` makes an A/B swap a one-line env change.

## 4. Governance dimension (from prior project research)

Deloitte has **no named governance alliance with OpenAI** (OpenAI's "Frontier
Alliance" partners are McKinsey/BCG/Accenture/Capgemini); prior project
research cleared OpenAI/Azure for **prototyping only**, with Anthropic and
Google on the governance-track shortlist (UC2_V2 §3, §7). The PDF spec's
GPT-5.5 choice is consistent with a ~20 EUR/month prototype; a production
path would re-open the provider question through governance regardless of
benchmarks.

## 5. Decision parameters (proposed scorecard)

1. Cost per report at expected volume (incl. caching/batch discounts)
2. Structured-output (JSON schema) reliability — % valid parses over N runs
3. Numerical faithfulness — % bullets whose figures match the data model
4. Audience-fit quality — blinded human rating on our held-out PMI set
5. Calibration — abstention vs fabrication on missing data
6. Latency per report (interactive UI target: < ~15 s)
7. Governance/hosting eligibility (EU processing, DPA terms, alliance status)
8. Engineering fit — both first-class in LangGraph
   (`langchain-openai` / `langchain-anthropic`); switch cost is trivial

**Bottom line:** for the prototype, either works at near-identical flagship
cost; evidence tilts toward Claude on the two axes that matter most here
(document understanding, calibration), toward OpenAI on speed and agentic
throughput; the cheapest credible option is Claude Sonnet 5/Haiku 4.5 at
3–10× below the spec's 20 EUR budget. Run the A/B on our own harness before
committing; for production, governance (§4) dominates benchmarks.

## 6. Filled scorecard: Claude Sonnet 5 vs OpenAI GPT-5.5 (standard)

Project-specific fill-in, 2026-07-09. Workload basis: our pipeline makes 2 LLM
calls per report — request classification (~0.3K in / ~0.05K out) and summary
bullets from the serialized data model (~10–20K in / ~1–2K out). Numbers are
deterministic upstream. Open items marked, [assumptions in brackets].

| # | Parameter | Claude Sonnet 5 | OpenAI GPT-5.5 (standard) | Edge |
|---|---|---|---|---|
| 1 | **Cost per report** | Intro to 2026-08-31: $2/$10 → **$0.03–0.06**; from Sep: $3/$15 → $0.04–0.09. 20 EUR ≈ 350–1,000 reports/mo | $5/$30 → **$0.09–0.16**; caching cuts repeated system prompt ~90%. 20 EUR ≈ 130–250 reports/mo | Sonnet 5, ~2.5–3× cheaper [assumed volume ≤200 reports/mo: 5–10 workstreams × weekly + ad hoc — both fit spec's 20 EUR] |
| 2 | **Structured-output (JSON) reliability** | Structured outputs / tool-use JSON schema supported | Native `response_format: json_object` — already implemented in `app/agent/llm.py` | OPEN — measure % valid parses over N=100 runs on our harness; no public benchmark isolates this. [Assumption: both ≥99% on our two small, simple schemas] |
| 3 | **Numerical faithfulness** | Claude family better calibrated in 2026 hallucination studies | Higher fabrication tendency in same studies | OPEN — Stage-3 bullet-number precision test on held-out PMI set. [Assumption: both ≥95% since all figures are handed to the model in-prompt; risk is transcription, not recall] |
| 4 | **Audience-fit quality (SteerCo register)** | Opus 4.8 leads OfficeQA Pro 66.2 vs 54.1 [assumption: Sonnet 5 inherits part of the doc-understanding edge — unverified, benchmark is Opus-only] | 54.1 OfficeQA Pro (flagship) | OPEN — blinded SM rating (1–5) on the 15–30 held-out examples is the only valid test; no public benchmark covers PMI reporting |
| 5 | **Calibration (missing data → abstain, not invent)** | Claude abstains on ~64% of unknown-answer questions (attempt rate ~36%, measured on Opus 4.7/4.8) [assumption: family behavior carries to Sonnet 5] | Attempts ~86% of unknown-answer questions, mostly confidently wrong | Claude — directly relevant: absent owners/dates/status must surface as "unknown" in reports behind the SM gate |
| 6 | **Latency (interactive UI, target <15 s/report)** | Anthropic's fast tier; short calls | ~2× faster than Opus-class on agentic benchmarks; flex/batch modes are async (not UI-suitable) | OPEN — measure on harness. [Assumption: both <10 s for our ≤20K-token calls; not a differentiator] |
| 7 | **Governance / hosting** | Anthropic on project's governance-track shortlist; available via AWS Bedrock / GCP Vertex [EU-region availability of Sonnet 5 specifically: not verified] | Prototype-only clearance per prior research; no Deloitte alliance; Azure OpenAI EU hosting exists | Sonnet 5 for anything beyond prototype; tie for the current MVP |
| 8 | **Engineering fit** | `langchain-anthropic` first-class in LangGraph; swap = one client class in `app/agent/llm.py` [~1 h effort incl. tests] | Already implemented (spec's choice); zero switching cost | GPT-5.5 today; delta trivial by design (env-switched provider layer) |

**Read of the scorecard:** decided-by-evidence parameters lean Sonnet 5 (1, 5, 7);
GPT-5.5 wins 8 trivially; 2, 3, 4, 6 are genuinely open and are exactly what the
Stage 1–4 harness measures — run the A/B there before committing. If costs must
shrink or a production path opens, Sonnet 5 is the default; if the team wants
zero-touch continuity with the spec, GPT-5.5 stands.

## Sources

- OpenAI pricing — https://developers.openai.com/api/docs/pricing ; https://www.morphllm.com/openai-api-pricing ; https://devtk.ai/en/blog/openai-api-pricing-guide-2026/
- Anthropic pricing — https://platform.claude.com/docs/en/about-claude/pricing ; https://www.cloudzero.com/blog/claude-api-pricing/ ; https://evolink.ai/blog/claude-api-pricing-guide-2026
- Benchmarks — https://codingfleet.com/blog/claude-opus-4-8-vs-gpt-5-5-comparison/ ; https://www.datacamp.com/blog/claude-opus-4-8-vs-gpt-5-5 ; https://benchlm.ai/compare/claude-opus-4-8-vs-gpt-5-5 ; https://www.requesty.ai/blog/gpt-5-5-vs-claude-opus-4-8-which-model-wins-for-agents-in-2026
- Hallucination/calibration — https://www.digitalapplied.com/blog/ai-model-hallucination-rate-benchmarks-2026-study ; https://www.cometapi.com/gpt-5-5-vs-claude-opus-4-7-which-ai-to-use-when-hallucination-matters-2026-benchmark-data/ ; https://www.mindstudio.ai/blog/gpt-55-vs-claude-opus-46-hallucination-medical-legal-financial
- Artificial Analysis (Opus 4.8) — https://artificialanalysis.ai/articles/claude-opus-4-8-analysis-and-benchmarks
