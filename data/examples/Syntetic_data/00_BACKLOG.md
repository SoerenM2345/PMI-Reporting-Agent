# Corpus backlog

Open items, ordered by how much each one blocks a research result rather than by effort.
Parked here so the list survives between sessions.

## 1. Two agent repos have diverged, and the image extractor landed in the wrong one
`~/Downloads/Projects/PMI/PMI-Reporting-Agent` is the older tree. `GIT/PMI-Reporting_Agent`
is the current, spec-driven one: it has a `csv.py` extractor, the QMSum / ECTSum / AMI
dataset-augmentation plan in `MASTER.md`, and **already contains its own
`app/extractors/image.py`** written against spec §5.6 / §21.14 / §7, with a more careful
confidence model than the one added earlier. That earlier extractor is therefore redundant
work sitting in a dead tree. **Decide which tree is canonical and retire the other before
anything else lands in both.**

## 2. Weeks 1 and 2 do not exist
The corpus is the W3 vintage plus an aged backdrop, so the agent can be tested on extraction
and on conflict resolution, but not on **week-over-week deltas** — which is what H2 reporting
actually claims. Roll `_generators/case.py` back two weeks and re-run; the generators already
support it.

## 3. No machine-readable ground-truth key
The six planted conflicts and every extractable record can only be checked by eye. `case.py`
holds everything needed; it needs a JSON export so extraction recall and conflict resolution
can be **scored** rather than inspected. (The flawed corpus now has a key —
`../Syntetic_data_with_errors/00_ERROR_KEY.xlsx` — but the clean corpus still does not.)

## 4. No expected-output reference
The corpus tests what goes in, not what should come out. There is no reference deliverable
saying "given these 21 files, this is the correct SteerCo deck", so report quality cannot be
measured at all yet. Together with item 3 this is the highest-value pair: the
transcript / minutes pair is the natural first scored task and there is currently nothing to
score it against.

## 5. No adversarial or negative documents
Every file is well-formed and on-topic. Missing:
- an off-topic file, to test whether the agent invents PMI structure where there is none
- a scan-only, image-based PDF, to exercise the OCR path
- a document in a language neither extractor configuration expects

The flawed corpus covers corruption (E-01) but not these.

## 6. The two corpora use different workstream cuts
"Project Atlas" (empty masters, `Master file data/`) has five workstreams; this one has seven,
matching the seven functional areas the advisory case study names. Fine if deliberate,
confusing if not.

## 7. `.msg` / `.eml` and `.mpp` remain absent
Real PMI formats. Note as a limitation in the paper, or add.

## 8. Tesseract German language pack
`tesseract-ocr-deu` is required for the two German images. Without it stage 1 silently falls
back to English-only OCR, which is a quiet failure rather than a loud one.

## 9. Stale LibreOffice lock files
`.~lock.*` files sit in `Master file data/` and could not be deleted from the sandbox. Remove
by hand.

---

## Done

- 21-document clean corpus, single fact base, 130-check audit at 0 failures
- Session 01 transcript, alignment with the signed minutes enforced by the audit
- Flawed copy with 10 injected errors and an error key workbook
  (`../Syntetic_data_with_errors/`)
