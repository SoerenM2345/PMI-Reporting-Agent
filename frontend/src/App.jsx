import { useEffect, useState } from "react";

import * as api from "./api";
import AnalysisPanel from "./components/AnalysisPanel";
import Downloads from "./components/Downloads";
import ProjectSetup from "./components/ProjectSetup";
import RequestBar from "./components/RequestBar";
import UploadZone from "./components/UploadZone";

/**
 * The §4 core user journey: upload → ask → resolve → generate.
 *
 * Analysis and generation are separate calls on purpose. Resolving a conflict must not
 * re-run extraction — that would re-pay for the vision calls on every screenshot and
 * could change the answer underneath the user between the question and their reply.
 */
export default function App() {
  const [sessionId, setSessionId] = useState(null);
  const [files, setFiles] = useState([]);
  const [rejected, setRejected] = useState([]);
  const [projectSaved, setProjectSaved] = useState(false);

  const [request, setRequest] = useState("");
  const [audience, setAudience] = useState(null);
  const [askingAudience, setAskingAudience] = useState(false);

  const [analysis, setAnalysis] = useState(null);
  const [result, setResult] = useState(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.createSession()
      .then((body) => setSessionId(body.session_id))
      .catch((e) => setError(`Could not start a session: ${e.message}`));
  }, []);

  const run = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const handleUpload = (selected) =>
    run(async () => {
      const body = await api.uploadFiles(sessionId, selected);
      setFiles(body.files);
      setRejected(body.rejected ?? []);
      // New files invalidate any previous analysis.
      setAnalysis(null);
      setResult(null);
    });

  const handleProject = (form) =>
    run(async () => {
      await api.setProject({ session_id: sessionId, ...form });
      setProjectSaved(true);
    });

  const handleAnalyze = () =>
    run(async () => {
      setResult(null);
      const body = await api.analyze({
        session_id: sessionId,
        request_text: request,
        audience,
      });

      if (body.needs_audience) {
        // §4: the agent could not infer the audience, so it asks rather than guessing.
        setAskingAudience(true);
        setAnalysis(null);
        return;
      }

      setAskingAudience(false);
      setAudience(body.audience);
      setAnalysis(body);
    });

  const handleResolve = (conflictId, choice) =>
    run(async () => {
      const body = await api.resolveConflicts(sessionId, { [conflictId]: choice });
      setAnalysis(body);
    });

  const handleGenerate = (force) =>
    run(async () => {
      const body = await api.generate(sessionId, force);
      setResult(body);
    });

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-bold text-slate-900">PMI Reporting Agent</h1>
        <p className="text-sm text-slate-500">
          Turn a week of fragmented integration files into an audience-specific report —
          with every figure traced back to the file it came from.
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded border border-rag-red/40 bg-red-50 p-3 text-sm text-rag-red">
          {error}
        </div>
      )}

      <div className="space-y-4">
        <UploadZone
          files={files}
          rejected={rejected}
          onUpload={handleUpload}
          busy={busy || !sessionId}
        />

        {files.length > 0 && (
          <ProjectSetup onSave={handleProject} saved={projectSaved} busy={busy} />
        )}

        {files.length > 0 && (
          <RequestBar
            request={request}
            setRequest={setRequest}
            audience={audience}
            setAudience={setAudience}
            askingAudience={askingAudience}
            onAnalyze={handleAnalyze}
            busy={busy}
            canAnalyze={request.trim().length > 0 && (!askingAudience || audience)}
          />
        )}

        {analysis && (
          <AnalysisPanel
            analysis={analysis}
            onResolve={handleResolve}
            onGenerate={handleGenerate}
            busy={busy}
          />
        )}

        {result && (
          <Downloads
            sessionId={sessionId}
            outputs={result.outputs ?? []}
            summary={result.summary ?? []}
            unresolved={result.generated_with_unresolved_conflicts ?? []}
          />
        )}
      </div>
    </div>
  );
}
