// Shared app state: who is signed in (staff only), which screen, which road, and a refresh tick.
// Residents are never signed in. All business data lives on the server; the session token is the
// only thing remembered here, and only for this browser tab (sessionStorage).
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiRequestError, setAuthToken, setResidentExpiredHandler, setResidentToken, setUnauthorizedHandler } from "./api";
import { forgetReport, referencesToForget, savedReports, unreadCount } from "./myReports";
import type { Bootstrap, ComplaintTrackView, DemoUser, Resident } from "./types";

export type PublicScreen = "find" | "road" | "report" | "track" | "mine" | "account" | "login";
export type StaffScreen = "overview" | "projects" | "coordinate" | "work" | "complaints" | "history" | "team";
export type Screen = PublicScreen | StaffScreen;

export const STAFF_SCREENS: StaffScreen[] = ["overview", "projects", "coordinate", "work", "complaints", "history", "team"];
export const isStaffScreen = (s: Screen): s is StaffScreen => (STAFF_SCREENS as string[]).includes(s);

interface AppState {
  boot: Bootstrap | null;
  bootError: ApiRequestError | null;
  /** The signed-in staff member, or null for the public. */
  user: DemoUser | null;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  sessionNotice: string | null;
  /** A resident who chose to sign in with Google (optional; guests have none). */
  resident: Resident | null;
  signInWithGoogle: (credential: string) => Promise<void>;
  /** Local account (e-mail + password). Both throw an ApiRequestError with field messages on failure. */
  registerResident: (name: string, email: string, password: string) => Promise<void>;
  signInResident: (email: string, password: string) => Promise<void>;
  signOutResident: () => Promise<void>;
  /** The person's own reports (from their account and/or saved on this device) and what is new. */
  myReports: ComplaintTrackView[];
  unread: number;
  refreshMyReports: () => Promise<void>;
  toast: string | null;
  dismissToast: () => void;
  /** Road chosen in the staff screens. */
  roadId: string;
  setRoadId: (id: string) => void;
  /** Road a resident opened from the "near me" list. */
  publicRoadId: string | null;
  openRoad: (id: string) => void;
  screen: Screen;
  go: (screen: Screen, opts?: { caseId?: string }) => void;
  focusCaseId: string | null;
  tick: number;
  refresh: () => void;
}

const Ctx = createContext<AppState | null>(null);

