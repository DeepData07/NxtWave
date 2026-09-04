const apiUrl = (path) => path;

async function request(path, options) {
  const response = await fetch(apiUrl(path), options);
  if (!response.ok) throw new Error(`API request failed (${response.status}).`);
  return response.json();
}

export function listRuns() {
  return request("/api/runs");
}

export function getRun(runId) {
  return request(`/api/runs/${encodeURIComponent(runId)}`);
}

export function createRun({ topic, maxRevisions, demoFault }) {
  return request("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic,
      max_revisions: maxRevisions,
      demo_fault: demoFault,
    }),
  });
}

export function subscribeToRunEvents(runId, onEvent) {
  const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
  source.addEventListener("workflow", onEvent);
  return () => source.close();
}
