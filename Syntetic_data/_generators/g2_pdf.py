"""Populated PDF: signed SteerCo minutes session 01, synergy baseline sign-off,
merger agreement key terms summary."""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

import case as C

GREEN = colors.HexColor("#" + C.D_DARK)
GREY = colors.HexColor("#" + C.D_GREY)
PALE = colors.HexColor("#" + C.D_PALE)
LIGHT = colors.HexColor("#" + C.D_LIGHT)
REDC = colors.HexColor("#" + C.RAG_COLOR["Red"])
AMBC = colors.HexColor("#" + C.RAG_COLOR["Amber"])

H1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=13, textColor=GREEN,
                    spaceBefore=13, spaceAfter=5, leading=16)
H2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=10, textColor=GREEN,
                    spaceBefore=9, spaceAfter=3, leading=12)
BODY = ParagraphStyle("BODY", fontName="Helvetica", fontSize=8.5, leading=12, spaceAfter=5)
NOTE = ParagraphStyle("NOTE", fontName="Helvetica-Oblique", fontSize=7, textColor=GREY,
                      leading=9.5, spaceAfter=4)
TITLE = ParagraphStyle("TITLE", fontName="Helvetica-Bold", fontSize=17, textColor=GREEN,
                       leading=21, spaceAfter=2)
SUB = ParagraphStyle("SUB", fontName="Helvetica", fontSize=9, textColor=GREY,
                     leading=12, spaceAfter=11)
CELL = ParagraphStyle("CELL", fontName="Helvetica", fontSize=7, leading=8.8)
CELLB = ParagraphStyle("CELLB", parent=CELL, fontName="Helvetica-Bold")
CELLH = ParagraphStyle("CELLH", fontName="Helvetica-Bold", fontSize=7, leading=8.8,
                       textColor=colors.white)
USABLE = 17.0


def build(fname, story, footer_text):
    doc = BaseDocTemplate(str(C.OUT / fname), pagesize=A4,
                          leftMargin=2.0 * cm, rightMargin=2.0 * cm,
                          topMargin=1.8 * cm, bottomMargin=2.0 * cm,
                          title=fname.replace(".pdf", "").replace("_", " "),
                          author=f"{C.OFFICE} ({C.OFFICE_ABBR})")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")

    def deco(canv, d):
        canv.saveState()
        canv.setStrokeColor(LIGHT)
        canv.setLineWidth(0.5)
        canv.line(doc.leftMargin, A4[1] - 1.4 * cm, A4[0] - doc.rightMargin, A4[1] - 1.4 * cm)
        canv.setFont("Helvetica", 6.5)
        canv.setFillColor(GREY)
        canv.drawString(doc.leftMargin, A4[1] - 1.25 * cm, footer_text)
        canv.line(doc.leftMargin, 1.5 * cm, A4[0] - doc.rightMargin, 1.5 * cm)
        canv.drawString(doc.leftMargin, 1.15 * cm, footer_text)
        canv.drawRightString(A4[0] - doc.rightMargin, 1.15 * cm, f"Page {canv.getPageNumber()}")
        canv.restoreState()

    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=deco)])
    doc.build(story)


def meta(pairs):
    data = [[Paragraph(f"<b>{k}</b>", CELL), Paragraph(str(v), CELL)] for k, v in pairs]
    t = Table(data, colWidths=[4.6 * cm, 12.4 * cm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, LIGHT),
        ("BACKGROUND", (0, 0), (0, -1), PALE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def grid(headers, rows, widths, red_cols=()):
    scale = USABLE / sum(widths)
    widths = [w * scale for w in widths]
    data = [[Paragraph(h, CELLH) for h in headers]]
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, LIGHT),
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, row in enumerate(rows, start=1):
        cells = []
        for j, v in enumerate(row):
            st = CELL
            if j in red_cols and str(v) in ("Delayed", "Overdue", "Blocked", "High",
                                            "Critical", "Red", "No"):
                st = ParagraphStyle(f"r{i}{j}", parent=CELLB, textColor=REDC)
            elif j in red_cols and str(v) in ("At risk", "Amber", "Medium"):
                st = ParagraphStyle(f"a{i}{j}", parent=CELLB, textColor=AMBC)
            cells.append(Paragraph(str(v), st))
        data.append(cells)
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F7F9F3")))
    t = Table(data, colWidths=[w * cm for w in widths], repeatRows=1)
    t.setStyle(TableStyle(style))
    return t


def sig(roles):
    data = [[Paragraph(f"<b>{n}</b><br/><font size=6.5 color='#75787B'>{r}</font><br/><br/>"
                       f"____________________________<br/>"
                       f"<font size=6 color='#75787B'>Signature and date</font>", CELL)
             for n, r in roles]]
    t = Table(data, colWidths=[(17.0 / len(roles)) * cm] * len(roles))
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 8),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