function load(store: "local" | "session", key: string): string | null {
  try {
    return (store === "local" ? window.localStorage : window.sessionStorage).getItem(key);
  } catch {
    return null;
  }
}
function save(store: "local" | "session", key: string, value: string | null): void {
  try {
    const s = store === "local" ? window.localStorage : window.sessionStorage;
    if (value === null) s.removeItem(key);
    else s.setItem(key, value);
  } catch {
    /* storage can be unavailable; the app still works without it */
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => load("session", "ws.token"));
  const [residentTok, setResidentTok] = useState<string | null>(() => load("session", "ws.resident"));
  const [resident, setResident] = useState<Resident | null>(null);
  const [myReports, setMyReports] = useState<ComplaintTrackView[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const lastEvents = useRef<Map<string, number> | null>(null);
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [bootError, setBootError] = useState<ApiRequestError | null>(null);
  const [roadId, setRoadIdState] = useState<string>(load("local", "ws.road") ?? "");
  const [publicRoadId, setPublicRoadId] = useState<string | null>(null);
  const [screen, setScreen] = useState<Screen>("find");
  const [focusCaseId, setFocusCaseId] = useState<string | null>(null);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);

  // The credential must be in place before any child effect fetches staff data, so it is applied during render.
  setAuthToken(token);
  setResidentToken(residentTok);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  const endSession = useCallback((notice: string | null) => {
    save("session", "ws.token", null);
    setAuthToken(null);
    setToken(null);
    setBoot(null);
    setSessionNotice(notice);
    setScreen((s) => (isStaffScreen(s) ? (notice ? "login" : "find") : s));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => endSession("Your session ended. Please sign in again."));
    return () => setUnauthorizedHandler(null);
  }, [endSession]);

  const endResident = useCallback(() => {
    save("session", "ws.resident", null);
    setResidentToken(null);
    setResidentTok(null);
    setResident(null);
  }, []);

  useEffect(() => {
    setResidentExpiredHandler(endResident);
    return () => setResidentExpiredHandler(null);
  }, [endResident]);

  // Restore a Google-signed-in resident for this tab, if the server still accepts the session.
  useEffect(() => {
    if (!residentTok) {
      setResident(null);
      return;
    }
    let live = true;
    api.residentMe().then((r) => live && setResident(r)).catch(() => live && endResident());
    return () => { live = false; };
  }, [residentTok, endResident]);

  // The person's own reports: from their account, plus any they chose to remember on this device.
  const refreshMyReports = useCallback(async () => {
    const found: ComplaintTrackView[] = [];
    if (residentTok) {
      try { found.push(...(await api.myComplaints())); } catch { /* shown as empty; a 401 ends the session elsewhere */ }
    }
    const rest = savedReports().filter((r) => !found.some((f) => f.reference === r.reference));
    const settled = await Promise.allSettled(rest.map((r) => api.trackComplaint(r.reference, r.code)));
    settled.forEach((s) => { if (s.status === "fulfilled") found.push(s.value); });
    referencesToForget(rest, settled as { status: "fulfilled" | "rejected"; reason?: { status?: number } }[]).forEach(forgetReport);
    // First load only records what is already there. Later loads announce anything that changed.
    const before = lastEvents.current;
    const now = new Map(found.map((f) => [f.reference, f.last_event_id] as const));
    if (before) {
      for (const f of found) {
        const latest = f.timeline[f.timeline.length - 1];
        // Announce changes made by others, not the person's own actions.
        if (before.has(f.reference) && (before.get(f.reference) ?? 0) < f.last_event_id && latest && latest.actor_label !== "You") {
          setToast(`Update on ${f.reference}: ${latest.message}`);
          break;
        }
      }
    }
    lastEvents.current = now;
    setMyReports(found);
  }, [residentTok]);

  useEffect(() => {
    lastEvents.current = null;
    void refreshMyReports();
    const id = window.setInterval(() => { if (document.visibilityState === "visible") void refreshMyReports(); }, 30000);
    return () => window.clearInterval(id);
  }, [refreshMyReports, tick]);

  // (Re)load the bootstrap whenever the credential or tick changes. The server decides what it contains.
  useEffect(() => {
    const mine = ++seq.current;
    api
      .bootstrap(!token)
      .then((b) => {
        if (mine !== seq.current) return;
        setBoot(b);
        setBootError(null);
        setRoadIdState((r) => (r && b.roads.some((x) => x.id === r) ? r : b.roads[0]?.id ?? ""));
        // A stored token the server no longer accepts simply falls back to the public view.
        if (token && !b.current_user) {
          save("session", "ws.token", null);
          setAuthToken(null);
          setToken(null);
        }
      })
      .catch((e: ApiRequestError) => {
        if (mine !== seq.current) return;
        setBootError(e);
      });
  }, [token, tick]);

  const user = useMemo(() => (token ? boot?.current_user ?? null : null), [token, boot]);

  const value: AppState = {
    boot,
    bootError,
    user,
    signIn: async (username, password) => {
      const result = await api.login(username, password);
      save("session", "ws.token", result.token);
      setAuthToken(result.token);
      setSessionNotice(null);
      // Start on a road where this person actually has work, rather than whichever road was last chosen.
      try {
        const mine = await api.listProjects();
        if (mine.length) {
          setRoadIdState(mine[0].road_id);
          save("local", "ws.road", mine[0].road_id);
        }
      } catch {
        /* keep the previous road */
      }
      setBoot(null);
      setToken(result.token);
      setScreen(result.user.role === "INSPECTOR" ? "work" : result.user.role === "CONTRACTOR" ? "projects" : "overview");
    },
    signOut: async () => {
      try {
        await api.logout();
      } catch {
        /* the token is dropped locally either way */
      }
      endSession(null);
    },
    sessionNotice,
    resident,
    signInWithGoogle: async (credential) => {
      const out = await api.googleLogin(credential);
      save("session", "ws.resident", out.token);
      setResidentToken(out.token);
      setResidentTok(out.token);
      setResident(out.resident);
    },
    registerResident: async (name, email, password) => {
      const out = await api.register(name, email, password);
      save("session", "ws.resident", out.token);
      setResidentToken(out.token);
      setResidentTok(out.token);
      setResident(out.resident);
    },
    signInResident: async (email, password) => {
      const out = await api.residentLogin(email, password);
      save("session", "ws.resident", out.token);
      setResidentToken(out.token);
      setResidentTok(out.token);
      setResident(out.resident);
    },
    signOutResident: async () => {
      try { await api.residentLogout(); } catch { /* dropped locally either way */ }
      endResident();
    },
    myReports,
    unread: myReports.reduce((n, r) => n + unreadCount(r.reference, r.timeline), 0),
    refreshMyReports,
    toast,
    dismissToast: () => setToast(null),
    roadId,
    setRoadId: (id) => {
      setRoadIdState(id);
      save("local", "ws.road", id);
    },
    publicRoadId,
    openRoad: (id) => {
      setPublicRoadId(id);
      setScreen("road");
      window.scrollTo?.({ top: 0 });
    },
    screen,
    go: (s, opts) => {
      setScreen(s);
      setFocusCaseId(opts?.caseId ?? null);
      window.scrollTo?.({ top: 0 });
    },
    focusCaseId,
    tick,
    refresh,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp must be used inside AppProvider");
  return v;
}
