import { beforeEach, describe, expect, it, vi } from "vitest";

function installStorage() {
  const data = new Map<string, string>();
  vi.stubGlobal("window", {
    localStorage: {
      getItem: (k: string) => (data.has(k) ? data.get(k)! : null),
      setItem: (k: string, v: string) => void data.set(k, v),
      removeItem: (k: string) => void data.delete(k),
    },
  });
  return data;
}

describe("reports remembered on this device", () => {
  beforeEach(() => { vi.resetModules(); installStorage(); });

  it("remembers, replaces and forgets reports", async () => {
    const m = await import("./myReports");
    m.saveReport("CMP-2026-0001", "AAAAAAAAAA");
    m.saveReport("CMP-2026-0002", "BBBBBBBBBB");
    m.saveReport("CMP-2026-0001", "CCCCCCCCCC");                    // the same reference replaces, never duplicates
    expect(m.savedReports().map((r) => r.reference)).toEqual(["CMP-2026-0001", "CMP-2026-0002"]);
    expect(m.savedReports()[0].code).toBe("CCCCCCCCCC");
    m.forgetReport("CMP-2026-0001");
    expect(m.savedReports().map((r) => r.reference)).toEqual(["CMP-2026-0002"]);
    m.forgetAllReports();
    expect(m.savedReports()).toEqual([]);
  });

  it("counts only updates newer than the ones already seen", async () => {
    const m = await import("./myReports");
    const timeline = [{ id: 3 }, { id: 5 }, { id: 8 }];
    expect(m.unreadCount("CMP-2026-0001", timeline)).toBe(3);
    m.markSeen("CMP-2026-0001", 5);
    expect(m.unreadCount("CMP-2026-0001", timeline)).toBe(1);
    m.markSeen("CMP-2026-0001", 2);                                 // never moves backwards
    expect(m.seenEvent("CMP-2026-0001")).toBe(5);
    m.markSeen("CMP-2026-0001", 8);
    expect(m.unreadCount("CMP-2026-0001", timeline)).toBe(0);
  });

  it("forgets only reports the server says do not exist, never ones that were merely throttled or unreachable", async () => {
    const m = await import("./myReports");
    const saved = [{ reference: "A" }, { reference: "B" }, { reference: "C" }, { reference: "D" }];
    const outcomes = [
      { status: "fulfilled" as const },
      { status: "rejected" as const, reason: { status: 404 } },
      { status: "rejected" as const, reason: { status: 429 } },
      { status: "rejected" as const, reason: { status: 0 } },
    ];
    expect(m.referencesToForget(saved, outcomes)).toEqual(["B"]);
  });

  it("keeps working when storage is unavailable", async () => {
    vi.stubGlobal("window", { localStorage: { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); }, removeItem: () => { throw new Error("blocked"); } } });
    vi.resetModules();
    const m = await import("./myReports");
    expect(m.savedReports()).toEqual([]);
    expect(() => m.saveReport("CMP-2026-0001", "AAAAAAAAAA")).not.toThrow();
    expect(m.unreadCount("CMP-2026-0001", [{ id: 1 }])).toBe(1);
  });
});
