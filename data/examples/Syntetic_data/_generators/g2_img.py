"""Populated images: RAG dashboard screenshot (EN), Teams escalation screenshot (DE),
DACH target operating model organigram (DE)."""
from PIL import Image, ImageDraw, ImageFont

import case as C

F = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FB = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def font(sz, bold=False):
    return ImageFont.truetype(FB if bold else F, sz)


def box(d, xy, fill=None, outline="#D6DBD6", w=1, radius=0):
    if radius:
        d.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=w)
    else:
        d.rectangle(xy, fill=fill, outline=outline, width=w)


def txt(d, x, y, s, sz=13, bold=False, fill="#222222", anchor="la", maxw=None):
    f = font(sz, bold)
    if maxw:
        words, lines, cur = s.split(), [], ""
        for wd in words:
            t = (cur + " " + wd).strip()
            if d.textlength(t, font=f) <= maxw:
                cur = t
            else:
                lines.append(cur)
                cur = wd
        lines.append(cur)
        for i, ln in enumerate(lines):
            d.text((x, y + i * (sz + 3)), ln, font=f, fill=fill, anchor=anchor)
        return y + len(lines) * (sz + 3)
    d.text((x, y), s, font=f, fill=fill, anchor=anchor)
    return y + sz + 3


RAGC = {"Green": "#43B02A", "Amber": "#ED8B00", "Red": "#DA291C"}


def clip(s, n):
    """Truncate on a word boundary so nothing reads as cut mid-word."""
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;.") + " ..."


