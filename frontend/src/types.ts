export type DatabaseKind = "sample" | "upload" | "external";

export interface DatabaseInfo {
  id: string;
  name: string;
  kind: DatabaseKind;
  dialect: string;
  description: string;
  deletable: boolean;
}

export interface Column {
  name: string;
  type: string;
  nullable: boolean;
  primary_key: boolean;
  foreign_key: string | null;
  values: string[] | null;
}

export interface Table {
  name: string;
  kind: "table" | "view";
  row_count: number | null;
  columns: Column[];
  ddl: string;
  sample_rows: Cell[][];
}

export interface Schema {
  database_id: string;
  dialect: string;
  tables: Table[];
}

export type Cell = string | number | boolean | null;
export type ColumnType = "number" | "text" | "boolean" | "empty";

export interface QueryResult {
  columns: string[];
  column_types: ColumnType[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
  /** Columns whose values were hidden because they look like personal data. */
  masked_columns?: string[];
}

export interface Attempt {
  sql: string;
  error: string;
}

export interface HistoryTurn {
  question: string;
  sql: string;
}

export interface GenerateResponse {
  question: string;
  database_id: string;
  routed_from: string | null;
  answerable: boolean;
  sql: string;
  explanation: string;
  result: QueryResult | null;
  error: string | null;
  attempts: Attempt[];
  history_id: number | null;
  summary: string;
  followups: string[];
  used_memory: number;
}

export interface ExecuteResponse {
  sql: string;
  result: QueryResult | null;
  error: string | null;
  history_id: number | null;
}

export interface HistoryItem {
  id: number;
  database_id: string;
  question: string | null;
  sql: string;
  explanation: string | null;
  row_count: number | null;
  error: string | null;
  source: "ai" | "manual";
  starred: boolean;
  created_at: string;
}

export interface Health {
  status: "ok";
  llm_enabled: boolean;
  provider: "anthropic" | "groq" | "demo" | null;
  model: string;
  max_rows: number;
  version: string;
}

/** One question (or hand-written query) and its answer in the conversation. */
export interface Turn {
  id: string;
  databaseId: string;
  mode: "ai" | "sql";
  question?: string;
  sql: string;
  explanation?: string;
  answerable?: boolean;
  result?: QueryResult | null;
  error?: string | null;
  attempts?: Attempt[];
  historyId?: number | null;
  /** Plain-language answer written from the result rows, and suggested next questions. */
  summary?: string;
  followups?: string[];
  /** How many taught examples and rules were added to the prompt. */
  usedMemory?: number;
  /** Live progress messages while the answer is being worked out. */
  steps?: string[];
  /** The database the SQL runs on, when the answer came from a different database than the selected one. */
  queryDb?: string;
  routedFrom?: string | null;
  /** "thinking": waiting for the AI; "running": re-running edited SQL; "done": finished */
  status: "thinking" | "running" | "done";
}

export type Theme = "light" | "dark";

export interface ProfileColumn {
  name: string;
  type: string;
  nulls: number;
  null_pct: number;
  distinct: number;
  min: Cell;
  max: Cell;
  flags: string[];
}

export interface ProfileTable {
  name: string;
  row_count: number;
  columns: ProfileColumn[];
  completeness: number;
}

export interface Profile {
  database_id: string;
  tables: ProfileTable[];
  completeness: number;
  issues: number;
}

export interface Stats {
  total: number;
  ai: number;
  manual: number;
  failed: number;
  repaired: number;
  avg_seconds: number | null;
  success_rate: number | null;
  daily: { day: string; count: number }[];
}

export type View = "home" | "documents" | "training" | "admin" | "ask" | "dashboard" | "explore" | "usage";

export interface ExplainResponse {
  summary: string;
  steps: string[];
}

export interface AutoWidget {
  title: string;
  sql: string;
  note: string;
  result: QueryResult;
}

export interface AutoDashboard {
  database_id: string;
  source: "ai" | "rules";
  widgets: AutoWidget[];
}

export interface DocumentInfo {
  id: number;
  name: string;
  pages: number;
  chunks: number;
  chars: number;
  created_at: string;
}

export interface DocSource {
  n: number;
  kind: "document" | "database";
  document: string;
  page: number | null;
  text: string;
  score: number;
}

export interface DocAnswer {
  question: string;
  answer: string | null;
  found: boolean;
  sources: DocSource[];
  sql: string | null;
}

export type Role = "viewer" | "analyst" | "admin";

export interface Me {
  auth_enabled: boolean;
  user: { username: string; role: Role } | null;
  restricted_tables: string[];
}

export interface MemoryItem {
  id: number;
  database_id: string;
  kind: "example" | "note";
  question: string | null;
  sql: string | null;
  text: string | null;
  created_by: string;
  created_at: string;
  uses: number;
}

export interface AuditRow {
  id: number;
  ts: string;
  username: string;
  role: string;
  action: string;
  database_id: string | null;
  detail: string | null;
  status: string;
  ip: string | null;
}

export interface UserRow {
  id: number;
  username: string;
  role: Role;
  created_at: string;
}
