import { fmtDate, ROLE_TEXT } from "./format";
import { Notice } from "./components/Notice";
import { Account } from "./screens/Account";
import { Complaints } from "./screens/Complaints";
import { Coordinate } from "./screens/Coordinate";
import { FindArea } from "./screens/FindArea";
import { History } from "./screens/History";
import { Login } from "./screens/Login";
import { MyReports } from "./screens/MyReports";
import { MyRoad } from "./screens/MyRoad";
import { Overview } from "./screens/Overview";
import { Projects } from "./screens/Projects";
import { ReportProblem } from "./screens/ReportProblem";
import { Team } from "./screens/Team";
import { TrackComplaint } from "./screens/TrackComplaint";
import { WorkChecks } from "./screens/WorkChecks";
import { isStaffScreen, useApp, type Screen } from "./state";

export default function App() {
  const { boot, bootError, user, screen, go, signOut, roadId, setRoadId, resident, signOutResident, unread, toast, dismissToast } = useApp();
  const signedIn = !!user;
  const canSeeComplaints = !!boot?.allowed_actions.includes("VIEW_COMPLAINTS");
  const isDeptOrAdmin = user?.role === "DEPARTMENT" || user?.role === "ADMIN";
  const isOverseer = user?.role === "ADMIN" || !!user?.is_head;

  const publicTabs: { id: Screen; label: string }[] = [
    { id: "find", label: "Near me" },
    { id: "report", label: "Report a problem" },
    { id: "track", label: "Track a complaint" },
    { id: "mine", label: unread ? `My reports (${unread} new)` : "My reports" },
  ];
  // Staff screens are only ever rendered for a signed-in user (the server enforces this too).
  const staffTabs: { id: Screen; label: string }[] = [
    ...(isDeptOrAdmin ? [{ id: "overview" as Screen, label: "Overview" }] : []),
    { id: "projects", label: "Projects" },
    { id: "coordinate", label: "Coordinate work" },
    { id: "work", label: "Work and checks" },
    ...(canSeeComplaints ? [{ id: "complaints" as Screen, label: "Complaints" }] : []),
    ...(isDeptOrAdmin ? [{ id: "history" as Screen, label: "History" }] : []),
    ...(isOverseer ? [{ id: "team" as Screen, label: user?.role === "ADMIN" ? "Teams" : "My team" }] : []),
  ];

  const body = (() => {
    if (signedIn) {
      switch (screen) {
        case "overview": return isDeptOrAdmin ? <Overview /> : <Projects />;
        case "coordinate": return <Coordinate />;
        case "work": return <WorkChecks />;
        case "complaints": return canSeeComplaints ? <Complaints /> : <Projects />;
        case "history": return isDeptOrAdmin ? <History /> : <Projects />;
        case "team": return isOverseer ? <Team /> : <Overview />;
        default: return <Projects />;
      }
    }
    if (isStaffScreen(screen) || screen === "login") return <Login />;
    switch (screen) {
      case "road": return <MyRoad />;
      case "report": return <ReportProblem />;
      case "track": return <TrackComplaint />;
      case "mine": return <MyReports />;
      case "account": return <Account />;
      default: return <FindArea />;
    }
  })();

  const tabs = signedIn ? staffTabs : publicTabs;
  const active: Screen = signedIn ? (isStaffScreen(screen) ? screen : isDeptOrAdmin ? "overview" : "projects") : screen === "road" ? "find" : screen;

  return (
    <>
      <header className="app-header">
        <div className="app-header__inner">
          <div className="brand">
            <span className="brand__name">WorkSync</span>
            <span className="brand__tag">What's happening on my road</span>
          </div>
          <div className="header-controls">
            {signedIn ? (
              <>
                <label>
                  Street
                  <select value={roadId} onChange={(e) => setRoadId(e.target.value)} disabled={!boot || boot.roads.length === 0}>
                    {boot?.roads.length ? boot.roads.map((r) => <option key={r.id} value={r.id}>{r.name}</option>) : <option value="">No streets yet</option>}
                  </select>
                </label>
                <span className="clock-chip" style={{ marginLeft: 0 }} aria-label="Signed in user">
                  <strong>{user!.name}</strong> · {user!.is_head ? "Head, " : ""}{ROLE_TEXT[user!.role]}, {user!.org_name}
                </span>
                <button type="button" className="tab" onClick={() => void signOut()}>Sign out</button>
              </>
            ) : (
              <>
                {resident ? (
                  <>
                    <button type="button" className="tab" onClick={() => go("account")} aria-current={screen === "account" ? "page" : undefined}>
                      {resident.name ?? resident.email}
                    </button>
                    <button type="button" className="tab" onClick={() => void signOutResident()}>Sign out</button>
                  </>
                ) : (
                  <button type="button" className="tab" onClick={() => go("account")} aria-current={screen === "account" ? "page" : undefined}>Sign in / Create account</button>
                )}
                <button type="button" className="tab" onClick={() => go("login")} aria-current={screen === "login" ? "page" : undefined}>Staff sign in</button>
              </>
            )}
            {boot ? <span className="clock-chip" title="Simulated demo clock">Demo date: <strong>{fmtDate(boot.clock.date)}</strong> (simulated)</span> : null}
          </div>
        </div>
        {screen !== "login" || signedIn ? (
          <nav className="tabs" aria-label={signedIn ? "Staff workspace" : "Public pages"}>
            {tabs.map((t) => (
              <button key={t.id} type="button" className="tab" aria-current={active === t.id ? "page" : undefined} onClick={() => go(t.id)}>{t.label}</button>
            ))}
          </nav>
        ) : null}
      </header>
      <main>
        {toast ? (
          <div className="toast" role="status" aria-live="polite">
            <Notice kind="info" title="You have an update">
              <p>{toast}</p>
              <div className="row">
                <button type="button" className="btn" onClick={() => { dismissToast(); go("mine"); }}>See my reports</button>
                <button type="button" className="btn btn--link" onClick={dismissToast}>Dismiss</button>
              </div>
            </Notice>
          </div>
        ) : null}
        {bootError ? (
          <Notice kind="bad" title="Cannot reach the WorkSync server">
            <p>{bootError.message}</p>
            <p className="small">Start the backend (see the README), then reload this page. Open the app at http://localhost:5173.</p>
          </Notice>
        ) : null}
        {!bootError && !boot ? <p className="loading">Loading…</p> : null}
        {boot ? body : null}
      </main>
    </>
  );
}