DISC = ("Synthetic document. The case anchoring, meaning the entities, the transaction value, "
        "the close date, the governance structure and the workstream cut, follows publicly "
        "available sources listed at the end. All operational names, figures, risks, decisions "
        "and synergy values are invented, internally consistent, and are not a representation "
        "of what any party actually did.")


def sources(story):
    story.append(Paragraph("Sources for the case anchoring", H2))
    for i, s in enumerate(C.SOURCES, 1):
        story.append(Paragraph(f"{i}. {s}", NOTE))
    story.append(Paragraph(DISC, NOTE))


# =====================================================================
# 1. Signed SteerCo minutes, session 01
# =====================================================================
def minutes():
    s = []
    s.append(Paragraph(f"{C.OFFICE} - Steering Committee Minutes, Session 01", TITLE))
    s.append(Paragraph(f"Approved and signed record of the first Steering Committee meeting "
                       f"after close. This document supersedes the draft circulated on "
                       f"{C.en(C.STEERCO_01)} and is the binding record of the decisions in "
                       f"section 4.", SUB))
    s.append(meta([
        ("Document", "Steering Committee Minutes, session 01, approved"),
        ("Programme", f"{C.PROGRAM}, run by the {C.OFFICE} ({C.OFFICE_ABBR})"),
        ("Parties", f"{C.ACQUIRER} and {C.TARGET}, combined as {C.NEWCO}"),
        ("Meeting date", f"{C.en(C.STEERCO_01)}, day "
                         f"{(C.STEERCO_01 - C.DAY1).days} after Day 1"),
        ("Approved and signed", C.en(C.STEERCO_01_SIGNED)),
        ("Chair", f"{C.nm('prog_dir')}, {C.role('prog_dir')}"),
        ("Minutes taken by", f"{C.nm('imo_pmo')}, {C.role('imo_pmo')}"),
        ("Distribution", "Steering Committee members, workstream leads, executive sponsor"),
        ("Classification", "Strictly confidential"),
        ("Version and status", "v1.0, approved and signed"),
    ]))
    s.append(Spacer(1, 6))

    s.append(Paragraph("1. Attendance", H1))
    att = [[C.nm(k), C.role(k), org, vote, pres]
           for k, org, vote, pres in [
               ("prog_dir", C.NEWCO, "No, chairs", "Present"),
               ("imo_mgr", C.NEWCO, "No", "Present"),
               ("imo_pmo", C.NEWCO, "No", "Present"),
               ("synergy", C.NEWCO, "No", "Present"),
               ("risk", C.NEWCO, "No", "Present"),
               ("change", C.NEWCO, "No", "Present"),
               ("WS1", C.NEWCO, "Yes", "Present"),
               ("WS2", C.NEWCO, "Yes", "Present"),
               ("WS3", C.NEWCO, "Yes", "Present"),
               ("hc_prev", C.NEWCO, "Yes", "Present"),
               ("WS5", C.NEWCO, "Yes", "Present"),
               ("WS6", C.NEWCO, "Yes", "Present"),
               ("WS7", C.NEWCO, "Yes", "Apologies, represented by " + C.nm("imo_mgr")),
               ("dach_lead", "DACH region", "No", "Present"),
               ("advisor", C.ADVISOR, "No", "Present"),
           ]]
    s.append(grid(["Name", "Role", "Organisation", "Voting member", "Attendance"],
                  att, [3.2, 4.4, 2.6, 1.8, 3.4]))
    nvote = sum(1 for a in att if a[3] == "Yes")
    s.append(Paragraph(f"Quorum confirmed: all {nvote} voting members, the workstream leads, "
                       f"were present or represented. The chair does not vote. Agenda "
                       f"approved without change.", BODY))

    s.append(Paragraph("2. Integration status noted", H1))
    s.append(Paragraph(f"The committee noted the status as at {C.en(C.STEERCO_01)}, day "
                       f"{(C.STEERCO_01 - C.DAY1).days} after close. All three Day 1 milestones "
                       f"were achieved on the day, including the employee welcome guide for "
                       f"{C.EMPLOYEES:,} employees and the sales runbook for more than "
                       f"{C.SALES_PROFESSIONALS:,} sales professionals.", BODY))
    s.append(Paragraph(f"The committee challenged two items. First, the office was reporting "
                       f"secured synergy above the figure Finance could validate. Second, "
                       f"status was arriving in six different formats and reconciliation was "
                       f"consuming analyst capacity intended for analysis. Both were converted "
                       f"into decisions, recorded below.", BODY))
    rag = [[C.ws_full(c), C.RAG_LAST_WEEK[c], C.RAG_LAST_WEEK[c],
            "Noted" if C.RAG_LAST_WEEK[c] == "Green"
            else "Challenged, mitigation requested"] for c in C.WS_CODES]
    s.append(grid(["Workstream", "RAG reported", "RAG accepted", "Committee position"],
                  rag, [4.0, 2.4, 2.4, 5.2], red_cols=(1, 2)))

    s.append(Paragraph("3. Decisions taken", H1))
    s.append(Paragraph("Each decision below is binding from the date recorded and was carried "
                       "without dissent.", NOTE))
    dec = [[d[0], d[1], d[3], C.nm(d[7]), C.en(d[5]), d[6]]
           for d in C.DECISIONS if d[5] == C.STEERCO_01]
    s.append(grid(["ID", "Decision", "Rationale recorded", "Implementation owner",
                   "Effective from", "Affects"],
                  dec, [0.9, 4.6, 4.4, 2.2, 1.8, 1.6]))

    s.append(Paragraph("4. Actions agreed", H1))
    s.append(Paragraph(f"Action {C.ACTIONS[0][0]} is recorded against "
                       f"{C.nm(C.OP01_OWNER_MINUTES)}, {C.role(C.OP01_OWNER_MINUTES)}.", NOTE))
    acts = [[a[0], a[1], C.nm(a[4]), a[5], C.en(a[6]), a[3]]
            for a in C.ACTIONS if "session 01" in a[3]]
    s.append(grid(["ID", "Action", "Owner", "WS", "Due date", "Source"],
                  acts, [0.9, 5.6, 2.4, 0.9, 2.0, 3.0]))

    s.append(Paragraph("5. Risks escalated to and accepted by the committee", H1))
    esc = [[r[0], r[1], C.ws_full(r[3]), f"{r[5]} x {r[6]} = {C.sev(r)}", C.band(C.sev(r)),
            r[7], C.nm(r[4])]
           for r in sorted(C.RISKS, key=C.sev, reverse=True)
           if r[11] == "Steering Committee"]
    s.append(grid(["ID", "Risk", "Workstream", "L x I", "Band", "Mitigation endorsed",
                   "Owner"], esc, [0.9, 4.4, 2.4, 1.4, 1.2, 4.4, 2.0], red_cols=(4,)))
    s.append(Paragraph(f"The committee confirmed the escalation threshold at severity "
                       f"{C.ESCALATION_THRESHOLD} and required any risk reaching it to appear "
                       f"in the pack of the next session without further filtering.", BODY))

    s.append(Paragraph("6. Items deferred", H1))
    s.append(grid(["Item", "Reason for deferral", "Deferred to", "Additional input required"],
                  [["Day 100 scope decision", "The ERP blueprint recovery plan was not yet "
                    "available, so the committee could not judge what scope would have to "
                    "move", f"Session 02, {C.en(C.STEERCO_02)}",
                    f"Recovery plan with a dated forecast from {C.nm('WS3')}"],
                   ["Site consolidation plan for EMEA", "Lease expiry analysis incomplete",
                    "Session 03", f"Completed analysis from {C.nm('WS7')}"]],
                  [3.4, 6.0, 3.2, 4.4]))

    s.append(Paragraph("7. Next meeting", H1))
    s.append(meta([("Date", f"{C.en(C.STEERCO_02)}, session 02"),
                   ("Focus topics", "Day 100 scope decision, ERP blueprint recovery plan, "
                                    "works council consultation timetable"),
                   ("Papers due to members by", C.en(C.D_WS_ONEPAGER))]))

    s.append(Paragraph("8. Approval", H1))
    s.append(Paragraph("By signing, the chair and the minute taker confirm that these minutes "
                       "are a true record of the meeting and that the decisions recorded in "
                       "section 3 were taken as stated. Amendments after signature require a "
                       "corrigendum tabled at the following session.", BODY))
    s.append(Spacer(1, 4))
    s.append(sig([(C.nm("prog_dir"), C.role("prog_dir")),
                  (C.nm("imo_mgr"), C.role("imo_mgr")),
                  (C.nm("imo_pmo"), C.role("imo_pmo"))]))
    sources(s)

    build("DellEMC_VCIO_SteerCo_Minutes_Session01_signed_2016-09-22.pdf", s,
          f"{C.NEWCO}  |  {C.OFFICE_ABBR} Steering Committee minutes, session 01, approved  "
          f"|  Strictly confidential")


