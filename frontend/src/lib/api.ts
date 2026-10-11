// The backend serves the built UI at /app, so the page talks to whichever
// backend served it (a test copy can run on another port); the Vite dev
// server talks to the usual one.
const SERVED = /^https?:$/.test(location.protocol) && location.pathname.startsWith("/app");
export const ORIGIN = SERVED ? location.origin : "http://127.0.0.1:8765";
export const API = `${ORIGIN}/api`;
export const WS_URL = `${ORIGIN.replace(/^http/, "ws")}/api/ws/chat`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export interface Conversation {
  id: string;
  title: string;
  folder: string;
  mode?: "chat" | "code";
  project_id?: string | null;
  updated_at: number;
}

export interface Attachment {
  id: string;
  name: string;
  kind: "file" | "image";
  created_at: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta: { agent?: string; tools?: { name: string; result: string }[] };
  created_at: number;
}

export interface OllamaModel {
  name: string;
  size: number;
  details?: { parameter_size?: string; quantization_level?: string };
}

export const api = {
  status: () => request<{ ok: boolean; ollama_up: boolean; model: string }>("/status"),
  settings: () => request<any>("/settings"),
  updateSettings: (patch: any) =>
    request<any>("/settings", { method: "PUT", body: JSON.stringify({ patch }) }),
  models: () =>
    request<{ models: OllamaModel[]; active: string; error?: string }>("/models"),
  deleteModel: (name: string) =>
    request(`/models/${encodeURIComponent(name)}`, { method: "DELETE" }),
  conversations: (q = "") =>
    request<Conversation[]>(`/conversations${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  newConversation: (mode: "chat" | "code" = "chat") =>
    request<Conversation>("/conversations", { method: "POST", body: JSON.stringify({ mode }) }),
  attachments: (convId: string) =>
    request<Attachment[]>(`/conversations/${convId}/attachments`),
  deleteAttachment: (attId: string) =>
    request(`/attachments/${attId}`, { method: "DELETE" }),
  messages: (id: string) => request<Message[]>(`/conversations/${id}/messages`),
  renameConversation: (id: string, body: { title?: string; folder?: string }) =>
    request(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteConversation: (id: string) =>
    request(`/conversations/${id}`, { method: "DELETE" }),
  truncate: (convId: string, messageId: string) =>
    request(`/conversations/${convId}/truncate`, {
      method: "POST",
      body: JSON.stringify({ message_id: messageId }),
    }),
  memories: () => request<any[]>("/memories"),
  addMemory: (content: string, category = "general") =>
    request("/memories", { method: "POST", body: JSON.stringify({ content, category }) }),
  editMemory: (id: string, content: string) =>
    request(`/memories/${id}`, { method: "PUT", body: JSON.stringify({ content }) }),
  deleteMemory: (id: string) => request(`/memories/${id}`, { method: "DELETE" }),
  tools: () => request<any[]>("/tools"),
  agents: () => request<any[]>("/agents"),
  plugins: () => request<any[]>("/plugins"),
  audit: () => request<any[]>("/audit"),
};

export interface Gap {
  id: string;
  capability: string;
  user_prompt: string;
  goal: string;
  reason: string;
  technical_limitation: string;
  missing_tool: string;
  missing_integration: string;
  missing_permission: string;
  missing_ai_capability: string;
  suggested_fix: string;
  difficulty: string;
  status: string;
  count: number;
  priority: "low" | "medium" | "high" | "critical";
  created_at: number;
  updated_at: number;
}

export interface SystemStats {
  cpu_percent: number;
  memory_percent: number;
  memory_used_gb: number;
  memory_total_gb: number;
  ollama_up: boolean;
  active_model: string;
  loaded_models: { name: string; size_gb: number; gpu_percent: number }[];
  running_tools: string[];
  recent_activity: any[];
}

export const gapsApi = {
  list: () => request<Gap[]>("/gaps"),
  add: (body: Partial<Gap>) =>
    request<Gap>("/gaps", { method: "POST", body: JSON.stringify(body) }),
  patch: (id: string, body: Partial<Gap>) =>
    request(`/gaps/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  remove: (id: string) => request(`/gaps/${id}`, { method: "DELETE" }),
  reports: () => request<{ id: string; created: number }[]>("/gaps/reports"),
  report: (id: string) => request<{ id: string; markdown: string }>(`/gaps/reports/${id}`),
  generateReport: () =>
    request<{ id: string; markdown: string }>("/gaps/report", { method: "POST" }),
};

export const statsApi = {
  stats: () => request<SystemStats>("/stats"),
  context: () => request<any>("/context"),
  ttsEngines: () => request<any[]>("/tts/engines"),
};

export async function serverTts(text: string): Promise<Blob | null> {
  const res = await fetch(`${API}/tts/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  const type = res.headers.get("content-type") ?? "";
  if (type.includes("audio")) return res.blob();
  return null;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  template: string;
}

export const skillsApi = {
  list: () => request<Skill[]>("/skills"),
  create: (body: { name: string; template: string; description?: string }) =>
    request<Skill>("/skills", { method: "POST", body: JSON.stringify(body) }),
  update: (id: string, body: Partial<Skill>) =>
    request(`/skills/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  remove: (id: string) => request(`/skills/${id}`, { method: "DELETE" }),
  import: (skills: any) =>
    request<{ added: string[]; skipped: string[] }>("/skills/import", {
      method: "POST", body: JSON.stringify({ skills }),
    }),
};

/** Expand a "/skillname rest of text" message using saved skills. Returns the
 *  expanded prompt, or the original text if it isn't a known skill command. */
export function expandSkill(text: string, skills: Skill[]): string {
  const m = text.match(/^\/([a-z0-9-]+)\s*([\s\S]*)$/i);
  if (!m) return text;
  const skill = skills.find((s) => s.name === m[1].toLowerCase());
  if (!skill) return text;
  const input = m[2].trim();
  return skill.template.includes("{input}")
    ? skill.template.replace(/\{input\}/g, input)
    : `${skill.template}\n\n${input}`.trim();
}

export async function pullModel(
  name: string,
  onProgress: (e: any) => void
): Promise<void> {
  const res = await fetch(`${API}/models/pull`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim()) onProgress(JSON.parse(line));
    }
  }
}
