import { useEffect, useState } from "react";

/**
 * What the agent is doing while you wait.
 *
 * Analysis is synchronous and can run for many seconds — a vision call per
 * screenshot, 39 consistency checks, then planning. With no feedback at all the
 * user cannot tell "still working" from "silently did nothing", which is
 * exactly how the dead-end bug felt: an instant wrong answer and a blank pause
 * are indistinguishable when neither says anything.
 *
 * The phases are the ones the pipeline actually moves through, in order, rather
 * than decorative filler. They advance on a timer because the backend is a
 * single blocking request with no progress channel — so this is an *honest
 * approximation*, not a real progress bar, and it deliberately stops at the
 * last phase instead of looping back to the first. A cycle that restarts reads
 * as "stuck"; a label that stays put reads as "still on the hard part", which
 * is true.
 */
const PHASES = [
  { after: 0, label: "Reading your files" },
  { after: 2500, label: "Extracting tasks, risks and figures" },
  { after: 6000, label: "Interpreting images and scans" },
  { after: 11000, label: "Checking the sources against each other" },
  { after: 17000, label: "Scoring data quality" },
  { after: 23000, label: "Working out what the report should say" },
  { after: 32000, label: "Still working — larger file sets take a while" },
];

export default function Thinking({ active }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!active) {
      setElapsed(0);
      return undefined;
    }
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Date.now() - started), 500);
    return () => clearInterval(timer);
  }, [active]);

  if (!active) return null;

  const phase =
    [...PHASES].reverse().find((entry) => elapsed >= entry.after) ?? PHASES[0];

  return (
    <div className="flex justify-start" aria-live="polite">
      <div className="flex items-center gap-2.5 rounded-2xl rounded-bl-sm bg-white
                      px-4 py-2.5 text-sm text-slate-500 shadow-sm ring-1
                      ring-slate-200">
        <span className="flex gap-1" aria-hidden="true">
          {[0, 1, 2].map((dot) => (
            <span
              key={dot}
              className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400"
              style={{ animationDelay: `${dot * 150}ms` }}
            />
          ))}
        </span>
        <span>{phase.label}…</span>
        {elapsed > 8000 && (
          <span className="text-xs text-slate-400">
            {Math.round(elapsed / 1000)}s
          </span>
        )}
      </div>
    </div>
  );
}