# =====================================================================
# 2. Synergy baseline sign-off
# =====================================================================
def baseline():
    s = []
    s.append(Paragraph(f"{C.OFFICE} - Synergy Baseline Sign-Off", TITLE))
    s.append(Paragraph(f"Formal attestation by Group Controlling that the financial baseline "
                       f"against which all synergies of the combination are measured is "
                       f"complete, consistent and locked as at Day 1, {C.en(C.DAY1)}.", SUB))
    s.append(meta([
        ("Document", "Synergy baseline sign-off and attestation"),
        ("Programme", f"{C.PROGRAM}, {C.OFFICE} ({C.OFFICE_ABBR})"),
        ("Parties", f"{C.ACQUIRER} and {C.TARGET}"),
        ("Baseline as at", f"Day 1, {C.en(C.DAY1)}"),
        ("Currency and unit", "USD million"),
        ("Prepared by", f"{C.nm('synergy')}, {C.role('synergy')}"),
        ("Reviewed by", f"{C.nm('WS1')}, {C.role('WS1')}"),
        ("Approved by", f"{C.nm('prog_dir')}, {C.role('prog_dir')}"),
        ("Sign-off date", C.en(C.D_BASELINE)),
        ("Classification", "Strictly confidential"),
        ("Version and status", "v1.0, signed, baseline locked"),
    ]))
    s.append(Spacer(1, 6))

    s.append(Paragraph("1. Purpose and effect", H1))
    s.append(Paragraph("Once signed, the figures in section 3 are the sole reference point "
                       "for measuring synergy realisation. Any subsequent change requires a "
                       "baseline change request approved by the Steering Committee and "
                       "recorded in section 7.", BODY))

    s.append(Paragraph("2. Scope of the baseline", H1))
    s.append(meta([
        ("Entities included", f"The combined perimeter of {C.ACQUIRER} and {C.TARGET} "
                              f"excluding the businesses listed below"),
        ("Entities excluded", "Majority-owned but separately listed subsidiaries are excluded "
                              "from the cost baseline because their cost base is not "
                              "controllable by the integration programme"),
        ("Financial year covered", "FY16 actual and FY17 budget"),
        ("Accounting basis", "US GAAP, target figures conformed to acquirer policy"),
        ("Source systems", "Statutory accounts of both groups, combined spend cube, "
                           "combined FY17 operating plan, combined lease register"),
        ("Cut-off date for source data", C.en(C.DAY1)),
    ]))

    s.append(Paragraph("3. Baseline figures", H1))
    rows = [[b[0], b[1], b[2], b[3], f"{b[4]:,}", f"{b[5]:,}", b[6]] for b in C.BASELINE]
    tot16 = sum(b[4] for b in C.BASELINE)
    tot17 = sum(b[5] for b in C.BASELINE)
    rows.append(["", "Total addressable baseline", "", "", f"{tot16:,}", f"{tot17:,}", ""])
    s.append(grid(["ID", "Line item", "Entity", "Category", "FY16 actual",
                   "FY17 budget", "Source document"],
                  rows, [1.0, 4.6, 2.0, 1.8, 1.6, 1.6, 4.4]))

    s.append(Paragraph("4. Normalisation adjustments", H1))
    s.append(Paragraph("Every adjustment to reported figures is listed. An adjustment not "
                       "listed here has not been made.", NOTE))
    s.append(grid(["ID", "Description", "Reason", "Amount (USD m)", "Affects", "Approved by"],
                  [["N-01", "Remove one-off transaction and advisory fees from the FY16 "
                    "cost base", "These costs do not recur and would overstate the "
                    "addressable base", "-186", "BL-06", C.nm("WS1")],
                   ["N-02", "Conform target depreciation policy to acquirer policy",
                    "Comparability of the IT cost base", "-42", "BL-01, BL-02",
                    C.nm("WS1")],
                   ["N-03", "Exclude spend already contracted at fixed price beyond FY18",
                    "Not addressable within the synergy horizon", "-311",
                    "BL-03, BL-05", C.nm("WS5")],
                   ["N-04", "Reclassify contractor spend from personnel to indirect "
                    "procurement", "Consistent treatment across both groups", "0",
                    "BL-03, BL-06", C.nm("WS4")]],
                  [1.0, 4.4, 4.0, 1.8, 2.0, 2.2]))

    s.append(Paragraph("5. Synergy target reconciliation", H1))
    s.append(grid(["Item", "Amount (USD m)", "Basis"],
                  [["Deal model synergy target, run-rate", f"{C.DEAL_MODEL_TARGET:,}",
                    "Investment committee paper, run-rate by the third full year"],
                   ["Cost synergy target in the register", f"{C.COST_TARGET:,}",
                    f"{sum(1 for x in C.SYNERGIES if x[4] == 'Cost')} initiatives"],
                   ["Revenue synergy target in the register", f"{C.REV_TARGET:,}",
                    f"{sum(1 for x in C.SYNERGIES if x[4] == 'Revenue')} initiatives"],
                   ["Total in the register", f"{C.SYN_TARGET:,}",
                    "Sum of both categories"],
                   ["Gap to the deal model", f"{C.SYN_GAP:,}",
                    "Initiatives not yet identified at the level of a named owner"],
                   ["Revenue to cost ratio in the register", f"{C.REV_COST_RATIO}",
                    "Designed to the ratio management stated publicly at announcement"]],
                  [6.4, 2.8, 7.8]))

    s.append(Paragraph("6. Limitations and open points", H1))
    s.append(grid(["No.", "Limitation", "Impact on reliability", "Resolution by"],
                  [["L-01", "The pension obligation of the target is carried at the value in "
                    "the last published accounts and has not been revalued",
                    "The personnel baseline may move once the actuarial review is complete",
                    C.en(C.ACTIONS[8][7])],
                   ["L-02", "The EMEA entity chain review is not complete, so the legal "
                    "perimeter of the baseline is provisional in that region",
                    "Entity-level allocation of the cost base may shift",
                    C.en(C.MILESTONES[4][7])],
                   ["L-03", "Contracts of the top logistics providers have not all been "
                    "reviewed for change of control clauses",
                    "Addressability of the freight baseline is assumed, not confirmed",
                    C.en(C.ASSUMPTIONS[3][6])]],
                  [1.0, 5.6, 5.4, 2.4]))

    s.append(Paragraph("7. Baseline change log", H1))
    s.append(Paragraph("To be completed only after sign-off, for approved baseline changes. "
                       "No change has been approved to date.", NOTE))
    s.append(grid(["Change ID", "Date", "Change made", "Reason", "Approved by",
                   "New value"],
                  [["-", "-", "No baseline change approved since sign-off", "-", "-", "-"]],
                  [1.4, 1.6, 5.4, 3.6, 2.4, 2.0]))

    s.append(Paragraph("8. Attestation", H1))
    s.append(Paragraph(f"We confirm that the baseline set out in section 3 has been derived "
                       f"from the source documents named, that all normalisation adjustments "
                       f"are disclosed in section 4, that the limitations in section 6 are "
                       f"complete to our knowledge, and that the baseline is locked with "
                       f"effect from {C.en(C.D_BASELINE)}.", BODY))
    s.append(Spacer(1, 4))
    s.append(sig([(C.nm("synergy"), C.role("synergy")),
                  (C.nm("WS1"), C.role("WS1")),
                  (C.nm("prog_dir"), C.role("prog_dir"))]))
    sources(s)

    build("DellEMC_VCIO_Synergy_Baseline_SignOff_2016-09-02.pdf", s,
          f"{C.NEWCO}  |  Synergy baseline sign-off, locked  |  Strictly confidential")


