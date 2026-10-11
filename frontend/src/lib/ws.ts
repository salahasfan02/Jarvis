import { WS_URL } from "./api";

export type ChatEvent =
  | { type: "conversation"; conversation_id: string }
  | { type: "agent"; agent: { id: string; name: string } }
  | { type: "memory"; recalled: { id: string; content: string }[] }
  | { type: "token"; content: string }
  | { type: "reset_text"; content: string }
  | { type: "ui_request"; id: string; kind: string }
  | { type: "announce"; title: string; text: string; speak?: boolean }
  | { type: "tool_start"; name: string; arguments: any }
  | { type: "tool_result"; name: string; result: string; denied?: boolean }
  | { type: "confirm_request"; id: string; tool: string; arguments: any; risk: string; always_ask?: boolean }
  | { type: "plan"; steps: string[] }
  | { type: "step"; index: number; total: number; title: string; status: "running" | "done" }
  | { type: "done"; content: string; message_id: string }
  | { type: "title"; title: string }
  | { type: "stopped" }
  | { type: "error"; message: string };

/** Auto-reconnecting chat socket. */
export class ChatSocket {
  private ws: WebSocket | null = null;
  private queue: string[] = [];
  onEvent: (e: ChatEvent) => void = () => {};
  onStatus: (connected: boolean) => void = () => {};

  connect() {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;
    this.ws = new WebSocket(WS_URL);
    this.ws.onopen = () => {
      // Tell the backend this is a Jarvis window, so tools can ask it for
      // things only it can do (camera photos).
      this.ws!.send(JSON.stringify({ type: "hello", ui: true }));
      this.onStatus(true);
      for (const m of this.queue.splice(0)) this.ws!.send(m);
    };
    this.ws.onmessage = (ev) => this.onEvent(JSON.parse(ev.data));
    this.ws.onclose = () => {
      this.onStatus(false);
      setTimeout(() => this.connect(), 1500);
    };
    this.ws.onerror = () => this.ws?.close();
  }

  private send(obj: unknown) {
    const raw = JSON.stringify(obj);
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(raw);
    else {
      this.queue.push(raw);
      this.connect();
    }
  }

  chat(conversationId: string | null, content: string, mode: "chat" | "code" = "chat") {
    this.send({ type: "chat", conversation_id: conversationId, content, mode });
  }

  confirm(id: string, approved: boolean, tool?: string, remember?: boolean) {
    this.send({ type: "confirm", id, approved, tool, remember });
  }

  stop() {
    this.send({ type: "stop" });
  }

  uiResponse(id: string, data: unknown) {
    this.send({ type: "ui_response", id, data });
  }
}
