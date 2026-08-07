/**
 * Preview of generated content with revision options.
 */
import { useState } from "react";
import LLMReviser from "./LLMReviser";

export default function LLMPreview({ content, onRevise, onApprove, busy }) {
  const [showReviser, setShowReviser] = useState(false);

  if (showReviser) {
    return (
      <LLMReviser
        content={content}
        onRevise={async (revision) => {
          await onRevise(revision);
          setShowReviser(false);
        }}
        onCancel={() => setShowReviser(false)}
        busy={busy}
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* Title and Subtitle */}
      <div>
        <h3 className="text-2xl font-bold text-slate-900">{content.title}</h3>
        {content.subtitle && (
          <p className="text-lg text-slate-600 mt-1">{content.subtitle}</p>
        )}
      </div>

      {/* Metadata */}
      {content.metadata && (
        <div className="bg-slate-50 rounded-lg p-4 text-sm">
          {content.metadata.audience && (
            <p>
              <span className="font-medium">Audience:</span>{" "}
              {content.metadata.audience}
            </p>
          )}
          {content.metadata.reporting_date && (
            <p>
              <span className="font-medium">Date:</span>{" "}
              {content.metadata.reporting_date}
            </p>
          )}
        </div>
      )}

      {/* Sections Preview */}
      <div className="space-y-6">
        {content.sections && content.sections.map((section, idx) => (
          <div key={idx} className="border-b border-slate-200 pb-6">
            <h4 className="text-lg font-semibold text-slate-900 mb-3">
              {section.title}
            </h4>

            {section.type === "text" && (
              <p className="text-slate-700 leading-relaxed">{section.content}</p>
            )}

            {section.type === "bullets" && (
              <ul className="space-y-2">
                {(Array.isArray(section.content) ? section.content : [section.content]).map(
                  (item, i) => (
                    <li key={i} className="flex gap-2 text-slate-700">
                      <span className="text-slate-400">•</span>
                      <span>{item}</span>
                    </li>
                  ),
                )}
              </ul>
            )}

            {section.type === "table" && (
              <div className="overflow-x-auto">
                <table className="min-w-full border border-slate-200">
                  <tbody>
                    {Array.isArray(section.content) &&
                      section.content.map((row, i) => (
                        <tr
                          key={i}
                          className={i % 2 === 0 ? "bg-slate-50" : ""}
                        >
                          {(Array.isArray(row) ? row : [row]).map((cell, j) => (
                            <td
                              key={j}
                              className="px-4 py-2 text-sm text-slate-700 border-r border-slate-200"
                            >
                              {cell}
                            </td>
                          ))}
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}

            {section.type === "chart" && (
              <div className="bg-slate-100 rounded h-32 flex items-center justify-center text-slate-500">
                [Chart: {section.title}]
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Action Buttons */}
      <div className="flex gap-3 pt-4 border-t border-slate-200">
        <button
          onClick={() => setShowReviser(true)}
          disabled={busy}
          className="px-4 py-2 text-slate-700 border border-slate-300 rounded-lg hover:bg-slate-50 disabled:opacity-50"
        >
          Revise
        </button>
        <button
          onClick={onApprove}
          disabled={busy}
          className="flex-1 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-slate-300"
        >
          {busy ? "Approving..." : "Approve"}
        </button>
      </div>
    </div>
  );
}
