/** Wake-word matching that forgives speech recognition.
 *
 * Whisper rarely writes the wake word exactly: "Jarvis" comes back as
 * "Jervis", "Javis", "Jarvis," or "Jar is" — and an exact `includes()` check
 * missed every one of those. A word counts as the wake word when it is one
 * edit away (or a known mishearing), and two adjacent words are also tried
 * joined together.
 */

const VARIANTS: Record<string, string[]> = {
  jarvis: ["jervis", "jarvus", "javis", "jarves", "jarvas", "garvis", "gervais",
           "jervais", "charvis", "chavis", "jarbis", "jaavis", "jarvez", "jarvice"],
};

const FILLER = new Set(["um", "uh", "uhm", "hmm", "hey", "ok", "okay", "so", "and"]);

// Everyday words used as wake words only count at the start of what was said
// ("Computer, lights off"), or "my computer is slow" would wake Jarvis.
const COMMON = new Set(["computer", "assistant", "hey", "okay", "listen"]);

function distance(a: string, b: string): number {
  if (Math.abs(a.length - b.length) > 2) return 3;
  const prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let diag = prev[0];
    prev[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const up = prev[j];
      prev[j] = Math.min(prev[j] + 1, prev[j - 1] + 1, diag + (a[i - 1] === b[j - 1] ? 0 : 1));
      diag = up;
    }
  }
  return prev[b.length];
}

function sounds(heard: string, wake: string): boolean {
  if (heard === wake) return true;
  if (VARIANTS[wake]?.includes(heard)) return true;
  // One slip is fine for real words (5+ letters); short words must be exact,
  // or "hey"/"yo"-style wake words would fire on everything.
  return wake.length >= 5 && heard.length >= 4 && distance(heard, wake) <= 1;
}

export interface WakeMatch {
  word: string;      // the configured wake word that matched
  command: string;   // what was said after it ("open youtube"), may be ""
}

/** Find the first wake word in `text`; return it and the rest of the sentence. */
export function findWake(text: string, wakeWords: string[]): WakeMatch | null {
  const tokens = [...text.matchAll(/[\p{L}']+/gu)].map((m) => ({
    word: m[0].toLowerCase().replace(/'/g, ""), end: (m.index ?? 0) + m[0].length,
  }));
  const wakes = wakeWords.map((w) => w.toLowerCase().trim()).filter(Boolean);
  const firstReal = tokens.findIndex((t) => !FILLER.has(t.word));
  for (let i = 0; i < tokens.length; i++) {
    for (const wake of wakes) {
      if (COMMON.has(wake) && i !== firstReal) continue;
      const parts = wake.split(/\s+/);
      const span = tokens.slice(i, i + parts.length).map((t) => t.word);
      let end = -1;
      if (span.length === parts.length && span.every((w, k) => sounds(w, parts[k]))) {
        end = tokens[i + parts.length - 1].end;
      } else if (parts.length === 1 && i + 1 < tokens.length
                 && sounds(tokens[i].word + tokens[i + 1].word, wake)) {
        end = tokens[i + 1].end;  // "jar is" -> "jaris" ~ "jarvis"
      }
      if (end >= 0) return { word: wake, command: cleanCommand(text.slice(end)) };
    }
  }
  return null;
}

/** "…, um, open YouTube." -> "open YouTube" */
export function cleanCommand(rest: string): string {
  const words = rest.replace(/^[\s,.!?:;-]+/, "").replace(/[\s.!?]+$/, "").split(/\s+/);
  while (words.length && FILLER.has(words[0].toLowerCase().replace(/[^a-z]/g, ""))) words.shift();
  return words.join(" ").replace(/^[\s,.!?:;-]+/, "").trim();
}
