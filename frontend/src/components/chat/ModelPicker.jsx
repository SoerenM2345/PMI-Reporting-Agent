import { useEffect, useState } from "react";

import * as api from "../../api";

/**
 * Which model this chat uses.
 *
 * Per chat, not global: two chats can be on different backends at once, and a
 * setting that silently changed every other conversation would be worse than no
 * setting at all.
 *
 * The list comes from the server — model IDs live only in `app/config.py`
 * (§21.10), so hard-coding them here would put them somewhere the grep test
 * cannot see and let them drift from what the backend accepts.
 */
export default function ModelPicker({ chat, onChange, busy }) {
  const [catalogue, setCatalogue] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.listModels().then(setCatalogue).catch(() => setCatalogue(null));
  }, []);

  if (!catalogue) return null;

  const current =
    catalogue.models.find((m) => m.id === chat?.model) ??
    catalogue.models.find((m) => m.id === catalogue.default.model);

  const select = (model) => {
    setOpen(false);
    onChange({ provider: model.provider, model: model.id });
  };

  return (
    <div className="relative">
      <button
        type="button"
        disabled={busy}
        onClick={() => setOpen((was) => !was)}
        className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs
                   text-slate-600 hover:border-slate-500 disabled:opacity-40"
      >
        {current?.label ?? "Model"} ▾
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-1 w-80 rounded-lg border
                        border-slate-200 bg-white p-1 shadow-lg">
          {catalogue.keyless && (
            <p className="m-1 rounded bg-amber-50 p-2 text-[11px] text-slate-600">
              No API key is configured. The agent still runs end to end —
              extraction, conflict detection and file generation are plain
              Python — but summaries become templates and images cannot be read.
            </p>
          )}

          {["anthropic", "openai"].map((provider) => {
            const models = catalogue.models.filter((m) => m.provider === provider);
            if (!models.length) return null;
            return (
              <div key={provider} className="mb-1">
                <p className="px-2 py-1 text-[10px] uppercase tracking-wide text-slate-400">
                  {provider}
                  {!catalogue.providers[provider] && " — no key"}
                </p>
                {models.map((model) => (
                  <button
                    key={model.id}
                    type="button"
                    disabled={!model.available}
                    onClick={() => select(model)}
                    title={model.available ? model.note : "No API key for this provider"}
                    className={`block w-full rounded px-2 py-1.5 text-left text-xs
                      ${model.id === current?.id ? "bg-slate-100" : "hover:bg-slate-50"}
                      disabled:cursor-not-allowed disabled:opacity-40`}
                  >
                    <span className="font-medium text-slate-800">{model.label}</span>
                    {model.note && (
                      <span className="block text-[11px] text-slate-500">
                        {model.note}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
