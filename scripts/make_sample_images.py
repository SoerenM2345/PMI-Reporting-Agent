"""Generate the sample images required by spec §19.

Three files, each exercising a different branch of the §5.6 image pipeline:

* `risk_dashboard.png`  — a risk matrix + KPI tiles. Position and colour *are* the
  data, which is why the spec insists a vision model is needed rather than OCR.
  Carries a critical GDPR risk that appears in NO other sample file: that is what
  §20 step 13 means by "the presentation includes the new risk extracted from the
  image".
* `milestone_whiteboard.jpg` — a photographed whiteboard: handwriting-style text,
  slightly rotated, JPEG-compressed. Should come back with low confidence.
* `workstream_dashboard.jpeg` — a traffic-light status board with no text labels on
  the indicators, so the reader must interpret RAG colours (§5.6).

Deliberately inconsistent with the other samples (§19): the whiteboard shows the ERP
go-live on 30 September while the Excel masterplan says 15 September.

Run:  python scripts/make_sample_images.py
"""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
SAMPLES.mkdir(parents=True, exist_ok=True)

WHITE = (255, 255, 255)
INK = (26, 26, 26)
GREY = (117, 117, 117)
GREEN = (46, 125, 50)
AMBER = (249, 168, 37)
RED = (198, 40, 40)
PALE = (240, 240, 240)


def _font(size: int, bold: bool = False):
    for name in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


# --------------------------------------------------------------- risk dashboard
def make_risk_dashboard() -> Path:
    width, height = 960, 640
    img = Image.new("RGB", (width, height), WHITE)
    d = ImageDraw.Draw(img)

    d.text((32, 20), "Integration Risk Dashboard", font=_font(24, True), fill=INK)
    d.text((32, 52), "Project Aurora · week 12", font=_font(13), fill=GREY)

    # KPI tiles across the top
    tiles = [
        ("Open critical risks", "2", RED),
        ("Open issues", "7", AMBER),
        ("Risks closed this week", "3", GREEN),
    ]
    for i, (label, value, colour) in enumerate(tiles):
        x = 32 + i * 200
        d.rectangle([x, 88, x + 180, 178], fill=PALE)
        d.rectangle([x, 88, x + 6, 178], fill=colour)
        d.text((x + 18, 100), label, font=_font(11), fill=GREY)
        d.text((x + 18, 122), value, font=_font(34, True), fill=INK)

    # 5x5 risk matrix, below the tiles and to the right
    ox, oy, cell = 520, 230, 76
    d.text((ox, oy - 28), "Risk matrix", font=_font(14, True), fill=INK)
    d.text((ox - 92, oy + 2 * cell), "Impact ↑", font=_font(11), fill=GREY)

    for row in range(5):          # impact: 5 at the top
        for col in range(5):      # probability: 1 on the left
            impact, probability = 5 - row, col + 1
            score = impact * probability
            colour = RED if score >= 16 else AMBER if score >= 9 else GREEN
            faded = tuple(int(c + (255 - c) * 0.62) for c in colour)
            x, y = ox + col * cell, oy + row * cell
            d.rectangle([x, y, x + cell - 4, y + cell - 4], fill=faded)

    d.text((ox, oy + 5 * cell + 6), "Probability →", font=_font(11), fill=GREY)

    # The critical risk that exists ONLY in this image (§20 step 8).
    x, y = ox + 3 * cell, oy + 0 * cell        # probability 4, impact 5
    d.rectangle([x, y, x + cell - 4, y + cell - 4], fill=RED)
    d.text((x + 8, y + 10), "GDPR", font=_font(13, True), fill=WHITE)
    d.text((x + 8, y + 30), "reten-", font=_font(11), fill=WHITE)
    d.text((x + 8, y + 46), "tion", font=_font(11), fill=WHITE)

    x, y = ox + 2 * cell, oy + 1 * cell        # probability 3, impact 4
    d.rectangle([x, y, x + cell - 4, y + cell - 4], fill=AMBER)
    d.text((x + 8, y + 10), "ERP", font=_font(13, True), fill=INK)
    d.text((x + 8, y + 30), "cutover", font=_font(10), fill=INK)

    # Legend, bottom-left under the tiles
    d.text((32, 236), "Top risks this week", font=_font(14, True), fill=INK)
    legend = [
        ("GDPR retention breach on", "customer data migration", "Lisa Chen", RED),
        ("ERP cutover window conflicts", "with year-end close", "Jonas Weber", AMBER),
    ]
    for i, (line1, line2, owner, colour) in enumerate(legend):
        y = 272 + i * 74
        d.rectangle([32, y + 2, 46, y + 16], fill=colour)
        d.text((56, y), line1, font=_font(13), fill=INK)
        d.text((56, y + 20), line2, font=_font(13), fill=INK)
        d.text((56, y + 40), owner, font=_font(12), fill=GREY)

    out = SAMPLES / "risk_dashboard.png"
    img.save(out)
    return out


