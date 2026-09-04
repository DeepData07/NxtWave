const form = document.querySelector("#run-form");
const startPanel = document.querySelector("#start-panel");
const runArea = document.querySelector("#run-area");
const generateButton = document.querySelector("#generate-button");
const summary = document.querySelector("#run-summary");
const currentStep = document.querySelector("#current-step");
const completionNotice = document.querySelector("#completion-notice");
const timeline = document.querySelector("#timeline");
const attemptCards = document.querySelector("#attempt-cards");
const gateSection = document.querySelector("#gate-section");
const gateList = document.querySelector("#gate-list");
const staticSection = document.querySelector("#static-section");
const staticChecks = document.querySelector("#static-checks");
const changesSection = document.querySelector("#changes-section");
const retryChanges = document.querySelector("#retry-changes");
const lessonHeading = document.querySelector("#lesson-heading");
const lessonStatus = document.querySelector("#lesson-status");
const lessonContent = document.querySelector("#lesson-content");
const downloadButton = document.querySelector("#download-lesson");
const runError = document.querySelector("#run-error");

let runId = null;
let eventSource = null;
let refreshTimer = null;
let selectedAttemptNumber = null;
let latestView = null;

const symbols = { completed: "✓", failed: "✕", retry: "↻", warning: "⚠", started: "◌" };

function statusClass(status) {
  if (["PASSED", "READY_TO_SHIP"].includes(status)) return "status-passed";
  if (["REJECTED", "NEEDS_HUMAN_REVIEW", "RESEARCH_FAILED", "FAILED"].includes(status)) return "status-rejected";
  return "status-running";
}

function setRunError(message) {
  runError.hidden = !message;
  runError.textContent = message || "";
}

function renderSummary(view) {
  const run = view.run;
  summary.replaceChildren();
  [
    ["Topic", run.topic || "Preparing run..."],
    ["Status", run.status.replaceAll("_", " ")],
    ["Attempts", String(view.attempts?.length ?? 0)],
    ["Sources", String(view.grounding?.source_count ?? 0)],
  ].forEach(([label, value]) => {
    const item = document.createElement("span");
    item.className = "summary-item";
    item.textContent = `${label}:`;
    const strong = document.createElement("strong");
    strong.textContent = value;
    item.append(strong);
    summary.append(item);
  });

  currentStep.hidden = false;
  currentStep.replaceChildren();
  const label = document.createElement("span");
  label.textContent = "CURRENT STEP";
  currentStep.append(label, document.createTextNode(run.current_step || run.status.replaceAll("_", " ")));

  const isComplete = run.status !== "RUNNING";
  completionNotice.hidden = !isComplete;
  completionNotice.className = "completion-notice";
  if (run.status === "READY_TO_SHIP") {
    completionNotice.textContent = "Workflow complete — all static checks and all 8 quality gates passed. This lesson is ready to ship.";
  } else if (run.status === "NEEDS_HUMAN_REVIEW") {
    completionNotice.classList.add("review");
    completionNotice.textContent = `Workflow complete — human review required after ${view.attempts.length} total attempts. The latest lesson is available below for review and download.`;
  } else {
    completionNotice.classList.add("failure");
    completionNotice.textContent = "Workflow stopped before it could produce a shippable lesson. Review the visible error and saved evidence.";
  }
}

function renderTimeline(events) {
  timeline.replaceChildren();
  events.forEach((event) => {
    const item = document.createElement("li");
    item.className = `timeline-item ${event.status}`;
    const icon = document.createElement("span");
    icon.className = "timeline-icon";
    icon.textContent = symbols[event.status] || "•";
    const copy = document.createElement("div");
    const title = document.createElement("p");
    title.className = "timeline-title";
    title.textContent = event.title;
    copy.append(title);
    if (event.detail) {
      const detail = document.createElement("p");
      detail.className = "timeline-detail";
      detail.textContent = event.detail;
      copy.append(detail);
    }
    item.append(icon, copy);
    timeline.append(item);
  });
}

function selectedAttempt(view) {
  const attempts = view.attempts || [];
  return attempts.find((attempt) => attempt.number === selectedAttemptNumber) || attempts.at(-1);
}

function renderAttempts(view) {
  const attempts = view.attempts || [];
  if (!attempts.some((attempt) => attempt.number === selectedAttemptNumber)) {
    selectedAttemptNumber = attempts.at(-1)?.number ?? null;
  }
  attemptCards.replaceChildren();
  attempts.forEach((attempt) => {
    const failed = attempt.failed_gates || [];
    const passedCount = (attempt.gates || []).filter((gate) => gate.passed).length;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `attempt-card ${attempt.number === selectedAttemptNumber ? "selected" : ""}`;
    button.addEventListener("click", () => {
      selectedAttemptNumber = attempt.number;
      renderAttemptDetails(latestView);
    });
    const title = document.createElement("strong");
    title.textContent = `Attempt ${attempt.number}`;
    const result = document.createElement("span");
    result.className = `attempt-result ${attempt.status.toLowerCase()}`;
    result.textContent = attempt.status;
    const detail = document.createElement("span");
    detail.textContent = attempt.gates?.length ? `${passedCount} / 8 gates passed` : "Evaluation in progress";
    button.append(title, result, detail);
    if (failed.length) {
      const failure = document.createElement("span");
      failure.textContent = `Failed: ${failed.map((gate) => `${gate.id} — ${gate.label}`).join(", ")}`;
      button.append(failure);
    }
    attemptCards.append(button);
  });
}

