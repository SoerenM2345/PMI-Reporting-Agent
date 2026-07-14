import { useState } from "react";

/**
 * Project metadata (spec §4 step 1).
 *
 * Collapsed by default, but not optional in effect: a masterplan does not state its own
 * Day 1 date. Without a reporting date the agent cannot say what is overdue, and
 * without a Day 1 date the check for Day-1 work scheduled after Day 1 cannot run at
 * all — so the data-quality report reports these as gaps rather than skipping the
 * checks silently.
 */

const PHASES = [
  "Unknown",
  "Integration project setup",
  "Integration strategy",
  "Target Operating Model design",
  "Day 1 readiness",
  "Integration planning",
  "Integration execution",
  "Value creation and synergy realization",
  "Change management and communication",
  "Stabilization",
  "Transition to business as usual",
];

export default function ProjectSetup({ onSave, saved, busy }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    project_name: "PMI Project",
    reporting_date: "",
    reporting_period: "",
    day_1_date: "",
    integration_phase: "Unknown",
  });

  const set = (key) => (event) =>
    setForm({ ...form, [key]: event.target.value });

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-left"
      >
        <div>
          <h2 className="font-semibold text-slate-900">Project details</h2>
          <p className="text-sm text-slate-500">
            {saved
              ? `${form.project_name}${form.reporting_date ? ` · ${form.reporting_date}` : ""}`
              : "Optional, but the reporting date and Day 1 date unlock checks that cannot otherwise run."}
          </p>
        </div>
        <span className="text-slate-400">{open ? "−" : "+"}</span>
      </button>

      {open && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-sm">
            <span className="mb-1 block text-slate-600">Project name</span>
            <input
              value={form.project_name}
              onChange={set("project_name")}
              className="w-full rounded border border-slate-300 px-3 py-1.5"
            />
          </label>

          <label className="text-sm">
            <span className="mb-1 block text-slate-600">Reporting date</span>
            <input
              type="date"
              value={form.reporting_date}
              onChange={set("reporting_date")}
              className="w-full rounded border border-slate-300 px-3 py-1.5"
            />
          </label>

          <label className="text-sm">
            <span className="mb-1 block text-slate-600">Day 1 date</span>
            <input
              type="date"
              value={form.day_1_date}
              onChange={set("day_1_date")}
              className="w-full rounded border border-slate-300 px-3 py-1.5"
            />
          </label>

          <label className="text-sm">
            <span className="mb-1 block text-slate-600">Reporting period</span>
            <input
              value={form.reporting_period}
              onChange={set("reporting_period")}
              placeholder="e.g. July 2026, week 28"
              className="w-full rounded border border-slate-300 px-3 py-1.5"
            />
          </label>

          <label className="text-sm sm:col-span-2">
            <span className="mb-1 block text-slate-600">Integration phase</span>
            <select
              value={form.integration_phase}
              onChange={set("integration_phase")}
              className="w-full rounded border border-slate-300 px-3 py-1.5"
            >
              {PHASES.map((phase) => (
                <option key={phase} value={phase}>{phase}</option>
              ))}
            </select>
          </label>

          <button
            type="button"
            disabled={busy}
            onClick={() =>
              onSave({
                ...form,
                reporting_date: form.reporting_date || null,
                day_1_date: form.day_1_date || null,
                reporting_period: form.reporting_period || null,
              })
            }
            className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white
                       hover:bg-slate-700 disabled:opacity-50 sm:col-span-2"
          >
            {saved ? "Update project details" : "Save project details"}
          </button>
        </div>
      )}
    </section>
  );
}