# ------------------------------------------------------------------- whiteboard
def make_whiteboard() -> Path:
    """A photo of a whiteboard: rotated, noisy, JPEG-compressed. Should score low."""
    width, height = 1100, 720
    img = Image.new("RGB", (width, height), (246, 246, 242))
    d = ImageDraw.Draw(img)

    d.text((60, 40), "Day 1 / Day 100 milestones", font=_font(30, True), fill=(20, 40, 90))
    d.line([60, 200, 1000, 200], fill=(60, 60, 60), width=3)

    milestones = [
        (120, "Legal close", "01-06"),
        (330, "Day 1", "15-06"),
        (560, "Payroll migr.", "31-07"),
        # Conflicts on purpose with the Excel masterplan's 15-09 (§19).
        (790, "ERP go-live", "30-09"),
        (960, "TSA exit", "31-12"),
    ]
    for x, label, when in milestones:
        d.ellipse([x - 9, 191, x + 9, 209], fill=(200, 40, 40))
        d.text((x - 40, 225), label, font=_font(19), fill=(30, 30, 30))
        d.text((x - 40, 250), when, font=_font(17), fill=(160, 40, 40))

    d.text((60, 330), "ERP go-live moved to 30 Sept (vendor)", font=_font(20),
           fill=(30, 30, 30))
    d.text((60, 370), "Action: confirm w/ Finance -> Marco Rossi", font=_font(20),
           fill=(30, 30, 30))
    d.text((60, 410), "Payroll still RED - no owner!", font=_font(20), fill=(190, 30, 30))

    # Make it look photographed rather than rendered.
    img = img.rotate(-1.4, resample=Image.BICUBIC, fillcolor=(246, 246, 242))
    pixels = img.load()
    random.seed(7)
    for _ in range(24_000):
        x, y = random.randrange(width), random.randrange(height)
        r, g, b = pixels[x, y]
        n = random.randint(-26, 26)
        pixels[x, y] = (
            max(0, min(255, r + n)),
            max(0, min(255, g + n)),
            max(0, min(255, b + n)),
        )

    out = SAMPLES / "milestone_whiteboard.jpg"
    img.save(out, quality=58)  # low quality on purpose — this is a phone photo
    return out


# ------------------------------------------------------- workstream dashboard
def make_workstream_dashboard() -> Path:
    """Traffic lights with no text labels — the reader must interpret RAG colour."""
    width, height = 820, 520
    img = Image.new("RGB", (width, height), WHITE)
    d = ImageDraw.Draw(img)

    d.text((32, 22), "Workstream status board", font=_font(22, True), fill=INK)
    d.text((32, 52), "No text labels — status is the indicator colour only",
           font=_font(11), fill=GREY)

    rows = [
        ("Finance", GREEN, "82%"),
        ("Human Resources", AMBER, "64%"),
        ("Information Technology", RED, "41%"),
        ("Legal", GREEN, "90%"),
        ("Operations", AMBER, "58%"),
        ("Data", RED, "35%"),
    ]
    d.text((32, 92), "Workstream", font=_font(12, True), fill=GREY)
    d.text((360, 92), "Status", font=_font(12, True), fill=GREY)
    d.text((470, 92), "Progress", font=_font(12, True), fill=GREY)

    for i, (name, colour, progress) in enumerate(rows):
        y = 124 + i * 58
        if i % 2 == 0:
            d.rectangle([28, y - 10, width - 28, y + 38], fill=(250, 250, 250))
        d.text((32, y), name, font=_font(16), fill=INK)
        d.ellipse([365, y, 393, y + 28], fill=colour)
        d.rectangle([470, y + 8, 470 + int(240 * int(progress[:-1]) / 100), y + 22],
                    fill=colour)
        d.text((722, y + 4), progress, font=_font(14), fill=INK)

    out = SAMPLES / "workstream_dashboard.jpeg"
    img.save(out, quality=88)
    return out


if __name__ == "__main__":
    for make in (make_risk_dashboard, make_whiteboard, make_workstream_dashboard):
        print(f"wrote {make()}")
