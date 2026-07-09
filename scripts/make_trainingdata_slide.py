"""Build the one-slide training-data decision summary (Deloitte style).

Output: ../../TrainingData_Decision_Slide.pptx (shared PMI folder).
Content source: docs/TrainingData_Decision.md
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

GREEN = RGBColor(0x2E, 0x7D, 0x32)
GREEN_DARK = RGBColor(0x1B, 0x5E, 0x20)
TINT = RGBColor(0xE8, 0xF5, 0xE9)
DARK = RGBColor(0x1A, 0x1A, 0x1A)
GREY = RGBColor(0x69, 0x69, 0x69)
LIGHT = RGBColor(0xF4, 0xF4, 0xF4)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
RED = RGBColor(0xB7, 0x1C, 0x1C)
FONT = "Verdana"

W, H = Inches(13.333), Inches(7.5)
prs = Presentation()
prs.slide_width, prs.slide_height = W, H
slide = prs.slides.add_slide(prs.slide_layouts[6])
shapes = slide.shapes


def textbox(x, y, w, h, lines, default_size=9, margin=0.03):
    """lines: list of (text, size, bold, color, space_after) tuples or strings."""
    box = shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(margin)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    for i, spec in enumerate(lines):
        if isinstance(spec, str):
            spec = (spec, default_size, False, DARK, 2)
        text, size, bold, color, space = spec
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = text
        r.font.name, r.font.size, r.font.bold = FONT, Pt(size), bold
        r.font.color.rgb = color
        p.space_after = Pt(space)
    return box


def card(x, y, w, h, fill=WHITE, line=RGBColor(0xD6, 0xD6, 0xD6)):
    from pptx.enum.shapes import MSO_SHAPE
    shp = shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    shp.line.color.rgb = line
    shp.line.width = Pt(0.75)
    shp.shadow.inherit = False
    return shp


def header_bar(x, y, w, title, h=0.28):
    bar = card(x, y, w, h, fill=GREEN, line=GREEN)
    tf = bar.text_frame
    tf.margin_left, tf.margin_top, tf.margin_bottom = Inches(0.06), Inches(0.01), Inches(0.01)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = title
    r.font.name, r.font.size, r.font.bold, r.font.color.rgb = FONT, Pt(11), True, WHITE


# ---------------------------------------------------------------- header + action title
textbox(0.35, 0.12, 9.0, 0.25,
        [("H2 Automated Reporting · Training Data Concept & Decision", 9, False, GREY, 0)])
textbox(10.6, 0.10, 2.4, 0.3, [("Deloitte. | TUM", 11, True, DARK, 0)])
tb = textbox(0.35, 0.38, 12.63, 0.85,
        [("Proxy corpora cover report generation only — closing the two remaining data "
          "gaps requires a synthetic vs. SEC EDGAR decision, validated on a held-out PMI test set",
          17, True, DARK, 0)])

# ---------------------------------------------------------------- row 1: bottleneck strip
strip = [
    ("BOTTLENECK — UNCHANGED", "0 PMI-native reporting datasets exist (confirmed by search); every candidate is a proxy domain", True),
    ("VERIFIED PROXIES", "ECTSum 2,425 pairs in repo (1681/249/495); QMSum + AMI gated by open transcript-scope decision", False),
    ("GAP 1 — NOT COVERED", "Multi-format extraction (xlsx/pptx/docx/pdf/html → one PMI schema): no corpus teaches it", True),
    ("GAP 2 — NOT COVERED", "Cross-source conflicts (Excel 82% vs. PPT 75%): no corpus contains them by design", True),
]
sw = 3.10
for i, (label, body, is_red) in enumerate(strip):
    x = 0.35 + i * (sw + 0.075)
    card(x, 1.32, sw, 0.78, fill=LIGHT, line=LIGHT)
    textbox(x + 0.04, 1.36, sw - 0.08, 0.7, [
        (label, 8.5, True, RED if is_red else GREEN_DARK, 2),
        (body, 8.5, False, DARK, 0),
    ])

# ---------------------------------------------------------------- row 2: three columns
row_y, row_h = 2.24, 2.42
# Col 1 — decision questions
header_bar(0.35, row_y, 3.35, "DECISION QUESTIONS")
card(0.35, row_y + 0.28, 3.35, row_h - 0.28)
textbox(0.42, row_y + 0.35, 3.21, row_h - 0.42, [
    ("D1  Transcript ingestion in V2 scope? Gates QMSum + AMI entirely", 8.5, False, DARK, 4),
    ("D2  Fill gaps 1–2: synthetic, SEC EDGAR proxy, or hybrid?", 8.5, False, DARK, 4),
    ("D3  Run D2 through the full 8-step review protocol (Xiao & Watson 2017)?", 8.5, False, DARK, 4),
    ("D4  ECTSum: accept 310-ticker train/test overlap or re-split ticker-disjoint?", 8.5, False, DARK, 4),
    ("D5  License gate: ECTSum GPL-3.0 — internal use OK; re-check before any redistribution", 8.5, False, DARK, 0),
])

# Col 2 — synthetic
cx, cw = 3.83, 4.60
header_bar(cx, row_y, cw, "OPTION A — SYNTHETIC DATA")
card(cx, row_y + 0.28, cw, row_h - 0.28)
textbox(cx + 0.07, row_y + 0.35, cw - 0.14, row_h - 0.42, [
    ("Context: gap 2 is narrow and mechanical, on a schema we own; seeded-conflict generator + tests already exist in the repo", 8, False, GREY, 4),
    ("+  Exact fit to PMI schema and priority rule; gold labels by construction", 8.5, False, GREEN_DARK, 2),
    ("+  Only practical source of guaranteed conflicts; unlimited volume, no license risk", 8.5, False, GREEN_DARK, 2),
    ("+  Near-zero cost — pipeline already built", 8.5, False, GREEN_DARK, 4),
    ("–  Circular: tests what we generated; weak external validity as thesis evidence", 8.5, False, RED, 2),
    ("–  LLM-generated data risks bias and model collapse if it replaces real data (Long et al. 2024, ACL Findings)", 8.5, False, RED, 2),
    ("–  Lacks real-world formatting noise", 8.5, False, RED, 0),
])

# Col 3 — proxy / EDGAR
px, pw = 8.56, 4.42
header_bar(px, row_y, pw, "OPTION B — PROXY: SEC EDGAR")
card(px, row_y + 0.28, pw, row_h - 0.28)
textbox(px + 0.07, row_y + 0.35, pw - 0.14, row_h - 0.42, [
    ("Context: free SEC filings APIs (no key, ~10 req/s); same fact appears per company-quarter in XBRL tags, 10-K/10-Q HTML, 8-K Ex-99.1 press releases, PDFs", 8, False, GREY, 4),
    ("+  XBRL = free ground-truth labels for gap-1 extraction from real documents", 8.5, False, GREEN_DARK, 2),
    ("+  Real formatting noise; auditable and citable; M&A-adjacent forms (8-K, S-4, DEFM14A)", 8.5, False, GREEN_DARK, 4),
    ("–  Register mismatch: regulated filings ≠ internal PMI status reports", 8.5, False, RED, 2),
    ("–  True conflicts rare — gap 2 still needs synthetic injection (exception: non-GAAP vs. GAAP deltas)", 8.5, False, RED, 2),
    ("–  Prep effort (alignment, parsing); US-listed firms only", 8.5, False, RED, 0),
])

# ---------------------------------------------------------------- row 3: recommendation
card(0.35, 4.78, 12.63, 0.46, fill=TINT, line=GREEN)
textbox(0.45, 4.85, 12.45, 0.36, [
    ("Recommendation — hybrid per sub-skill:  ECTSum (+QMSum if D1 = yes) for generation  ·  "
     "EDGAR XBRL↔HTML pairs for extraction (gap 1)  ·  synthetic conflict injection (gap 2)  ·  "
     "15–30 real PMI examples always held out", 9.5, True, GREEN_DARK, 0),
])

# ---------------------------------------------------------------- row 4: evaluation process
textbox(0.35, 5.38, 8.0, 0.28, [("EVALUATION AFTER THE DECISION — does the choice actually work?", 11, True, DARK, 0)])
steps = [
    ("0  FREEZE", "Hold out 15–30 real PMI examples + ticker-disjoint ECTSum test before any training"),
    ("1  EXTRACTION", "Field-level F1 per entity type; numerical accuracy ≥ 95% (hard floor)"),
    ("2  CONFLICTS", "Detection recall on seeded conflicts; resolution accuracy vs. human gold; false-positive rate"),
    ("3  GENERATION", "ROUGE-1/2/L + BERTScore; numerical precision of bullets; blinded human rating (audience fit)"),
    ("4  GATE", "Transfer gap proxy → PMI ≤ 10–15% relative, else back to D2; in production: SM-correction rate"),
]
sw2, gap = 2.42, 0.13
for i, (label, body) in enumerate(steps):
    x = 0.35 + i * (sw2 + gap)
    last = i == len(steps) - 1
    card(x, 5.70, sw2, 1.18, fill=GREEN if last else LIGHT, line=GREEN if last else LIGHT)
    textbox(x + 0.05, 5.76, sw2 - 0.10, 1.06, [
        (label, 9, True, WHITE if last else GREEN_DARK, 2),
        (body, 8, False, WHITE if last else DARK, 0),
    ])
    if not last:
        a = textbox(x + sw2 - 0.02, 6.10, 0.2, 0.3, [("→", 12, True, GREY, 0)])

# ---------------------------------------------------------------- footer
textbox(0.35, 7.08, 12.63, 0.35, [
    ("Sources: Mukherjee et al. 2022 (EMNLP); Zhong et al. 2021 (NAACL); Carletta et al. 2005 (MLMI); "
     "Long et al. 2024 (ACL Findings); SEC.gov EDGAR developer resources; H2 Deep Dive doc (2026-07-08); "
     "UC2_V2_SingleAgent_Definition §5.   |   TUM Project Study x Deloitte 2026 · 09.07.2026", 7.5, False, GREY, 0),
])

out = Path(__file__).resolve().parents[2] / "TrainingData_Decision_Slide.pptx"
prs.save(str(out))
print(f"Saved {out}")
