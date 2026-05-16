import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  askQuestion,
  deleteDocument,
  getHealth,
  listDocuments,
  uploadDocument,
  type AskResponse,
  type DocumentRead,
  type HealthResponse,
  type Provider,
} from "./api";
import GraphView from "./GraphView";

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [docs, setDocs] = useState<DocumentRead[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refreshDocs = useCallback(async () => {
    try {
      setDocs(await listDocuments());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    getHealth().then(setHealth).catch((e: Error) => setError(e.message));
    void refreshDocs();
  }, [refreshDocs]);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <Header health={health} />
      <main className="mx-auto max-w-4xl space-y-8 px-6 py-8">
        {error && (
          <div className="rounded border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-800">
            {error}
            <button
              onClick={() => setError(null)}
              className="float-right text-red-600 hover:underline"
            >
              dismiss
            </button>
          </div>
        )}
        <DocumentsSection
          docs={docs}
          refresh={refreshDocs}
          onError={setError}
        />
        <AskSection docs={docs} onError={setError} />
        <GraphView docs={docs} onError={setError} />
      </main>
    </div>
  );
}

function Header({ health }: { health: HealthResponse | null }) {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
        <h1 className="text-xl font-semibold tracking-tight">PaperMind</h1>
        {health && (
          <div className="flex gap-2 text-xs">
            <Badge label="LLM" value={health.claude_model} />
            <Badge label="Embeddings" value={health.embedding_model.split("/").pop()!} />
          </div>
        )}
      </div>
    </header>
  );
}

function Badge({ label, value }: { label: string; value: string }) {
  return (
    <span className="rounded bg-slate-100 px-2 py-1 font-mono text-slate-700">
      <span className="text-slate-500">{label}:</span> {value}
    </span>
  );
}

