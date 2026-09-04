const form = document.querySelector("#run-form");
const startPanel = document.querySelector("#start-panel");
const runArea = document.querySelector("#run-area");
const generateButton = document.querySelector("#generate-button");
const summary = document.querySelector("#run-summary");
const timeline = document.querySelector("#timeline");
const lessonHeading = document.querySelector("#lesson-heading");
const lessonStatus = document.querySelector("#lesson-status");
const lessonContent = document.querySelector("#lesson-content");
const runError = document.querySelector("#run-error");

let runId = null;
let eventSource = null;
let refreshTimer = null;

const symbols = { completed: "✓", failed: "✕", retry: "↻", warning: "⚠", started: "◌" };

function statusClass(status) {
  if (status === "PASSED" || status === "READY_TO_SHIP") return "status-passed";
  if (status === "REJECTED" || status === "NEEDS_HUMAN_REVIEW" || status === "RESEARCH_FAILED" || status === "FAILED") return "status-rejected";
  return "status-running";
}

function setRunError(message) {
  runError.hidden = !message;
  runError.textContent = message || "";
}

function renderSummary(view) {
  const run = view.run;
  const sourceCount = view.grounding?.source_count ?? 0;
  summary.replaceChildren();
  const values = [
    ["Topic", run.topic || "Preparing run..."],
    ["Status", run.status.replaceAll("_", " ")],
    ["Attempts", String(view.attempts?.length ?? 0)],
    ["Sources", String(sourceCount)],
    ["Current step", run.current_step || "Starting"],
  ];
  values.forEach(([label, value]) => {
    const item = document.createElement("span");
    item.className = "summary-item";
    item.textContent = `${label}:`;
    const strong = document.createElement("strong");
    strong.textContent = value;
    item.append(strong);
    summary.append(item);
  });
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

function renderLessonText(markdown) {
  lessonContent.replaceChildren();
  lessonContent.classList.remove("empty-state");
  const lines = markdown.split(/\r?\n/);
  let paragraph = [];
  const flushParagraph = () => {
    if (!paragraph.length) return;
    const node = document.createElement("p");
    node.textContent = paragraph.join("\n");
    lessonContent.append(node);
    paragraph = [];
  };
  lines.forEach((line) => {
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      const node = document.createElement(`h${heading[1].length}`);
      node.textContent = heading[2];
      lessonContent.append(node);
    } else if (!line.trim()) {
      flushParagraph();
    } else {
      paragraph.push(line);
    }
  });
  flushParagraph();
}

function renderLesson(view) {
  const attempts = view.attempts || [];
  const latest = attempts.at(-1);
  if (!latest?.lesson) {
    lessonHeading.textContent = "Waiting for first lesson draft...";
    lessonStatus.textContent = view.run.status.replaceAll("_", " ");
    lessonStatus.className = `status-pill ${statusClass(view.run.status)}`;
    lessonContent.className = "lesson-content empty-state";
    lessonContent.textContent = "The first generated lesson will appear here while its quality checks run.";
    return;
  }
  lessonHeading.textContent = `Attempt ${latest.number}`;
  lessonStatus.textContent = latest.status === "PASSED" ? "READY TO SHIP" : latest.status;
  lessonStatus.className = `status-pill ${statusClass(latest.status)}`;
  renderLessonText(latest.lesson);
}

async function refreshRun() {
  if (!runId) return;
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!response.ok) throw new Error("Unable to load workflow state.");
    const view = await response.json();
    renderSummary(view);
    renderTimeline(view.events || []);
    renderLesson(view);
    const error = view.workflow_error?.message || view.run?.error;
    setRunError(error);
    if (view.run.status !== "RUNNING") stopLiveUpdates();
  } catch (error) {
    setRunError(error.message || "Unable to update the workflow view.");
  }
}

function startLiveUpdates() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
  eventSource.addEventListener("workflow", refreshRun);
  eventSource.onerror = () => { /* Polling below is the durable fallback. */ };
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
