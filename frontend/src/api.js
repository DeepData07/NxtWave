const apiUrl = (path) => path;

async function request(path) {
  const response = await fetch(apiUrl(path));
  if (!response.ok) throw new Error(`API request failed (${response.status}).`);
  return response.json();
}

export function listRuns() {
  return request("/api/runs");
}

export function getRun(runId) {
  return request(`/api/runs/${encodeURIComponent(runId)}`);
}
