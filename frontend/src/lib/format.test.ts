import { describe, expect, it } from "vitest";
import {
  describeAction, greeting, inkFor, linkCitations, parseListing, shortWhen, splitSources,
  stepLabel, timeAgo,
} from "./format";

describe("sources under an answer", () => {
  it("splits linked sources off the answer", () => {
    const { body, sources } = splitSources(
      "MCP links apps to tools [1].\n\nSources:\n[1] [What is MCP](https://mcp.io/intro)\n[2] [Guide](https://www.g.dev/mcp)");
    expect(body).toBe("MCP links apps to tools [1].");
    expect(sources).toEqual([
      { n: 1, title: "What is MCP", url: "https://mcp.io/intro", site: "mcp.io" },
      { n: 2, title: "Guide", url: "https://www.g.dev/mcp", site: "g.dev" },
    ]);
  });

  it("reads the other ways models write source lists", () => {
    const { sources } = splitSources(
      "Text.\n\n**Sources:**\n1. Model Context Protocol — https://modelcontextprotocol.io/\n- Wikipedia: https://en.wikipedia.org/wiki/MCP.");
    expect(sources.map((s) => [s.n, s.title, s.url])).toEqual([
      [1, "Model Context Protocol", "https://modelcontextprotocol.io/"],
      [2, "Wikipedia", "https://en.wikipedia.org/wiki/MCP"],
    ]);
  });

  it("leaves a 'Sources' heading without links alone", () => {
    const text = "Plan:\n\n## Sources\nAsk your manager and the team wiki.";
    expect(splitSources(text)).toEqual({ body: text, sources: [] });
  });

  it("turns [n] into citation links, but not real markdown links", () => {
    const sources = [{ n: 1, title: "A", url: "https://a.com", site: "a.com" },
                     { n: 2, title: "B \"x\"", url: "https://b.com", site: "b.com" }];
    expect(linkCitations("Fact [1][2]. See [docs](https://d.com). Also [1, 2].", sources)).toBe(
      'Fact [1](https://a.com "cite:A")[2](https://b.com "cite:B \'x\'"). See [docs](https://d.com). ' +
      'Also [1](https://a.com "cite:A")[2](https://b.com "cite:B \'x\'").');
    expect(linkCitations("Array index [3] stays", sources)).toBe("Array index [3] stays");
  });
});

describe("folder listings", () => {
  it("parses a listing with its folder and dates", () => {
    const l = parseListing("/Users/me/Desktop (2 items, newest first):\n" +
                           "2026-10-11 15:03  Screenshot.png\n2026-09-14 21:16  [dir] Spain");
    expect(l).toEqual({
      path: "/Users/me/Desktop", note: "2 items, newest first",
      rows: [{ when: "2026-10-11 15:03", name: "Screenshot.png", dir: false },
             { when: "2026-09-14 21:16", name: "Spain", dir: true }],
    });
  });

  it("parses search results that are bare paths", () => {
    const l = parseListing("2026-10-09 10:00  /Users/me/Desktop/CV.pdf");
    expect(l?.path).toBe("");
    expect(l?.rows[0]).toEqual({ when: "2026-10-09 10:00", name: "/Users/me/Desktop/CV.pdf", dir: false });
  });

  it("shows dates the way people say them", () => {
    const now = new Date(2026, 9, 11, 16, 0);
    expect(shortWhen("2026-10-11 15:03", now)).toBe("Today 15:03");
    expect(shortWhen("2026-10-10 09:00", now)).toBe("Yesterday");
    expect(shortWhen("2026-09-14 21:16", now)).toBe("14 Sept");
    expect(shortWhen("2024-07-20 23:11", now)).toBe("20 Jul 2024");
  });
});

describe("words for what Jarvis did", () => {
  it("names tool steps while running and when done", () => {
    expect(stepLabel("research", false)).toBe("Researching the web");
    expect(stepLabel("send_file", true)).toBe("Sent the file");
    expect(stepLabel("some_new_tool", true)).toBe("Some new tool");
  });

  it("describes an email in the permission prompt", () => {
    const a = describeAction("send_email", { to: "sam@x.com", subject: "Hi", body: "Hello", attachments: ["/Users/me/CV.pdf"] });
    expect(a.title).toBe("Send an email");
    expect(a.lines).toEqual([["To", "sam@x.com"], ["Subject", "Hi"], ["Attach", "CV.pdf"], ["Message", "Hello"]]);
  });

  it("falls back to readable key/value lines for other tools", () => {
    const a = describeAction("custom_tool", { file_path: "/x", options: { a: 1 }, empty: "" });
    expect(a.title).toBe("Custom tool");
    expect(a.lines).toEqual([["File path", "/x"], ["Options", '{"a":1}']]);
  });

  it("asks before a call with the person and the number it found", () => {
    const a = describeAction("facetime_call", {
      contact: "Salah's business number", kind: "video", who: "Salah Asfan",
      number: "+44 20 7946 0222 (work)", handle: "+44 20 7946 0222" });
    expect(a.title).toBe("FaceTime video call");
    expect(a.lines).toEqual([["To", "Salah Asfan"], ["Number", "+44 20 7946 0222 (work)"]]);
    expect(describeAction("facetime_call", { contact: "mum", kind: "audio" }).title).toBe("FaceTime audio call");
    expect(stepLabel("facetime_call", true)).toBe("Started the call");
  });

  it("asks before taking a photo, and says when it'll be sent", () => {
    expect(describeAction("take_photo", {}).lines).toEqual([["Timer", "3 seconds"]]);
    expect(describeAction("take_photo", { countdown: 0, send_to_phone: true }).lines)
      .toEqual([["Timer", "Right away"], ["Then", "Send it to your phone"]]);
    expect(describeAction("send_to_phone", { what: "photo" }).lines)
      .toEqual([["What", "The photo you just took"], ["As", "A photo"]]);
  });
});

describe("small helpers", () => {
  it("relative times", () => {
    const now = Date.UTC(2026, 9, 11, 12) ;
    expect(timeAgo(now / 1000 - 20, now)).toBe("just now");
    expect(timeAgo(now / 1000 - 300, now)).toBe("5m");
    expect(timeAgo(now / 1000 - 7200, now)).toBe("2h");
    expect(timeAgo(now / 1000 - 90000, now)).toBe("Yesterday");
  });

  it("greets by time of day", () => {
    expect(greeting("Salah", new Date(2026, 9, 11, 9))).toBe("Good morning, Salah");
    expect(greeting("", new Date(2026, 9, 11, 15))).toBe("Good afternoon");
    expect(greeting("Salah", new Date(2026, 9, 11, 21))).toBe("Good evening, Salah");
  });

  it("picks readable text for an accent colour", () => {
    expect(inkFor("#00ff2a")).toBe("#06120a");     // bright green -> dark text
    expect(inkFor("#2f6fec")).toBe("#ffffff");     // deep blue -> white
    expect(inkFor("nonsense")).toBe("#ffffff");
  });
});
