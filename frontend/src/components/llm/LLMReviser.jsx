/**
 * Chat-like interface for revising generated content.
 */
import { useState } from "react";

export default function LLMReviser({ content, onRevise, onCancel, busy }) {
  const [revision, setRevision] = useState("");
  const [revisions, setRevisions] = useState([]);

  const handleSubmit = async () => {
    if (!revision.trim()) return;

    // Add to revision history
    setRevisions([...revisions, revision]);
    setRevision("");

    // Call the revise handler
    await onRevise(revision);
  };

  return (
    <div className="flex flex-col h-full space-y-4">
      {/* Revision history */}
      <div className="flex-1 overflow-auto space-y-4">
        <div className="bg-blue-50 rounded-lg p-4">
          <h4 className="font-medium text-sm mb-2">Current Content</h4>
          <p className="text-sm text-slate-700">{content.title}</p>
        </div>

        {revisions.map((rev, idx) => (
          <div key={idx} className="bg-slate-50 rounded-lg p-4">
            <p className="text-sm text-slate-600 italic">Revision {idx + 1}:</p>
            <p className="text-sm text-slate-700 mt-1">{rev}</p>
          </div>
        ))}
      </div>

      {/* Revision input */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-slate-700">
          How would you like to change this?
        </label>
        <textarea
          value={revision}
          onChange={(e) => setRevision(e.target.value)}
          placeholder="e.g., Make this section shorter, add more detail about risks, change the tone to be more professional..."
          className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          rows={3}
          disabled={busy}
        />
      </div>

      {/* Action buttons */}
      <div className="flex gap-3">
        <button
          onClick={onCancel}
          disabled={busy}
          className="flex-1 px-4 py-2 text-slate-700 border border-slate-300 rounded-lg hover:bg-slate-50 disabled:opacity-50"
        >
          Back
        </button>
        <button
          onClick={handleSubmit}
          disabled={busy || !revision.trim()}
          className="flex-1 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-slate-300"
        >
          {busy ? "Revising..." : "Revise"}
        </button>
      </div>
    </div>
  );
}