# =====================================================================
# 3. Merger agreement key terms summary
# =====================================================================
def terms():
    s = []
    s.append(Paragraph("Merger Agreement: Key Terms Summary for the Integration Team", TITLE))
    s.append(Paragraph(f"Summary of the agreement announced on {C.en(C.ANNOUNCE)} under which "
                       f"{C.ACQUIRER} acquires {C.TARGET}. This is a summary prepared for "
                       f"integration planning only. The executed agreement and the filings "
                       f"made with the securities regulator govern in every case of doubt.",
                       SUB))
    s.append(meta([
        ("Document", "Merger agreement key terms summary, integration extract"),
        ("Transaction", f"{C.ACQUIRER} acquires {C.TARGET}, combined as {C.NEWCO}"),
        ("Announced", C.en(C.ANNOUNCE)),
        ("Expected close", f"{C.en(C.DAY1)} (actual close, confirmed)"),
        ("Prepared by", f"{C.nm('imo_mgr')}, {C.role('imo_mgr')}"),
        ("Reviewed by", "Legal and M&A"),
        ("Distribution", "Programme leadership and workstream leads only. "
                         "Not for onward distribution"),
        ("Classification", "Strictly confidential"),
        ("Version and status", "v1.0, final"),
    ]))
    s.append(Spacer(1, 6))

    s.append(Paragraph("1. Parties and transaction structure", H1))
    s.append(meta([
        ("Acquirer", C.ACQUIRER),
        ("Target", C.TARGET),
        ("Combined entity", C.NEWCO),
        ("Transaction value", f"{C.DEAL_VALUE}, reported at announcement with a headline "
                              f"figure of {C.DEAL_VALUE_HEADLINE} depending on the measure "
                              f"used"),
        ("Structure", "Cash and stock. Target shareholders receive cash plus a tracking "
                      "stock linked to a portion of the target's economic interest in its "
                      "majority-owned virtualisation subsidiary"),
        ("Family of businesses after close", ", ".join(C.FAMILY)),
    ]))

    s.append(Paragraph("2. Consideration", H1))
    s.append(grid(["Item", "Term", "Value", "Consequence for the integration team"],
                  [["Cash consideration", "Per target share", C.CASH_PER_SHARE,
                    "Fixes the equity bridge input to the opening balance sheet, M-04"],
                   ["Tracking stock", "Per target share",
                    f"{C.TRACKING_RATIO} tracking shares",
                    "Creates a separate reporting requirement that the finance workstream "
                    "must design for from Day 1"],
                   ["Committed debt financing", "Facility commitment", C.DEBT_COMMITMENT,
                    "Debt service constrains discretionary integration spend, recorded as "
                    "risk R-11"],
                   ["Combined revenue at close", "Reported scale", C.COMBINED_REVENUE,
                    "Sets the denominator for every synergy percentage reported to the "
                    "committee"]],
                  [3.0, 2.4, 3.0, 8.6]))

    s.append(Paragraph("3. Conditions precedent and closing", H1))
    s.append(grid(["ID", "Condition precedent", "Responsible", "Status at close",
                   "Satisfied on"],
                  [["CP-01", "Target shareholder approval", "Target", "Satisfied",
                    "Pre-close"],
                   ["CP-02", "Antitrust and merger control clearances in all required "
                    "jurisdictions", "Both parties", "Satisfied", "Pre-close"],
                   ["CP-03", "Regulatory approvals for the tracking stock listing",
                    "Acquirer", "Satisfied", "Pre-close"],
                   ["CP-04", "Availability of the committed debt financing", "Acquirer",
                    "Satisfied", "Pre-close"],
                   ["CP-05", "No material adverse change", "Both parties", "Satisfied",
                    C.en(C.DAY1)]],
                  [1.0, 6.4, 2.4, 2.2, 2.0]))

    s.append(Paragraph("4. Signing to closing covenants", H1))
    s.append(Paragraph("These restricted what could be done in the eleven months between "
                       "announcement and close. They have now lapsed, but the integration "
                       "plan was built under them and several sequencing choices still "
                       "reflect that.", NOTE))
    s.append(grid(["Covenant", "Restriction", "Lapsed at", "Effect still visible in the plan"],
                  [["Ordinary course of business", "Target to operate its business as before "
                    "and not to make material commitments outside the ordinary course",
                    C.en(C.DAY1),
                    "The legacy ERP upgrade at the target continued as an ordinary course "
                    "programme and was therefore not stopped before close, which is the "
                    "origin of risk R-01"],
                   ["Clean team and information exchange", "Competitively sensitive "
                    "information exchanged only through a clean team",
                    C.en(C.DAY1),
                    "The combined spend cube could only be built after close, which is why "
                    "procurement synergies are still at business case stage"],
                   ["No solicitation of employees", "Neither party to solicit the other's "
                    "employees", C.en(C.DAY1),
                    "Retention design could not begin until close, compressing the window "
                    "before the coverage model takes effect"]],
                  [3.0, 5.4, 1.8, 6.8]))

    s.append(Paragraph("5. Terms with direct integration relevance", H1))
    s.append(Paragraph("Each item below constrains integration planning directly and is "
                       "reflected in the plan as shown.", NOTE))
    s.append(grid(["Topic", "Term", "Owning workstream", "Reflected in the plan as"],
                  [["Employee protections", "Continuity of terms for a defined period after "
                    "close in specified jurisdictions", C.ws_full("WS4"),
                    "Milestone M-09, task A-032, risk R-04"],
                   ["Co-determination and consultation", "Local consultation obligations "
                    "survive the transaction and must be discharged before structural change",
                    C.ws_full("WS4"),
                    "Milestone M-13, task A-033, risk R-02, decision B-05"],
                   ["Brand and name usage", "Combined brand launched at close, target brand "
                    "retained for the infrastructure business", C.ws_full("WS6"),
                    "Milestone M-01, task A-063"],
                   ["Customer and supplier consents", "Change of control consents required "
                    "under a defined set of contracts", C.ws_full("WS5"),
                    "Assumption AS-04, task A-043"],
                   ["Pension obligations", "Target pension arrangements transfer with the "
                    "business", C.ws_full("WS1"), "Risk R-13, action OP-09"],
                   ["Legacy systems", "Target's enterprise system modernisation continues as "
                    "an ordinary course programme", C.ws_full("WS3"),
                    "Risk R-01, milestone M-07, decision B-04"],
                   ["Legal entity structure", "Post-close rationalisation permitted subject "
                    "to local law and tax clearance", C.ws_full("WS2"),
                    "Milestone M-05, task A-011, dependency D-01"]],
                  [2.6, 6.0, 2.8, 5.6]))

    s.append(Paragraph("6. Key dates", H1))
    s.append(grid(["Event", "Date", "Significance"],
                  [["Announcement", C.en(C.ANNOUNCE),
                    "Start of the eleven-month journey to close"],
                   ["Close, Day 1", C.en(C.DAY1),
                    "Legal transfer, brand launch, employee and sales enablement live"],
                   ["Day 30", C.en(C.DAY30),
                    "Opening balance sheet, entity plan, ERP blueprint gate"],
                   ["Flagship customer event", C.en(C.DELL_EMC_WORLD),
                    "External fixed date, cannot move, forces the portfolio milestones"],
                   ["Day 100", C.en(C.DAY100),
                    "Value realisation review to the sponsor, a fixed commitment"]],
                  [4.0, 3.0, 10.0]))

    s.append(Paragraph("7. Distribution and confidentiality", H1))
    s.append(Paragraph("Named recipients only. This summary contains an interpretation of "
                       "contractual terms prepared for planning purposes and is not legal "
                       "advice. Any question about the meaning or effect of a term goes to "
                       "Legal before it is acted on.", BODY))
    sources(s)

    build("DellEMC_VCIO_Merger_Agreement_Key_Terms_2015-10-12.pdf", s,
          f"{C.NEWCO}  |  Merger agreement key terms, integration extract  |  "
          f"Strictly confidential")


if __name__ == "__main__":
    minutes()
    baseline()
    terms()
    print("pdf done")
