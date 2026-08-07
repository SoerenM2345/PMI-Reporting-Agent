/**
 * LLM-driven document generation flow.
 *
 * Simplified workflow: upload files → request content → preview → revise →
 * approve → generate files → download.
 *
 * No complex analysis, conflict resolution, or data quality reports.
 * Just: "Here are my files. Generate a PowerPoint/Excel/PDF."
 */
import { useState } from "react";
import * as api from "../../api";
import LLMPreview from "./LLMPreview";
import LLMReviser from "./LLMReviser";
import LLMFileGenerator from "./LLMFileGenerator";

export default function LLMGenerator({ sessionId, onClose }) {
  const [stage, setStage] = useState("request"); // request | preview | approved | complete
  const [request, setRequest] = useState("");
  const [outputFormat, setOutputFormat] = useState("PowerPoint");
  const [audience, setAudience] = useState("");
  const [content, setContent] = useState(null);
  const [version, setVersion] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  const handleGenerateRequest = async () => {
    if (!request.trim()) {
      setError("Please describe what you want to generate");
      return;
    }

    setError(null);
    setGenerating(true);

    try {
      const result = await api.generateContent(sessionId, request, {
        outputFormat,
        audience: audience || null,
      });

      setContent(result);
      setStage("preview");
    } catch (e) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleRevise = async (revision) => {
    setError(null);
    setGenerating(true);

    try {
      const result = await api.reviseContent(sessionId, revision);
      setContent(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleApprove = async () => {
    setError(null);
    setGenerating(true);

    try {
      const result = await api.approveContent(sessionId);
      setVersion(result.version);
      setStage("approved");
    } catch (e) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleGenerateFiles = async (formats) => {
    setError(null);
    setGenerating(true);

    try {
      await api.generateFiles(sessionId, version, formats);
      setStage("complete");
    } catch (e) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
        <h2 className="text-lg font-semibold">Generate Document</h2>
        <button
          onClick={onClose}
          className="text-slate-500 hover:text-slate-700"
        >
          ✕
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="px-6 py-3 bg-red-50 border-b border-red-200 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Content area */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {stage === "request" && (
          <div className="space-y-4 max-w-2xl">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                What would you like to generate?
              </label>
              <textarea
                value={request}
                onChange={(e) => setRequest(e.target.value)}
                placeholder="e.g., Create a risk report for the steering committee covering top 10 risks, mitigation, and owners"
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                rows={4}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  Output Format
                </label>
                <select
                  value={outputFormat}
                  onChange={(e) => setOutputFormat(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="PowerPoint">PowerPoint</option>
                  <option value="Excel">Excel</option>
                  <option value="PDF">PDF</option>
                  <option value="Word">Word</option>
                  <option value="HTML">HTML</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  Audience (Optional)
                </label>
                <input
                  type="text"
                  value={audience}
                  onChange={(e) => setAudience(e.target.value)}
                  placeholder="e.g., Steering Committee"
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
          </div>
        )}

        {stage === "preview" && content && (
          <LLMPreview
            content={content}
            onRevise={handleRevise}
            onApprove={handleApprove}
            busy={generating}
          />
        )}

        {stage === "approved" && (
          <LLMFileGenerator
            sessionId={sessionId}
            version={version}
            onGenerateFiles={handleGenerateFiles}
            busy={generating}
          />
        )}

        {stage === "complete" && (
          <div className="text-center py-8">
            <div className="text-4xl mb-4">✓</div>
            <h3 className="text-lg font-semibold mb-2">Files Generated</h3>
            <p className="text-slate-600 mb-6">
              Your files have been generated and are ready to download.
            </p>
            <button
              onClick={onClose}
              className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
            >
              Done
            </button>
          </div>
        )}
      </div>

      {/* Footer buttons */}
      {stage === "request" && (
        <div className="flex gap-3 px-6 py-4 border-t border-slate-200">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 text-slate-700 border border-slate-300 rounded-lg hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            onClick={handleGenerateRequest}
            disabled={generating || !request.trim()}
            className="flex-1 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-slate-300"
          >
            {generating ? "Generating..." : "Generate"}
          </button>
        </div>
      )}
    </div>
  );
}
