# Evaluation Plan

How to tell whether this system is any good — and, more importantly, how to tell whether
it is *dangerous*.

## The failure mode that matters

Most reporting tools are evaluated on what they produce. This one has to be evaluated on
what it produces **wrongly and confidently**, because that is the failure that ends up in
a boardroom.

So the metrics below are split. The first group measures capability. The second group
measures honesty, and it is the one that decides whether the system is fit to use.

## 1 · Capability metrics

Run against the §19 sample project (11 files, planted inconsistencies).

| Metric | How | Target |
|---|---|---|
| **Extraction recall** | Entities extracted ÷ entities present in the sample files | ≥ 90% for tabular sources |
| **Entity-type coverage** | All 10 record types populate from the sample set | 100% (tested: `test_every_entity_type_survives_extraction`) |
| **Conflict detection recall** | Planted conflicts found ÷ planted (§19 lists them) | 100% for tabular conflicts |
| **Conflict precision** | True conflicts ÷ reported conflicts | ≥ 95% — a false conflict wastes a consultant's time and trains them to ignore the panel |
| **Check coverage** | Registered checks vs §8's list | 39 implemented (32 registered + 7 derived) |
| **Output validity** | Every generated file re-opens with python-pptx / openpyxl / PIL | 100% (enforced at runtime by `verify_outputs`) |

## 2 · Honesty metrics — the ones that matter

| Metric | How | Target |
|---|---|---|
| **Fabrication rate** | Figures in the output that appear in **no** source file | **0.** Any non-zero value is a stop-ship defect. |
| **Silent-loss rate** | Files/rows that contributed nothing and were **not** reported as such | **0.** A hole in the report the user does not know about is the worst outcome. |
| **Confidence calibration** | For image-sourced findings: accuracy vs stated confidence | Findings at 0.4 should be wrong ~60% of the time. Findings at 0.9 should be wrong ~10% of the time. A model that is confidently wrong is worse than one that is uncertainly wrong. |
| **Critical-conflict escalation** | Conflicts on §9's critical topics that reached the user | **100%.** An auto-resolved critical conflict is a silent decision the system was not entitled to make. |
| **Caveat propagation** | Fallbacks / failures that reached the data-quality report | 100% |

### Testing fabrication

The direct test: take the generated deck, extract every number from it, and check each
one against the source files.

```bash
python scripts/demo_acceptance.py   # writes example_outputs/
```

Then, for each figure on a slide, ask: *which file, which cell?* The deck's source notes
and the conflict report should answer that for every one. Any figure they cannot account
for is a fabrication, and a defect.

### Testing calibration (requires a key)

```bash
ANTHROPIC_API_KEY=... python scripts/record_vision_fixture.py
```

Read the diff against the committed fixture. Ask:

- Did it find the GDPR risk (which exists **only** in the image)?
- Did it place it correctly at probability 4 / impact 5, from cell position alone?
- Did it report the two ambiguous amber/red cells as unreadable, or did it guess?
- Is `model_confidence` honest — around 0.85 for the crisp legend, lower for the matrix
  cells it inferred from colour?

A model that returns 0.95 on everything has failed calibration even if every answer is
right, because the confidence score is then carrying no information — and the whole
low-confidence review panel becomes decoration.

## 3 · The acceptance scenario (§20)

Automated, runs in CI with no API key:

```bash
pytest tests/test_acceptance.py -v
```

It asserts the full §20 sequence, including the two things that are easy to get wrong:

- Generation is **refused (409)** while the 82-vs-75 conflict is open. A system that
  produces a deck here has failed, however good the deck is.
- The deck contains the risk that exists **only in the image**, marked low-confidence.

## 4 · Human evaluation (UAT)

The metrics above cannot tell you whether the deck is any good. See
[uat_questionnaire.md](uat_questionnaire.md).

The question to actually listen to is: *"Would you have sent this to a Steering Committee
without changing it?"* — and then, *"What did you change, and why?"* The edits are the
data.

## 5 · What we are not measuring, and should

Honest gaps in this plan:

- **No ground-truth PMI corpus.** The sample project is synthetic and we wrote the
  inconsistencies into it, so detection recall against it is close to a tautology. A real
  evaluation needs anonymised files from a real integration, with a human-labelled list
  of what is actually in them.
- **No inter-rater agreement on severity.** We assert that a Day-1 readiness conflict is
  critical because §9 says so. Whether *PMI professionals* agree is untested and worth
  asking in the UAT.
- **No cost/latency benchmarks.** Vision calls on a 40-screenshot session are the obvious
  scaling risk and are not yet measured.
- **`data/ectsum/`** — a summarization dataset is checked into the repo. It is not wired
  into anything. It could be used to evaluate the executive-summary step against
  reference summaries, but that work has not been done, and pretending otherwise would be
  the same dishonesty this system is built to avoid.
