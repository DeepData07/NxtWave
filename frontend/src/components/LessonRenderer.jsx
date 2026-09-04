import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

function normaliseLegacyMath(math) {
  return math
    .replace(/(?<!\\)\|([A-Za-z][A-Za-z0-9_]*)\|/g, "\\lVert $1 \\rVert")
    .replace(/\\rVert\s*;\s*\\lVert/g, "\\rVert \\cdot \\lVert");
}

function normaliseLessonMarkdown(markdown) {
  const lines = markdown.split(/\r?\n/);
  const output = [];
  for (let index = 0; index < lines.length;) {
    const line = lines[index];
    if (!line.includes("\t")) {
      output.push(line);
      index += 1;
      continue;
    }
    const rows = [];
    let cursor = index;
    const columnCount = line.split("\t").length;
    while (cursor < lines.length && lines[cursor].includes("\t") && lines[cursor].split("\t").length === columnCount) {
      rows.push(lines[cursor].split("\t").map((cell) => cell.trim().replaceAll("|", "\\|")));
      cursor += 1;
    }
    if (rows.length < 2 || columnCount < 2) {
      output.push(...rows.map((row) => row.join("\t")));
      index = cursor;
      continue;
    }
    output.push(
      `| ${rows[0].join(" | ")} |`,
      `| ${rows[0].map(() => "---").join(" | ")} |`,
      ...rows.slice(1).map((row) => `| ${row.join(" | ")} |`),
    );
    index = cursor;
  }
  const withTables = output.join("\n");

  return withTables
    .replace(/^\[\s*\n([\s\S]*?)\n\s*\]$/gm, (block, inner) => {
      const looksMathematical = /\\(?:frac|sqrt|operatorname|text|cdot|times|top|theta|mathbf)|[=^]/.test(inner);
      return looksMathematical ? `$$\n${normaliseLegacyMath(inner.trim())}\n$$` : block;
    })
    .replace(/\\\[\s*\n?([\s\S]*?)\n?\s*\\\]/g, (_, inner) => `$$\n${normaliseLegacyMath(inner.trim())}\n$$`)
    .replace(/\\\(([^\n]*?)\\\)/g, (_, inner) => `$${normaliseLegacyMath(inner.trim())}$`);
}

function displayTitle(value) {
  const text = String(value || "");
  return text.replace(/^(what is|introduction to)\s+\1\s+/i, "$1 ");
}

export function LessonRenderer({ lesson, isRunning, currentStep }) {
  if (!lesson) {
    return (
      <div className="empty-state">
        {isRunning && <span className="lesson-loader" aria-label="Workflow is running" />}
        <p className="loading-title">{isRunning ? currentStep || "Preparing the lesson…" : "Waiting for first lesson draft…"}</p>
        <p>The first generated lesson will appear here while its quality checks run.</p>
      </div>
    );
  }
  return (
    <article className="lesson-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false }]]}
        components={{
          h1: ({ children }) => <h1>{displayTitle(children)}</h1>,
          table: ({ children }) => <div className="table-wrap"><table>{children}</table></div>,
          a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer">{children}</a>,
        }}
      >
        {normaliseLessonMarkdown(lesson)}
      </ReactMarkdown>
    </article>
  );
}
