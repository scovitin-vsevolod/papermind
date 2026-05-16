// Thin typed wrapper over the backend REST API.
//
// One module owns the URL + the wire types — components import these
// instead of building fetch() calls inline. Keeps the API surface
// reviewable from one place and makes swapping the transport (e.g.
// to React Query later) a one-file change.

// Default to a relative URL — Vite's dev server (see vite.config.ts) proxies
// /api/* to the FastAPI backend. Same-origin in the browser, no CORS dance,
// and a custom Valet/nginx domain "just works" without env tweaks.
// Override with VITE_API_URL when running a built bundle pointed at a
// non-proxied backend.
const API_URL = import.meta.env.VITE_API_URL ?? "/api";

export interface HealthResponse {
  status: string;
  claude_model: string;
  embedding_model: string;
}

export interface DocumentRead {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: string;
  error: string | null;
  chunk_count: number;
  created_at: string;
}

export interface CitationOut {
  chunk_id: number;
  document_id: number;
  position: number;
  text: string;
}

export interface AskResponse {
  answer: string;
  model: string;
  citations: CitationOut[];
  tool_uses: ToolUseOut[];
}

export type Provider = "claude" | "openai";

export interface AskRequest {
  question: string;
  top_k?: number;
  document_id?: number | null;
  provider?: Provider;
  use_tools?: boolean;
}

export interface ToolUseOut {
  name: string;
  input: Record<string, unknown>;
  result: string;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: string;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail ?? res.statusText;
    } catch {
      detail = res.statusText;
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

export async function getHealth(): Promise<HealthResponse> {
  return handle(await fetch(`${API_URL}/health`));
}

export async function listDocuments(): Promise<DocumentRead[]> {
  return handle(await fetch(`${API_URL}/documents`));
}

export async function uploadDocument(file: File): Promise<DocumentRead> {
  const formData = new FormData();
  formData.append("file", file);
  return handle(
    await fetch(`${API_URL}/documents`, { method: "POST", body: formData }),
  );
}

export async function deleteDocument(id: number): Promise<void> {
  const res = await fetch(`${API_URL}/documents/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
}

export async function askQuestion(req: AskRequest): Promise<AskResponse> {
  return handle(
    await fetch(`${API_URL}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),
  );
}