# =====================================================================
# 1. RAG dashboard screenshot
# =====================================================================
def dashboard():
    W, H = 1700, 990
    img = Image.new("RGB", (W, H), "#F4F6F4")
    d = ImageDraw.Draw(img)

    box(d, [0, 0, W, 54], fill="#1C3D26", outline="#1C3D26")
    txt(d, 24, 18, f"Integration Hub  >  {C.PROGRAM}  >  Reporting  >  Integration Dashboard",
        13, False, "#DDE8DC")
    txt(d, W - 24, 18, f"Last refreshed: {C.de(C.D_DASHBOARD)} 06:15 CEST   |   "
                       f"Source: Integration Tracker", 12, False, "#AFC6AE", anchor="ra")

    box(d, [0, 54, W, 120], fill="#FFFFFF", outline="#E2E6E2")
    txt(d, 24, 66, f"{C.OFFICE} ({C.OFFICE_ABBR}) - Integration Dashboard", 21, True, "#046A38")
    txt(d, 24, 96, f"{C.ACQUIRER} and {C.TARGET}   |   Reporting week {C.WEEK_LABEL}   |   "
                   f"Day {C.DAYS_AFTER_DAY1} after Day 1   |   {C.DAYS_TO_DAY100} days to "
                   f"Day 100   |   Filter: all workstreams", 12, False, "#75787B")

    tiles = [
        ("Overall RAG", C.OVERALL_RAG, RAGC[C.OVERALL_RAG], "Green last week"),
        ("Overall progress", f"{C.OVERALL_PROGRESS}%", "#222222",
         "cached, WS3 row pre-update"),
        ("Milestones on track", f"{C.MS_ON_TRACK} of {C.MS_TOTAL}", "#222222",
         f"{C.MS_DELAYED} delayed, {C.MS_AT_RISK} at risk"),
        ("Overdue or blocked", f"{C.T_OVERDUE + C.T_BLOCKED}", "#DA291C",
         f"of {C.T_TOTAL} tracked tasks"),
        ("Risks at or above 15", f"{C.R_HIGH}", "#DA291C", f"of {C.R_TOTAL} open"),
        ("Synergy secured", f"USD {C.SYN_SECURED:,} m", "#222222",
         f"of USD {C.SYN_TARGET:,} m target"),
    ]
    tw, gap = 258, 16
    for i, (lab, val, col, sub) in enumerate(tiles):
        x = 24 + i * (tw + gap)
        box(d, [x, 136, x + tw, 246], fill="#FFFFFF", outline="#DCE3DC", radius=4)
        txt(d, x + 16, 150, lab, 12, True, "#75787B")
        txt(d, x + 16, 178, val, 24, True, col)
        txt(d, x + 16, 216, sub, 10.5, False, "#9AA09A")

    # workstream table
    box(d, [24, 268, 960, 646], fill="#FFFFFF", outline="#DCE3DC", radius=4)
    txt(d, 40, 284, "Status by workstream", 15, True, "#046A38")
    cols = [("Workstream", 40), ("RAG", 386), ("Prog. %", 452), ("Open ms.", 540),
            ("Ovd.", 636), ("Risks", 704), ("Top risk", 784), ("Trend", 872)]
    y = 320
    box(d, [40, y, 944, y + 26], fill="#046A38", outline="#046A38")
    for lab, x in cols:
        txt(d, x + 6, y + 6, lab, 11, True, "#FFFFFF")
    y += 26
    for i, code in enumerate(C.WS_CODES):
        rag = C.ws_rag(code)
        rk = C.ws_risks(code)
        top = max(rk, key=C.sev) if rk else None
        box(d, [40, y, 944, y + 43], fill="#FFFFFF" if i % 2 else "#F7F9F3",
            outline="#E8ECE8")
        txt(d, 46, y + 7, code, 11, True, "#222222")
        txt(d, 46, y + 23, C.WS_NAME[code], 10, False, "#75787B")
        d.ellipse([392, y + 13, 412, y + 33], fill=RAGC[rag], outline=RAGC[rag])
        prog = C.IT_PROGRESS_DASHBOARD if code == "WS3" else C.ws_progress(code)
        for lab, val, x in [("p", f"{prog}%", 452),
                            ("m", str(sum(1 for m in C.ws_milestones(code) if m[8] != "done")), 540),
                            ("o", str(C.ws_overdue(code)), 636),
                            ("r", str(len(rk)), 704),
                            ("t", top[0] if top else "-", 784),
                            ("tr", (top[10] if top else "-"), 872)]:
            col = "#DA291C" if (x == 636 and val not in ("0",)) else "#222222"
            txt(d, x + 6, y + 15, val, 11, False, col)
        y += 43

    # milestone burn-down
    box(d, [980, 268, 1676, 646], fill="#FFFFFF", outline="#DCE3DC", radius=4)
    txt(d, 996, 284, "Milestone burn-down, Day 1 to Day 100", 15, True, "#046A38")
    cx0, cy0, cx1, cy1 = 1055, 330, 1650, 586
    d.rectangle([cx0, cy0, cx1, cy1], outline="#E8ECE8")
    for i in range(1, 5):
        yy = cy0 + i * (cy1 - cy0) / 5
        d.line([cx0, yy, cx1, yy], fill="#EEF1EE")
    for i, lab in enumerate(["Day 1", "Day 20", "Day 40", "Day 60", "Day 80", "Day 100"]):
        xx = cx0 + i * (cx1 - cx0) / 5
        txt(d, xx, cy1 + 8, lab, 10, False, "#9AA09A", anchor="ma")
    # plan line: 18 open at day 1 down to 0 at day 100
    plan = [(0, 18), (20, 14), (40, 10), (60, 6), (80, 3), (100, 0)]
    pts = [(cx0 + (dd / 100) * (cx1 - cx0), cy0 + (1 - v / 18) * (cy1 - cy0))
           for dd, v in plan]
    d.line(pts, fill="#C9D2C9", width=2)
    actual = [(0, 18), (7, 16), (14, 16), (22, 15)]
    apts = [(cx0 + (dd / 100) * (cx1 - cx0), cy0 + (1 - v / 18) * (cy1 - cy0))
            for dd, v in actual]
    d.line(apts, fill="#DA291C", width=3)
    for px, py in apts:
        d.ellipse([px - 4, py - 4, px + 4, py + 4], fill="#DA291C")
    txt(d, cx1 - 12, cy1 - 34, "Plan", 10, False, "#9AA09A", anchor="ra")
    txt(d, cx1 - 12, cy1 - 18, "Actual, open milestones", 10, True, "#DA291C", anchor="ra")
    txt(d, 1030, (cy0 + cy1) // 2, "open", 10, False, "#9AA09A", anchor="ma")
    txt(d, 996, 606, f"{C.MS_TOTAL - C.MS_DONE} of {C.MS_TOTAL} milestones still open at day "
                     f"{C.DAYS_AFTER_DAY1}. Plan assumed {14}.", 11, False, "#75787B")

    # risk heat map, populated
    box(d, [24, 666, 690, 950], fill="#FFFFFF", outline="#DCE3DC", radius=4)
    txt(d, 40, 682, "Risk heat map, likelihood x impact", 15, True, "#046A38")
    gx0, gy0, cell = 130, 716, 40
    for r in range(5):
        for c in range(5):
            like, imp = 5 - r, c + 1
            sv = like * imp
            fill = "#FBECEA" if sv >= 15 else "#FEF6E7" if sv >= 8 else "#F2F8F0"
            box(d, [gx0 + c * cell, gy0 + r * cell,
                    gx0 + (c + 1) * cell, gy0 + (r + 1) * cell],
                fill=fill, outline="#E2E6E2")
    placed = {}
    for rk in C.RISKS:
        key = (rk[5], rk[6])
        placed.setdefault(key, []).append(rk[0])
    for (like, imp), ids in placed.items():
        cx = gx0 + (imp - 1) * cell + cell / 2
        cy = gy0 + (5 - like) * cell + cell / 2
        txt(d, cx, cy, " ".join(i.replace("R-", "") for i in ids), 8.5, True,
            "#DA291C" if like * imp >= 15 else "#75787B", anchor="mm")
    for i in range(5):
        txt(d, gx0 - 8, gy0 + i * cell + cell / 2, str(5 - i), 10, False, "#9AA09A",
            anchor="rm")
        txt(d, gx0 + i * cell + cell / 2, gy0 + 5 * cell + 6, str(i + 1), 10, False,
            "#9AA09A", anchor="ma")
    txt(d, 66, gy0 + 100, "Likelihood", 10, False, "#75787B")
    txt(d, gx0 + 100, gy0 + 5 * cell + 24, "Impact", 10, False, "#75787B", anchor="ma")
    txt(d, 350, gy0 + 6,
        f"{C.R_HIGH} risks at or above the escalation threshold of "
        f"{C.ESCALATION_THRESHOLD}:", 11, True, "#222222", maxw=320)
    yy = gy0 + 44
    for rk in sorted([r for r in C.RISKS if C.sev(r) >= 15], key=C.sev, reverse=True):
        txt(d, 350, yy, f"{rk[0]}  sev {C.sev(rk)}  {C.WS_NAME[rk[3]]}", 10, True, "#DA291C")
        yy = txt(d, 350, yy + 14, clip(rk[1], 132), 9.5, False, "#75787B", maxw=322) + 8

    # synergy thermometer
    box(d, [710, 666, 1676, 950], fill="#FFFFFF", outline="#DCE3DC", radius=4)
    txt(d, 726, 682, "Synergy realisation vs. target, USD m run-rate", 15, True, "#046A38")
    bars = [("Deal model target", C.DEAL_MODEL_TARGET, "#C9D2C9"),
            ("In register", C.SYN_TARGET, "#86BC25"),
            ("Secured, all initiatives", C.SYN_SECURED, "#046A38"),
            ("Secured, Finance validated", C.SYN_VALIDATED, "#1C3D26"),
            ("Realised to date", C.SYN_REALISED, "#75787B")]
    by = 722
    maxv = C.DEAL_MODEL_TARGET
    for lab, val, col in bars:
        txt(d, 730, by + 7, lab, 11, False, "#75787B")
        box(d, [960, by, 1560, by + 28], fill="#F5F7F5", outline="#E2E6E2")
        w = int(600 * val / maxv)
        if w > 2:
            box(d, [960, by, 960 + w, by + 28], fill=col, outline=col)
        txt(d, 1660, by + 7, f"{val:,}", 11, True, "#222222", anchor="ra")
        by += 44
    txt(d, 730, by + 8,
        f"Only Finance-validated initiatives are reportable, per Steering Committee decision "
        f"B-06. The difference between secured and validated is USD "
        f"{C.SYN_SECURED - C.SYN_VALIDATED:,} m and sits entirely in revenue buckets.",
        10.5, False, "#9AA09A", maxw=920)

    txt(d, 24, 966,
        f"Screenshot of the Integration Hub dashboard, pasted into the weekly status mail. "
        f"Cached view: the overall progress tile and the WS3 row were rendered before the "
        f"tracker update of {C.de(C.D_TRACKER)}.", 10.5, False, "#9AA09A")
    img.save(C.OUT / "DellEMC_VCIO_RAG_Dashboard_Screenshot_2016-09-29.png")


# =====================================================================
# 2. Teams escalation screenshot (German), risk R-02
# =====================================================================
def teams():
    W, H = 1220, 760
    img = Image.new("RGB", (W, H), "#F5F5F5")
    d = ImageDraw.Draw(img)

    box(d, [0, 0, W, 46], fill="#464775", outline="#464775")
    txt(d, 20, 15, "Microsoft Teams", 13, True, "#FFFFFF")
    txt(d, W - 20, 15, C.nm("dach_hr"), 12, False, "#D8D8E8", anchor="ra")

    box(d, [0, 46, 258, H], fill="#EDEBE9", outline="#E1DFDD")
    txt(d, 16, 62, "Teams und Kanaele", 12, True, "#252423")
    channels = [f"{C.OFFICE_ABBR} {C.PROGRAM[:18]} (Team)", "  Allgemein", "  VCIO Weekly"] + \
        [f"  {c} {C.WS_NAME_DE[c]}" for c in C.WS_CODES] + ["  Eskalationen DACH"]
    yy = 92
    for ch in channels:
        sel = "Eskalationen" in ch
        if sel:
            box(d, [8, yy - 4, 250, yy + 22], fill="#DEDEEE", outline="#DEDEEE", radius=3)
        txt(d, 20, yy, ch[:34], 11.5, sel, "#252423" if sel else "#484644")
        yy += 28

    box(d, [258, 46, W, 92], fill="#FFFFFF", outline="#E1DFDD")
    txt(d, 278, 56, "Eskalationen DACH", 15, True, "#252423")
    txt(d, 278, 76, f"{C.PROGRAM}  |  14 Mitglieder  |  Beitraege", 11, False, "#605E5C")

    r02 = [r for r in C.RISKS if r[0] == "R-02"][0]
    msgs = [
        (C.nm("br_liaison"), C.role("br_liaison"), f"{C.de(C.D_TEAMS)} 08:12",
         [f"kurze Rueckmeldung aus der gestrigen Sitzung mit dem Gesamtbetriebsrat: der "
          f"Verhandlungstermin fuer die naechste Runde ist auf den 04.11. verschoben worden.",
          f"Damit ist der Prognosetermin fuer M-13, {C.de(C.MILESTONES[12][7])}, nur noch "
          f"knapp haltbar und nur, wenn in der ersten Novemberwoche alles glatt laeuft."],
         None),
        (C.nm("imo_mgr"), C.role("imo_mgr"), f"{C.de(C.D_TEAMS)} 08:31",
         [f"danke. Ist das aus deiner Sicht noch das Risiko R-02 in der bestehenden Bewertung, "
          f"oder muessen wir hochstufen?",
          f"Im RAID Log steht R-02 aktuell mit Wahrscheinlichkeit {r02[5]} und Auswirkung "
          f"{r02[6]}, also Schwere {C.R02_SEVERITY_REGISTER}, Band "
          f"{C.band(C.R02_SEVERITY_REGISTER)}."],
         None),
        (C.nm("dach_hr"), C.role("dach_hr"), f"{C.de(C.D_TEAMS)} 09:04",
         [f"aus HR-Sicht muessen wir hochstufen. Die Auswirkung ist nicht mehr 3 sondern 5: "
          f"wenn die Anhoerung nicht abgeschlossen ist, koennen wir die Zielstruktur nicht "
          f"veroeffentlichen, und daran haengt das Verguetungsmodell M-09 und darueber die "
          f"Gebiets- und Quotenzuordnung im Vertrieb.",
          f"Neue Bewertung aus meiner Sicht: {r02[5]} x 5 = "
          f"{C.R02_SEVERITY_CHAT}, Band {C.band(C.R02_SEVERITY_CHAT)}. Damit liegt es ueber "
          f"der Eskalationsschwelle von {C.ESCALATION_THRESHOLD} und gehoert in die Vorlage "
          f"fuer das Steering Committee am {C.de(C.STEERCO_02)}."],
         f"Diese Nachricht enthaelt eine hoehere Bewertung als das RAID Log. Das Register "
         f"zeigt weiterhin Schwere {C.R02_SEVERITY_REGISTER}."),
        (C.nm("dach_lead"), C.role("dach_lead"), f"{C.de(C.D_TEAMS)} 09:26",
         [f"einverstanden mit der Hochstufung. @{C.nm('br_liaison')} bitte die neue Bewertung "
          f"im RAID Log eintragen und im VCIO Weekly aufrufen.",
          f"Wichtig: bis der Eintrag im Register steht, existiert die Hochstufung formal "
          f"nicht. Beschluss B-05, mitbestimmte Einheiten aus der ersten Ankuendigung "
          f"auszunehmen, bleibt davon unberuehrt und gilt weiter."],
         None),
    ]
    y = 108
    for name, rl, when, lines, flag in msgs:
        d.ellipse([280, y + 4, 316, y + 40], fill="#6264A7", outline="#6264A7")
        initials = "".join(p[0] for p in name.replace(".", "").split()[:2]).upper()
        txt(d, 298, y + 22, initials, 12, True, "#FFFFFF", anchor="mm")
        txt(d, 330, y + 5, name, 12, True, "#252423")
        txt(d, 330 + int(d.textlength(name, font=font(12, True))) + 12, y + 7,
            f"{rl}   {when}", 10, False, "#605E5C")
        by = y + 27
        for ln in lines:
            by = txt(d, 330, by, ln, 12, False, "#3b3a39", maxw=830) + 3
        if flag:
            box(d, [330, by + 4, 1180, by + 32], fill="#FDF3F4", outline="#F1BFC3", radius=3)
            txt(d, 340, by + 11, "(!) " + flag, 10.5, False, "#A4262C")
            by += 38
        txt(d, 330, by + 4, "Antworten  |  2 Reaktionen", 10, False, "#8A8886")
        y = by + 32
        d.line([278, y - 8, W - 30, y - 8], fill="#EDEBE9")

    box(d, [278, H - 70, W - 30, H - 24], fill="#FFFFFF", outline="#E1DFDD", radius=4)
    txt(d, 294, H - 54, "Neue Nachricht eingeben", 12, False, "#A19F9D")
    txt(d, 278, H - 16,
        "Screenshot aus MS Teams, an das VCIO weitergeleitet. Synthetisches Dokument.",
        10, False, "#A19F9D")
    img.save(C.OUT / "DellEMC_VCIO_Teams_Eskalation_R-02_2016-09-29.png")


# =====================================================================
# 3. DACH target operating model organigram
# =====================================================================
def organigram():
    W, H = 1860, 1180
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)

    txt(d, 40, 32, f"{C.PROGRAM} - Zielorganisation DACH (Target Operating Model)",
        25, True, "#046A38")
    txt(d, 40, 68, f"{C.NEWCO}, Region DACH  |  Ebene 1 bis 3  |  Stand {C.de(C.D_ORG)}  |  "
                   f"Freigegeben durch {C.nm('prog_dir')}  |  Version 1.2  |  "
                   f"Meilenstein M-13 offen", 12.5, False, "#75787B")
    d.line([40, 98, W - 40, 98], fill="#E2E6E2", width=2)

    def node(x, y, w, h, label, sub, level):
        fills = {1: "#046A38", 2: "#86BC25", 3: "#F1F6E4"}
        fg = {1: "#FFFFFF", 2: "#FFFFFF", 3: "#222222"}
        box(d, [x, y, x + w, y + h], fill=fills[level], outline="#C9D2C9", radius=4)
        txt(d, x + w // 2, y + 12, label, 13 if level < 3 else 11, True, fg[level],
            anchor="ma")
        txt(d, x + w // 2, y + 32, sub, 9.5, False,
            "#DDE8DC" if level == 1 else ("#F0F6E4" if level == 2 else "#75787B"),
            anchor="ma")

    n1w, n1h = 340, 62
    n1x = (W - n1w) // 2
    node(n1x, 126, n1w, n1h, ORG1 := C.ORG_L1[0],
         f"{C.nm('dach_lead')}  |  berichtet an {C.NEWCO} EMEA", 1)

    l2 = C.ORG_L2_DE
    n2w, n2h = 320, 58
    gap = (W - 80 - len(l2) * n2w) // (len(l2) - 1)
    y2 = 286
    d.line([W // 2, 188, W // 2, 248], fill="#9AA09A", width=2)
    xs = []
    heads = {"Finanzen": "dach_fin", "IT": "dach_it", "Personal": "dach_hr",
             "Lieferkette und Logistik": "WS5", "Vertrieb und Marketing": "WS6"}
    ftes = {"Finanzen": 168, "IT": 296, "Personal": 121,
            "Lieferkette und Logistik": 342, "Vertrieb und Marketing": 357}
    for i, (name, ws) in enumerate(l2):
        x = 40 + i * (n2w + gap)
        xs.append(x + n2w // 2)
        node(x, y2, n2w, n2h, f"{name}  ({ws})",
             f"{C.nm(heads[name])}  |  {ftes[name]} FTE", 2)
    d.line([xs[0], 248, xs[-1], 248], fill="#9AA09A", width=2)
    for cx in xs:
        d.line([cx, 248, cx, y2], fill="#9AA09A", width=2)

    n3w, n3h = 320, 60
    y3 = 400
    unit_fte = {
        "Finanzen": [72, 61, 35], "IT": [138, 104, 54], "Personal": [58, 41, 22],
        "Lieferkette und Logistik": [126, 143, 73],
        "Vertrieb und Marketing": [164, 121, 72]}
    for i, cx in enumerate(xs):
        name = l2[i][0]
        d.line([cx, y2 + n2h, cx, y3 - 22], fill="#C9D2C9", width=2)
        d.line([cx, y3 - 22, cx - n3w // 2 - 16, y3 - 22], fill="#C9D2C9", width=2)
        for j, unit in enumerate(C.ORG_L3_DE[name]):
            yy = y3 + j * (n3h + 18)
            node(cx - n3w // 2, yy, n3w, n3h, unit,
                 f"{unit_fte[name][j]} FTE", 3)
            d.line([cx - n3w // 2 - 16, yy + n3h // 2, cx - n3w // 2, yy + n3h // 2],
                   fill="#C9D2C9", width=2)
        d.line([cx - n3w // 2 - 16, y3 - 22,
                cx - n3w // 2 - 16, y3 + 2 * (n3h + 18) + n3h // 2], fill="#C9D2C9", width=2)

    ly = 660
    box(d, [40, ly, 640, ly + 176], fill="#FAFBFA", outline="#E2E6E2", radius=4)
    txt(d, 58, ly + 14, "Legende", 14, True, "#046A38")
    yy = ly + 44
    for col, lab in [("#046A38", "Ebene 1: Regionalleitung DACH"),
                     ("#86BC25", "Ebene 2: Funktionsleitung, direkt berichtend"),
                     ("#F1F6E4", "Ebene 3: Abteilung, FTE im Zielbild")]:
        box(d, [58, yy, 82, yy + 16], fill=col, outline="#C9D2C9")
        txt(d, 92, yy + 1, lab, 12, False, "#444444")
        yy += 32

    box(d, [672, ly, 1820, ly + 176], fill="#FAFBFA", outline="#E2E6E2", radius=4)
    txt(d, 690, ly + 14, "Kennzahlen der Zielorganisation DACH", 14, True, "#046A38")
    kpis = [("FTE Zielorganisation", f"{C.DACH_FTE_TARGET:,}".replace(",", ".")),
            ("FTE Ist zu Day 1", f"{C.DACH_FTE_DAY1:,}".replace(",", ".")),
            ("Delta FTE", f"{C.DACH_FTE_TARGET - C.DACH_FTE_DAY1}"),
            ("Fuehrungsspanne", f"{C.DACH_SPAN}".replace(".", ",")),
            ("Leitungsebenen", str(C.DACH_LAYERS)),
            ("Offene Positionen", str(C.DACH_OPEN_POS))]
    for k, (lab, val) in enumerate(kpis):
        cx = 690 + (k % 3) * 376
        cyy = ly + 48 + (k // 3) * 62
        txt(d, cx, cyy, lab, 11, False, "#75787B")
        txt(d, cx, cyy + 17, val, 18, True,
            "#DA291C" if lab == "Delta FTE" else "#222222")

    box(d, [40, ly + 196, 1820, ly + 262], fill="#FDF3F4", outline="#F1BFC3", radius=4)
    txt(d, 58, ly + 208,
        f"Hinweis: Die Zielorganisation ist mit den Betriebsraeten noch nicht abschliessend "
        f"abgestimmt. Meilenstein M-13, Abschluss der Anhoerung, ist von "
        f"{C.de(C.MILESTONES[12][6])} auf {C.de(C.MILESTONES[12][7])} verschoben "
        f"(Risiko R-02).", 12, False, "#A4262C")
    txt(d, 58, ly + 232,
        f"Eine Veroeffentlichung vor Abschluss der Anhoerung ist ausgeschlossen. Beschluss "
        f"B-05 nimmt mitbestimmte Einheiten aus der ersten Ankuendigung ausdruecklich aus.",
        12, False, "#A4262C")

    txt(d, 40, ly + 280,
        f"Quelle: Zielbild {C.WS_NAME['WS4']}, Anlage 3 zur Integration Charter. "
        f"Export aus Visio, als Bild in die Statusunterlagen eingebettet. "
        f"Fuehrende Quelle fuer die aktuelle Besetzung ist die RACI-Matrix im Integration Hub.",
        11, False, "#9AA09A")
    txt(d, 40, ly + 302,
        "Synthetisches Dokument. Alle Namen und FTE-Werte sind erfunden und in sich konsistent.",
        11, False, "#9AA09A")

    img.convert("RGB").save(C.OUT / "DellEMC_VCIO_Zielorganisation_DACH_2016-08-25.jpg",
                            quality=88)


if __name__ == "__main__":
    dashboard()
    teams()
    organigram()
    print("img done")
