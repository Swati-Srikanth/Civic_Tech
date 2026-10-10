import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiRequestError, setAuthToken, setResidentExpiredHandler, setResidentToken, setUnauthorizedHandler, _pendingKeyCount } from "./api";

type Call = { url: string; init: RequestInit };

function mockFetch(responses: Array<Response | Error>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    const next = responses.shift();
    if (!next) throw new Error("no more mocked responses");
    if (next instanceof Error) throw next;
    return next;
  }));
  return calls;
}

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
async function failure(p: Promise<unknown>): Promise<ApiRequestError> {
  try {
    await p;
  } catch (e) {
    return e as ApiRequestError;
  }
  throw new Error("expected the request to be rejected");
}
const header = (c: Call, name: string) => (c.init.headers as Record<string, string>)[name];

beforeEach(() => setAuthToken("tok-abcdefgh-1234"));
afterEach(() => { vi.unstubAllGlobals(); setAuthToken(null); setResidentToken(null); setUnauthorizedHandler(null); setResidentExpiredHandler(null); });

describe("api client", () => {
  it("sends the session token on staff calls but never on public ones", async () => {
    const calls = mockFetch([json(200, { items: [] }), json(200, { road: {}, projects: [] })]);
    await api.listProjects("road-market");
    await api.publicRoad("road-market");
    expect(header(calls[0], "Authorization")).toBe("Bearer tok-abcdefgh-1234");
    expect(header(calls[0], "X-Demo-User")).toBeUndefined();
    expect(calls[0].url).toContain("/api/v1/projects?road_id=road-market");
    expect(header(calls[1], "Authorization")).toBeUndefined();
  });

  it("sends public complaint calls without credentials, and submitting carries an Idempotency-Key", async () => {
    const calls = mockFetch([
      json(201, { id: "CMP-2026-0001", tracking_code: "ABCDEF0123", message: "ok", recorded_at: "t" }),
      json(200, { reference: "CMP-2026-0001", status: "NEW" }),
    ]);
    await api.submitComplaint({ category: "SAFETY_HAZARD", description: "Open trench with no barrier" });
    await api.trackComplaint("CMP-2026-0001", "ABCDEF0123");
    expect(header(calls[0], "Authorization")).toBeUndefined();
    expect(header(calls[0], "Idempotency-Key")).toMatch(/.{8,}/);
    expect(header(calls[1], "Authorization")).toBeUndefined();
    expect(header(calls[1], "Idempotency-Key")).toBeUndefined();
  });

  it("signs in without a token or idempotency key, and tells the app when a session is refused", async () => {
    const calls = mockFetch([
      json(200, { token: "t", token_type: "Bearer", expires_at: "x", user: { id: "u-water" } }),
      json(401, { error: { code: "UNAUTHENTICATED", message: "Please sign in to continue.", failures: [] } }),
    ]);
    const expired = vi.fn();
    setUnauthorizedHandler(expired);
    await api.login("water.dept", "pw");
    expect(header(calls[0], "Authorization")).toBeUndefined();
    expect(header(calls[0], "Idempotency-Key")).toBeUndefined();
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ username: "water.dept", password: "pw" });
    await expect(api.listProjects()).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledTimes(1);
  });

  it("keeps resident (Google) and staff credentials strictly apart", async () => {
    setResidentToken("resident-token-xyz");
    const calls = mockFetch([
      json(201, { id: "CMP-2026-0001", tracking_code: "ABCDEF0123" }),
      json(200, { items: [] }),
      json(200, { items: [] }),
    ]);
    await api.submitComplaint({ category: "ELECTRICAL", description: "Street light is out near the stop" });   // public, recognises a resident
    await api.myComplaints();                                                                               // resident only
    await api.listComplaints();                                                                             // staff only
    expect(header(calls[0], "Authorization")).toBe("Bearer resident-token-xyz");
    expect(header(calls[1], "Authorization")).toBe("Bearer resident-token-xyz");
    expect(header(calls[2], "Authorization")).toBe("Bearer tok-abcdefgh-1234");
    expect(header(calls[2], "Authorization")).not.toContain("resident");
  });

  it("a guest report call sends no credentials at all, and a refused resident session only ends the resident session", async () => {
    const calls = mockFetch([
      json(200, { reference: "CMP-2026-0001" }),
      json(401, { error: { code: "UNAUTHENTICATED", message: "Sign in with Google to see your reports.", failures: [] } }),
    ]);
    setAuthToken(null);
    await api.trackComplaint("CMP-2026-0001", "ABCDEF0123");
    expect(header(calls[0], "Authorization")).toBeUndefined();
    setAuthToken("staff-token-keepme"); setResidentToken("resident-token-xyz");
    const staffExpired = vi.fn(); const residentExpired = vi.fn();
    setUnauthorizedHandler(staffExpired); setResidentExpiredHandler(residentExpired);
    await expect(api.myComplaints()).rejects.toMatchObject({ status: 401 });
    expect(residentExpired).toHaveBeenCalledTimes(1);
    expect(staffExpired).not.toHaveBeenCalled();
  });

  it("sends the promised time with a status update, and the coordinator's assignment", async () => {
    const calls = mockFetch([json(200, { id: "CMP-1", version: 2 }), json(200, { id: "CMP-1", version: 3 })]);
    await api.setComplaintStatus("CMP-1", 1, "IN_PROGRESS", { resolve_in_days: 5, note: "Crew booked" });
    await api.assignComplaint("CMP-1", 2, "power");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ expected_version: 1, status: "IN_PROGRESS", resolve_in_days: 5, note: "Crew booked" });
    expect(JSON.parse(calls[1].init.body as string)).toEqual({ expected_version: 2, department_id: "power" });
  });

  it("creating an account or signing in as a resident sends no credentials and no idempotency key", async () => {
    const calls = mockFetch([
      json(201, { token: "t", expires_at: "x", resident: { id: "r-1", provider: "local" } }),
      json(200, { token: "t2", expires_at: "x", resident: { id: "r-1", provider: "local" } }),
    ]);
    await api.register("Ana", "ana@example.com", "river-stone-77");
    await api.residentLogin("ana@example.com", "river-stone-77");
    for (const c of calls) {
      expect(header(c, "Authorization")).toBeUndefined();
      expect(header(c, "Idempotency-Key")).toBeUndefined();
    }
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ name: "Ana", email: "ana@example.com", password: "river-stone-77" });
  });

  it("claiming a report and changing the password use the resident session, never the staff one", async () => {
    setResidentToken("resident-token-xyz");
    const calls = mockFetch([json(200, { reference: "CMP-2026-0001" }), json(200, { message: "ok", token: "n" })]);
    await api.claimComplaint("CMP-2026-0001", "ABCDEF0123");
    await api.changePassword("old-pass-1", "new-pass-22");
    expect(header(calls[0], "Authorization")).toBe("Bearer resident-token-xyz");
    expect(header(calls[1], "Authorization")).toBe("Bearer resident-token-xyz");
  });

  it("history searches send only the filters that are set", async () => {
    const calls = mockFetch([json(200, { items: [], total: 0 }), json(200, { items: [] })]);
    await api.listComplaints({ scope: "closed", q: "hydrant", category: "", limit: 12, offset: 24 });
    await api.listProjects(undefined, { state: "past", q: "" });
    const url = new URL(calls[0].url);
    expect(Object.fromEntries(url.searchParams)).toEqual({ scope: "closed", q: "hydrant", limit: "12", offset: "24" });
    expect(Object.fromEntries(new URL(calls[1].url).searchParams)).toEqual({ state: "past" });
    expect(header(calls[0], "Authorization")).toBe("Bearer tok-abcdefgh-1234");
  });

  it("assigning staff sends the person (or null to remove them)", async () => {
    const calls = mockFetch([json(200, { id: "x", version: 2 }), json(200, { id: "p", version: 3 })]);
    await api.assignComplaintStaff("CMP-2026-0001", 4, "u-water2");
    await api.assignProjectStaff("water-1", 2, null);
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ expected_version: 4, user_id: "u-water2" });
    expect(JSON.parse(calls[1].init.body as string)).toEqual({ expected_version: 2, user_id: null });
    expect(calls[0].url).toContain("/complaints/CMP-2026-0001/assign-staff");
  });

  it("downloads a CSV with the staff session and reports a refusal clearly", async () => {
    const calls = mockFetch([new Response("a,b\n1,2\n", { status: 200, headers: { "Content-Type": "text/csv" } }), new Response("", { status: 403 })]);
    const blob = await api.downloadCsv("complaints");
    expect(await blob.text()).toBe("a,b\n1,2\n");
    expect(header(calls[0], "Authorization")).toBe("Bearer tok-abcdefgh-1234");
    expect(calls[0].url).toContain("/export/complaints.csv");
    await expect(api.downloadCsv("projects")).rejects.toMatchObject({ status: 403, code: "EXPORT_FAILED" });
  });

  it("does not treat a failed sign-in as an expired session", async () => {
    mockFetch([json(401, { error: { code: "INVALID_CREDENTIALS", message: "Incorrect username or password.", failures: [] } })]);
    const expired = vi.fn();
    setUnauthorizedHandler(expired);
    await expect(api.login("x", "y")).rejects.toMatchObject({ code: "INVALID_CREDENTIALS" });
    expect(expired).not.toHaveBeenCalled();
  });

  it("sends an Idempotency-Key on mutations only", async () => {
    const calls = mockFetch([json(200, { items: [] }), json(200, { id: "x", version: 2, message: "ok", recorded_at: "t" })]);
    await api.listCases();
    await api.cancelProject("water-1", 1, "no longer needed");
    expect(header(calls[0], "Idempotency-Key")).toBeUndefined();
    expect(header(calls[1], "Idempotency-Key")).toMatch(/.{8,}/);
    expect(JSON.parse(calls[1].init.body as string)).toEqual({ expected_version: 1, reason: "no longer needed" });
  });

  it("keeps the same key when the identical action is retried after a network failure", async () => {
    const calls = mockFetch([new TypeError("failed to fetch"), json(200, { id: "x", version: 2, message: "ok", recorded_at: "t" })]);
    await expect(api.start("surface-1", 3, 1)).rejects.toMatchObject({ network: true, code: "NETWORK_ERROR" });
    await api.start("surface-1", 3, 1);
    expect(header(calls[0], "Idempotency-Key")).toBe(header(calls[1], "Idempotency-Key"));
    expect(_pendingKeyCount()).toBe(0);                                  // forgotten once the server answered
  });

  it("uses a new key for a changed or new action", async () => {
    const calls = mockFetch([new TypeError("offline"), json(200, { id: "x", version: 2, message: "ok", recorded_at: "t" })]);
    await expect(api.start("surface-1", 3, 1)).rejects.toBeInstanceOf(ApiRequestError);
    await api.start("surface-1", 4, 1);                                  // newer version -> different action
    expect(header(calls[0], "Idempotency-Key")).not.toBe(header(calls[1], "Idempotency-Key"));
  });

  it("forgets the key after a definitive server refusal so a corrected request is a new action", async () => {
    mockFetch([json(422, { error: { code: "GATE_BLOCKED", message: "no", failures: [{ code: "X", message: "m" }] } })]);
    await expect(api.start("surface-1", 3, 1)).rejects.toMatchObject({ status: 422, code: "GATE_BLOCKED" });
    expect(_pendingKeyCount()).toBe(0);
  });

  it("parses the shared error envelope, including field failures and stale codes", async () => {
    mockFetch([json(409, { error: { code: "STALE_PLAN", message: "This plan changed. Refresh it before responding.", failures: [] } }),
               json(422, { error: { code: "VALIDATION_ERROR", message: "Check the highlighted fields.", failures: [{ field: "deadline", message: "Too early" }] } })]);
    const stale = await failure(api.generatePlan("case-market", 1));
    expect(stale.isStale).toBe(true);
    expect(stale.message).toMatch(/plan changed/i);
    const bad = await failure(api.advanceClock(1, 0));
    expect(bad.fieldMessage("deadline")).toBe("Too early");
  });

  it("falls back to a readable message when the server sends something unexpected", async () => {
    mockFetch([new Response("<html>oops</html>", { status: 502 })]);
    const err = await failure(api.bootstrap());
    expect(err.status).toBe(502);
    expect(err.message).toMatch(/could not complete/i);
  });
});
