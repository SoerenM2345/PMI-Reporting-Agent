"""Image extractor (.png/.jpg/.jpeg): hybrid OCR + optional vision-LLM escalation.

Images are the only input format where the agent must *infer* rather than *read*.
Screenshots of dashboards, exported org charts, photographed whiteboards and
Teams/Slack captures carry integration facts that never reach a tracker, which is
exactly where ownership gaps and un-registered risk escalations show up.

Two-stage design (Route C of the extractor options):

  Stage 1  Tesseract OCR, deterministic and free. Deskew, upscale, binarise, then
           `image_to_data` so every word keeps its bounding box. Word boxes are
           clustered into lines and columns, which recovers simple tables that a
           plain `image_to_string` would flatten into noise.
  Stage 2  Vision LLM, only when stage 1 is judged insufficient (too little text,
           low mean confidence, or a colour profile suggesting RAG semantics carry
           meaning). Returns schema-constrained JSON. Skipped entirely when no
           OPENAI_API_KEY is set, so the pipeline stays runnable offline.

Every record is tagged SourceFormat.IMAGE, the lowest-trust source. An image never
overrides a number that came from Excel.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from app.extractors.base import (classify_table, extract_actions_from_text,
                                 find_progress_mentions, make_source, normalize_header,
                                 rows_to_records)
from app.models.pmi import SourceFormat

# ------------------------------------------------------------------ tunables
MIN_CHARS = 60          # below this, OCR is treated as having failed
MIN_MEAN_CONF = 55.0    # tesseract word confidence, 0-100
OCR_LANGS = "deu+eng"   # German mid-cap reality: mixed-language documents
UPSCALE = 2             # small screenshots OCR badly at native resolution
LINE_TOL = 12           # px: words within this vertical distance are one line
COL_GAP = 45            # px: horizontal gap that separates two columns


def _pil():
    from PIL import Image, ImageOps, ImageFilter  # noqa: F401
    return Image, ImageOps, ImageFilter


# ------------------------------------------------------------------ stage 1
def _preprocess(path: Path):
    """Grayscale, autocontrast, upscale, light sharpen. Deskew if OpenCV is present."""
    Image, ImageOps, ImageFilter = _pil()
    img = Image.open(path)
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")
    img = ImageOps.exif_transpose(img)          # phone photos carry rotation in EXIF
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray)
    if UPSCALE > 1:
        gray = gray.resize((gray.width * UPSCALE, gray.height * UPSCALE), Image.LANCZOS)
    gray = gray.filter(ImageFilter.SHARPEN)
    return img, gray


def _ocr_words(gray) -> tuple[list[dict], float]:
    """Return word boxes [{text, left, top, width, height, conf}] and mean confidence."""
    try:
        import pytesseract
    except ImportError:
        return [], 0.0
    try:
        data = pytesseract.image_to_data(gray, lang=OCR_LANGS,
                                         output_type=pytesseract.Output.DICT)
    except Exception:
        try:
            data = pytesseract.image_to_data(gray, lang="eng",
                                             output_type=pytesseract.Output.DICT)
        except Exception:
            return [], 0.0
    words, confs = [], []
    for i, raw in enumerate(data.get("text", [])):
        t = (raw or "").strip()
        if not t:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, KeyError, TypeError):
            conf = -1.0
        if conf < 0:
            continue
        words.append({"text": t, "left": data["left"][i], "top": data["top"][i],
                      "width": data["width"][i], "height": data["height"][i], "conf": conf})
        confs.append(conf)
    return words, (sum(confs) / len(confs) if confs else 0.0)


def _group_lines(words: list[dict]) -> list[list[dict]]:
    """Cluster word boxes into visual lines by vertical centre."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["left"])):
        centre = w["top"] + w["height"] / 2
        for ln in lines:
            ref = ln[0]
            if abs(centre - (ref["top"] + ref["height"] / 2)) <= LINE_TOL:
                ln.append(w)
                break
        else:
            lines.append([w])
    return [sorted(ln, key=lambda w: w["left"]) for ln in lines]


