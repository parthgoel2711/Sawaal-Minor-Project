import type {
  AuditRow,
  MemoryItem,
  Me,
  Role,
  UserRow,
  AutoDashboard,
  DocAnswer,
  DocumentInfo,
  DatabaseInfo,
  ExecuteResponse,
  ExplainResponse,
  GenerateResponse,
  Health,
  HistoryItem,
  HistoryTurn,
  Profile,
  Schema,
  Stats,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can't reach the server. Is the backend running?");
  }

  if (res.status === 401 && !path.startsWith("/auth/")) window.dispatchEvent(new Event("sawaal:unauthorized"));
  if (!res.ok) {
    let message = res.statusText || `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export const api = {
  health: () => request<Health>("/health"),
  me: () => request<Me>("/auth/me"),
  login: (username: string, password: string) =>
    request<{ user: { username: string; role: Role } }>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  users: () => request<UserRow[]>("/users"),
  addUser: (username: string, password: string, role: Role) =>
    request<UserRow>("/users", { method: "POST", body: JSON.stringify({ username, password, role }) }),
  deleteUser: (id: number) => request<void>(`/users/${id}`, { method: "DELETE" }),
  audit: (action?: string) => request<AuditRow[]>(`/audit?limit=300${action ? `&action=${enc(action)}` : ""}`),
  memory: (databaseId: string) => request<MemoryItem[]>(`/memory?database_id=${enc(databaseId)}`),
  teachExample: (database_id: string, question: string, sql: string) =>
    request<MemoryItem>("/memory/examples", { method: "POST", body: JSON.stringify({ database_id, question, sql }) }),
  teachNote: (database_id: string, text: string) =>
    request<MemoryItem>("/memory/notes", { method: "POST", body: JSON.stringify({ database_id, text }) }),
  forget: (id: number) => request<void>(`/memory/${id}`, { method: "DELETE" }),
  databases: () => request<DatabaseInfo[]>("/databases"),
  schema: (id: string) => request<Schema>(`/databases/${enc(id)}/schema`),
  profile: (id: string) => request<Profile>(`/databases/${enc(id)}/profile`),
  stats: (id: string) => request<Stats>(`/stats?database_id=${enc(id)}`),
  examples: (id: string) => request<string[]>(`/databases/${enc(id)}/examples`),
  upload: (file: File, databaseId?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (databaseId) form.append("database_id", databaseId);
    return request<DatabaseInfo>("/databases/upload", { method: "POST", body: form });
  },
  connect: (name: string, url: string) =>
    request<DatabaseInfo>("/databases/connect", { method: "POST", body: JSON.stringify({ name, url }) }),
  autoDashboard: (id: string) =>
    request<AutoDashboard>(`/databases/${enc(id)}/auto-dashboard`, { method: "POST", body: JSON.stringify({ count: 6 }) }),

  documents: () => request<DocumentInfo[]>("/documents"),
  uploadDocument: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentInfo>("/documents", { method: "POST", body: form });
  },
  deleteDocument: (id: number) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  askDocuments: (body: { question: string; document_ids?: number[]; database_id?: string }) =>
    request<DocAnswer>("/documents/ask", { method: "POST", body: JSON.stringify(body) }),

  deleteDatabase: (id: string) => request<void>(`/databases/${enc(id)}`, { method: "DELETE" }),

  generate: (body: { database_id: string; question: string; history: HistoryTurn[] }, signal?: AbortSignal) =>
    request<GenerateResponse>("/generate", { method: "POST", body: JSON.stringify(body), signal }),
  /** Same as `generate`, but reports each step as it happens. Resolves with the final answer. */
  generateStream: async (
    body: { database_id: string; question: string; history: HistoryTurn[] },
    onStatus: (message: string) => void,
    signal?: AbortSignal,
  ): Promise<GenerateResponse> => {
    let res: Response;
    try {
      res = await fetch("/api/generate/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      });
    } catch {
      throw new ApiError(0, "Can't reach the server. Is the backend running?");
    }
    if (res.status === 401) window.dispatchEvent(new Event("sawaal:unauthorized"));
    if (!res.ok || !res.body) {
      let message = res.statusText || `Request failed (${res.status})`;
      try {
        const b = await res.json();
        if (typeof b.detail === "string") message = b.detail;
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, message);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut: number;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const event = /^event: (.+)$/m.exec(block)?.[1];
        const data = /^data: (.+)$/m.exec(block)?.[1];
        if (!event || !data) continue;
        const payload = JSON.parse(data);
        if (event === "status") onStatus(payload.message);
        else if (event === "repair") onStatus("That query failed, trying again");
        else if (event === "error") throw new ApiError(payload.status ?? 500, payload.detail ?? "Something went wrong");
        else if (event === "done") return payload as GenerateResponse;
      }
    }
    throw new ApiError(0, "The connection closed before an answer arrived.");
  },
  execute: (body: { database_id: string; sql: string; question?: string; save_to_history?: boolean }) =>
    request<ExecuteResponse>("/execute", { method: "POST", body: JSON.stringify(body) }),

  explain: (body: { database_id: string; sql: string }) =>
    request<ExplainResponse>("/explain", { method: "POST", body: JSON.stringify(body) }),

  history: (databaseId: string, starred = false) =>
    request<HistoryItem[]>(`/history?database_id=${enc(databaseId)}&starred=${starred}`),
  starHistory: (id: number, starred: boolean) =>
    request<HistoryItem>(`/history/${id}`, { method: "PATCH", body: JSON.stringify({ starred }) }),
  deleteHistory: (id: number) => request<void>(`/history/${id}`, { method: "DELETE" }),
  clearHistory: (databaseId: string) => request<void>(`/history?database_id=${enc(databaseId)}`, { method: "DELETE" }),
};

export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}