function renderGates(attempt) {
  gateSection.hidden = !attempt?.gates?.length;
  gateList.replaceChildren();
  (attempt?.gates || []).forEach((gate) => {
    const row = document.createElement("div");
    row.className = "gate-row";
    const icon = document.createElement("span");
    icon.className = `gate-icon ${gate.passed ? "pass" : "fail"}`;
    icon.textContent = gate.passed ? "✓" : "✕";
    const text = document.createElement("span");
    text.textContent = `${gate.id}  ${gate.label}`;
    row.append(icon, text);
    gateList.append(row);
    if (!gate.passed) {
      const details = document.createElement("details");
      details.className = "gate-details";
      const title = document.createElement("summary");
      title.textContent = "Why this gate failed";
      details.append(title);
      [["WHY IT FAILED", gate.reason], ["EVIDENCE", gate.evidence], ["TARGETED FIX", gate.required_fix]].forEach(([label, value]) => {
        const paragraph = document.createElement("p");
        const heading = document.createElement("strong");
        heading.textContent = label;
        paragraph.append(heading, document.createTextNode(value || "Unavailable."));
        details.append(paragraph);
      });
      gateList.append(details);
    }
  });
}

function renderStaticChecks(attempt) {
  staticSection.hidden = !attempt?.static_checks;
  staticChecks.replaceChildren();
  if (!attempt?.static_checks) return;
  const checks = attempt.static_checks;
  const rows = [
    [checks.word_count >= 700 && checks.word_count <= 2200, `Word count: ${checks.word_count}`],
    [!checks.missing_headings?.length, `Required sections: ${checks.missing_headings?.length ? `missing ${checks.missing_headings.join(", ")}` : "complete"}`],
    [checks.learner_questions >= 3, `Learner questions: ${checks.learner_questions} / minimum 3`],
    [checks.passed, checks.passed ? "Lesson structure valid" : "Lesson structure needs revision"],
  ];
  rows.forEach(([passed, label]) => {
    const row = document.createElement("div");
    row.className = "static-row";
    const icon = document.createElement("span");
    icon.className = `static-icon ${passed ? "pass" : "fail"}`;
    icon.textContent = passed ? "✓" : "✕";
    row.append(icon, document.createTextNode(label));
    staticChecks.append(row);
  });
}

function renderRetryChanges(view, attempt) {
  const change = (view.retry_changes || []).find((item) => item.to_attempt === attempt?.number);
  changesSection.hidden = !change;
  retryChanges.replaceChildren();
  if (!change) return;
  const header = document.createElement("p");
  header.textContent = `Attempt ${change.from_attempt} → Attempt ${change.to_attempt}`;
  retryChanges.append(header);
  (change.resolved_gates || []).forEach((gate) => {
    const row = document.createElement("div");
    row.className = "retry-change";
    row.innerHTML = "";
    const title = document.createElement("p");
    title.textContent = `${gate.id} — ${gate.label}: FAIL → PASS`;
    const fix = document.createElement("p");
    fix.textContent = `Evaluator requested: ${gate.targeted_fix}`;
    row.append(title, fix);
    retryChanges.append(row);
  });
  (change.supporting_diagnostics || []).forEach((diagnostic) => {
    const row = document.createElement("p");
    row.textContent = `${diagnostic.label}: ${diagnostic.before} → ${diagnostic.after}`;
    retryChanges.append(row);
  });
}

function normaliseBracketedMath(markdown) {
  return markdown.replace(/^\[\s*\n([\s\S]*?\\(?:frac|sqrt|operatorname|text|cdot|top|theta|[A-Za-z]))[\s\S]*?\n\s*\]$/gm, (block) => {
    const inner = block.slice(1, -1).trim();
    return `\\[\n${inner}\n\\]`;
  });
}

function normaliseDisplayTitle(title, topic) {
  const clean = title.trim();
  const repeatedPrefix = /^(what is|introduction to)\s+\1\s+/i;
  if (repeatedPrefix.test(clean)) return clean.replace(repeatedPrefix, "$1 ");
  return clean;
}

