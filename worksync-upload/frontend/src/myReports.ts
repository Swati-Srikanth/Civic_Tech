// Reports a guest chose to remember on this device. This is a per-viewer convenience (like a receipt kept in
// a pocket): nothing here is needed for the app to work, and the person can forget them at any time.
// The tracking code is a secret that lets someone follow (and respond to) that one report, so it stays on this
// device only. It is never sent anywhere except back to the WorkSync server with that report's reference.

export interface SavedReport {
  reference: string;
  code: string;
  savedAt: string;
}

const KEY = "ws.myReports";
const SEEN = "ws.seenEvents";

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage can be unavailable; the app still works without it */
  }
}

export function savedReports(): SavedReport[] {
  return read<SavedReport[]>(KEY, []);
}

export function saveReport(reference: string, code: string): void {
  const rest = savedReports().filter((r) => r.reference !== reference);
  write(KEY, [{ reference, code, savedAt: new Date().toISOString() }, ...rest].slice(0, 50));
}

export function forgetReport(reference: string): void {
  write(KEY, savedReports().filter((r) => r.reference !== reference));
  const seen = read<Record<string, number>>(SEEN, {});
  delete seen[reference];
  write(SEEN, seen);
}

export function forgetAllReports(): void {
  write(KEY, []);
  write(SEEN, {});
}

/** Highest timeline entry the person has already looked at, per report. */
export function seenEvent(reference: string): number {
  return read<Record<string, number>>(SEEN, {})[reference] ?? 0;
}

export function markSeen(reference: string, lastEventId: number): void {
  const seen = read<Record<string, number>>(SEEN, {});
  if ((seen[reference] ?? 0) < lastEventId) {
    seen[reference] = lastEventId;
    write(SEEN, seen);
  }
}

/** How many timeline entries are newer than what was last seen. */
export function unreadCount(reference: string, timeline: { id: number }[]): number {
  const seen = seenEvent(reference);
  return timeline.filter((e) => e.id > seen).length;
}

/**
 * After checking every saved report, which ones does the server say do not exist (404)? Those are forgotten so they are
 * never asked about again: a stale entry must not keep counting as a failed code guess and lock the person out.
 * Anything else (a 429 throttle, a network error) is kept and retried later.
 */
export function referencesToForget(saved: { reference: string }[], outcomes: { status: "fulfilled" | "rejected"; reason?: { status?: number } }[]): string[] {
  const out: string[] = [];
  outcomes.forEach((o, i) => {
    if (o.status === "rejected" && o.reason?.status === 404 && saved[i]) out.push(saved[i].reference);
  });
  return out;
}
