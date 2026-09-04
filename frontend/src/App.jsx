import { useEffect, useState } from "react";

import { getRun, listRuns } from "@/api";
import { Button } from "@/components/ui/button";

export default function App() {
  const [runs, setRuns] = useState([]);
  const [run, setRun] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    listRuns()
      .then((items) => {
        if (!active) return;
        setRuns(items);
        if (items[0]?.id) return getRun(items[0].id);
        return null;
      })
      .then((view) => active && view && setRun(view))
      .catch(() => active && setError("Start the FastAPI server to load a saved run."));
    return () => { active = false; };
  }, []);

  return (
    <main className="min-h-screen bg-slate-50 px-6 py-12 text-slate-900">
      <section className="mx-auto max-w-3xl rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <p className="text-xs font-semibold tracking-[0.16em] text-slate-500">NXTWAVE</p>
        <h1 className="mt-2 text-3xl font-semibold">Lesson Quality Agent</h1>
        <p className="mt-2 text-slate-600">React migration shell — connected to the existing read-only FastAPI contract.</p>

        {error && <p className="mt-6 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {!error && !run && <p className="mt-6 text-sm text-slate-500">Loading the newest saved run…</p>}
        {run && (
          <div className="mt-6 rounded-lg border border-slate-200 p-5">
            <p className="text-sm text-slate-500">Saved run successfully loaded</p>
            <h2 className="mt-1 text-xl font-semibold">{run.run.topic || "Untitled topic"}</h2>
            <p className="mt-2 text-sm text-slate-600">
              {run.run.status.replaceAll("_", " ")} · {run.attempts.length} attempt(s) · {run.grounding.source_count} source(s)
            </p>
          </div>
        )}

        <div className="mt-6 flex flex-wrap gap-2">
          {runs.slice(0, 3).map((item) => (
            <Button key={item.id} variant="outline" size="sm" onClick={() => getRun(item.id).then(setRun).catch(() => setError("Could not load that saved run."))}>
              Load {item.topic || "saved run"}
            </Button>
          ))}
        </div>
      </section>
    </main>
  );
}
