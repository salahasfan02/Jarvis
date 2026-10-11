/** Turning what Jarvis says and does into something pleasant to read:
 *  sources under an answer, [1] citations, folder listings, tool steps,
 *  and plain-words permission prompts. Pure functions (see format.test.ts). */

export interface Source {
  n: number;
  title: string;
  url: string;
  site: string;
}

export function siteOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// "Sources:" / "**Sources**" / "## References" — the list Jarvis ends a
// researched answer with.
const SOURCES_HEAD = /\n[ \t]*(?:#{1,6}[ \t]*|\*\*)?(?:Sources|References)(?:\*\*)?[ \t]*:?(?:\*\*)?[ \t]*\n/i;

/** Split an answer into its body and the sources listed at the end. Lines
 *  look like "[1] [Title](url)", "[1] Title — url", "1. [Title](url) — site"
 *  or "- Title: url". Anything else stays in the body. */
export function splitSources(content: string): { body: string; sources: Source[] } {
  const m = SOURCES_HEAD.exec(content);
  if (!m) return { body: content, sources: [] };
  const tail = content.slice(m.index + m[0].length);
  const sources: Source[] = [];
  for (const raw of tail.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const num = line.match(/^(?:\[(\d+)\]|(\d+)[.)])\s*/);
    const rest = num ? line.slice(num[0].length) : line.replace(/^[-*•]\s*/, "");
    const n = num ? Number(num[1] ?? num[2]) : sources.length + 1;
    const link = rest.match(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/);
    const bare = rest.match(/https?:\/\/[^\s)>\]]+/);
    if (!link && !bare) return { body: content, sources: [] };   // not a source list
    const url = link ? link[2] : bare![0].replace(/[.,;]+$/, "");
    let title = link ? link[1] : rest.slice(0, rest.indexOf(bare![0]));
    title = title.replace(/\s*[—–:-]\s*$/, "").replace(/^\s*[—–-]\s*/, "").trim();
    sources.push({ n, title: title || siteOf(url), url, site: siteOf(url) });
  }
  if (!sources.length) return { body: content, sources: [] };
  return { body: content.slice(0, m.index).trimEnd(), sources };
}

/** "[1]" / "[1][2]" / "[1, 3]" in the body -> markdown links the chat renders
 *  as citation chips (their title starts with "cite:"). Real markdown links
 *  "[text](url)" are left alone. */