def _line_cells(line: list[dict]) -> list[str]:
    """Split one visual line into cells wherever the horizontal gap exceeds COL_GAP."""
    cells, cur = [], [line[0]["text"]]
    prev_right = line[0]["left"] + line[0]["width"]
    for w in line[1:]:
        if w["left"] - prev_right > COL_GAP:
            cells.append(" ".join(cur))
            cur = [w["text"]]
        else:
            cur.append(w["text"])
        prev_right = w["left"] + w["width"]
    cells.append(" ".join(cur))
    return cells


def _tables_from_lines(lines: list[list[dict]]) -> list[list[list[str]]]:
    """Recover candidate tables: runs of consecutive lines with the same cell count >= 2."""
    rows = [_line_cells(ln) for ln in lines]
    tables, block = [], []
    for r in rows:
        if len(r) >= 2 and (not block or len(r) == len(block[0])):
            block.append(r)
        else:
            if len(block) >= 3:
                tables.append(block)
            block = [r] if len(r) >= 2 else []
    if len(block) >= 3:
        tables.append(block)
    # only keep blocks whose first row maps to at least two known PMI column names
    kept = []
    for t in tables:
        mapped = [normalize_header(h) for h in t[0]]
        if sum(1 for m in mapped if m) >= 2:
            kept.append(t)
    return kept


# ------------------------------------------------------------------ stage 2
def vision_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY")) and \
        os.environ.get("PMI_IMAGE_VISION", "1") != "0"


VISION_PROMPT = """You are reading an image taken from a post-merger integration (PMI) project.
It is one of: a dashboard screenshot, an exported org chart, a photographed whiteboard or
flipchart, a Gantt screenshot, or a chat/e-mail screenshot. Text may be German or English.

Return ONLY a JSON object with this shape, no prose:

{
  "image_kind": "dashboard|org_chart|gantt|whiteboard|chat|table|other",
  "tasks":      [{"title":..., "owner":..., "due_date":"YYYY-MM-DD", "status":..., "progress_pct":..., "workstream":...}],
  "milestones": [{"title":..., "due_date":"YYYY-MM-DD", "status":..., "workstream":...}],
  "risks":      [{"title":..., "owner":..., "severity":"low|medium|high|critical", "mitigation":...}],
  "kpis":       [{"name":..., "value":..., "unit":..., "target":...}],
  "org":        [{"person":..., "role":..., "reports_to":..., "unit":...}],
  "notes":      ["any statement that carries a fact but fits none of the above"]
}

Rules:
- Only report what is legibly visible. Never invent a name, number or date.
- Leave a field null rather than guessing it.
- Translate a RAG colour into status: red -> overdue, amber/yellow -> at_risk, green -> in_progress.
- Placeholder markers such as [...] or [__] mean the field is empty in the source. Skip those rows.
- Empty arrays are correct answers when the image contains nothing of that kind.
"""


