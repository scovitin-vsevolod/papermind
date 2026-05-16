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
  source: "vector" | "graph";
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
  use_graph?: boolean;
}

export interface ToolUseOut {
  name: string;
  input: Record<string, unknown>;
  result: string;
}

// ── Auth ────────────────────────────────────────────────────────────────────

export interface UserOut {
  id: number;
  email: string;
  created_at: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  user: UserOut;
  access_token: string;
  token_type: "bearer";
}

/**
 * Typed error thrown by all API helpers on a non-2xx response. The status
 * field lets callers branch on auth failures (401) vs everything else
 * without parsing the message string.
 */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
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
    throw new ApiError(res.status, `${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

// `credentials: "include"` ensures the httpOnly session cookie travels with
// every request — required once the routers are auth-gated. Same-origin
// fetches already do this by default in modern browsers, but being explicit
// keeps the contract obvious and works under any VITE_API_URL.
const credentials: RequestCredentials = "include";

export async function getHealth(): Promise<HealthResponse> {
  return handle(await fetch(`${API_URL}/health`, { credentials }));
}

export async function listDocuments(): Promise<DocumentRead[]> {
  return handle(await fetch(`${API_URL}/documents`, { credentials }));
}

export async function uploadDocument(file: File): Promise<DocumentRead> {
  const formData = new FormData();
  formData.append("file", file);
  return handle(
    await fetch(`${API_URL}/documents`, {
      method: "POST",
      body: formData,
      credentials,
    }),
  );
}

export async function deleteDocument(id: number): Promise<void> {
  const res = await fetch(`${API_URL}/documents/${id}`, {
    method: "DELETE",
    credentials,
  });
  if (!res.ok) throw new ApiError(res.status, `${res.status}: ${res.statusText}`);
}

export async function askQuestion(req: AskRequest): Promise<AskResponse> {
  return handle(
    await fetch(`${API_URL}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
      credentials,
    }),
  );
}

export interface GraphNode {
  name: string;
  type: string;
  document_ids: number[];
}

export interface GraphEdge {
  head: string;
  label: string;
  tail: string;
  document_ids: number[];
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export async function getGraph(documentId: number | null = null): Promise<GraphResponse> {
  const qs = documentId !== null ? `?document_id=${documentId}` : "";
  return handle(await fetch(`${API_URL}/graph${qs}`, { credentials }));
}

// ── Auth helpers ────────────────────────────────────────────────────────────

export async function login(body: LoginRequest): Promise<LoginResponse> {
  return handle(
    await fetch(`${API_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials,
    }),
  );
}

export async function logout(): Promise<void> {
  // The backend always returns 200; we don't care about the body.
  await fetch(`${API_URL}/auth/logout`, { method: "POST", credentials });
}

export async function getMe(): Promise<UserOut> {
  return handle(await fetch(`${API_URL}/auth/me`, { credentials }));
}
