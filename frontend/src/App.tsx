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
} from "./api";

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

function AskSection({
  docs,
  onError,
}: {
  docs: DocumentRead[];
  onError: (msg: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [scope, setScope] = useState<"all" | number>("all");
  const [asking, setAsking] = useState(false);
  const [result, setResult] = useState<AskResponse | null>(null);

  async function handleAsk() {
    if (!question.trim()) return;
    setAsking(true);
    setResult(null);
    try {
      const response = await askQuestion({
        question,
        top_k: 5,
        document_id: scope === "all" ? null : scope,
      });
      setResult(response);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setAsking(false);
    }
  }

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-medium">Ask</h2>
      <div className="space-y-3 rounded border border-slate-200 bg-white p-4">
        <label className="block text-sm">
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
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What does your document say about…"
          rows={3}
          className="w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
        />
        <button
          onClick={handleAsk}
          disabled={asking || !question.trim()}
          className="rounded bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-900 disabled:opacity-50"
        >
          {asking ? "Asking…" : "Ask"}
        </button>
      </div>

      {result && (
        <div className="space-y-4 rounded border border-slate-200 bg-white p-4">
          <div>
            <h3 className="mb-2 text-sm font-medium text-slate-500">
              Answer · {result.model}
            </h3>
            {/* Claude responds in markdown — render it as such. `prose` gives
                sensible defaults for headings/lists/code; `max-w-none` opts
                out of the typography plugin's default 65ch line cap. */}
            <div className="prose prose-slate prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {result.answer}
              </ReactMarkdown>
            </div>
          </div>
          {result.citations.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-medium text-slate-500">
                Citations ({result.citations.length})
              </h3>
              <ul className="space-y-2">
                {result.citations.map((c) => (
                  <li
                    key={c.chunk_id}
                    className="rounded bg-slate-50 px-3 py-2 text-sm"
                  >
                    <div className="mb-1 font-mono text-xs text-slate-500">
                      [chunk:{c.chunk_id}] · doc {c.document_id} · pos {c.position}
                    </div>
                    {/* Chunks are extracted from markdown source docs, so
                        rendering them as markdown preserves headings/lists/
                        code blocks from the original. */}
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
      )}
    </section>
  );
}
