# Prompt: Reconcile local `main` with `origin/main` (work live on `main`, keep both datasets)

*Copy-paste this whole file as the instruction to whichever agent (Claude Code, a Cowork
subagent, etc.) actually executes the reconciliation. It is self-contained — it does not
assume the executing agent has seen the conversation that produced it.*

## Decision this implements

Sören decided: (a) work live on `main` going forward — no long-lived feature branch — and
(b) merge the two diverged git histories together on `main`, keeping the two synthetic test
datasets (`Syntetic_data/`, `Syntetic_data_with_errors/`) that already live on `origin/main`.

## Why this is not a routine `git pull`

Repo: `PMI-Reporting-Agent`, remote `https://github.com/SoerenM2345/PMI-Reporting-Agent.git`.

- **The two histories share no common ancestor** (`git merge-base main origin/main` returns
  nothing). Local `main` and `origin/main` were built as separate root trees that were never
  based on each other. A plain `git merge` will refuse to run without
  `--allow-unrelated-histories`, and even then it will not be a clean fast-forward — do not
  attempt a bare `git merge origin/main` on top of history as-is.
- Local `main` (HEAD `0f9e6d5`) has 4 commits `origin/main` (HEAD `3b43bcc`) does not: a
  single-agent MVP plus two slide-generator commits. It also has **uncommitted work**:
  modified `MASTER.md`, `OPEN_POINTS.md`, `app/extractors/__init__.py`, `app/models/pmi.py`,
  `docs/TrainingData_Decision.md`, `requirements.txt`; untracked `app/extractors/image.py`,
  `docs/DataIngestion_CriticalReview.md`, `docs/IMPLEMENTATION_STATUS.md`,
  `docs/RAG_Flywheel_Engineering_Handoff.md`, `docs/TrainingData_UseCase_Fit_Analysis.md`,
  `static/review_mockup.html`.
- `origin/main` has 25 commits local doesn't: the full project/chat API, the session →
  upload → analyze → conflicts → generate → quality pipeline, the React frontend, **and**
  both synthetic corpora already merged in (commit `3b43bcc "Merge soeren: add Syntetic_data
  / Syntetic_data_with_errors case datasets"`).
- **Known content conflicts already identified** (do not blind-merge these — see §3):
  `app/models/pmi.py`, `app/extractors/__init__.py`, `app/extractors/image.py`,
  `requirements.txt`, `MASTER.md`.

## Non-negotiable safety rules

1. Never force-push. Never `git reset --hard` or `git clean` before everything unsaved is
   captured on a backup branch (step 1 below does this).
2. Do not delete the backup branch created in step 1, ever, without Sören explicitly saying so.
3. If a conflict can't be resolved with confidence from reading the code (§3 flags which ones
   these are), stop and ask rather than guessing — these are architecture decisions, not
   formatting differences.
4. Do not touch `Syntetic_data/` or `Syntetic_data_with_errors/` at all. They must come out of
   this reconciliation byte-identical to what's on `origin/main` today.
5. Before the final push, the app must actually boot and the test suite must pass. "It merged
   without conflict markers" is not the same as "it works."

## Step-by-step

### 1. Snapshot everything currently unsaved on a backup branch — do this first, before anything else

```bash
cd PMI-Reporting-Agent
git fetch origin
git switch -c backup/local-work-2026-08-04       # branches off current local main, keeps uncommitted changes
git add -A
git commit -m "Snapshot: local-only work before reconciling main with origin/main"
```

Confirm this worked (`git log -1`, `git status` clean) before proceeding. This branch is now
the undo point for everything local — nothing from here on can lose data as long as this
branch exists.

### 2. Fast-forward `main` to match `origin/main` exactly

```bash
git switch main
git reset --hard origin/main
```

`main` now has the full product build: project/chat API, the session/analyze/conflicts/
generate pipeline, the frontend, both corpora. The 4 old local commits and the uncommitted
changes are not lost — they're safe on `backup/local-work-2026-08-04` from step 1.

### 3. Port the valuable local-only work back onto the new `main` — file by file, with judgment

**3a. Pure additions — no conflict, just bring them over:**

```bash
git checkout backup/local-work-2026-08-04 -- \
  OPEN_POINTS.md \
  docs/TrainingData_Decision.md \
  docs/DataIngestion_CriticalReview.md \
  docs/IMPLEMENTATION_STATUS.md \
  docs/RAG_Flywheel_Engineering_Handoff.md \
  docs/TrainingData_UseCase_Fit_Analysis.md \
  static/review_mockup.html \
  scripts/make_llm_comparison_slide.py \
  scripts/make_trainingdata_slide.py
git add -A
git commit -m "Port local-only docs and slide scripts onto reconciled main"
```

