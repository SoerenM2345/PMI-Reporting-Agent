"""SINGLE SOURCE OF TRUTH for the Dell-EMC synthetic corpus.

Every document generator reads from this module. No figure is ever typed twice: aggregates
(counts, percentages, sums) are computed from the record lists below, so the SteerCo deck,
the tracker, the dashboard and the minutes cannot drift apart.

The ONLY permitted divergences are the six entries in PLANTED_CONFLICTS, which are
deliberate and documented.

--------------------------------------------------------------------------------------
FACT PROVENANCE
  [PUBLIC]    verifiable in the sources listed in SOURCES below
  [SYNTHETIC] invented for the test corpus, internally consistent, not a claim about
              what Dell, EMC or Deloitte actually did
--------------------------------------------------------------------------------------
"""
from datetime import date
from pathlib import Path

OUT = Path("/sessions/inspiring-great-ptolemy/mnt/02_Sommer 26--PMI/GIT/"
           "PMI-Reporting_Agent/Syntetic_data")
OUT.mkdir(parents=True, exist_ok=True)
TEMPLATE = "/sessions/inspiring-great-ptolemy/mnt/outputs/DeloitteMaster.pptx"

SOURCES = [
    "EMC Corp, Form 8-K Exhibit 99.1, filed 7 September 2016 (SEC EDGAR)",
    "Deloitte Global, 'Dell, EMC, and Deloitte create the next tech icon: a technology "
    "M&A case study', deloitte.com",
    "Dell Technologies press release, 7 September 2016",
]

# ======================================================================= the deal
PROGRAM = "Dell Technologies Integration"          # [PUBLIC] the combination itself
OFFICE = "Value Creation Integration Office"       # [PUBLIC] the VCIO, per Deloitte case study
OFFICE_ABBR = "VCIO"
ACQUIRER = "Dell Inc."                             # [PUBLIC]
TARGET = "EMC Corporation"                         # [PUBLIC]
NEWCO = "Dell Technologies"                        # [PUBLIC]
ADVISOR = "Deloitte Consulting LLP"                # [PUBLIC] named external advisor

DEAL_VALUE = "USD 58 billion"                      # [PUBLIC] Deloitte case study
DEAL_VALUE_HEADLINE = "USD 67 billion"             # [PUBLIC] announced headline value
CASH_PER_SHARE = "USD 24.05"                       # [PUBLIC] 8-K
TRACKING_RATIO = "0.11146"                         # [PUBLIC] DVMT shares per EMC share
DEBT_COMMITMENT = "USD 49.5 billion"               # [PUBLIC] committed debt financing
COMBINED_REVENUE = "USD 74 billion"                # [PUBLIC] 8-K
EMPLOYEES = 140000                                 # [PUBLIC] Deloitte case study
SALES_PROFESSIONALS = 40000                        # [PUBLIC] e-runbook audience
COUNTRIES = 180                                    # [PUBLIC]
FORTUNE_500_PCT = 98                               # [PUBLIC]
GARTNER_MQ = 20                                    # [PUBLIC]
PATENTS = "20,000+"                                # [PUBLIC]
WORKSTREAM_COUNT_TOTAL = "more than 20"            # [PUBLIC] Deloitte case study
JOURNEY_MONTHS = 11                                # [PUBLIC] announcement to close

FAMILY = ["Dell client solutions", "Dell EMC infrastructure solutions", "Dell EMC Services",
          "Boomi", "Pivotal", "RSA", "SecureWorks", "Virtustream", "VMware"]   # [PUBLIC]

# ======================================================================= timeline
ANNOUNCE = date(2015, 10, 12)      # [PUBLIC]
DAY1 = date(2016, 9, 7)            # [PUBLIC] close of the merger
DAY30 = date(2016, 10, 7)          # [SYNTHETIC] derived
DAY100 = date(2016, 12, 16)        # [SYNTHETIC] derived
DELL_EMC_WORLD = date(2016, 10, 18)  # [PUBLIC] Dell EMC World 2016, 18-20 October, Austin
TODAY = date(2016, 9, 29)          # [SYNTHETIC] Thursday, day 22 after Day 1
WEEK_START = date(2016, 9, 26)
WEEK_END = date(2016, 9, 30)
WEEK_LABEL = "W3 (26 - 30 September 2016)"
CW = "KW 39"
DAYS_AFTER_DAY1 = (TODAY - DAY1).days
DAYS_TO_DAY100 = (DAY100 - TODAY).days

STEERCO_01 = date(2016, 9, 15)     # first SteerCo after Day 1
STEERCO_01_SIGNED = date(2016, 9, 22)
STEERCO_02 = date(2016, 9, 29)     # today

# document dates
D_ROADMAP = date(2016, 9, 16)
D_EXPERT = date(2016, 9, 21)
D_ROLECARDS = date(2016, 8, 1)
D_RACI = date(2016, 9, 23)
D_ORG = date(2016, 8, 25)
D_BASELINE = date(2016, 9, 2)
D_MERGER_TERMS = ANNOUNCE
D_WS_ONEPAGER = date(2016, 9, 28)
D_PROTOKOLL = date(2016, 9, 27)
D_TRACKER = date(2016, 9, 29)
D_SYNERGY = date(2016, 9, 28)
D_DASHBOARD = date(2016, 9, 29)
D_MAIL = date(2016, 9, 28)
D_TEAMS = date(2016, 9, 29)
D_HIGHLIGHT = date(2016, 9, 30)


