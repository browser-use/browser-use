"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";

type ResearchItem = {
  task: string;
  result: string;
  executionTime: number;
};

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function Home() {
  const [task, setTask] = useState("");
  const [result, setResult] = useState("");
  const [loading, setLoading] = useState(false);
  const [executionTime, setExecutionTime] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<ResearchItem[]>([]);

  const runResearch = async () => {
    const trimmedTask = task.trim();

    if (!trimmedTask) return;

    setLoading(true);
    setResult("");
    setError("");
    setExecutionTime(null);

    try {
      const response = await fetch(`${API_URL}/research`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          task: trimmedTask,
        }),
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(
          data.detail || data.error || "Research failed.",
        );
      }

      setResult(data.result);
      setExecutionTime(data.execution_time);

      setHistory((previous) => [
        {
          task: trimmedTask,
          result: data.result,
          executionTime: data.execution_time,
        },
        ...previous.slice(0, 19),
      ]);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Something went wrong.",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-zinc-950 text-white">
      <div className="mx-auto max-w-5xl px-6 py-16">
        <div className="mb-12">
          <div className="mb-4 flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-green-400" />
            <span className="text-xs font-medium tracking-widest text-zinc-400">
              LIVE AGENT
            </span>
          </div>

          <h1 className="text-4xl font-semibold tracking-tight md:text-6xl">
            Research the web.
            <br />
            <span className="text-zinc-500">Let the agent work.</span>
          </h1>

          <p className="mt-5 max-w-2xl text-zinc-400">
            Give the browser agent a research task. It will browse the web,
            collect information, and return the result.
          </p>
        </div>

        <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
          <label
            htmlFor="research-task"
            className="mb-3 block text-sm font-medium text-zinc-300"
          >
            Research task
          </label>

          <div className="mb-4 flex flex-wrap gap-2">
            {[
              "Find the latest stable version of React and its official documentation.",
              "Compare React, Vue, and Angular using their official websites.",
              "Research the current top AI coding assistants and summarize their features.",
            ].map((example) => (
              <button
                key={example}
                onClick={() => setTask(example)}
                className="rounded-lg border border-zinc-800 px-3 py-2 text-xs text-zinc-500 transition hover:border-zinc-600 hover:text-zinc-300"
              >
                {example}
              </button>
            ))}
          </div>

          <textarea
            id="research-task"
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="Example: Compare the official documentation of React, Vue, and Angular and summarize their main differences."
            className="min-h-36 w-full resize-none rounded-xl border border-zinc-700 bg-zinc-950 p-4 text-sm outline-none placeholder:text-zinc-600 focus:border-zinc-500"
          />

          <div className="mt-4 flex items-center justify-between">
            <span className="text-xs text-zinc-500">
              {task.length} characters
            </span>

            <button
              onClick={runResearch}
              disabled={loading || !task.trim()}
              className="rounded-xl bg-white px-5 py-2.5 text-sm font-medium text-black transition hover:bg-zinc-200 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? "Researching..." : "Run Research"}
            </button>
          </div>
        </section>

        {loading && (
          <section className="mt-6 rounded-2xl border border-zinc-800 bg-zinc-900 p-6">
            <div className="flex items-center gap-3">
              <div className="h-2.5 w-2.5 animate-pulse rounded-full bg-green-400" />

              <div>
                <p className="text-sm font-medium text-zinc-200">
                  Agent is researching
                </p>

                <p className="mt-1 text-xs text-zinc-500">
                  Searching the web and analyzing the information...
                </p>
              </div>
            </div>

            <div className="mt-5 h-1 overflow-hidden rounded-full bg-zinc-800">
              <div className="h-full w-1/3 animate-pulse rounded-full bg-zinc-400" />
            </div>
          </section>
        )}

        {error && (
          <section className="mt-6 rounded-2xl border border-red-900 bg-red-950/30 p-6">
            <p className="text-sm font-medium text-red-400">Research failed</p>
            <p className="mt-2 text-sm text-red-300">{error}</p>
          </section>
        )}

        {result && !loading && (
          <section className="mt-6 rounded-2xl border border-zinc-800 bg-zinc-900 p-6">
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Research Result</h2>

              {executionTime !== null && (
                <span className="text-xs text-zinc-500">
                  {executionTime}s
                </span>
              )}
            </div>

            <div className="max-w-none text-sm leading-7">
              <ReactMarkdown
                components={{
                  a: ({ children, ...props }) => (
  <a
    {...props}
    target="_blank"
    rel="noreferrer"
    className="underline"
  >
    {children}
  </a>
),
                }}
              >
                {result}
              </ReactMarkdown>
            </div>
          </section>
        )}

        {history.length > 0 && (
          <section className="mt-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Recent Research</h2>

              <button
                onClick={() => setHistory([])}
                className="text-xs text-zinc-500 transition hover:text-white"
              >
                Clear history
              </button>
            </div>

            <div className="space-y-3">
              {history.map((item, index) => (
                <button
                  key={`${item.task}-${index}`}
                  onClick={() => {
                    setTask(item.task);
                    setResult(item.result);
                    setExecutionTime(item.executionTime);
                    setError("");
                  }}
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-left transition hover:border-zinc-600"
                >
                  <div className="flex items-start justify-between gap-4">
                    <p className="text-sm text-zinc-300">{item.task}</p>

                    <span className="shrink-0 text-xs text-zinc-500">
                      {item.executionTime}s
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}