# User Acceptance Test — Questionnaire

For a PMI practitioner: an IMO lead, a PMO analyst, a workstream lead, or an integration
director.

**Please use your own project's files if you can.** The sample data was written by us,
and we planted the inconsistencies in it, so it cannot tell us what we most need to know.

Scale: **1 = strongly disagree, 5 = strongly agree.** The free-text answers are worth
more to us than the numbers.

---

## A · Setup

- **A1.** Role: ☐ IMO ☐ PMO ☐ Workstream lead ☐ Finance ☐ Integration Director ☐ Other: ______
- **A2.** Files used: ☐ Sample project ☐ My own project's files
- **A3.** How many files did you upload? ______
- **A4.** Roughly how long does the report you are replacing take you to build by hand? ______

---

## B · Upload and extraction

| | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| **B1.** Uploading was straightforward. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **B2.** The agent read the files I would have expected it to read. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **B3.** The entity counts (tasks, risks, milestones…) looked about right. | ☐ | ☐ | ☐ | ☐ | ☐ |

**B4.** Did it **miss** anything important that was in your files? What?

> ______________________________________________

**B5.** Did it **invent** anything that was *not* in your files? What?

> ______________________________________________

*(B5 is the single most important question in this document. A "yes" here is a defect we
would stop everything to fix. Please look hard.)*

---

## C · Conflicts — the core of the system

| | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| **C1.** The conflicts it found were real conflicts. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **C2.** It found conflicts I did not know about. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **C3.** Showing me *where* each value came from (sheet, cell, slide) was useful. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **C4.** The things it asked me about were worth asking about. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **C5.** The things it resolved automatically were fine to resolve automatically. | ☐ | ☐ | ☐ | ☐ | ☐ |

**C6.** Did it **ask** you about anything it should have just decided itself?

> ______________________________________________

**C7.** Did it **decide** anything itself that it should have asked you about?

> ______________________________________________

*(C7 matters more than C6. Being asked too often is annoying. Deciding something you
should have decided is the system exceeding its authority.)*

**C8.** The system refuses to generate a report while a **critical** conflict is
unresolved. Is that right?

☐ Yes, that's correct behaviour  ☐ Too strict — let me through  ☐ Not strict enough

> Why? ______________________________________________

**C9.** Did you ever want to enter a value that was in **neither** source (i.e. both files
were stale)? Did you find you could?

> ______________________________________________

---

## D · Images (skip if you uploaded none)

| | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| **D1.** It read the screenshot/photo about as well as a person would. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **D2.** The confidence scores matched how much I would actually trust each reading. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **D3.** The "please verify" panel was useful rather than noise. | ☐ | ☐ | ☐ | ☐ | ☐ |

**D4.** Did it read anything from an image **wrongly** while claiming **high** confidence?

> ______________________________________________

*(A confidently wrong image reading is the most dangerous thing this system can do.
Please check the low-confidence panel against the actual picture.)*

---

## E · The outputs

| | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| **E1.** The deck is structured the way a PMI deck should be structured. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **E2.** The slide titles told me the finding, not just the topic. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **E3.** The executive summary was accurate. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **E4.** The Excel dashboard is something I would actually use. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **E5.** The charts communicated something. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **E6.** The data-quality report told me something I needed to know. | ☐ | ☐ | ☐ | ☐ | ☐ |
| **E7.** "Not Reported" (rather than a blank or a zero) is the right thing to show. | ☐ | ☐ | ☐ | ☐ | ☐ |

**E8. The question that decides this.** Would you have sent the deck to a Steering
Committee **without changing it**?

☐ Yes  ☐ After minor edits  ☐ After major edits  ☐ No

**E9.** What did you change, and why? *(Please be specific — the edits are the data.)*

> ______________________________________________
> ______________________________________________

**E10.** Was there anything on a slide you could **not** trace back to a source file?

> ______________________________________________

---

## F · Overall

**F1.** How long did the whole thing take, against the ______ hours you gave in A4?

> ______________________________________________

**F2.** Would you use this next reporting cycle?

☐ Yes  ☐ Yes, with changes  ☐ No

**F3.** What is the **one thing** that would most improve it?

> ______________________________________________

**F4.** What is the thing that would most **stop** you using it?

> ______________________________________________

**F5.** Did the system ever make you trust it *more* than you should have?

> ______________________________________________

*(F5 is what we are really testing. A tool that makes a consultant confident about a
number they should have checked has failed, no matter how good the deck looks.)*

---

Thank you. Please attach the `data_quality_report_*.md` from your run — it tells us what
the system thought it could not do, and comparing that against what you found it *actually*
got wrong is the most useful signal we can get.
