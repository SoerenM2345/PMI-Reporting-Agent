"""Populated HTML: exported Outlook escalation thread (DE), Confluence RACI page (EN/DE)."""
import case as C

WIKI_CSS = """
body{font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#222;margin:0;background:#fff}
.wrap{max-width:1040px;margin:0 auto;padding:24px}
h1{font-size:20px;color:#046A38;margin:0 0 4px}
h2{font-size:15px;color:#046A38;margin:22px 0 8px}
h3{font-size:13px;color:#222;margin:16px 0 6px}
.sub{color:#75787B;font-size:12px;margin:0 0 18px}
table{border-collapse:collapse;width:100%;margin:8px 0 14px;font-size:11.5px}
th{background:#046A38;color:#fff;text-align:left;padding:6px 7px;font-weight:bold;
   border:1px solid #cfd8cf;vertical-align:top}
td{padding:6px 7px;border:1px solid #cfd8cf;vertical-align:top;color:#333}
tr:nth-child(even) td{background:#F7F9F3}
.r{color:#DA291C;font-weight:bold}
.a{color:#ED8B00;font-weight:bold}
.g{color:#43B02A;font-weight:bold}
.meta{background:#F1F6E4;border:1px solid #cfd8cf;padding:10px 12px;margin:0 0 16px}
.meta dl{margin:0;display:grid;grid-template-columns:190px 1fr;gap:3px 10px;font-size:12px}
.meta dt{font-weight:bold;color:#222}
.meta dd{margin:0;color:#444}
.note{font-size:11px;color:#75787B;font-style:italic;margin:6px 0 12px}
.warn{background:#FDF3F4;border:1px solid #F1BFC3;padding:8px 10px;font-size:11.5px;
      color:#A4262C;margin:8px 0 14px}
"""

MAIL_CSS = """
body{font-family:'Segoe UI',Calibri,Arial,sans-serif;font-size:13px;color:#201f1e;margin:0;
     background:#f3f2f1}
.wrap{max-width:920px;margin:0 auto;background:#fff;padding:0 0 30px}
.subjectbar{border-bottom:1px solid #e1dfdd;padding:16px 26px}
.subject{font-size:18px;font-weight:600;color:#201f1e;margin:0 0 4px}
.classline{font-size:11px;color:#a4262c;font-weight:600}
.msg{border-bottom:1px solid #edebe9;padding:18px 26px}
.hdr{display:grid;grid-template-columns:74px 1fr;gap:2px 8px;font-size:12px;margin-bottom:12px}
.lbl{color:#605e5c;font-weight:600}
.val{color:#201f1e}
.body{font-size:13px;line-height:1.55;color:#201f1e}
.sig{margin-top:16px;font-size:11px;color:#605e5c;line-height:1.5}
.att{margin-top:12px;font-size:11.5px;color:#0f6cbd}
table.act{border-collapse:collapse;width:100%;margin:12px 0;font-size:11.5px}
table.act th{background:#f3f2f1;text-align:left;padding:5px 6px;border:1px solid #e1dfdd;
             color:#201f1e}
table.act td{padding:5px 6px;border:1px solid #e1dfdd;color:#3b3a39}
.disc{font-size:10px;color:#a19f9d;padding:14px 26px;line-height:1.4}
"""

DISC_EN = ("Synthetic document. The case anchoring follows publicly available sources. All "
           "operational names, figures, risks, decisions and synergy values are invented and "
           "internally consistent; they are not a representation of what any party actually did.")
DISC_DE = ("Synthetisches Dokument. Der Fallbezug folgt oeffentlich verfuegbaren Quellen. Alle "
           "operativen Namen, Zahlen, Risiken, Beschluesse und Synergiewerte sind erfunden und "
           "in sich konsistent; sie stellen keine Aussage darueber dar, was die beteiligten "
           "Parteien tatsaechlich getan haben.")


