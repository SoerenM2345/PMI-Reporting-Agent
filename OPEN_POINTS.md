# Open Points — Rolling List

Living document mirroring the rolling list maintained in chat. Update on every
working session. Status: 2026-07-09.

## Open

| # | Point | Owner / next step |
|---|-------|-------------------|
| 1 | **Git push** — commit(s) exist locally only; sandbox has no GitHub credentials | Sören: `cd Downloads/Projects/PMI/PMI-Reporting-Agent && git push -u origin main` |
| 2 | **OpenAI vs Claude key** — mock mode active; provider decision pending | Team; see `docs/LLM_Provider_Comparison.md` |
| 3 | **Transcript ingestion in V2 scope?** — in H2 scope per Interview 7, absent from slide 5 input list; determines QMSum/AMI relevance | Team decision (UC2_V2 §7) |
| 4 | **Training data for conflict-resolution skill** — synthetic vs proxy (SEC EDGAR) vs hybrid | Team; see `docs/TrainingData_Decision.md` + slide |
| 5 | **ECTSum ticker overlap** — accept 310-ticker train/test overlap or re-split ticker-disjoint | Team; affects eval validity |
| 6 | **AMI corpus download** — blocked from sandbox; manual download needed if transcript scope confirmed | Sören (links in Google Doc "H2 Deep Dive" §3) |
| 7 | **Senior Manager review gate** — stated guardrail, not an enforced workflow step; candidate step 8 | Engineering, after team confirms design |
| 8 | **Repo size** — data/ectsum ≈ 56 MB; fine for GitHub, consider LFS if data grows | Watch |

## Decided (log)

| Date | Decision |
|------|----------|
| 2026-07-09 | Frontend: plain HTML/JS served by FastAPI (over React) — fastest to test instance |
| 2026-07-09 | LLM: mock mode first; OpenAI activates via `OPENAI_API_KEY` env switch |
| 2026-07-09 | ECTSum checked into repo under `data/ectsum/` (1681/249/495 verified) |
| 2026-07-09 | Separate repo for V2 (per UC2_V2 §8), cloned from SoerenM2345/PMI-Reporting-Agent |
| 2026-07-09 | Conflict resolution implements both spec options: source priority (default) + ask-user mode |
