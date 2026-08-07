/**
 * Generate and download files in multiple formats.
 */
import { useState } from "react";
import * as api from "../../api";

const FORMATS = [
  { id: "powerpoint", label: "PowerPoint", icon: "📊", description: "Presentation" },
  { id: "excel", label: "Excel", icon: "📈", description: "Spreadsheet" },
  { id: "pdf", label: "PDF", icon: "📄", description: "Document" },
  { id: "word", label: "Word", icon: "📝", description: "Document" },
  { id: "html", label: "HTML", icon: "🌐", description: "Web page" },
];

export default function LLMFileGenerator({ sessionId, version, onGenerateFiles, busy }) {
  const [selectedFormats, setSelectedFormats] = useState(["powerpoint"]);
  const [generatedFiles, setGeneratedFiles] = useState({});
  const [generating, setGenerating] = useState(false);

  const toggleFormat = (format) => {
    setSelectedFormats((prev) =>
      prev.includes(format)
        ? prev.filter((f) => f !== format)
        : [...prev, format],
    );
  };

  const handleGenerate = async () => {
    if (!selectedFormats.length) return;

    setGenerating(true);
    try {
      const result = await api.generateFiles(sessionId, version, selectedFormats);
      setGeneratedFiles(result.files || {});
      await onGenerateFiles(selectedFormats);
    } catch (e) {
      console.error("Failed to generate files:", e);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold mb-4">Generate Files</h3>
        <p className="text-sm text-slate-600 mb-6">
          Select the formats you'd like to generate
        </p>
      </div>

      {/* Format selection */}
      <div className="grid grid-cols-2 gap-3">
        {FORMATS.map((fmt) => (
          <button
            key={fmt.id}
            onClick={() => toggleFormat(fmt.id)}
            className={`p-4 rounded-lg border-2 transition text-left ${
              selectedFormats.includes(fmt.id)
                ? "border-blue-500 bg-blue-50"
                : "border-slate-200 bg-white hover:border-slate-300"
            }`}
          >
            <div className="text-2xl mb-2">{fmt.icon}</div>
            <div className="font-medium text-sm">{fmt.label}</div>
            <div className="text-xs text-slate-500">{fmt.description}</div>
          </button>
        ))}
      </div>

      {/* Generated files list */}
      {Object.keys(generatedFiles).length > 0 && (
        <div className="bg-green-50 rounded-lg p-4 border border-green-200">
          <h4 className="font-medium text-sm mb-3 text-green-900">Files Ready</h4>
          <div className="space-y-2">
            {Object.entries(generatedFiles).map(([format, filepath]) => (
              <a
                key={format}
                href={api.downloadUrl(sessionId, filepath.split("/").pop())}
                download
                className="flex items-center justify-between p-2 bg-white rounded hover:bg-slate-50"
              >
                <span className="text-sm font-medium text-slate-700">
                  {FORMATS.find((f) => f.id === format)?.label}
                </span>
                <span className="text-blue-500 text-sm">↓ Download</span>
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-3 pt-4 border-t border-slate-200">
        <button
          disabled={generating || busy || selectedFormats.length === 0}
          className="flex-1 px-4 py-2 text-slate-700 border border-slate-300 rounded-lg hover:bg-slate-50 disabled:opacity-50"
        >
          More Options
        </button>
        <button
          onClick={handleGenerate}
          disabled={generating || busy || selectedFormats.length === 0}
          className="flex-1 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-slate-300"
        >
          {generating || busy ? "Generating..." : "Generate Files"}
        </button>
      </div>
    </div>
  );
}