export function linkCitations(body: string, sources: Source[]): string {
  if (!sources.length) return body;
  const byN = new Map(sources.map((s) => [s.n, s]));
  return body.replace(/\[(\d+(?:\s*[,–-]\s*\d+)*)\](?!\()/g, (whole, inner: string) => {
    const nums = inner.split(/\s*[,–-]\s*/).map(Number);
    if (!nums.every((n) => byN.has(n))) return whole;
    return nums.map((n) => `[${n}](${byN.get(n)!.url} "cite:${byN.get(n)!.title.replace(/"/g, "'")}")`).join("");
  });
}

export interface Listing {
  path: string;
  note: string;          // "240 items, newest first"
  rows: { when: string; name: string; dir: boolean }[];
}

/** A folder listing from list_directory / search_files:
 *    /Users/me/Desktop (240 items, newest first):
 *    2026-10-11 15:03  Screenshot.png
 *    2026-09-14 21:16  [dir] Spain                                         */
export function parseListing(text: string): Listing | null {
  const lines = text.split("\n").map((l) => l.replace(/\s+$/, "")).filter(Boolean);
  if (!lines.length) return null;
  let path = "", note = "";
  const head = lines[0].match(/^(\/.*?|~.*?)(?:\s+\((.*)\))?:?$/);
  if (head && !/^\d{4}-\d\d-\d\d/.test(lines[0])) {
    path = head[1];
    note = head[2] ?? "";
    lines.shift();
  }
  const rows = lines.map((l) => {
    const m = l.match(/^(\d{4}-\d\d-\d\d(?: \d\d:\d\d)?)\s+(.*)$/);
    let when = m ? m[1] : "";
    let name = (m ? m[2] : l).trim();
    const dir = /^\[dir\]\s*/.test(name);
    name = name.replace(/^\[dir\]\s*/, "");
    if (!m && name.startsWith("/")) {   // search results: full paths
      when = "";
    }
    return { when, name, dir };
  });
  return rows.length ? { path, note, rows } : null;
}

/** "2026-10-11 15:03" -> "Today 15:03" / "Yesterday" / "11 Oct" / "11 Oct 2024". */
export function shortWhen(stamp: string, now = new Date()): string {
  const m = stamp.match(/^(\d{4})-(\d\d)-(\d\d)(?: (\d\d:\d\d))?$/);
  if (!m) return stamp;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((today.getTime() - d.getTime()) / 86400000);
  if (days === 0) return m[4] ? `Today ${m[4]}` : "Today";
  if (days === 1) return "Yesterday";
  const sameYear = d.getFullYear() === now.getFullYear();
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
}

/** Seconds since epoch -> "just now", "5m", "3h", "Yesterday", "12 Oct". */
export function timeAgo(ts: number, now = Date.now()): string {
  const s = Math.max(0, now / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 2 * 86400) return "Yesterday";
  const d = new Date(ts * 1000);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function greeting(name: string, d = new Date()): string {
  const h = d.getHours();
  const part = h < 5 ? "Good evening" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  return name ? `${part}, ${name}` : part;
}

// ---- tool steps -------------------------------------------------------------------

/** What each tool is called while it runs, and once it's done. */
const STEP: Record<string, [string, string]> = {
  research: ["Researching the web", "Researched the web"],
  research_report: ["Researching and writing", "Wrote a researched document"],
  web_search: ["Searching the web", "Searched the web"],
  web_fetch: ["Reading a page", "Read a page"],
  weather: ["Checking the weather", "Checked the weather"],
  list_directory: ["Looking in the folder", "Looked in the folder"],
  search_files: ["Searching your files", "Searched your files"],
  search_documents: ["Searching your documents", "Searched your documents"],
  open_file: ["Opening the file", "Opened the file"],
  read_document: ["Reading the document", "Read the document"],
  read_file: ["Reading the file", "Read the file"],
  write_file: ["Writing the file", "Wrote the file"],
  send_file: ["Sending the file", "Sent the file"],
  move_file: ["Moving the file", "Moved the file"],
  trash_file: ["Moving to the Bin", "Moved to the Bin"],
  create_folder: ["Creating the folder", "Created the folder"],
  create_word_document: ["Writing the document", "Created a Word document"],
  create_spreadsheet: ["Building the spreadsheet", "Created a spreadsheet"],
  create_presentation: ["Building the slides", "Created a presentation"],
  compare_documents: ["Comparing documents", "Compared the documents"],
  send_email: ["Sending the email", "Sent the email"],
  draft_email: ["Drafting the email", "Drafted the email"],
  send_reply: ["Sending the reply", "Sent the reply"],
  draft_reply: ["Drafting the reply", "Drafted the reply"],
  read_emails: ["Checking your email", "Checked your email"],
  read_email: ["Reading the email", "Read the email"],
  search_emails: ["Searching your email", "Searched your email"],
  draft_imessage: ["Drafting the message", "Drafted the message"],
  read_messages: ["Reading your messages", "Read your messages"],
  read_conversation_with: ["Reading the conversation", "Read the conversation"],
  calendar_events: ["Checking your calendar", "Checked your calendar"],
  calendar_today: ["Checking today's calendar", "Checked your calendar"],
  calendar_create_event: ["Adding the event", "Added the event"],
  create_reminder: ["Setting the reminder", "Set a reminder"],
  create_note: ["Writing the note", "Created a note"],
  append_note: ["Updating the note", "Updated the note"],
  read_note: ["Reading the note", "Read the note"],
  search_notes: ["Searching your notes", "Searched your notes"],
  screen_read: ["Reading your screen", "Read your screen"],
  screen_look: ["Looking at your screen", "Looked at your screen"],
  camera_look: ["Looking through the camera", "Looked through the camera"],
  watch_screen: ["Watching your screen", "Watching your screen"],
  remember: ["Remembering that", "Remembered that"],
  remember_person: ["Saving the contact", "Saved the contact"],
  find_person: ["Looking up the person", "Looked up the person"],
  project_remember: ["Updating project notes", "Updated project notes"],
  browser_open: ["Opening the page", "Opened the page"],
  open_url: ["Opening the link", "Opened the link"],
  browser_tabs: ["Checking your tabs", "Checked your tabs"],
  browser_close_tab: ["Closing the tab", "Closed the tab"],
  browser_click: ["Clicking on the page", "Clicked on the page"],
  browser_read_page: ["Reading the page", "Read the page"],
  browser_js: ["Running on the page", "Ran on the page"],
  youtube_play: ["Finding it on YouTube", "Playing on YouTube"],
  youtube_control: ["Controlling YouTube", "Controlled YouTube"],
  music_play: ["Starting the music", "Playing music"],
  music_control: ["Controlling Music", "Controlled Music"],
  open_app: ["Opening the app", "Opened the app"],
  quit_app: ["Quitting the app", "Quit the app"],
  ui_press: ["Pressing the button", "Pressed the button"],
  ui_type: ["Typing", "Typed it in"],
  ui_elements: ["Reading the window", "Read the window"],
  press_keys: ["Pressing keys", "Pressed the keys"],
  click_on_screen: ["Clicking on screen", "Clicked on screen"],
  scroll: ["Scrolling", "Scrolled"],
  drag: ["Dragging", "Dragged"],
  fill_form: ["Filling in the form", "Filled in the form"],
  set_timer: ["Setting the timer", "Set a timer"],
  timers: ["Checking timers", "Checked timers"],
  set_volume: ["Changing the volume", "Changed the volume"],
  create_routine: ["Setting up the routine", "Set up a routine"],
  daily_briefing: ["Gathering your briefing", "Gathered your briefing"],
  run_command: ["Running a command", "Ran a command"],
  run_python: ["Running Python", "Ran Python"],
  run_applescript: ["Running AppleScript", "Ran AppleScript"],
  run_shortcut: ["Running the shortcut", "Ran the shortcut"],
  undo_last: ["Undoing it", "Undid it"],
  calculator: ["Calculating", "Calculated"],
  current_datetime: ["Checking the time", "Checked the time"],
};

export function stepLabel(tool: string, done: boolean): string {
  const s = STEP[tool];
  if (s) return done ? s[1] : s[0];
  const words = tool.replace(/_/g, " ");
  return words[0].toUpperCase() + words.slice(1);
}

// ---- permission prompts --------------------------------------------------------

export interface ActionSummary {
  title: string;                   // "Send an email"
  lines: [string, string][];       // shown as a small table
}

const s = (v: unknown) => (Array.isArray(v) ? v.join(", ") : v == null ? "" : String(v));
const base = (p: unknown) => s(p).split("/").filter(Boolean).pop() ?? s(p);

/** What a tool call will do, in words — instead of raw JSON in the prompt. */
export function describeAction(tool: string, args: Record<string, any>): ActionSummary {
  const a = args ?? {};
  const pick = (...pairs: [string, unknown][]) =>
    pairs.filter(([, v]) => s(v).trim()).map(([k, v]) => [k, s(v)] as [string, string]);
  switch (tool) {
    case "send_email":
    case "draft_email":
      return { title: tool === "send_email" ? "Send an email" : "Draft an email",
               lines: pick(["To", a.to], ["Cc", a.cc], ["Subject", a.subject], ["Attach", (a.attachments ?? []).map(base)], ["Message", a.body]) };
    case "send_reply":
    case "draft_reply":
      return { title: tool === "send_reply" ? "Send a reply" : "Draft a reply", lines: pick(["Message", a.body]) };
    case "send_file":
      return { title: "Send a file to your phone", lines: pick(["File", base(a.path)], ["From", a.path], ["Note", a.caption]) };
    case "trash_file":
      return { title: "Move to the Bin", lines: pick(["File", base(a.path)], ["From", a.path]) };
    case "move_file":
      return { title: "Move a file", lines: pick(["File", a.source], ["To", a.destination]) };
    case "write_file":
      return { title: "Write a file", lines: pick(["File", a.path], ["Content", s(a.content).slice(0, 400)]) };
    case "run_command":
      return { title: "Run a Terminal command", lines: pick(["Command", a.command]) };
    case "run_python":
      return { title: "Run Python code", lines: pick(["Code", a.code]) };
    case "run_applescript":
      return { title: "Run AppleScript", lines: pick(["Script", a.script]) };
    case "read_emails":
    case "search_emails":
    case "read_email":
      return { title: "Read your email",
               lines: pick(["Search", a.query], ["Mailbox", a.mailbox], ["How many", a.count],
                           ["Only unread", a.unread_only ? "yes" : ""], ["Past days", a.days]) };
    case "calendar_create_event":
      return { title: "Add a calendar event", lines: pick(["Event", a.title], ["Starts", a.start], ["Ends", a.end], ["Where", a.location]) };
    case "create_reminder":
      return { title: "Create a reminder", lines: pick(["Reminder", a.title], ["Due", a.due]) };
    case "create_note":
    case "append_note":
      return { title: tool === "create_note" ? "Create a note" : "Add to a note", lines: pick(["Note", a.title], ["Text", s(a.body ?? a.text).slice(0, 300)]) };
    case "draft_imessage":
      return { title: "Draft a message", lines: pick(["To", a.recipient], ["Message", a.body]) };
    case "ui_press":
    case "browser_click":
    case "click_on_screen":
      return { title: "Click on your screen", lines: pick(["App", a.app], ["Target", a.target]) };
    case "ui_type":
      return { title: "Type on your screen", lines: pick(["App", a.app], ["Into", a.field], ["Text", a.text]) };
    case "press_keys":
      return { title: "Press keys", lines: pick(["Keys", a.keys], ["App", a.app]) };
    case "screen_read":
    case "screen_look":
      return { title: "Look at your screen", lines: pick(["Question", a.question]) };
    case "read_messages":
    case "read_conversation_with":
      return { title: "Read your messages", lines: pick(["With", a.person ?? a.name ?? a.contact]) };
    case "camera_look":
      return { title: "Look through the camera", lines: pick(["Question", a.question]) };
    case "quit_app":
      return { title: "Quit an app", lines: pick(["App", a.name]) };
  }
  const label = tool.replace(/_/g, " ");
  return {
    title: label[0].toUpperCase() + label.slice(1),
    lines: Object.entries(a).filter(([, v]) => s(v).trim()).slice(0, 6)
      .map(([k, v]) => [k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()),
                        typeof v === "object" && !Array.isArray(v) ? JSON.stringify(v) : s(v)]),
  };
}

/** Text to show on an accent colour: dark on bright accents, white on deep ones. */
export function inkFor(hex: string): string {
  const m = hex.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  if (!m) return "#ffffff";
  const [r, g, b] = m.slice(1).map((x) => parseInt(x, 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return lum > 0.36 ? "#06120a" : "#ffffff";
}