function DocumentsSection({
  docs,
  refresh,
  onError,
}: {
  docs: DocumentRead[];
  refresh: () => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [uploading, setUploading] = useState(false);

  async function handleUpload(file: File) {
    setUploading(true);
    try {
      await uploadDocument(file);
      await refresh();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteDocument(id);
      await refresh();
    } catch (e) {
      onError((e as Error).message);
    }
  }

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-medium">Documents</h2>
      <label className="block">
        <span className="sr-only">Upload a document</span>
        <input
          type="file"
          disabled={uploading}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) {
              void handleUpload(file);
              e.target.value = ""; // allow re-upload of the same file
            }
          }}
          className="block w-full cursor-pointer rounded border border-slate-300 bg-white text-sm file:mr-3 file:cursor-pointer file:border-0 file:bg-slate-700 file:px-4 file:py-2 file:text-white hover:file:bg-slate-800 disabled:opacity-50"
        />
        {uploading && (
          <p className="mt-2 text-xs text-slate-500">
            Uploading and ingesting… first run downloads the embedding model.
          </p>
        )}
      </label>

      {docs.length === 0 ? (
        <p className="text-sm text-slate-500">No documents yet.</p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded border border-slate-200 bg-white">
          {docs.map((doc) => (
            <li key={doc.id} className="flex items-center justify-between px-4 py-3">
              <div>
                <div className="font-medium">{doc.filename}</div>
                <div className="text-xs text-slate-500">
                  {doc.status} · {doc.chunk_count} chunks ·{" "}
                  {(doc.size_bytes / 1024).toFixed(1)} KB
                  {doc.error && (
                    <span className="ml-2 text-red-600">error: {doc.error}</span>
                  )}
                </div>
              </div>
              <button
                onClick={() => handleDelete(doc.id)}
                className="text-sm text-red-600 hover:underline"
              >
                delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

type AskState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ok"; response: AskResponse }
  | { status: "error"; message: string };

function AskSection({
  docs,
  onError,
}: {
  docs: DocumentRead[];
  onError: (msg: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [scope, setScope] = useState<"all" | number>("all");
  const [compare, setCompare] = useState(false);
  const [useTools, setUseTools] = useState(false);
  const [useGraph, setUseGraph] = useState(false);

  // Two independent slots so each provider's pane updates as soon as its
  // own request comes back (no waiting for the slower one).
  const [claudeState, setClaudeState] = useState<AskState>({ status: "idle" });
  const [openaiState, setOpenaiState] = useState<AskState>({ status: "idle" });

  async function runOne(
    provider: Provider,
    setState: (s: AskState) => void,
  ): Promise<void> {
    setState({ status: "loading" });
    try {
      const response = await askQuestion({
        question,
        top_k: 5,
        document_id: scope === "all" ? null : scope,
        provider,
        use_tools: provider === "claude" ? useTools : false,
        use_graph: useGraph,
      });
      setState({ status: "ok", response });
    } catch (e) {
      const message = (e as Error).message;
      setState({ status: "error", message });
      onError(`${provider}: ${message}`);
    }
  }

  async function handleAsk() {
    if (!question.trim()) return;
    setClaudeState({ status: "idle" });
    setOpenaiState({ status: "idle" });
    if (compare) {
      // Fire both in parallel — each pane fills in as its request finishes.
      void Promise.all([
        runOne("claude", setClaudeState),
        runOne("openai", setOpenaiState),
      ]);
    } else {
      void runOne("claude", setClaudeState);
    }
  }

  const anyBusy =
    claudeState.status === "loading" || openaiState.status === "loading";

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-medium">Ask</h2>
      <div className="space-y-3 rounded border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <label>
            Scope:{" "}
            <select
              value={scope}
              onChange={(e) =>
                setScope(e.target.value === "all" ? "all" : Number(e.target.value))
              }
              className="ml-2 rounded border border-slate-300 px-2 py-1"
            >
              <option value="all">All documents</option>
              {docs
                .filter((d) => d.status === "ready")
                .map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.filename}
                  </option>
                ))}
            </select>
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={compare}
              onChange={(e) => setCompare(e.target.checked)}
            />
            Compare Claude vs GPT-4
          </label>
          <label className="flex items-center gap-1" title="Claude-only; GPT-4 pane ignores this">
            <input
              type="checkbox"
              checked={useTools}
              onChange={(e) => setUseTools(e.target.checked)}
            />
            Enable tools (web_search · web_fetch · calculator)
          </label>
          <label
            className="flex items-center gap-1"
            title="Expand retrieval through the knowledge graph: extract entities from the question, look up their neighbours, pull in chunks from related documents."
          >
            <input
              type="checkbox"
              checked={useGraph}
              onChange={(e) => setUseGraph(e.target.checked)}
            />
            Use knowledge graph (GraphRAG)
          </label>
        </div>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What does your document say about…"
          rows={3}
          className="w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
        />
        <button
          onClick={handleAsk}
          disabled={anyBusy || !question.trim()}
          className="rounded bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-900 disabled:opacity-50"
        >
          {anyBusy ? "Asking…" : compare ? "Ask both" : "Ask"}
        </button>
      </div>

      {compare ? (
        <div className="grid gap-4 md:grid-cols-2">
          <ResultPane title="Claude" state={claudeState} />
          <ResultPane title="GPT-4" state={openaiState} />
        </div>
      ) : (
        claudeState.status !== "idle" && (
          <ResultPane title="Claude" state={claudeState} />
        )
      )}
    </section>
  );
}

function ResultPane({ title, state }: { title: string; state: AskState }) {
  return (
    <div className="space-y-4 rounded border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-medium text-slate-500">{title}</h3>
      {state.status === "idle" && (
        <p className="text-sm text-slate-400">No response yet.</p>
      )}
      {state.status === "loading" && (
        <p className="text-sm text-slate-500">Asking…</p>
      )}
      {state.status === "error" && (
        <p className="text-sm text-red-600">{state.message}</p>
      )}
      {state.status === "ok" && <ResultBody response={state.response} />}
    </div>
  );
}

function ResultBody({ response }: { response: AskResponse }) {
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 font-mono text-xs text-slate-500">
          {response.model}
        </div>
        <div className="prose prose-slate prose-sm max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {response.answer}
          </ReactMarkdown>
        </div>
      </div>
      {response.tool_uses.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-medium uppercase text-slate-500">
            Tool calls ({response.tool_uses.length})
          </h4>
          <ul className="space-y-1 text-xs">
            {response.tool_uses.map((t, i) => (
              <li key={i} className="rounded bg-amber-50 px-2 py-1">
                <span className="font-mono text-amber-900">{t.name}</span>
                <span className="ml-2 text-slate-600">
                  {JSON.stringify(t.input)}
                </span>
                <span className="ml-2 text-slate-500">→ {t.result}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {response.citations.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-medium uppercase text-slate-500">
            Citations ({response.citations.length})
          </h4>
          <ul className="space-y-2">
            {response.citations.map((c) => (
              <li
                key={c.chunk_id}
                className="rounded bg-slate-50 px-3 py-2 text-sm"
              >
                <div className="mb-1 flex items-center gap-2 font-mono text-xs text-slate-500">
                  <span>
                    [chunk:{c.chunk_id}] · doc {c.document_id} · pos {c.position}
                  </span>
                  {c.source === "graph" && (
                    <span
                      className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium uppercase text-amber-900"
                      title="Surfaced via knowledge-graph expansion — vector search would have missed this chunk."
                    >
                      via graph
                    </span>
                  )}
                </div>
                <div className="prose prose-slate prose-sm max-w-none text-slate-700">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {c.text}
                  </ReactMarkdown>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