def de(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def en(d: date) -> str:
    return d.strftime("%d %B %Y").lstrip("0")


def iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


# ======================================================================= workstreams
# [PUBLIC] the seven functional areas Deloitte names in the case study. The programme
# ran more than 20 workstreams in total; these seven report into the SteerCo.
WORKSTREAMS = [
    ("WS1", "Finance", "Finanzen"),
    ("WS2", "Tax", "Steuern"),
    ("WS3", "IT", "IT"),
    ("WS4", "Human Capital", "Personal"),
    ("WS5", "Supply Chain", "Lieferkette"),
    ("WS6", "Go-to-Market", "Vertrieb und Marketing"),
    ("WS7", "Real Estate", "Immobilien"),
]
WS_CODES = [c for c, _, _ in WORKSTREAMS]
WS_NAME = {c: n for c, n, _ in WORKSTREAMS}
WS_NAME_DE = {c: n for c, _, n in WORKSTREAMS}


def ws_full(code):
    return f"{code} {WS_NAME[code]}"


# ======================================================================= people
# [PUBLIC] documented governance. Real people, named only in their documented roles.
# No statement, decision or action anywhere in this corpus is attributed to them.
PUBLIC_GOVERNANCE = [
    ("Michael Dell", "Chairman and CEO, Dell Technologies", "Executive Sponsor"),
    ("Rory Read", "Chief Operating Executive, Dell", f"{OFFICE_ABBR} Co-Lead"),
    ("Howard Elias", "President and COO, EMC", f"{OFFICE_ABBR} Co-Lead"),
    ("Lukas L. Hoebarth", f"Principal, {ADVISOR}", "Lead Advisory Partner"),
]

# [SYNTHETIC] every operational name below is invented. All meeting statements,
# decisions, actions, risks and escalations in the corpus belong to these people.
PEOPLE = {
    "prog_dir":  ("A. Vasquez", "VCIO Programme Director"),
    "imo_mgr":   ("D. Okonjo", "VCIO Integration Manager"),
    "imo_pmo":   ("S. Lindqvist", "VCIO Reporting Lead"),
    "synergy":   ("M. Haddad", "Value Realisation Controller"),
    "risk":      ("P. Nakamura", "Integration Risk Officer"),
    "change":    ("E. Brannigan", "Change and Communications Lead"),
    "advisor":   ("C. Ferreira", f"Engagement Manager, {ADVISOR}"),
    "WS1":       ("R. Whitfield", "Workstream Lead, Finance"),
    "WS2":       ("N. Devereux", "Workstream Lead, Tax"),
    "WS3":       ("T. Bergström", "Workstream Lead, IT"),
    "WS4":       ("J. Adeyemi", "Workstream Lead, Human Capital"),
    "WS5":       ("K. Matsuda", "Workstream Lead, Supply Chain"),
    "WS6":       ("L. Kowalczyk", "Workstream Lead, Go-to-Market"),
    "WS7":       ("F. Ricciardi", "Workstream Lead, Real Estate"),
    "dach_lead": ("H. Wegener", "Regional Integration Lead, DACH"),
    "dach_hr":   ("B. Steinmüller", "HR Integration Manager, DACH"),
    "dach_it":   ("G. Aydin", "IT Integration Manager, DACH"),
    "dach_fin":  ("U. Hoffmeister", "Finance Integration Manager, DACH"),
    "br_liaison": ("W. Kempowski", "Betriebsratskoordination DACH"),
    "hc_prev":   ("V. Osei-Bonsu", "Workstream Lead, Human Capital (until 16.09.2016)"),
}


def nm(key):
    return PEOPLE[key][0]


def role(key):
    return PEOPLE[key][1]


# ======================================================================= milestones
# status: on_track | at_risk | delayed | done
# (id, title_en, title_de, ws, owner_key, phase, baseline, forecast, status, gate, comment_en)
MILESTONES = [
    ("M-01", "Day 1 legal close and brand launch executed",
     "Day 1 Vollzug und Markenauftritt umgesetzt", "WS6", "WS6", "Day 1",
     date(2016, 9, 7), date(2016, 9, 7), "done", True,
     "Closed on schedule. New Dell Technologies and Dell EMC branding launched the same day."),
    ("M-02", "Day 1 employee welcome eGuide live for all 140,000 employees",
     "Willkommens-eGuide zu Day 1 fuer alle 140.000 Mitarbeitenden verfuegbar", "WS4", "WS4",
     "Day 1", date(2016, 9, 7), date(2016, 9, 7), "done", True,
     "Digital tool delivered with advisory support. Adoption tracking continues to Day 30."),
    ("M-03", "Sales e-runbook live for 40,000+ sales professionals",
     "Vertriebs-Runbook fuer ueber 40.000 Vertriebsmitarbeitende verfuegbar", "WS6", "WS6",
     "Day 1", date(2016, 9, 7), date(2016, 9, 7), "done", True,
     "Cross-sell guidance for the combined portfolio available at close."),
    ("M-04", "Combined opening balance sheet prepared",
     "Kombinierte Eroeffnungsbilanz erstellt", "WS1", "WS1", "Day 1 to Day 30",
     date(2016, 10, 7), date(2016, 10, 7), "on_track", True,
     "Purchase price allocation input from valuation advisor received on schedule."),
    ("M-05", "Legal entity rationalisation plan approved",
     "Plan zur Gesellschaftsrechtlichen Straffung freigegeben", "WS2", "WS2",
     "Day 1 to Day 30", date(2016, 10, 7), date(2016, 10, 14), "delayed", True,
     "Slipped one week. Tax review of the EMEA entity chain is not complete."),
    ("M-06", "Interim consolidated reporting pack produced",
     "Vorlaeufiges Konzernberichtspaket erstellt", "WS1", "WS1", "Day 1 to Day 30",
     date(2016, 10, 7), date(2016, 10, 7), "on_track", False,
     "First combined management pack for the sponsor."),
    ("M-07", "ERP consolidation blueprint signed off",
     "Zielbild ERP-Konsolidierung freigegeben", "WS3", "WS3", "Day 1 to Day 30",
     date(2016, 10, 7), date(2016, 10, 21), "delayed", True,
     "Two weeks late. Legacy ERP upgrade at the target ran into the integration design. "
     "See escalation thread and expert session record."),
    ("M-08", "Single sign-on and directory federation live",
     "Einheitliche Anmeldung und Verzeichnisfoederation aktiv", "WS3", "WS3",
     "Day 1 to Day 30", date(2016, 10, 7), date(2016, 10, 7), "on_track", False,
     "Pilot population migrated, full cutover on plan."),
    ("M-09", "Harmonised sales compensation plan communicated",
     "Harmonisiertes Verguetungsmodell Vertrieb kommuniziert", "WS4", "WS4",
     "Day 1 to Day 30", date(2016, 10, 7), date(2016, 10, 11), "at_risk", True,
     "Depends on works council consultation in DACH concluding first."),
    ("M-10", "Supplier master consolidated for top 200 vendors",
     "Lieferantenstammdaten fuer die 200 groessten Lieferanten konsolidiert", "WS5", "WS5",
     "Day 1 to Day 30", date(2016, 10, 7), date(2016, 10, 7), "on_track", False,
     "Data cleanse complete for 168 of 200 vendors."),
    ("M-11", "Combined portfolio presented at Dell EMC World",
     "Kombiniertes Portfolio auf der Dell EMC World praesentiert", "WS6", "WS6",
     "Day 30 to Day 100", date(2016, 10, 18), date(2016, 10, 18), "on_track", True,
     "Fixed external date, 18 to 20 October, Austin. Cannot move."),
    ("M-12", "Account coverage model in force for the combined field",
     "Kundenbetreuungsmodell fuer die kombinierte Vertriebsorganisation in Kraft", "WS6", "WS6",
     "Day 30 to Day 100", date(2016, 11, 4), date(2016, 11, 4), "on_track", True,
     "Territory and quota alignment for the merged field organisation."),
    ("M-13", "Works council consultation DACH concluded",
     "Anhoerung der Betriebsraete DACH abgeschlossen", "WS4", "dach_hr",
     "Day 30 to Day 100", date(2016, 10, 28), date(2016, 11, 11), "delayed", True,
     "Two weeks late. Consultation under German co-determination law is a hard legal gate."),
    ("M-14", "Site consolidation plan approved for EMEA",
     "Standortkonzept EMEA freigegeben", "WS7", "WS7", "Day 30 to Day 100",
     date(2016, 11, 18), date(2016, 11, 18), "on_track", False,
     "Lease expiry analysis complete for 41 of 52 EMEA sites."),
    ("M-15", "Transfer pricing model for the combined group agreed",
     "Verrechnungspreismodell fuer den kombinierten Konzern abgestimmt", "WS2", "WS2",
     "Day 30 to Day 100", date(2016, 11, 25), date(2016, 11, 25), "on_track", True,
     "Documentation drafting begins once the entity plan is approved."),
    ("M-16", "Procurement synergy wave 1 contracts renegotiated",
     "Beschaffungssynergien Welle 1 nachverhandelt", "WS5", "WS5", "Day 30 to Day 100",
     date(2016, 12, 2), date(2016, 12, 2), "on_track", True,
     "Covers logistics, components and indirect categories."),
    ("M-17", "Day 100 value realisation review delivered to the sponsor",
     "Wertrealisierungsbericht Day 100 an den Sponsor uebergeben", "WS1", "imo_mgr",
     "Day 30 to Day 100", DAY100, DAY100, "on_track", True,
     "Fixed commitment. Cannot move without sponsor approval."),
    ("M-18", "Integration organisation transitioned to run",
     "Integrationsorganisation in den Regelbetrieb ueberfuehrt", "WS4", "imo_mgr",
     "Post Day 100", date(2016, 12, 16), date(2016, 12, 16), "on_track", False,
     "Handover of open items to functional owners."),
]

MS_ON_TRACK = sum(1 for m in MILESTONES if m[8] in ("on_track", "done"))
MS_TOTAL = len(MILESTONES)
MS_DELAYED = sum(1 for m in MILESTONES if m[8] == "delayed")
MS_AT_RISK = sum(1 for m in MILESTONES if m[8] == "at_risk")
MS_DONE = sum(1 for m in MILESTONES if m[8] == "done")
MS_GATE = sum(1 for m in MILESTONES if m[9])
MS_MAX_SLIP = max((m[7] - m[6]).days for m in MILESTONES)

# ======================================================================= tasks
# (id, title_en, title_de, ws, owner_key, due, status, progress, priority, dependency)
# status: Open | In progress | Done | Blocked | Overdue
TASKS = [
    ("A-001", "Map EMC chart of accounts to the Dell group chart",
     "Kontenplan des Zielunternehmens auf den Konzernkontenplan abbilden",
     "WS1", "WS1", date(2016, 10, 3), "In progress", 70, "High", ""),
    ("A-002", "Align statutory close calendar across both groups",
     "Abschlusskalender beider Gruppen angleichen",
     "WS1", "WS1", date(2016, 9, 30), "In progress", 85, "High", ""),
    ("A-003", "Define consolidation scope for the first combined quarter",
     "Konsolidierungskreis fuer das erste kombinierte Quartal festlegen",
     "WS1", "dach_fin", date(2016, 10, 14), "Open", 20, "High", "A-012"),
    ("A-004", "Produce purchase price allocation input pack",
     "Datenpaket zur Kaufpreisallokation erstellen",
     "WS1", "WS1", date(2016, 9, 28), "Done", 100, "High", ""),
    ("A-005", "Reconcile intercompany balances at close date",
     "Konzerninterne Salden zum Stichtag abstimmen",
     "WS1", "dach_fin", date(2016, 10, 21), "Open", 0, "Medium", "A-001"),
    ("A-006", "Draft treasury and cash pooling target model",
     "Zielmodell fuer Treasury und Cash Pooling entwerfen",
     "WS1", "WS1", date(2016, 11, 4), "Open", 10, "Medium", ""),
    ("A-011", "Complete tax review of the EMEA entity chain",
     "Steuerliche Pruefung der EMEA-Gesellschaftskette abschliessen",
     "WS2", "WS2", date(2016, 10, 7), "Overdue", 55, "High", ""),
    ("A-012", "Issue the legal entity rationalisation plan for approval",
     "Plan zur gesellschaftsrechtlichen Straffung zur Freigabe vorlegen",
     "WS2", "WS2", date(2016, 10, 12), "Blocked", 40, "High", "A-011"),
    ("A-013", "Draft transfer pricing documentation outline",
     "Gliederung der Verrechnungspreisdokumentation entwerfen",
     "WS2", "WS2", date(2016, 11, 11), "Open", 5, "Medium", "A-012"),
    ("A-014", "Assess permanent establishment exposure in 12 jurisdictions",
     "Betriebsstaettenrisiko in zwoelf Jurisdiktionen bewerten",
     "WS2", "WS2", date(2016, 10, 28), "In progress", 30, "Medium", ""),
    ("A-021", "Complete application landscape inventory for both estates",
     "Anwendungslandschaft beider Unternehmen vollstaendig erfassen",
     "WS3", "WS3", date(2016, 9, 23), "Done", 100, "High", ""),
    ("A-022", "Agree the ERP target system and migration path",
     "Zielsystem und Migrationspfad fuer das ERP festlegen",
     "WS3", "WS3", date(2016, 9, 30), "Overdue", 60, "High", "A-021"),
    ("A-023", "Re-extract material master with corrected field mapping",
     "Materialstammdaten mit korrigiertem Feldmapping erneut extrahieren",
     "WS3", "dach_it", date(2016, 10, 5), "In progress", 45, "High", "A-022"),
    ("A-024", "Migrate pilot population to federated single sign-on",
     "Pilotgruppe auf die foederierte Anmeldung migrieren",
     "WS3", "WS3", date(2016, 9, 30), "In progress", 80, "Medium", ""),
    ("A-025", "Complete network interconnect between the two backbones",
     "Netzkopplung zwischen beiden Backbones herstellen",
     "WS3", "WS3", date(2016, 10, 14), "In progress", 35, "High", ""),
    ("A-026", "Consolidate service desk tooling onto one platform",
     "Service-Desk-Werkzeuge auf einer Plattform zusammenfuehren",
     "WS3", "WS3", date(2016, 11, 18), "Open", 0, "Low", "A-025"),
    ("A-031", "Publish combined organisation structure to level 3",
     "Kombinierte Organisationsstruktur bis Ebene 3 veroeffentlichen",
     "WS4", "WS4", date(2016, 10, 11), "Blocked", 65, "High", "A-033"),
    ("A-032", "Harmonise sales compensation plan design",
     "Verguetungsmodell im Vertrieb harmonisieren",
     "WS4", "WS4", date(2016, 10, 11), "In progress", 55, "High", ""),
    ("A-033", "Conclude works council consultation in Germany",
     "Anhoerung des Betriebsrats in Deutschland abschliessen",
     "WS4", "br_liaison", date(2016, 10, 28), "In progress", 40, "High", ""),
    ("A-034", "Confirm retention packages for named critical roles",
     "Halteprogramme fuer benannte Schluesselrollen bestaetigen",
     "WS4", "WS4", date(2016, 10, 7), "In progress", 75, "High", ""),
    ("A-035", "Track welcome eGuide adoption to Day 30",
     "Nutzung des Willkommens-eGuide bis Day 30 nachverfolgen",
     "WS4", "change", date(2016, 10, 7), "In progress", 60, "Medium", ""),
    ("A-036", "Align job architecture and grading across both groups",
     "Stellenarchitektur und Eingruppierung beider Gruppen angleichen",
     "WS4", "WS4", date(2016, 11, 25), "Open", 0, "Medium", "A-031"),
    ("A-041", "Cleanse supplier master for the top 200 vendors",
     "Lieferantenstammdaten der 200 groessten Lieferanten bereinigen",
     "WS5", "WS5", date(2016, 10, 5), "In progress", 84, "High", ""),
    ("A-042", "Build the combined spend cube for wave 1 categories",
     "Beschaffungswuerfel fuer die Kategorien der Welle 1 aufbauen",
     "WS5", "WS5", date(2016, 10, 14), "In progress", 50, "High", "A-041"),
    ("A-043", "Open renegotiation with the top 12 logistics providers",
     "Nachverhandlung mit den zwoelf groessten Logistikdienstleistern eroeffnen",
     "WS5", "WS5", date(2016, 10, 28), "Open", 15, "High", "A-042"),
    ("A-044", "Map warehouse footprint overlap in EMEA and APJ",
     "Ueberschneidungen im Lagernetz in EMEA und APJ erfassen",
     "WS5", "WS5", date(2016, 11, 11), "Open", 0, "Medium", ""),
    ("A-051", "Publish combined product portfolio cross-reference",
     "Produktportfolio-Konkordanz veroeffentlichen",
     "WS6", "WS6", date(2016, 9, 26), "Done", 100, "High", ""),
    ("A-052", "Align territory and quota model for the merged field",
     "Gebiets- und Quotenmodell fuer die kombinierte Vertriebsorganisation angleichen",
     "WS6", "WS6", date(2016, 10, 21), "In progress", 40, "High", "A-032"),
    ("A-053", "Prepare the Dell EMC World customer narrative",
     "Kundenbotschaft fuer die Dell EMC World vorbereiten",
     "WS6", "change", date(2016, 10, 11), "In progress", 55, "High", ""),
    ("A-054", "Consolidate partner programme terms",
     "Konditionen der Partnerprogramme zusammenfuehren",
     "WS6", "WS6", date(2016, 11, 4), "Open", 10, "Medium", ""),
    ("A-055", "Measure customer net promoter score baseline",
     "Ausgangswert des Kunden-NPS erheben",
     "WS6", "imo_pmo", date(2016, 10, 14), "In progress", 30, "Medium", ""),
    ("A-061", "Complete lease expiry analysis for 52 EMEA sites",
     "Mietvertragsanalyse fuer 52 EMEA-Standorte abschliessen",
     "WS7", "WS7", date(2016, 10, 21), "In progress", 79, "Medium", ""),
    ("A-062", "Assess co-location options for the DACH head offices",
     "Zusammenlegung der DACH-Hauptstandorte pruefen",
     "WS7", "dach_lead", date(2016, 11, 4), "Open", 20, "Medium", "A-061"),
    ("A-063", "Confirm signage and rebranding schedule for tier 1 sites",
     "Beschilderung und Rebranding fuer Standorte der Stufe 1 terminieren",
     "WS7", "WS7", date(2016, 10, 14), "In progress", 45, "Low", ""),
    ("A-071", "Publish the value prioritisation framework scoring",
     "Bewertung im Wertpriorisierungsrahmen veroeffentlichen",
     "WS1", "synergy", date(2016, 9, 23), "Done", 100, "High", ""),
    ("A-072", "Validate synergy wave 1 initiatives with Finance",
     "Synergieinitiativen der Welle 1 mit Finance validieren",
     "WS1", "synergy", date(2016, 10, 7), "In progress", 65, "High", ""),
    ("A-073", "Refresh the cross-workstream dependency map",
     "Abhaengigkeitskarte zwischen den Teilprojekten aktualisieren",
     "WS3", "imo_mgr", date(2016, 9, 30), "In progress", 90, "High", ""),
    ("A-074", "Close out open actions from SteerCo session 01",
     "Offene Punkte aus der ersten SteerCo-Sitzung abschliessen",
     "WS1", "imo_mgr", date(2016, 9, 29), "In progress", 67, "High", ""),
]

T_TOTAL = len(TASKS)
T_DONE = sum(1 for t in TASKS if t[6] == "Done")
T_OVERDUE = sum(1 for t in TASKS if t[6] == "Overdue")
T_BLOCKED = sum(1 for t in TASKS if t[6] == "Blocked")
T_INPROG = sum(1 for t in TASKS if t[6] == "In progress")
T_OPEN = sum(1 for t in TASKS if t[6] == "Open")


def ws_tasks(code):
    return [t for t in TASKS if t[3] == code]


def ws_progress(code):
    ts = ws_tasks(code)
    return round(sum(t[7] for t in ts) / len(ts)) if ts else 0


def ws_milestones(code):
    return [m for m in MILESTONES if m[3] == code]


OVERALL_PROGRESS = round(sum(t[7] for t in TASKS) / len(TASKS))

# ======================================================================= risks
# (id, title_en, title_de, ws, owner_key, likelihood, impact, mitigation_en, due,
#  status, trend, escalated_to)
RISKS = [
    ("R-01", "Legacy ERP upgrade at the target collides with the integration design, "
     "delaying the consolidation blueprint",
     "Die laufende ERP-Modernisierung beim Zielunternehmen kollidiert mit dem "
     "Integrationsdesign und verzoegert das Zielbild",
     "WS3", "WS3", 4, 5,
     "Freeze the legacy upgrade scope, run a joint architecture session, resequence the "
     "blueprint against the Day 100 commitment", date(2016, 10, 14), "Open", "Increasing",
     "Steering Committee"),
    ("R-02", "Works council consultation in Germany does not conclude before the "
     "organisation announcement, blocking the structure release",
     "Die Anhoerung des Betriebsrats in Deutschland wird nicht vor der "
     "Organisationsankuendigung abgeschlossen und blockiert die Veroeffentlichung",
     "WS4", "br_liaison", 4, 3,
     "Weekly alignment with the works council chair, prepare a reduced announcement scope "
     "that excludes co-determined units", date(2016, 10, 21), "Open", "Increasing", "VCIO"),
    ("R-03", "Master data quality in the supplier and material records prevents a clean "
     "migration dry run",
     "Die Datenqualitaet in Lieferanten- und Materialstammdaten verhindert einen "
     "sauberen Migrationstest",
     "WS3", "dach_it", 4, 4,
     "Re-extract with a corrected field mapping, add a data quality gate before each "
     "migration wave", date(2016, 10, 5), "In progress", "Stable", "VCIO"),
    ("R-04", "Key talent attrition in the combined field organisation before the coverage "
     "model is in force",
     "Abwanderung von Schluesselkraeften in der kombinierten Vertriebsorganisation vor "
     "Inkrafttreten des Betreuungsmodells",
     "WS4", "WS4", 3, 5,
     "Confirm retention packages for named critical roles, bring the coverage model "
     "communication forward", date(2016, 10, 7), "In progress", "Stable", "Steering Committee"),
    ("R-05", "Customer confusion during the portfolio transition depresses the net promoter "
     "score ahead of the flagship event",
     "Unklarheit beim Portfolioübergang druckt den Kunden-NPS vor der Leitveranstaltung",
     "WS6", "WS6", 3, 4,
     "Publish the portfolio cross-reference, brief the field with the e-runbook, measure "
     "the NPS baseline before the event", date(2016, 10, 11), "In progress", "Decreasing", ""),
    ("R-06", "Entity rationalisation slips and delays the transfer pricing model, "
     "creating an exposure at the first combined year end",
     "Die gesellschaftsrechtliche Straffung verzoegert das Verrechnungspreismodell und "
     "erzeugt ein Risiko zum ersten gemeinsamen Jahresabschluss",
     "WS2", "WS2", 3, 4,
     "Escalate the entity chain review, run the transfer pricing outline in parallel "
     "rather than in sequence", date(2016, 10, 21), "Open", "Increasing", "Steering Committee"),
    ("R-07", "Interdependencies between workstreams are not visible to the teams that "
     "create them",
     "Abhaengigkeiten zwischen den Teilprojekten sind fuer die verursachenden Teams "
     "nicht sichtbar",
     "WS3", "imo_mgr", 4, 3,
     "Refresh the dependency map weekly, require both leads to confirm every handover "
     "date in the register", date(2016, 9, 30), "In progress", "Decreasing", ""),
    ("R-08", "Supplier renegotiation slips past the wave 1 window and the procurement "
     "synergy lands in the following financial year",
     "Die Lieferantennachverhandlung verpasst das Zeitfenster der Welle 1 und die "
     "Beschaffungssynergie faellt in das Folgejahr",
     "WS5", "WS5", 3, 3,
     "Open negotiations with the top 12 logistics providers before the spend cube is "
     "complete rather than after", date(2016, 10, 28), "Open", "Stable", ""),
    ("R-09", "Two sales organisations continue to call on the same accounts before "
     "territory alignment takes effect",
     "Zwei Vertriebsorganisationen betreuen dieselben Kunden bis das Gebietsmodell greift",
     "WS6", "WS6", 3, 3,
     "Interim account ownership list published weekly until the coverage model is in force",
     date(2016, 10, 14), "In progress", "Stable", ""),
    ("R-10", "Site consolidation assumptions rest on lease data that is not yet complete "
     "for all EMEA locations",
     "Die Annahmen zur Standortkonsolidierung beruhen auf unvollstaendigen Mietdaten in EMEA",
     "WS7", "WS7", 3, 2,
     "Complete the lease expiry analysis for the remaining sites before the plan is approved",
     date(2016, 10, 21), "Open", "Stable", ""),
    ("R-11", "Debt service constrains discretionary integration spend below the level the "
     "plan assumes",
     "Der Schuldendienst begrenzt die verfuegbaren Integrationsmittel unter das im Plan "
     "unterstellte Niveau",
     "WS1", "WS1", 2, 5,
     "Re-phase cost to achieve into the following financial year for initiatives that are "
     "not on the critical path", date(2016, 11, 4), "Open", "Stable", "Steering Committee"),
    ("R-12", "Reporting arrives at the office in six different formats and reconciliation "
     "consumes the analyst capacity that should go into analysis",
     "Die Berichte erreichen das Office in sechs unterschiedlichen Formaten und die "
     "Abstimmung bindet die Kapazitaet, die fuer Analyse gedacht ist",
     "WS1", "imo_pmo", 5, 2,
     "Mandate the tracker as the single source, accept slide input only as commentary",
     date(2016, 10, 7), "In progress", "Stable", ""),
    ("R-13", "Pension obligation at the target is larger than the baseline assumes",
     "Die Pensionsverpflichtung beim Zielunternehmen ist hoeher als in der Basislinie "
     "unterstellt",
     "WS1", "WS1", 2, 4,
     "Commission an actuarial review before the opening balance sheet is finalised",
     date(2016, 10, 7), "Open", "Stable", ""),
    ("R-14", "Rebranding at customer-facing sites is not complete before the flagship event",
     "Das Rebranding an kundenrelevanten Standorten ist vor der Leitveranstaltung nicht "
     "abgeschlossen",
     "WS7", "WS7", 2, 2,
     "Prioritise tier 1 sites and event venues, accept a phased schedule elsewhere",
     date(2016, 10, 14), "In progress", "Decreasing", ""),
]


def sev(r):
    return r[5] * r[6]


def band(s):
    return "Critical" if s >= 25 else "High" if s >= 15 else "Medium" if s >= 8 else "Low"


R_TOTAL = len(RISKS)
R_HIGH = sum(1 for r in RISKS if sev(r) >= 15)
R_OPEN = sum(1 for r in RISKS if r[9] in ("Open", "In progress"))
R_ESCALATED = sum(1 for r in RISKS if r[11])
ESCALATION_THRESHOLD = 15

# ======================================================================= synergies
# All synergy figures are [SYNTHETIC]. Dell did not publish a cost synergy number at
# announcement. The one public anchor used here is Michael Dell's statement that revenue
# synergies would be roughly three times cost synergies; the register is built to that ratio.
# (id, title_en, title_de, bucket, type, ws, owner_key, target, secured, realised,
#  fy17_in_year, cta, status, validated)
SYNERGIES = [
    ("S-01", "Consolidate indirect procurement onto combined contracts",
     "Indirekte Beschaffung auf gemeinsame Vertraege buendeln",
     "Procurement", "Cost", "WS5", "WS5", 310, 214, 42, 96, 38, "In progress", "Yes"),
    ("S-02", "Renegotiate logistics and freight with the top 12 providers",
     "Logistik und Fracht mit den zwoelf groessten Anbietern nachverhandeln",
     "Procurement", "Cost", "WS5", "WS5", 245, 118, 0, 44, 21, "In progress", "Yes"),
    ("S-03", "Consolidate component sourcing across the combined bill of materials",
     "Komponentenbeschaffung ueber die kombinierte Stueckliste buendeln",
     "Procurement", "Cost", "WS5", "WS5", 268, 96, 0, 31, 26, "Approved", "No"),
    ("S-04", "Rationalise overlapping enterprise software licences",
     "Ueberschneidende Unternehmenslizenzen bereinigen",
     "IT cost", "Cost", "WS3", "WS3", 186, 141, 28, 62, 34, "In progress", "Yes"),
    ("S-05", "Consolidate data centre footprint and hosting contracts",
     "Rechenzentrumsflaeche und Hostingvertraege konsolidieren",
     "IT cost", "Cost", "WS3", "WS3", 152, 61, 0, 18, 44, "Approved", "No"),
    ("S-06", "Merge service desk and IT operations tooling",
     "Service Desk und IT-Betriebswerkzeuge zusammenfuehren",
     "IT cost", "Cost", "WS3", "WS3", 74, 22, 0, 6, 12, "Business case", "No"),
    ("S-07", "Remove duplicated corporate and shared service functions",
     "Doppelte Zentral- und Servicefunktionen abbauen",
     "Personnel", "Cost", "WS4", "WS4", 296, 148, 31, 74, 96, "In progress", "Yes"),
    ("S-08", "Harmonise sales compensation and reduce plan complexity",
     "Verguetung im Vertrieb harmonisieren und Planvielfalt reduzieren",
     "Personnel", "Cost", "WS4", "WS4", 118, 47, 0, 14, 18, "Approved", "No"),
    ("S-09", "Consolidate offices where both groups hold leases in one city",
     "Bueros zusammenlegen, wo beide Gruppen am selben Ort mieten",
     "Footprint", "Cost", "WS7", "WS7", 134, 52, 9, 22, 41, "In progress", "Yes"),
    ("S-10", "Consolidate warehouse and distribution network in EMEA and APJ",
     "Lager- und Distributionsnetz in EMEA und APJ konsolidieren",
     "Operations", "Cost", "WS5", "WS5", 97, 24, 0, 8, 29, "Business case", "No"),
    ("S-11", "Rationalise marketing spend and event portfolio",
     "Marketingausgaben und Veranstaltungsportfolio straffen",
     "Operations", "Cost", "WS6", "WS6", 62, 38, 11, 19, 7, "In progress", "Yes"),
    ("S-12", "Cross-sell infrastructure portfolio into the client installed base",
     "Infrastrukturportfolio in den bestehenden Client-Kundenstamm verkaufen",
     "Revenue cross-sell", "Revenue", "WS6", "WS6", 2240, 610, 0, 148, 74, "In progress", "No"),
    ("S-13", "Cross-sell client portfolio into the enterprise installed base",
     "Client-Portfolio in den Enterprise-Kundenstamm verkaufen",
     "Revenue cross-sell", "Revenue", "WS6", "WS6", 1680, 405, 0, 96, 61, "In progress", "No"),
    ("S-14", "Attach services and support to the combined portfolio",
     "Services und Support an das kombinierte Portfolio anbinden",
     "Revenue cross-sell", "Revenue", "WS6", "WS6", 760, 233, 0, 58, 22, "Approved", "No"),
    ("S-15", "Extend mid-market coverage using the combined field",
     "Mittelstandsabdeckung mit der kombinierten Vertriebsmannschaft ausweiten",
     "Revenue pricing", "Revenue", "WS6", "WS6", 420, 84, 0, 17, 33, "Business case", "No"),
    ("S-16", "Harmonise discount governance across the combined portfolio",
     "Rabattsteuerung ueber das kombinierte Portfolio vereinheitlichen",
     "Revenue pricing", "Revenue", "WS6", "WS1", 210, 61, 0, 14, 9, "Approved", "No"),
]

SYN_BUCKETS = ["Procurement", "IT cost", "Personnel", "Footprint", "Operations",
               "Revenue cross-sell", "Revenue pricing"]

COST_TARGET = sum(s[7] for s in SYNERGIES if s[4] == "Cost")
COST_SECURED = sum(s[8] for s in SYNERGIES if s[4] == "Cost")
REV_TARGET = sum(s[7] for s in SYNERGIES if s[4] == "Revenue")
REV_SECURED = sum(s[8] for s in SYNERGIES if s[4] == "Revenue")
SYN_TARGET = sum(s[7] for s in SYNERGIES)
SYN_SECURED = sum(s[8] for s in SYNERGIES)
SYN_REALISED = sum(s[9] for s in SYNERGIES)
SYN_FY17 = sum(s[10] for s in SYNERGIES)
SYN_CTA = sum(s[11] for s in SYNERGIES)
SYN_VALIDATED = sum(s[8] for s in SYNERGIES if s[13] == "Yes")
SYN_SECURED_PCT = round(100 * SYN_SECURED / SYN_TARGET)
REV_COST_RATIO = round(REV_TARGET / COST_TARGET, 1)

# figures as they stood at Steering Committee session 01, eight days after close.
# Both are lower than the W3 values, which is what makes the series monotonic and the
# session 01 overstatement (issue I-03) concrete.
SYN_SECURED_S01 = 1980     # [SYNTHETIC] reported in the session 01 pack
SYN_VALIDATED_S01 = 402    # [SYNTHETIC] what Finance could stand behind at that point
D_TRANSCRIPT = date(2016, 9, 15)   # the meeting itself; minutes signed 22.09.2016

# deal-model target: set so the register carries a visible, explainable gap
DEAL_MODEL_TARGET = 8000   # [SYNTHETIC] USD m run-rate
SYN_GAP = DEAL_MODEL_TARGET - SYN_TARGET

# ======================================================================= RAG per workstream
# derived, not typed: red if a gate milestone is delayed, amber if any is at risk or a
# high-severity risk is open, else green
def ws_rag(code):
    ms = ws_milestones(code)
    if any(m[8] == "delayed" and m[9] for m in ms):
        return "Red"
    if any(m[8] in ("at_risk", "delayed") for m in ms):
        return "Amber"
    if any(sev(r) >= 15 and r[9] in ("Open", "In progress") for r in RISKS if r[3] == code):
        return "Amber"
    return "Green"


RAG_LAST_WEEK = {"WS1": "Green", "WS2": "Amber", "WS3": "Amber", "WS4": "Amber",
                 "WS5": "Green", "WS6": "Green", "WS7": "Green"}

OVERALL_RAG = "Amber"   # derived narrative: two red workstreams but Day 100 still credible


def ws_overdue(code):
    return sum(1 for t in ws_tasks(code) if t[6] in ("Overdue", "Blocked"))


def ws_risks(code):
    return [r for r in RISKS if r[3] == code]


# ======================================================================= decisions
# (id, decision_en, decision_de, rationale_en, body, date, ws_affected, owner_key, status)
DECISIONS = [
    ("B-01", "Adopt the value prioritisation framework as the single basis for sequencing "
     "integration work",
     "Den Wertpriorisierungsrahmen als alleinige Grundlage fuer die Reihenfolge der "
     "Integrationsarbeit einfuehren",
     "Focus the office on the fifth of the opportunities that carries most of the accretive "
     "value, seen through a customer-first lens",
     "Steering Committee", STEERCO_01, "all", "prog_dir", "Implemented"),
    ("B-02", "Mandate the integration tracker as the single source of truth for tasks, "
     "milestones and dates",
     "Den Integration Tracker als alleinige Quelle fuer Aufgaben, Meilensteine und Termine "
     "verbindlich setzen",
     "Six reporting formats were reaching the office and reconciliation was consuming the "
     "analyst capacity intended for analysis",
     "Steering Committee", STEERCO_01, "all", "imo_pmo", "In progress"),
    ("B-03", "Require both workstream leads to confirm every cross-workstream handover date "
     "in the dependency register",
     "Jeden Uebergabetermin zwischen Teilprojekten von beiden Teilprojektleitungen im "
     "Abhaengigkeitsregister bestaetigen lassen",
     "Teams understand their own responsibilities but not how their activities land on "
     "others; unconfirmed handovers were the largest single source of slippage",
     "Steering Committee", STEERCO_01, "all", "imo_mgr", "In progress"),
    ("B-04", "Freeze the scope of the legacy ERP upgrade at the target until the "
     "consolidation blueprint is signed off",
     "Den Umfang der laufenden ERP-Modernisierung beim Zielunternehmen einfrieren, bis das "
     "Zielbild der Konsolidierung freigegeben ist",
     "The upgrade and the integration design were competing for the same architecture "
     "decisions and the same people",
     "VCIO", date(2016, 9, 21), "WS3, WS1, WS5", "WS3", "In progress"),
    ("B-05", "Exclude co-determined units from the first organisation announcement",
     "Mitbestimmte Einheiten aus der ersten Organisationsankuendigung ausnehmen",
     "German consultation is a legal gate, not a communication preference; announcing "
     "before it concludes would create a compliance exposure",
     "VCIO", date(2016, 9, 27), "WS4", "br_liaison", "Open"),
    ("B-06", "Count only Finance-validated initiatives towards secured synergy",
     "Nur von Finance validierte Initiativen als gesicherte Synergie ausweisen",
     "Reported secured value was running ahead of what the baseline could support",
     "Steering Committee", STEERCO_01, "all", "synergy", "Implemented"),
    ("B-07", "Hold the Day 100 value realisation review date and re-phase scope instead",
     "Den Termin des Wertrealisierungsberichts zu Day 100 halten und stattdessen den "
     "Umfang neu takten",
     "The date is a sponsor commitment; scope is the variable that can move",
     "Steering Committee", STEERCO_02, "all", "prog_dir", "Open"),
    ("B-08", "Publish an interim account ownership list weekly until the coverage model "
     "takes effect",
     "Bis zum Inkrafttreten des Betreuungsmodells woechentlich eine vorlaeufige "
     "Kundenzuordnung veroeffentlichen",
     "Two field organisations were calling on the same accounts",
     "VCIO", date(2016, 9, 20), "WS6", "WS6", "Implemented"),
]

# ======================================================================= actions
# (id, action_en, action_de, source, owner_key, ws, due_orig, due_new, shifts, status)
ACTIONS = [
    ("OP-01", "Circulate the refreshed cross-workstream dependency map to all leads",
     "Die aktualisierte Abhaengigkeitskarte an alle Teilprojektleitungen versenden",
     f"SteerCo session 01, {en(STEERCO_01)}", "imo_mgr", "WS3",
     date(2016, 9, 23), date(2016, 9, 30), 1, "In progress"),
    ("OP-02", "Report the ERP blueprint recovery plan with a dated forecast",
     "Wiederanlaufplan fuer das ERP-Zielbild mit datierter Prognose vorlegen",
     f"SteerCo session 01, {en(STEERCO_01)}", "WS3", "WS3",
     date(2016, 9, 29), date(2016, 9, 29), 0, "In progress"),
    ("OP-03", "Confirm the works council consultation timetable in writing",
     "Den Zeitplan der Betriebsratsanhoerung schriftlich bestaetigen",
     f"SteerCo session 01, {en(STEERCO_01)}", "br_liaison", "WS4",
     date(2016, 9, 30), date(2016, 9, 30), 0, "In progress"),
    ("OP-04", "Reconcile reported secured synergy to the Finance-validated figure",
     "Die berichtete gesicherte Synergie auf den von Finance validierten Wert abstimmen",
     f"SteerCo session 01, {en(STEERCO_01)}", "synergy", "WS1",
     date(2016, 9, 28), date(2016, 9, 28), 0, "Done"),
    ("OP-05", "Escalate the EMEA entity chain tax review and name a completion date",
     "Die steuerliche Pruefung der EMEA-Gesellschaftskette eskalieren und einen "
     "Abschlusstermin benennen",
     f"IMO weekly, {en(date(2016, 9, 27))}", "WS2", "WS2",
     date(2016, 10, 3), date(2016, 10, 3), 0, "Open"),
    ("OP-06", "Add a data quality gate ahead of each migration wave",
     "Vor jeder Migrationswelle ein Datenqualitaetstor einziehen",
     f"Expert session, {en(D_EXPERT)}", "dach_it", "WS3",
     date(2016, 10, 5), date(2016, 10, 5), 0, "In progress"),
    ("OP-07", "Bring the coverage model communication forward by two weeks",
     "Die Kommunikation des Betreuungsmodells um zwei Wochen vorziehen",
     f"IMO weekly, {en(date(2016, 9, 27))}", "WS6", "WS6",
     date(2016, 10, 7), date(2016, 10, 7), 0, "Open"),
    ("OP-08", "Update the role holder table after the Human Capital lead change",
     "Die Tabelle der Rolleninhaber nach dem Wechsel der Teilprojektleitung Personal "
     "aktualisieren",
     f"IMO weekly, {en(date(2016, 9, 20))}", "imo_mgr", "WS4",
     date(2016, 9, 23), date(2016, 9, 30), 1, "In progress"),
    ("OP-09", "Commission the actuarial review of the pension obligation",
     "Die versicherungsmathematische Pruefung der Pensionsverpflichtung beauftragen",
     f"WS1 jour fixe, {en(date(2016, 9, 27))}", "WS1", "WS1",
     date(2016, 10, 3), date(2016, 10, 3), 0, "Open"),
    ("OP-10", "Publish the interim account ownership list for the first time",
     "Die vorlaeufige Kundenzuordnung erstmals veroeffentlichen",
     f"VCIO decision B-08, {en(date(2016, 9, 20))}", "WS6", "WS6",
     date(2016, 9, 26), date(2016, 9, 26), 0, "Done"),
    ("OP-11", "Re-phase cost to achieve for initiatives off the critical path",
     "Umsetzungskosten fuer Initiativen ausserhalb des kritischen Pfades neu takten",
     f"IMO weekly, {en(date(2016, 9, 27))}", "WS1", "WS1",
     date(2016, 10, 14), date(2016, 10, 14), 0, "Open"),
    ("OP-12", "Brief the field on the portfolio cross-reference before the flagship event",
     "Den Vertrieb vor der Leitveranstaltung zur Portfolio-Konkordanz briefen",
     f"IMO weekly, {en(date(2016, 9, 27))}", "change", "WS6",
     date(2016, 10, 7), date(2016, 10, 7), 0, "In progress"),
]

ACT_TOTAL = len(ACTIONS)
ACT_DONE = sum(1 for a in ACTIONS if a[9] == "Done")
ACT_SHIFTED = sum(1 for a in ACTIONS if a[8] > 0)

# ======================================================================= dependencies
# (id, deliverable_en, from_ws, to_ws, needed_by, criticality, confirmed, status)
DEPENDENCIES = [
    ("D-01", "Approved legal entity structure required to fix the consolidation scope",
     "WS2", "WS1", date(2016, 10, 12), "Critical", "No", "At risk"),
    ("D-02", "ERP target system decision required before the material master re-extract",
     "WS3", "WS5", date(2016, 10, 3), "Critical", "Yes", "Delayed"),
    ("D-03", "Works council conclusion required before the organisation structure release",
     "WS4", "WS4", date(2016, 10, 28), "Critical", "Yes", "At risk"),
    ("D-04", "Compensation plan design required before territory and quota alignment",
     "WS4", "WS6", date(2016, 10, 11), "High", "Yes", "On track"),
    ("D-05", "Spend cube required before logistics renegotiation can be scoped",
     "WS5", "WS5", date(2016, 10, 14), "High", "Yes", "On track"),
    ("D-06", "Lease expiry analysis required before the EMEA site plan is approved",
     "WS7", "WS7", date(2016, 10, 21), "Medium", "Yes", "On track"),
    ("D-07", "Entity plan required before transfer pricing documentation can begin",
     "WS2", "WS2", date(2016, 10, 12), "High", "No", "At risk"),
    ("D-08", "Portfolio cross-reference required before the flagship event narrative",
     "WS6", "WS6", date(2016, 10, 11), "High", "Yes", "On track"),
]
DEP_UNCONFIRMED_CRITICAL = sum(1 for d in DEPENDENCIES
                               if d[5] in ("Critical", "High") and d[6] == "No")

# ======================================================================= assumptions
ASSUMPTIONS = [
    ("AS-01", "The legacy ERP maintenance agreement at the target can be exited on three "
     "months notice", "WS3", date(2016, 8, 12),
     "ERP decommissioning slips by up to nine months and the licence synergy in S-04 is lost",
     "Legal to review the maintenance clause and confirm the notice period", date(2016, 10, 7),
     "Open"),
    ("AS-02", "No further regulatory condition applies to the EMEA entity mergers", "WS2",
     date(2016, 8, 19), "Entity rationalisation and the transfer pricing model both slip",
     "External counsel to confirm per jurisdiction", date(2016, 10, 14), "Open"),
    ("AS-03", "Retention acceptance among named critical roles will exceed 85 percent", "WS4",
     date(2016, 8, 26), "Coverage model and account continuity are both exposed",
     "Track acceptance weekly and report at Day 30", date(2016, 10, 7), "Open"),
    ("AS-04", "Supplier contracts contain no change of control clause that blocks "
     "renegotiation", "WS5", date(2016, 9, 2),
     "Procurement synergy wave 1 cannot be booked in the current financial year",
     "Contract review for the top 12 logistics providers", date(2016, 10, 14), "Confirmed"),
    ("AS-05", "The flagship event date of 18 to 20 October is immovable", "WS6",
     date(2016, 8, 5), "Portfolio and narrative milestones lose their forcing function",
     "None, treated as fixed", date(2016, 9, 7), "Confirmed"),
    ("AS-06", "Integration spend approved at close remains available in full", "WS1",
     date(2016, 9, 7), "Cost to achieve must be re-phased and synergy delivery moves right",
     "Confirm with treasury at the first combined quarter end", date(2016, 10, 21), "Open"),
]

# ======================================================================= issues
ISSUES = [
    ("I-01", "Material master extract from the target is incomplete; 18 percent of records "
     "are missing mandatory fields", "R-03", date(2016, 9, 22), "WS3", "dach_it", "High",
     "M-07 blueprint sign-off", "Re-extract with corrected field mapping and a data quality "
     "gate", date(2016, 10, 5), "In progress", "VCIO"),
    ("I-02", "The EMEA entity chain tax review has passed its due date and now blocks the "
     "rationalisation plan", "R-06", date(2016, 9, 26), "WS2", "WS2", "High",
     "M-05 entity plan approval", "Escalated to the Steering Committee with a named "
     "completion date", date(2016, 10, 3), "Open", "Steering Committee"),
    ("I-03", "Reported secured synergy exceeded the Finance-validated figure in the "
     "session 01 pack", "", date(2016, 9, 15), "WS1", "synergy", "Medium",
     "Credibility of the value case", "Only Finance-validated initiatives are counted from "
     "session 02 onward, per decision B-06", date(2016, 9, 28), "Resolved", ""),
    ("I-04", "Two field organisations called on the same 40 named accounts in the first "
     "fortnight", "R-09", date(2016, 9, 19), "WS6", "WS6", "Medium",
     "Customer experience ahead of the flagship event", "Interim account ownership list "
     "published weekly", date(2016, 9, 26), "Resolved", ""),
    ("I-05", "The role holder table still names the previous Human Capital workstream lead",
     "", date(2016, 9, 20), "WS4", "imo_mgr", "Low", "Ownership clarity",
     "Update the role holder table and reconcile it against the role cards",
     date(2016, 9, 30), "In progress", ""),
]

# ======================================================================= baseline
# (id, line_item, entity, category, fy16_actual, fy17_budget, source)
BASELINE = [
    ("BL-01", "External IT maintenance and software licences", TARGET, "IT cost",
     1840, 1912, "Target FY16 statutory accounts, note 14"),
    ("BL-02", "Data centre hosting and co-location", TARGET, "IT cost",
     742, 768, "Target FY16 statutory accounts, note 14"),
    ("BL-03", "Indirect procurement, addressable spend", "Combined", "Procurement",
     4310, 4402, "Combined spend cube, wave 1 extract"),
    ("BL-04", "Logistics and freight", "Combined", "Procurement",
     1965, 2018, "Combined spend cube, wave 1 extract"),
    ("BL-05", "Component sourcing, addressable bill of materials", "Combined", "Procurement",
     6120, 6244, "Combined spend cube, wave 1 extract"),
    ("BL-06", "Corporate and shared service personnel cost", "Combined", "Personnel",
     2874, 2951, "Combined FY17 operating plan"),
    ("BL-07", "Sales compensation, plan cost", "Combined", "Personnel",
     1638, 1702, "Combined FY17 operating plan"),
    ("BL-08", "Property lease and facilities cost", "Combined", "Footprint",
     884, 903, "Combined lease register, September 2016"),
    ("BL-09", "Warehouse and distribution operating cost", "Combined", "Operations",
     612, 628, "Combined FY17 operating plan"),
    ("BL-10", "Marketing and events", "Combined", "Operations",
     428, 441, "Combined FY17 operating plan"),
]

# ======================================================================= org structure
ORG_L1 = ("Geschäftsführung Dell EMC DACH", "Managing Director, DACH")
ORG_L2_DE = [
    ("Finanzen", "WS1"), ("IT", "WS3"), ("Personal", "WS4"),
    ("Lieferkette und Logistik", "WS5"), ("Vertrieb und Marketing", "WS6"),
]
ORG_L3_DE = {
    "Finanzen": ["Konzernrechnungswesen", "Controlling", "Steuern und Treasury"],
    "IT": ["Anwendungen und ERP", "Infrastruktur und Netz", "Service Desk"],
    "Personal": ["Personalbetreuung", "Verguetung und Benefits", "Betriebsratskoordination"],
    "Lieferkette und Logistik": ["Beschaffung", "Lager und Distribution", "Auftragsabwicklung"],
    "Vertrieb und Marketing": ["Grosskunden", "Mittelstand und Partner", "Marketing"],
}
DACH_FTE_TARGET = 1284
DACH_FTE_DAY1 = 1417
DACH_SPAN = 7.4
DACH_LAYERS = 5
DACH_OPEN_POS = 46

# ======================================================================= planted conflicts
# The only permitted disagreements in the corpus. Everything else must tie exactly.
IT_PROGRESS_TRACKER = ws_progress("WS3")          # authoritative, computed
IT_PROGRESS_ONEPAGER = IT_PROGRESS_TRACKER + 7    # workstream deck rounds up
IT_PROGRESS_DASHBOARD = IT_PROGRESS_TRACKER - 6   # dashboard cached before the last update

M07_ROADMAP = date(2016, 10, 7)     # roadmap still carries the baseline
M07_MINUTES = date(2016, 10, 14)    # minutes record the first slip
M07_MAIL = date(2016, 10, 21)       # mail sets the current forecast, matches the tracker

SYN_SECURED_DECK = 2410             # deck rounds up and counts initiatives Finance has not validated
SYN_SECURED_TRACKER = SYN_SECURED   # exact
SYN_SECURED_VALIDATED = SYN_VALIDATED  # Finance-validated only, authoritative

R02_SEVERITY_REGISTER = 12          # RAID log, likelihood 4 x impact 3
R02_SEVERITY_CHAT = 20              # escalated in chat to 4 x 5, never entered in the register

OP01_OWNER_MINUTES = "imo_mgr"      # signed minutes
OP01_OWNER_MAIL = "imo_pmo"         # reassigned by mail after the meeting

PLANTED_CONFLICTS = [
    ("C1", "WS3 IT progress percent",
     f"Tracker {IT_PROGRESS_TRACKER}%, workstream one-pager {IT_PROGRESS_ONEPAGER}%, "
     f"dashboard screenshot {IT_PROGRESS_DASHBOARD}%",
     "Excel wins, source priority 1"),
    ("C2", "Milestone M-07 forecast date",
     f"Roadmap {en(M07_ROADMAP)}, SteerCo minutes {en(M07_MINUTES)}, mail thread "
     f"{en(M07_MAIL)}",
     "Most recent dated source, which is the mail thread and matches the tracker"),
    ("C3", "Human Capital workstream lead",
     f"Role cards name {PEOPLE['hc_prev'][0]}, RACI page names {PEOPLE['WS4'][0]}",
     "RACI page, which states itself to be authoritative for staffing"),
    ("C4", "Secured synergy run-rate",
     f"SteerCo deck USD {SYN_SECURED_DECK} m, synergy tracker USD {SYN_SECURED_TRACKER} m, "
     f"Finance-validated USD {SYN_SECURED_VALIDATED} m",
     "Finance-validated figure, per decision B-06"),
    ("C5", "Severity of risk R-02, works council",
     f"RAID log {R02_SEVERITY_REGISTER} (Medium), chat thread {R02_SEVERITY_CHAT} (High)",
     "Neither. Flag that the register is out of date, the escalation never reached it"),
    ("C6", "Owner of action OP-01",
     f"Signed minutes {PEOPLE[OP01_OWNER_MINUTES][0]}, mail thread reassigns to "
     f"{PEOPLE[OP01_OWNER_MAIL][0]}",
     "Later source, but flag the divergence: the minutes were never amended"),
]

# ======================================================================= palette
D_GREEN = "86BC25"
D_DARK = "046A38"
D_DEEP = "1C3D26"
D_BLACK = "222222"
D_GREY = "75787B"
D_PALE = "F1F6E4"
D_LIGHT = "E6E6E6"
RAG_COLOR = {"Green": "43B02A", "Amber": "ED8B00", "Red": "DA291C"}