def tbl(headers, rows, cls=""):
    out = [f'<table class="{cls}"><thead><tr>' + "".join(f"<th>{h}</th>" for h in headers)
           + "</tr></thead><tbody>"]
    for r in rows:
        out.append("<tr>" + "".join(f"<td>{v}</td>" for v in r) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def rag_span(v):
    cls = {"Green": "g", "Amber": "a", "Red": "r", "Gruen": "g", "Gelb": "a", "Rot": "r"}
    return f'<span class="{cls.get(v, "")}">{v}</span>' if v in cls else v


# =====================================================================
# 1. Outlook escalation thread (German), milestone M-07
# =====================================================================
def mail():
    m07 = [m for m in C.MILESTONES if m[0] == "M-07"][0]
    msgs = [
        dict(
            frm=f"{C.nm('prog_dir')} ({C.role('prog_dir')}) "
                f"&lt;a.vasquez@delltechnologies.example&gt;",
            sent=f"{C.de(C.D_MAIL)} 17:42",
            to=f"{C.nm('WS3')}; {C.nm('imo_mgr')}; {C.nm('dach_it')}",
            cc=f"{C.nm('imo_pmo')}; {C.nm('WS5')}; {C.nm('WS1')}; {C.nm('advisor')}",
            subj="AW: AW: Eskalation M-07, Zielbild ERP-Konsolidierung nicht zum "
                 "Basistermin erreichbar",
            body=[
                "vielen Dank fuer die Aufstellung. Ich entscheide das jetzt, damit wir nicht "
                "bis zur Sitzung des Steering Committee warten.",
                f"Erstens: der Prognosetermin fuer M-07 lautet ab sofort "
                f"<b>{C.de(C.M07_MAIL)}</b>. Der im Protokoll der Wochenbesprechung "
                f"festgehaltene Termin {C.de(C.M07_MINUTES)} ist damit ueberholt. Bitte "
                f"unverzueglich im Integration Tracker setzen, nicht nur in der Statusfolie. "
                f"Der Tracker ist nach Beschluss B-02 die fuehrende Quelle.",
                "Zweitens: der Umfang der laufenden Modernisierung des Altsystems bleibt "
                "eingefroren, bis das Zielbild freigegeben ist. Das ist Beschluss B-04 und "
                "gilt unveraendert.",
                f"Drittens: die Empfehlung der Expertenrunde vom {C.de(C.D_EXPERT)} fuer "
                f"Option 3, Zielsystem des Erwerbers mit Migration in zwei Wellen, lege ich "
                f"dem Steering Committee am {C.de(C.STEERCO_02)} zur Bestaetigung vor. Die "
                f"abweichende Meinung der Lieferkette nehme ich ausdruecklich mit in die "
                f"Vorlage auf.",
                f"Viertens, organisatorisch: die Massnahme {C.ACTIONS[0][0]}, Versand der "
                f"aktualisierten Abhaengigkeitskarte, uebernimmt ab sofort "
                f"<b>{C.nm(C.OP01_OWNER_MAIL)}</b> statt {C.nm(C.OP01_OWNER_MINUTES)}. "
                f"Das unterzeichnete Protokoll der Sitzung 01 fuehrt weiterhin "
                f"{C.nm(C.OP01_OWNER_MINUTES)}; ein Korrigendum reiche ich nicht nach, das "
                f"waere unverhaeltnismaessig.",
            ],
            actions=[
                [C.ACTIONS[1][2], C.nm("WS3"), C.de(C.ACTIONS[1][7])],
                [C.ACTIONS[5][2], C.nm("dach_it"), C.de(C.ACTIONS[5][7])],
                [f"Prognosetermin M-07 auf {C.de(C.M07_MAIL)} im Tracker setzen",
                 C.nm("imo_mgr"), C.de(C.TODAY)],
                [C.ACTIONS[0][2], C.nm(C.OP01_OWNER_MAIL), C.de(C.ACTIONS[0][7])],
            ],
            sig=f"{C.nm('prog_dir')}<br/>{C.role('prog_dir')}<br/>{C.OFFICE}<br/>"
                f"{C.NEWCO}",
            att=[f"Expertenrunde_ERP_Konsolidierung_{C.iso(C.D_EXPERT)}.docx",
                 f"Abhaengigkeitskarte_{C.iso(C.TODAY)}.pptx"]),
        dict(
            frm=f"{C.nm('WS3')} ({C.role('WS3')}) &lt;t.bergstroem@delltechnologies.example&gt;",
            sent=f"{C.de(C.D_MAIL)} 15:10",
            to=f"{C.nm('prog_dir')}; {C.nm('imo_mgr')}",
            cc=f"{C.nm('dach_it')}; {C.nm('WS5')}; {C.nm('advisor')}",
            subj="AW: Eskalation M-07, Zielbild ERP-Konsolidierung nicht zum Basistermin "
                 "erreichbar",
            body=[
                f"hier die fachliche Einschaetzung, wie erbeten.",
                f"<b>Ursache.</b> Die Verzoegerung entsteht nicht in der Integrationsarbeit, "
                f"sondern an der Schnittstelle zur laufenden Modernisierung des Altsystems "
                f"beim Zielunternehmen. Beide Vorhaben benoetigen dieselben "
                f"Architekturentscheidungen und im Wesentlichen dieselben Personen. Dieses "
                f"Risiko ist in den oeffentlichen Risikofaktoren der Transaktion ausdruecklich "
                f"benannt worden; es ist nun eingetreten und bei uns als R-01 gefuehrt, "
                f"Schwere {C.sev(C.RISKS[0])}.",
                f"<b>Umfang.</b> Die erneute Extraktion der Materialstammdaten (A-023) steht "
                f"bei {C.TASKS[12][7]} Prozent. Von den betroffenen Datensaetzen fehlen "
                f"weiterhin bei rund 18 Prozent Pflichtfelder; das ist als Vorgang I-01 "
                f"erfasst. Ohne verwertbare Stammdaten ist keine belastbare Aufwandsschaetzung "
                f"und damit keine Freigabe des Zielbilds moeglich.",
                f"<b>Optionen.</b> Die Expertenrunde hat drei Optionen bewertet und empfiehlt "
                f"Option 3 mit einer gewichteten Bewertung von 4,00 gegenueber 3,50 fuer "
                f"Option 2 und 3,30 fuer Option 1. {C.nm('WS5')} hat eine abweichende Meinung "
                f"zu Protokoll gegeben und haelt Option 1 fuer vorzugswuerdig.",
                f"<b>Termin.</b> Der im Protokoll der Wochenbesprechung festgehaltene "
                f"Prognosetermin {C.de(C.M07_MINUTES)} ist nach der Sitzung nicht mehr "
                f"haltbar, weil die Stammdatenextraktion erst zum "
                f"{C.de(C.TASKS[12][5])} verwertbar vorliegt. Mein Vorschlag lautet "
                f"{C.de(C.M07_MAIL)}. Damit betraegt die Abweichung gegenueber dem "
                f"Basistermin {C.de(m07[6])} genau {(C.M07_MAIL - m07[6]).days} Tage.",
                f"<b>Folgewirkung.</b> Die Abhaengigkeit D-02 zur Lieferkette bleibt bis dahin "
                f"im Status verzoegert. Die Synergien S-04 und S-05 verschieben sich zeitlich, "
                f"in der Hoehe bleiben sie unveraendert.",
            ],
            actions=None,
            sig=f"{C.nm('WS3')}<br/>{C.role('WS3')}<br/>{C.NEWCO}",
            att=[f"M-07_Wiederanlaufplan_Entwurf_{C.iso(C.D_MAIL)}.xlsx"]),
        dict(
            frm=f"{C.nm('imo_mgr')} ({C.role('imo_mgr')}) "
                f"&lt;d.okonjo@delltechnologies.example&gt;",
            sent=f"{C.de(C.D_MAIL)} 09:05",
            to=f"{C.nm('WS3')}",
            cc=f"{C.nm('prog_dir')}; {C.nm('imo_pmo')}",
            subj="Eskalation M-07, Zielbild ERP-Konsolidierung nicht zum Basistermin "
                 "erreichbar",
            body=[
                f"im VCIO Weekly am {C.de(C.D_PROTOKOLL)} wurde M-07 erneut als verzoegert "
                f"gemeldet. Der Basistermin lautet {C.de(m07[6])}, das ist ein "
                f"gate-relevanter Meilenstein.",
                f"Im Integration Tracker ist bislang keine datierte Gegenmassnahme hinterlegt. "
                f"Nach der Eskalationsregel der Integration Charter geht ein gate-relevanter "
                f"Meilenstein mit mehr als sieben Tagen Verzug an das Steering Committee; "
                f"die naechste Sitzung ist am {C.de(C.STEERCO_02)}.",
                "Bitte bis heute 16:00 Uhr um Rueckmeldung zu drei Punkten:",
                "1. Was ist die Ursache der Verzoegerung und liegt sie innerhalb oder "
                "ausserhalb des Teilprojekts?",
                "2. Welcher Prognosetermin ist belastbar und woran haengt er?",
                "3. Welche abhaengigen Arbeitspakete und Synergien sind betroffen?",
                f"Zur Erinnerung: die Massnahme {C.ACTIONS[1][0]} aus der Sitzung 01 des "
                f"Steering Committee, Vorlage des Wiederanlaufplans mit datierter Prognose, "
                f"ist heute faellig.",
            ],
            actions=None,
            sig=f"{C.nm('imo_mgr')}<br/>{C.role('imo_mgr')}<br/>{C.OFFICE}",
            att=[]),
    ]

    p = ["<!DOCTYPE html><html lang='de'><head><meta charset='utf-8'>",
         "<title>Eskalation M-07, Zielbild ERP-Konsolidierung</title>",
         f"<style>{MAIL_CSS}</style></head><body><div class='wrap'>",
         "<div class='subjectbar'>",
         "<p class='subject'>AW: AW: Eskalation M-07, Zielbild ERP-Konsolidierung nicht zum "
         "Basistermin erreichbar</p>",
         f"<p class='classline'>Streng vertraulich &ndash; {C.PROGRAM} &ndash; "
         f"{C.OFFICE} ({C.OFFICE_ABBR})</p></div>"]

    for m in msgs:
        p.append("<div class='msg'><div class='hdr'>")
        for lbl, val in (("Von:", m["frm"]), ("Gesendet:", m["sent"]), ("An:", m["to"]),
                         ("Cc:", m["cc"]), ("Betreff:", m["subj"])):
            p.append(f"<div class='lbl'>{lbl}</div><div class='val'>{val}</div>")
        p.append("</div><div class='body'><p>Hallo zusammen,</p>")
        for b in m["body"]:
            p.append(f"<p>{b}</p>")
        if m["actions"]:
            p.append("<table class='act'><thead><tr><th>Aufgabe</th><th>Verantwortlich</th>"
                     "<th>Faellig am</th></tr></thead><tbody>")
            for a in m["actions"]:
                p.append("<tr>" + "".join(f"<td>{x}</td>" for x in a) + "</tr>")
            p.append("</tbody></table>")
        p.append("<p>Viele Gruesse</p>")
        p.append(f"<div class='sig'>{m['sig']}</div>")
        if m["att"]:
            p.append("<div class='att'>" + " &nbsp;&nbsp; ".join(
                f"&#128206; {a}" for a in m["att"]) + "</div>")
        p.append("</div></div>")

    p.append(f"<div class='disc'>Diese Nachricht enthaelt vertrauliche Informationen zum "
             f"{C.PROGRAM}. Weiterleitung nur an den in der Integration Charter genannten "
             f"Personenkreis.<br/><br/>Exportiert aus Microsoft Outlook am "
             f"{C.de(C.TODAY)} durch {C.nm('imo_pmo')}. Ablage: Integration Hub &gt; "
             f"{C.OFFICE_ABBR} &gt; Eskalationen &gt; M-07.<br/><br/>{DISC_DE}</div>")
    p.append("</div></body></html>")

    (C.OUT / "DellEMC_VCIO_Eskalation_Mailverlauf_M-07_2016-09-28.html").write_text(
        "\n".join(p), encoding="utf-8")


# =====================================================================
# 2. Confluence RACI page
# =====================================================================
def raci():
    p = ["<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
         f"<title>{C.OFFICE_ABBR} RACI Matrix and Ownership | Integration Hub</title>",
         f"<style>{WIKI_CSS}</style></head><body><div class='wrap'>",
         f"<p class='sub'>Integration Hub &gt; {C.PROGRAM} &gt; Governance &gt; "
         f"RACI Matrix and Ownership</p>",
         f"<h1>{C.OFFICE} ({C.OFFICE_ABBR}) &ndash; RACI Matrix and Ownership</h1>",
         "<p class='sub'>Single source of truth for who is Responsible, Accountable, "
         "Consulted and Informed across the integration, and for who currently holds each "
         "role. This page governs where it disagrees with the role cards document.</p>",
         "<div class='meta'><dl>"]
    for k, v in [("Space", "Integration Hub"),
                 ("Page owner", f"{C.nm('imo_mgr')}, {C.role('imo_mgr')}"),
                 ("Created", f"{C.en(C.D_ROLECARDS)}, during mobilisation"),
                 ("Last edited by", f"{C.nm('imo_pmo')}"),
                 ("Last edited on", C.en(C.D_RACI)),
                 ("Version", "7"),
                 ("Review cycle", "Every two weeks, before the Steering Committee"),
                 ("Approved by", f"{C.nm('prog_dir')}, {C.role('prog_dir')}"),
                 ("Classification", "Strictly confidential"),
                 ("Related pages", "Integration Charter | Governance and Decision Rights | "
                                   "Workstream Charters | Escalation Path | Decision Log")]:
        p.append(f"<dt>{k}</dt><dd>{v}</dd>")
    p.append("</dl></div>")

    p.append("<h2>1. Legend</h2>")
    p.append(tbl(["Code", "Meaning", "Rule"], [
        ["R", "Responsible", "Does the work. More than one R is allowed."],
        ["A", "Accountable", "Answerable for the outcome. Exactly one A per activity, never "
                             "zero and never two."],
        ["C", "Consulted", "Two-way, before the decision is taken."],
        ["I", "Informed", "One-way, after the decision is taken."],
    ]))
    p.append("<p class='note'>A row with two A entries or none is an ownership gap and is "
             "listed in section 7 until resolved.</p>")

    p.append("<h2>2. RACI by integration activity</h2>")
    activities = [
        ("ACT-01", "Set and maintain the master milestone plan", "Day 1 to Day 100",
         {"imo_mgr": "A", "imo_pmo": "R", "prog_dir": "C", "leads": "C"}),
        ("ACT-02", "Maintain the integration tracker as the single source of truth",
         "Continuous", {"imo_pmo": "A", "imo_mgr": "R", "leads": "R", "prog_dir": "I"}),
        ("ACT-03", "Confirm cross-workstream handover dates", "Continuous",
         {"imo_mgr": "A", "leads": "R", "prog_dir": "I", "imo_pmo": "I"}),
        ("ACT-04", "Score and prioritise initiatives in the value framework", "Day 1 to Day 30",
         {"synergy": "A", "advisor": "R", "prog_dir": "C", "leads": "C"}),
        ("ACT-05", "Validate synergy initiatives with Finance", "Continuous",
         {"synergy": "A", "WS1": "R", "leads": "C", "prog_dir": "I"}),
        ("ACT-06", "Maintain the RAID register and apply the escalation threshold",
         "Continuous", {"risk": "A", "leads": "R", "imo_mgr": "C", "prog_dir": "I"}),
        ("ACT-07", "Approve the legal entity rationalisation plan", "Day 1 to Day 30",
         {"prog_dir": "A", "WS2": "R", "WS1": "C", "imo_mgr": "I"}),
        ("ACT-08", "Sign off the ERP consolidation blueprint", "Day 1 to Day 30",
         {"prog_dir": "A", "WS3": "R", "WS5": "C", "WS1": "C"}),
        ("ACT-09", "Release the combined organisation structure", "Day 30 to Day 100",
         {"WS4": "A", "br_liaison": "R", "change": "C", "prog_dir": "C"}),
        ("ACT-10", "Discharge works council consultation obligations", "Day 30 to Day 100",
         {"br_liaison": "A", "WS4": "R", "dach_lead": "C", "prog_dir": "I"}),
        ("ACT-11", "Agree the territory and quota model for the combined field",
         "Day 30 to Day 100", {"WS6": "A", "WS4": "C", "prog_dir": "I", "imo_mgr": "I"}),
        ("ACT-12", "Renegotiate wave 1 supplier contracts", "Day 30 to Day 100",
         {"WS5": "A", "WS1": "C", "synergy": "C", "prog_dir": "I"}),
        ("ACT-13", "Approve the EMEA site consolidation plan", "Day 30 to Day 100",
         {"WS7": "A", "dach_lead": "C", "WS1": "C", "prog_dir": "I"}),
        ("ACT-14", "Communicate to employees and customers", "Continuous",
         {"change": "A", "WS6": "R", "br_liaison": "C", "prog_dir": "C"}),
        ("ACT-15", "Deliver the Day 100 value realisation review", "Day 30 to Day 100",
         {"prog_dir": "A", "synergy": "R", "imo_pmo": "R", "leads": "C"}),
    ]
    cols = ["prog_dir", "imo_mgr", "imo_pmo", "synergy", "risk", "change", "br_liaison",
            "advisor", "leads"]
    colhead = [C.role(k).replace("VCIO ", "") if k != "leads" else "Workstream leads"
               for k in cols]
    rows = []
    for aid, name, phase, m in activities:
        cells = []
        for k in cols:
            v = m.get(k, "")
            if not v:
                for wk in C.WS_CODES:
                    if wk in m and k == "leads":
                        v = m[wk]
            cells.append(v)
        # workstream-specific entries collapse into the leads column
        for wk in C.WS_CODES:
            if wk in m:
                cells[-1] = f"{m[wk]} ({wk})"
        na = sum(1 for x in cells if x.startswith("A"))
        gap = "" if na == 1 else '<span class="r">yes</span>'
        rows.append([aid, name, phase] + cells + [gap])
    p.append(tbl(["ID", "Integration activity", "Phase"] + colhead + ["Ownership gap"], rows))

    p.append("<h2>3. RACI by workstream deliverable</h2>")
    for code in C.WS_CODES:
        p.append(f"<h3>{code} {C.WS_NAME[code]} &ndash; lead {C.nm(code)}</h3>")
        rows = []
        for m in C.ws_milestones(code):
            rows.append([m[0], m[1], m[5],
                         C.nm(m[4]) if m[4] in C.PEOPLE else C.nm(code),
                         C.nm(code), C.nm("imo_mgr"), C.nm("prog_dir"), "Yes"])
        p.append(tbl(["ID", "Deliverable", "Phase", "Responsible (R)", "Accountable (A)",
                      "Consulted (C)", "Informed (I)", "Confirmed by role holder"], rows))

    p.append("<h2>4. Current role holders</h2>")
    p.append("<p class='note'>This table, not the role cards document, reflects current "
             "staffing. Update here first, then notify HR so the role card can follow.</p>")
    holders = []
    for k in ["prog_dir", "imo_mgr", "imo_pmo", "synergy", "risk", "change", "br_liaison",
              "dach_lead", "advisor"]:
        holders.append([C.role(k), C.nm(k), "-", C.en(C.D_ROLECARDS), "-",
                        "1.0 FTE" if k in ("prog_dir", "imo_mgr", "imo_pmo") else "0.5 to 0.8 FTE",
                        C.role("prog_dir") if k != "prog_dir" else f"{C.OFFICE_ABBR} co-leads"])
    for code in C.WS_CODES:
        prev = C.nm("hc_prev") if code == "WS4" else "-"
        since = C.en(C.MILESTONES[0][6]) if code != "WS4" else "16 September 2016"
        holders.append([f"Workstream Lead, {C.WS_NAME[code]}", C.nm(code), "-", since,
                        prev, "0.8 FTE", C.role("prog_dir")])
    p.append(tbl(["Role", "Current holder", "Deputy", "Since", "Previous holder",
                  "FTE commitment", "Reports to"], holders))
    p.append(f'<div class="warn">Change on {C.en(C.MILESTONES[0][6]).replace("7 September", "16 September")}: '
             f'the Human Capital workstream lead changed from {C.nm("hc_prev")} to '
             f'{C.nm("WS4")}. The role cards document dated {C.en(C.D_ROLECARDS)} still names '
             f'the previous holder and has not been reissued. This page governs. Action '
             f'{C.ACTIONS[7][0]} tracks the correction.</div>')

    p.append("<h2>5. Decision thresholds</h2>")
    p.append(tbl(["Decision type", "Decided by", "Threshold", "Escalates to",
                  "Required within"], [
        ["Scope change within an approved workstream scope", "Workstream lead",
         "Up to 10 percent of workstream effort", C.role("prog_dir"), "5 working days"],
        ["Scope change across workstreams", C.role("prog_dir"), "Up to USD 5 m",
         "Steering Committee", "1 committee cycle"],
        ["Scope change above threshold", "Steering Committee", "Above USD 5 m",
         f"{C.OFFICE_ABBR} co-leads", "1 committee cycle"],
        ["Milestone baseline change", "Steering Committee", "Any gate-relevant milestone",
         f"{C.OFFICE_ABBR} co-leads", "1 committee cycle"],
        ["Risk acceptance", C.role("prog_dir"),
         f"Severity below {C.ESCALATION_THRESHOLD}", "Steering Committee", "Immediate"],
        ["Synergy value reported externally", C.role("synergy"),
         "Finance-validated initiatives only", "Steering Committee", "Immediate"],
    ]))

    p.append("<h2>6. Escalation path</h2>")
    p.append(tbl(["Level", "Body or role", "Trigger", "Response time", "Recorded in"], [
        ["1", "Workstream lead", "Any task overdue or blocked", "Same week",
         "Integration tracker"],
        ["2", C.role("imo_mgr"), "Any milestone forecast beyond baseline",
         "Within 2 working days", "Integration tracker, milestone tab"],
        ["3", C.role("prog_dir"),
         "Any gate-relevant milestone delayed by more than 7 days", "Within 1 working day",
         "Weekly highlight report"],
        ["4", "Steering Committee",
         f"Any risk at severity {C.ESCALATION_THRESHOLD} or above", "Next session",
         "Steering Committee minutes"],
    ]))

    p.append("<h2>7. Open ownership gaps</h2>")
    p.append(tbl(["Gap ID", "Activity", "Nature of the gap", "Raised on", "Raised by",
                  "Proposed owner", "Status"], [
        ["G-01", "ACT-09 Release the combined organisation structure",
         "Accountability sits with the workstream lead but the release cannot happen without "
         "the consultation being discharged, which is accountable elsewhere",
         C.en(C.D_PROTOKOLL), C.nm("imo_mgr"), C.nm("br_liaison"), "Open"],
        ["G-02", "Cross-workstream handover D-01 and D-07",
         "Only one lead has confirmed the handover date, contrary to decision B-03",
         C.en(C.D_RACI), C.nm("imo_mgr"), f"{C.nm('WS2')} and {C.nm('WS1')}", "Open"],
    ]))
    p.append(f"<p class='note'>{C.DEP_UNCONFIRMED_CRITICAL} critical or high dependencies are "
             f"currently confirmed by one side only. See the dependency register in the "
             f"integration tracker.</p>")

    p.append("<h2>8. Change log</h2>")
    p.append(tbl(["Date", "Changed by", "What changed", "Reason", "Communicated to"], [
        [C.en(C.D_RACI), C.nm("imo_pmo"),
         "Updated the Human Capital role holder and added gap G-02",
         "Lead change and unconfirmed dependencies", "All workstream leads"],
        [C.en(C.D_PROTOKOLL), C.nm("imo_mgr"), "Added gap G-01",
         "Raised in the weekly meeting", f"{C.role('prog_dir')}"],
        [C.en(C.STEERCO_01), C.nm("imo_mgr"),
         "Added the decision threshold for externally reported synergy value",
         "Decision B-06", "Steering Committee"],
        [C.en(C.D_ROLECARDS), C.nm("imo_mgr"), "Page created", "Mobilisation",
         "All"],
    ]))

    p.append(f"<p class='note'>Page exported from the Integration Hub on {C.en(C.TODAY)}. "
             f"Exported copies go stale. Check the live page before acting on it.</p>")
    p.append(f"<p class='note'>{DISC_EN}</p>")
    p.append("<p class='note'>Sources for the case anchoring: "
             + "; ".join(C.SOURCES) + "</p>")
    p.append("</div></body></html>")

    (C.OUT / "DellEMC_VCIO_RACI_Matrix_Integration_Hub_2016-09-23.html").write_text(
        "\n".join(p), encoding="utf-8")


if __name__ == "__main__":
    mail()
    raci()
    print("html done")
