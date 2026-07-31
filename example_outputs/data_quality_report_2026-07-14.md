# PMI Data-Quality Report

**Project:** Project Aurora  
**Generated:** 14-07-2026  
**Score:** 86 / 100

## Summary

- Data-quality score: 86/100 (29 items from 29 traceable source reference(s)).
- 1 cross-source conflict(s) were detected and resolved (0 by source priority, 1 by the user).
- 9 completeness issue(s) detected.
- 1 mathematical issue(s) detected.
- 1 temporal issue(s) detected.
- Gaps: 1 task(s) with no owner; 4 task(s) with no due date; 4 budget line(s) with no forecast.

## 11 validation issue(s)

### Mathematical (1)

- ⚪ LOW `MATH-004` Task 'Day-1 readiness checklist' is marked complete but has no completion date.

### Temporal (1)

- 🔴 CRITICAL `TIME-004` Milestone 'Day-100 review' is Day-1 critical but is planned for 20-08-2026, after Day 1 (15-06-2026).

### Completeness (9)

- 🟠 HIGH `COMP-003` Risk 'Key engineer attrition in target company' has a mitigation action but nobody is assigned to it.
- 🟠 HIGH `COMP-003` Risk 'ERP cutover slips past Q3' has a mitigation action but nobody is assigned to it.
- 🟠 HIGH `COMP-003` Risk 'Customer churn during rebranding' has a mitigation action but nobody is assigned to it.
- 🟡 MEDIUM `COMP-010` Workstream 'Finance' has no lead assigned.
- 🟡 MEDIUM `COMP-010` Workstream 'Human Resources' has no lead assigned.
- 🟡 MEDIUM `COMP-010` Workstream 'Information Technology' has no lead assigned.
- 🟡 MEDIUM `COMP-010` Workstream 'PMO' has no lead assigned.
- 🟡 MEDIUM `COMP-010` Workstream 'Real Estate' has no lead assigned.
- 🟡 MEDIUM `COMP-010` Workstream 'Sales' has no lead assigned.

## Processing caveats

Things that went differently than intended. Each one means the report is thinner than it looks.

- LLM unavailable for 'parse_request' (NotConfigured: ANTHROPIC_API_KEY is not set); used a deterministic fallback — output is template-based, not analysed.
- risk_dashboard.png: Could NOT interpret this image: no vision-capable model is configured, and no local OCR is available. Install a vision model (set ANTHROPIC_API_KEY) or local OCR (pip install -r requirements-ocr.txt). Any tasks, risks or figures in it are MISSING from this report.
- risk_dashboard.png: Could NOT interpret this image: no vision-capable model is configured, and no local OCR is available. Install a vision model (set ANTHROPIC_API_KEY) or local OCR (pip install -r requirements-ocr.txt). Any tasks, risks or figures in it are MISSING from this report.

---

*Generated outputs are a prototype and require Senior Manager review before distribution to stakeholders.*