**3b. Files both sides changed — read both versions in full before touching anything:**

- **`app/models/pmi.py`.** `origin/main`'s live pipeline imports from this module using the
  original flat schema. Local's uncommitted version is a refactor that splits the model into
  `entities.py` / `enums.py` / `source.py` / `quality.py`, with backward-compatible aliases at
  the bottom (`TaskItem`→`Task`, `SourceRef`→`SourceReference`, etc.) specifically so old
  imports keep working. Compare `git show backup/local-work-2026-08-04:app/models/pmi.py`
  against `main`'s current version. If adopting the refactor, you must also bring in the four
  new files it depends on (`entities.py`, `enums.py`, `source.py`, `quality.py` — check
  whether these exist in the backup branch's working tree, since the diff only showed
  `pmi.py`). After adopting, grep the whole codebase for every name imported from
  `app.models.pmi` and confirm each one still resolves — do not assume the aliases are
  complete.
- **`app/extractors/__init__.py`.** Local's version adds a `csv` extractor to the dispatch map
  and derives the extension table from each module's declared `suffixes` instead of a
  hand-written dict. Before adopting it, confirm `app/extractors/csv.py` actually exists (it
  wasn't in the diff you'll see, so it may only exist in local's working tree, or may not
  exist at all — if it doesn't exist, importing it will crash the app on startup).
- **`app/extractors/image.py`.** Two different implementations exist — local's uncommitted
  version (316 lines) and `origin/main`'s already-shipped version (300 lines, already wired to
  the `pytesseract` dependency `origin/main`'s `requirements.txt` declares). Diff them
  directly: `diff <(git show origin/main:app/extractors/image.py) <(git show
  backup/local-work-2026-08-04:app/extractors/image.py)`. Do not silently pick one — read what
  each does differently. Default recommendation if nothing else decides it: keep `origin/main`'s
  since it's the one already integrated with the pipeline and its declared dependency, and
  port any genuinely new capability from local's version in as a separate, documented follow-up
  commit rather than a wholesale swap.
- **`requirements.txt`.** Take the union of both files' packages (local adds
  `pydantic-settings`, `python-dotenv`, `anthropic`, `reportlab`, `lxml`, `numpy`; origin has
  `pytesseract`, `pytest`, `httpx` that local's working copy was missing). Check for version
  pin conflicts on any package listed in both.
- **`MASTER.md`.** Both sides edited this as a running narrative/status document. Read both in
  full and hand-merge the content into one coherent narrative — do not take either version
  wholesale, and do not mechanically concatenate them.

For each of these five files, commit separately with a message that says what you kept, what
you dropped, and why — so the decision is auditable later.

### 4. Verify before pushing

```bash
pytest -q
.venv/bin/uvicorn app.main:app --reload   # or however this project runs locally — confirm it boots with no import errors
```

Hit at minimum one endpoint from each pipeline to confirm the merge didn't break either
subsystem: one project-API call (`POST /api/projects`) and one session-pipeline call
(`POST /api/session`). Confirm `Syntetic_data/` and `Syntetic_data_with_errors/` still each
have their expected file counts, untouched.

### 5. Push

```bash
git push origin main
```

Because `main` was reset to exactly match `origin/main` in step 2 before anything new was
added on top, this should be a clean fast-forward — no force-push required. If git reports
it's *not* a fast-forward (meaning someone else pushed to `origin/main` in the meantime), stop,
re-fetch, and re-evaluate rather than forcing through it.

### 6. Leave the backup branch in place

`backup/local-work-2026-08-04` stays on the remote/local as the undo point. Do not delete it
without Sören's explicit go-ahead.

## Done-state checklist

- [ ] `backup/local-work-2026-08-04` exists and contains every uncommitted change from before
      this started
- [ ] `main` == `origin/main`'s prior tip, plus the ported local docs/scripts, plus the
      resolved versions of the five conflicting files
- [ ] Both corpora present and untouched
- [ ] `pytest` passes
- [ ] App boots; one call to each of the two API subsystems succeeds
- [ ] `git push origin main` succeeded as a fast-forward
- [ ] `PROJECT_MEMORY.md` updated with what was actually kept/dropped in the five-file merge
