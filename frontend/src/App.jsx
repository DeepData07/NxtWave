import { useCallback, useEffect, useMemo, useState } from "react";

import { createRun, getRun, subscribeToRunEvents } from "@/api";
import { Button } from "@/components/ui/button";
import { LessonRenderer } from "@/components/LessonRenderer";

export default function App() {
  const [view, setView] = useState(null);
  const [runId, setRunId] = useState(null);
  const [topic, setTopic] = useState("Introduction to RAG");
  const [maxRevisions, setMaxRevisions] = useState(2);
  const [demoFault, setDemoFault] = useState("none");
  const [selectedAttemptNumber, setSelectedAttemptNumber] = useState(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const ragLikeTopic = /rag|retrieval-augmented generation/i.test(topic);

  useEffect(() => {
    if (!ragLikeTopic && demoFault === "rag_factual_error") setDemoFault("none");
  }, [demoFault, ragLikeTopic]);

  const refreshRun = useCallback(async (id) => {
    const nextView = await getRun(id);
    setView(nextView);
    setSelectedAttemptNumber((current) => nextView.run?.status !== "RUNNING" ? nextView.attempts.at(-1)?.number ?? null : current ?? nextView.attempts.at(-1)?.number ?? null);
    if (nextView.workflow_error?.message || nextView.run?.error) setError(nextView.workflow_error?.message || nextView.run.error);
    return nextView;
  }, []);

  useEffect(() => {
    if (!runId || view?.run.status !== "RUNNING") return undefined;
    const refresh = () => refreshRun(runId).catch(() => setError("Unable to update the workflow view."));
    const unsubscribe = subscribeToRunEvents(runId, refresh);
    const interval = window.setInterval(refresh, 1000);
    return () => { unsubscribe(); window.clearInterval(interval); };
  }, [refreshRun, runId, view?.run.status]);

  const selectedAttempt = useMemo(() => {
    const attempts = view?.attempts || [];
    return attempts.find((attempt) => attempt.number === selectedAttemptNumber) || attempts.at(-1);
  }, [selectedAttemptNumber, view]);

  const workflowRunning = view?.run.status === "RUNNING";

  async function startRun(event) {
    event.preventDefault();
    if (!topic.trim()) return;
    setStarting(true);
    setError("");
    try {
      const created = await createRun({ topic: topic.trim(), maxRevisions: Number(maxRevisions), demoFault });
      setRunId(created.run_id);
      setSelectedAttemptNumber(null);
      await refreshRun(created.run_id);
    } catch {
      setError("The workflow could not be started. Check that FastAPI is running.");
    } finally {
      setStarting(false);
    }
  }

  function downloadLesson() {
    if (!selectedAttempt?.lesson) return;
    const safeTopic = (view.run.topic || "lesson").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([selectedAttempt.lesson], { type: "text/markdown;charset=utf-8" }));
    link.download = `${safeTopic || "lesson"}-attempt-${selectedAttempt.number}.md`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  const statusClass = (status) => ["PASSED", "READY_TO_SHIP"].includes(status) ? "pass" : ["REJECTED", "NEEDS_HUMAN_REVIEW", "FAILED", "RESEARCH_FAILED"].includes(status) ? "fail" : "running";
  const symbols = { completed: "✓", failed: "✕", retry: "↻", warning: "⚠", started: "◌" };

  return (
    <main className="shell">
      <header className="page-header">
        <p className="eyebrow">NXTWAVE</p>
        <h1>Lesson Quality Agent</h1>
        <p className="subtitle">Generate <span>→</span> Ground <span>→</span> Evaluate <span>→</span> Improve <span>→</span> Ship</p>
      </header>

      {!view && <section className="start-panel">
        <h2>Generate a grounded lesson</h2>
        <form onSubmit={startRun}>
          <label htmlFor="topic">Topic</label>
          <input id="topic" value={topic} onChange={(event) => setTopic(event.target.value)} maxLength="200" required />
          <div className="form-row">
            <div><label htmlFor="revisions">Maximum revisions</label><input id="revisions" type="number" min="0" max="2" value={maxRevisions} onChange={(event) => setMaxRevisions(event.target.value)} required /></div>
            <div><label htmlFor="fault">Demo fault</label><select id="fault" value={demoFault} onChange={(event) => setDemoFault(event.target.value)}><option value="none">None</option><option value="rag_factual_error" disabled={!ragLikeTopic}>RAG factual error</option><option value="overly_technical_language">Overly Technical Language</option><option value="remove_example_section">Remove Example</option></select></div>
          </div>
          <Button type="submit" disabled={starting}>{starting ? "Starting…" : "Generate Lesson"}</Button>
          <p className="muted">Lessons are grounded using dynamically selected authoritative sources.</p>
        </form>
        {error && <p className="run-error">{error}</p>}
      </section>}

      {view && <section className="run-area" aria-live="polite">
        <div className="run-summary">{[["Topic", view.run.topic], ["Status", view.run.status.replaceAll("_", " ")], ["Attempts", view.attempts.length], ["Sources", view.grounding.source_count]].map(([label, value]) => <span className="summary-item" key={label}>{label}: <strong>{value}</strong></span>)}{view.run.mode === "deterministic_demo" && <span className="demo-badge">DEMO SCENARIO</span>}</div>
        <div className="current-step"><span>CURRENT STEP</span>{view.run.current_step || view.run.status.replaceAll("_", " ")}</div>
        <form className="new-topic-form" onSubmit={startRun}>
          <label htmlFor="next-topic">Generate another lesson</label>
          <input id="next-topic" value={topic} onChange={(event) => setTopic(event.target.value)} maxLength="200" placeholder="Enter another topic" disabled={workflowRunning} required />
          <Button type="submit" size="sm" disabled={workflowRunning || starting}>{workflowRunning ? "Workflow running" : starting ? "Starting…" : "Generate Lesson"}</Button>
          {workflowRunning && <span className="new-topic-hint">Wait for this workflow to finish before starting another.</span>}
        </form>
        {view.run.status !== "RUNNING" && <div className={`completion-notice ${statusClass(view.run.status)}`}>{view.run.status === "READY_TO_SHIP" ? "Workflow complete — all static checks and all 8 quality gates passed. This lesson is ready to ship." : "Workflow complete — human review required after the maximum number of attempts. The latest lesson is available below for review and download."}</div>}
        {error && <p className="run-error">{error}</p>}

        <div className="workspace">
          <aside className="workflow-panel">
            <div className="section-heading"><p className="eyebrow">WORKFLOW</p><h2>How the system is working</h2></div>
            <ol className="timeline">{(view.events || []).map((event, index) => <li className={`timeline-item ${event.status}`} key={`${event.timestamp}-${event.stage}-${index}`}><span className="timeline-icon">{symbols[event.status] || "•"}</span><div><p className="timeline-title">{event.title}</p>{event.detail && <p className="timeline-detail">{event.detail}</p>}</div></li>)}</ol>

            <section className="attempt-section"><p className="eyebrow">ATTEMPTS</p><h2>Draft and revision history</h2><div className="attempt-cards">{view.attempts.map((attempt) => <button type="button" className={`attempt-card ${attempt.number === selectedAttempt?.number ? "selected" : ""}`} key={attempt.number} onClick={() => setSelectedAttemptNumber(attempt.number)}><strong>Attempt {attempt.number}</strong><span className={`attempt-result ${attempt.status.toLowerCase()}`}>{attempt.status}</span><span>{attempt.gates?.length ? `${attempt.gates.filter((gate) => gate.passed).length} / 8 gates passed` : "Evaluation in progress"}</span>{attempt.failed_gates?.length > 0 && <span>Failed: {attempt.failed_gates.map((gate) => `${gate.id} — ${gate.label}`).join(", ")}</span>}</button>)}</div></section>

            {selectedAttempt?.gates?.length > 0 && <section className="inspection-section"><p className="eyebrow">QUALITY GATES</p><h2>Selected attempt</h2><div className="gate-list">{selectedAttempt.gates.map((gate) => <div key={gate.id}><div className="gate-row"><span className={`gate-icon ${gate.passed ? "pass" : "fail"}`}>{gate.passed ? "✓" : "✕"}</span><span>{gate.id} &nbsp; {gate.label}</span></div>{!gate.passed && <details className="gate-details"><summary>Why this gate failed</summary><p><strong>WHY IT FAILED</strong>{gate.reason || "Unavailable."}</p><p><strong>EVIDENCE</strong>{gate.evidence || "Unavailable."}</p><p><strong>TARGETED FIX</strong>{gate.required_fix || "Unavailable."}</p></details>}</div>)}</div></section>}

            {selectedAttempt?.static_checks && <section className="inspection-section"><p className="eyebrow">STATIC CHECKS</p><div className="static-checks">{[[selectedAttempt.static_checks.word_count >= 700 && selectedAttempt.static_checks.word_count <= 2200, `Word count: ${selectedAttempt.static_checks.word_count}`], [!selectedAttempt.static_checks.missing_headings?.length, `Required sections: ${selectedAttempt.static_checks.missing_headings?.length ? `missing ${selectedAttempt.static_checks.missing_headings.join(", ")}` : "complete"}`], [selectedAttempt.static_checks.learner_questions >= 3, `Learner questions: ${selectedAttempt.static_checks.learner_questions} / minimum 3`], [selectedAttempt.static_checks.passed, selectedAttempt.static_checks.passed ? "Lesson structure valid" : "Lesson structure needs revision"]].map(([passed, label]) => <div className="static-row" key={label}><span className={`static-icon ${passed ? "pass" : "fail"}`}>{passed ? "✓" : "✕"}</span>{label}</div>)}</div></section>}

            {view.retry_changes?.find((change) => change.to_attempt === selectedAttempt?.number) && <section className="inspection-section"><p className="eyebrow">WHAT CHANGED</p><div className="retry-changes">{(() => { const change = view.retry_changes.find((item) => item.to_attempt === selectedAttempt.number); return <><p>Attempt {change.from_attempt} → Attempt {change.to_attempt}</p>{change.resolved_gates.map((gate) => <div className="retry-change" key={gate.id}><p>{gate.id} — {gate.label}: FAIL → PASS</p><p>Evaluator requested: {gate.targeted_fix}</p></div>)}{change.supporting_diagnostics.map((item) => <p key={item.label}>{item.label}: {item.before} → {item.after}</p>)}</>; })()}</div></section>}
          </aside>

          <section className="lesson-panel"><div className="lesson-header"><div><p className="eyebrow">LESSON OUTPUT</p><h2>{selectedAttempt ? `Attempt ${selectedAttempt.number}` : "Waiting for first lesson draft..."}</h2></div><div className="lesson-actions"><Button className="download-button" variant="outline" size="sm" type="button" disabled={!selectedAttempt?.lesson} onClick={downloadLesson}>Download .md</Button><span className={`status-pill ${statusClass(selectedAttempt?.status || view.run.status)}`}>{selectedAttempt?.status === "PASSED" ? "READY TO SHIP" : selectedAttempt?.status || "RUNNING"}</span></div></div><LessonRenderer lesson={selectedAttempt?.lesson} isRunning={workflowRunning} currentStep={view.run.current_step} /></section>
        </div>
      </section>}
    </main>
  );
}