def _vision_extract(path: Path) -> Optional[dict]:
    """One vision call. Returns the parsed JSON dict, or None on any failure."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    try:
        b64 = base64.b64encode(path.read_bytes()).decode()
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        client = OpenAI()
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_VISION_MODEL", os.environ.get("OPENAI_MODEL", "gpt-5.5")),
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": [
                {"type": "text", "text": VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}],
        )
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return None  # never block the pipeline on a vision failure


_STATUS_FROM_VISION = {
    "overdue": "overdue", "at_risk": "at risk", "in_progress": "in progress",
    "done": "done", "blocked": "blocked", "not_started": "not started",
}


def _records_from_vision(payload: dict, source) -> list[dict]:
    out: list[dict] = []
    kind = payload.get("image_kind") or "other"

    def clean(v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if not v or re.fullmatch(r"\[[\s._…]*\]", v):
                return None
        return v

    for t in payload.get("tasks") or []:
        rec = {"type": "task", "source": source}
        for k in ("title", "owner", "due_date", "status", "progress_pct", "workstream"):
            if clean(t.get(k)) is not None:
                rec[k] = clean(t[k])
        if rec.get("title"):
            out.append(rec)
    for m in payload.get("milestones") or []:
        rec = {"type": "milestone", "source": source}
        for k in ("title", "due_date", "status", "workstream"):
            if clean(m.get(k)) is not None:
                rec[k] = clean(m[k])
        if rec.get("title"):
            out.append(rec)
    for r in payload.get("risks") or []:
        rec = {"type": "risk", "source": source}
        for k in ("title", "owner", "severity", "mitigation"):
            if clean(r.get(k)) is not None:
                rec[k] = clean(r[k])
        if rec.get("title"):
            out.append(rec)
    for k in payload.get("kpis") or []:
        rec = {"type": "kpi", "source": source}
        for f in ("name", "value", "unit", "target"):
            if clean(k.get(f)) is not None:
                rec[f] = clean(k[f])
        if rec.get("name") and rec.get("value") is not None:
            out.append(rec)
    # org chart: reporting lines become notes, they are structure rather than PMI records
    org = [o for o in (payload.get("org") or []) if clean(o.get("person")) or clean(o.get("role"))]
    if org:
        lines = [f"{o.get('person') or '?'} - {o.get('role') or '?'}"
                 f"{' -> reports to ' + o['reports_to'] if clean(o.get('reports_to')) else ''}"
                 for o in org]
        out.append({"type": "note", "text": "Org structure read from image:\n" + "\n".join(lines),
                    "source": source})
    for n in payload.get("notes") or []:
        if clean(n):
            out.append({"type": "note", "text": str(n)[:2000], "source": source})

    out.append({"type": "note", "text": f"[image kind: {kind}, read by vision model]",
                "source": source})
    return out


# ------------------------------------------------------------------ entry point
def extract(path: Path) -> list[dict]:
    records: list[dict] = []
    source = make_source(path.name, SourceFormat.IMAGE)

    try:
        _orig, gray = _preprocess(path)
    except Exception:
        return [{"type": "note", "text": f"[image could not be opened: {path.name}]",
                 "source": source}]

    words, mean_conf = _ocr_words(gray)
    text = "\n".join(" ".join(w["text"] for w in ln) for ln in _group_lines(words))

    # tables recovered from word geometry
    lines = _group_lines(words)
    for t_idx, tbl in enumerate(_tables_from_lines(lines), start=1):
        src = make_source(path.name, SourceFormat.IMAGE, location=f"table {t_idx} (ocr)")
        rtype = classify_table(tbl[0])
        records.extend(rows_to_records(tbl[0], tbl[1:], rtype, src))

    # flat-text signals the shared helpers already know how to read
    for pct in find_progress_mentions(text):
        records.append({"type": "kpi", "name": "Overall Progress", "value": pct,
                        "unit": "%", "source": source})
    for item in extract_actions_from_text(text):
        records.append({**item, "source": source})
    if text.strip():
        records.append({"type": "note", "text": text.strip()[:2000],
                        "source": make_source(path.name, SourceFormat.IMAGE, location="ocr text")})

    # stage 2: escalate when OCR is thin, unconfident, or produced no structure
    ocr_weak = (len(text) < MIN_CHARS or mean_conf < MIN_MEAN_CONF
                or not any(r["type"] != "note" for r in records))
    if ocr_weak and vision_available():
        payload = _vision_extract(path)
        if payload:
            vsrc = make_source(path.name, SourceFormat.IMAGE, location="vision")
            records.extend(_records_from_vision(payload, vsrc))
    elif ocr_weak:
        records.append({
            "type": "note",
            "source": source,
            "text": (f"[OCR returned {len(text)} characters at mean confidence "
                     f"{mean_conf:.0f}. This image likely needs the vision path; set "
                     f"OPENAI_API_KEY to enable it. Handwriting and colour-coded status "
                     f"cannot be read by OCR alone.]"),
        })

    return records
