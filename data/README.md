# Data

## ectsum/ — ECTSum dataset

Mukherjee et al. (2022), *ECTSum: A New Benchmark Dataset For Bullet Point
Summarization of Long Earnings Call Transcripts*, EMNLP 2022, arXiv:2210.12467,
GPL-3.0.

| Split | Pairs | Layout |
|---|---|---|
| train | 1,681 | `train/ects/*.txt` (transcripts), `train/gt_summaries/*.txt` |
| val | 249 | `val/ects/`, `val/gt_summaries/` |
| test | 495 | `test/ects/`, `test/gt_summaries/` |

Matches the paper's 7:1:2 split exactly.

**Purpose here:** evaluation/fine-tuning candidate for the *report-generation*
step (structured status data in → audience-appropriate bullet summary out).
Not wired into the runtime pipeline.

**Known caveat (carried over from prior project research):** a measured
310-ticker overlap exists between train and test companies — evaluate with
ticker-disjoint subsets if using it for benchmarking.

**Gaps this dataset does NOT cover** (per `UC2_V2_SingleAgent_Definition.md` §5):
multi-format structured extraction (steps 3–4) and cross-source conflict
resolution (steps 5–6). The latter is tested with synthetic data
(`scripts/make_sample_data.py`, tests) pending a team decision on whether a
proxy corpus is worth hunting for.

## qmsum/ — QMSum dataset

Zhong et al. (2021), *QMSum: A New Benchmark for Query-based Multi-domain Meeting
Summarization*, NAACL 2021, arXiv:2104.05938, MIT license.
Source: https://github.com/Yale-LILY/QMSum.git

| Split | Meetings | General-query pairs | Specific-query pairs | Total |
|---|---|---|---|---|
| train | 162 | 162 | 1,095 | 1,257 |
| val | 35 | 35 | 237 | 272 |
| test | 35 | 37 | 244 | 281 |

Layout: `ALL/jsonl/{train,val,test}.jsonl` is the official combined split (use this
as-is); `ALL/{train,val,test}/*.json` is the same data as one file per meeting.
`Academic/`, `Committee/`, `Product/` re-group the same 232 meetings by domain. Each
meeting record carries `meeting_transcripts` (speaker-turn dialogue), a
`general_query_list` (one whole-meeting summary) and a `specific_query_list`
(topic-scoped summaries) — see `qmsum/README.md` for the full JSON schema.

**Purpose here:** the two-tier general/specific query structure maps naturally onto
this agent's Executive-digest vs. Workstream-detail report types. Not wired into the
runtime pipeline.

**Known caveat:** source domain is academic/product-design/committee meetings, not
PMI/M&A — vocabulary drift is the main transfer risk when using this as a proxy for
PMI-domain report generation.

## samples/ — generated sample inputs

Created by `python scripts/make_sample_data.py`. Contains a deliberate
cross-source conflict (Excel: progress 82%, PowerPoint: 75%) to demonstrate
consistency checking.