function promoteBareDisplayHeadings(container, topic) {
  const canonical = topic.trim().replace(/[?!:]+$/, "").toLowerCase();
  const sectionNames = new Set([
    "start with a simple problem", "why does it matter", "why it matters", "how does it work",
    "step-by-step example", "important terms", "limitations", "quick recap", "check your understanding",
  ]);
  [...container.querySelectorAll("p")].forEach((paragraph, index) => {
    const text = paragraph.textContent.trim();
    const normalized = text.replace(/[?!:]+$/, "").toLowerCase();
    const displayTitle = normaliseDisplayTitle(text, topic);
    const titleMatchesTopic = displayTitle.replace(/[?!:]+$/, "").toLowerCase() === canonical;
    const duplicateQuestionHeading = /^what is\s+what is\s+/i.test(text);
    if ((index === 0 && titleMatchesTopic) || duplicateQuestionHeading) {
      const heading = document.createElement(index === 0 ? "h1" : "h2");
      heading.textContent = normaliseDisplayTitle(text, topic);
      paragraph.replaceWith(heading);
    } else if (sectionNames.has(normalized)) {
      const heading = document.createElement("h2");
      heading.textContent = text;
      paragraph.replaceWith(heading);
    }
  });
}

async function renderMarkdown(markdown, topic) {
  lessonContent.classList.remove("empty-state");
  const safeMarkdown = normaliseBracketedMath(markdown);
  if (!window.marked || !window.DOMPurify) {
    lessonContent.textContent = markdown;
    return;
  }
  lessonContent.innerHTML = DOMPurify.sanitize(marked.parse(safeMarkdown, { gfm: true, breaks: true }));
  const firstHeading = lessonContent.querySelector("h1");
  if (firstHeading) firstHeading.textContent = normaliseDisplayTitle(firstHeading.textContent, topic);
  promoteBareDisplayHeadings(lessonContent, topic);
  if (window.MathJax?.typesetPromise) {
    try {
      await window.MathJax.typesetPromise([lessonContent]);
    } catch (_) {
      // The safe Markdown content remains readable if a provider emitted invalid LaTeX.
    }
  }
}

function renderLesson(view, attempt) {
  if (!attempt?.lesson) {
    lessonHeading.textContent = "Waiting for first lesson draft...";
    lessonStatus.textContent = view.run.status.replaceAll("_", " ");
    lessonStatus.className = `status-pill ${statusClass(view.run.status)}`;
    lessonContent.className = "lesson-content empty-state";
    lessonContent.textContent = "The first generated lesson will appear here while its quality checks run.";
    downloadButton.disabled = true;
    return;
  }
  lessonHeading.textContent = `Attempt ${attempt.number}`;
  lessonStatus.textContent = attempt.status === "PASSED" ? "READY TO SHIP" : attempt.status;
  lessonStatus.className = `status-pill ${statusClass(attempt.status)}`;
  downloadButton.disabled = false;
  renderMarkdown(attempt.lesson, view.run.topic);
}

function renderAttemptDetails(view) {
  const attempt = selectedAttempt(view);
  renderAttempts(view);
  renderGates(attempt);
  renderStaticChecks(attempt);
  renderRetryChanges(view, attempt);
  renderLesson(view, attempt);
}

function downloadSelectedLesson() {
  const attempt = selectedAttempt(latestView || {});
  if (!attempt?.lesson) return;
  const safeTopic = (latestView.run.topic || "lesson").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
  const blob = new Blob([attempt.lesson], { type: "text/markdown;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${safeTopic || "lesson"}-attempt-${attempt.number}.md`;
  link.click();
  URL.revokeObjectURL(link.href);
}

downloadButton.addEventListener("click", downloadSelectedLesson);

async function refreshRun() {
  if (!runId) return;
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!response.ok) throw new Error("Unable to load workflow state.");
    const view = await response.json();
    latestView = view;
    renderSummary(view);
    renderTimeline(view.events || []);
    renderAttemptDetails(view);
    setRunError(view.workflow_error?.message || view.run?.error);
    if (view.run.status !== "RUNNING") stopLiveUpdates();
  } catch (error) {
    setRunError(error.message || "Unable to update the workflow view.");
  }
}

function startLiveUpdates() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
  eventSource.addEventListener("workflow", refreshRun);
  eventSource.onerror = () => { /* Polling is the persistent-history fallback. */ };
  refreshTimer = window.setInterval(refreshRun, 1000);
}

function stopLiveUpdates() {
  if (eventSource) eventSource.close();
  eventSource = null;
  if (refreshTimer) window.clearInterval(refreshTimer);
  refreshTimer = null;
  generateButton.disabled = false;
  generateButton.textContent = "Generate Another Lesson";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const topic = document.querySelector("#topic").value.trim();
  if (!topic) return;
  generateButton.disabled = true;
  generateButton.textContent = "Starting...";
  setRunError("");
  try {
    const response = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic,
        max_revisions: Number(document.querySelector("#max-revisions").value),
        demo_fault: document.querySelector("#demo-fault").value,
      }),
    });
    if (!response.ok) throw new Error("The workflow could not be started.");
    const created = await response.json();
    runId = created.run_id;
    selectedAttemptNumber = null;
    latestView = null;
    startPanel.hidden = true;
    runArea.hidden = false;
    await refreshRun();
    startLiveUpdates();
  } catch (error) {
    generateButton.disabled = false;
    generateButton.textContent = "Generate Lesson";
    setRunError(error.message || "The workflow could not be started.");
  }
});
