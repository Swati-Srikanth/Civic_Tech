import { useState, type FormEvent } from "react";
import { api, ApiRequestError } from "../api";
import { Field } from "../components/Field";
import { GoogleSignIn } from "../components/GoogleSignIn";
import { ErrorNotice, Notice } from "../components/Notice";
import { savedReports, forgetReport } from "../myReports";
import { useAction } from "../hooks";
import { useApp } from "../state";

/** The resident's optional account. Guests need none. Create one with an e-mail and password, or use Google. */
export function Account() {
  const { resident, boot, go, signInResident, registerResident, signInWithGoogle, signOutResident, refreshMyReports } = useApp();
  const [mode, setMode] = useState<"signin" | "create">("signin");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<ApiRequestError | null>(null);
  const [googleError, setGoogleError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [localMismatch, setLocalMismatch] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setLocalMismatch(null);
    if (mode === "create" && password !== confirm) { setLocalMismatch("The two passwords are not the same."); return; }
    setBusy(true);
    try {
      if (mode === "create") await registerResident(name.trim(), email.trim(), password);
      else await signInResident(email.trim(), password);
      setPassword(""); setConfirm("");
      void refreshMyReports();
    } catch (err) {
      setError(err instanceof ApiRequestError ? err : new ApiRequestError(0, "UNKNOWN", "Something unexpected happened. Please try again."));
      setPassword(""); setConfirm("");
    } finally {
      setBusy(false);
    }
  };

  if (resident) {
    return (
      <div className="stack" style={{ maxWidth: 560 }}>
        <div className="page-head">
          <h1>Your account</h1>
          <p className="muted">Signed in as <strong>{resident.name ?? resident.email}</strong>{resident.email ? ` (${resident.email})` : ""} {resident.provider === "google" ? "with Google" : "with a local account"}.</p>
        </div>
        <section className="card stack-sm">
          <h2>Your reports</h2>
          <p className="muted">Reports you send while signed in are saved to this account, so you can follow them from any device.</p>
          <div className="row"><button type="button" className="btn btn--primary" onClick={() => go("mine")}>See my reports</button></div>
        </section>
        <ClaimDeviceReports />
        {resident.provider === "local" ? <ChangePassword /> : null}
        <div><button type="button" className="btn" onClick={() => void signOutResident().then(() => go("find"))}>Sign out</button></div>
      </div>
    );
  }

  return (
    <div className="stack" style={{ maxWidth: 560 }}>
      <div className="page-head">
        <h1>Sign in or create an account</h1>
        <p className="muted">Optional. You can always report and track problems as a guest. An account keeps your reports together across devices.</p>
      </div>
      <div className="seg" role="group" aria-label="Account action">
        <label><input type="radio" name="acct-mode" checked={mode === "signin"} onChange={() => { setMode("signin"); setError(null); }} /> Sign in</label>
        <label><input type="radio" name="acct-mode" checked={mode === "create"} onChange={() => { setMode("create"); setError(null); }} /> Create an account</label>
      </div>
      <form className="card stack" onSubmit={submit} noValidate aria-label={mode === "create" ? "Create an account" : "Sign in"}>
        {mode === "create" ? (
          <Field label="Your name" error={error?.fieldMessage("name")}>{(f) => <input type="text" {...f} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={80} />}</Field>
        ) : null}
        <Field label="E-mail" error={error?.fieldMessage("email")} help={mode === "create" ? "Used only as your username. It is not checked and we never send e-mail." : undefined}>
          {(f) => <input type="text" inputMode="email" {...f} value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoCapitalize="none" spellCheck={false} />}
        </Field>
        <Field label="Password" error={error?.fieldMessages("password")} help={mode === "create" ? "At least 8 characters, mixing letters with numbers or symbols. It is stored only as a salted hash and cannot be read back." : undefined}>
          {(f) => <input type="password" {...f} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "create" ? "new-password" : "current-password"} />}
        </Field>
        {mode === "create" ? (
          <Field label="Repeat the password" error={localMismatch ?? undefined}>{(f) => <input type="password" {...f} value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />}</Field>
        ) : null}
        {error && !error.failures.some((f) => f.field) ? <Notice kind="bad" title={error.status === 429 ? "Please wait" : "That did not work"}><p>{error.message}</p></Notice> : null}
        <div className="row">
          <button type="submit" className="btn btn--primary" disabled={busy || !email.trim() || !password || (mode === "create" && !name.trim())}>
            {busy ? "Please wait…" : mode === "create" ? "Create account" : "Sign in"}
          </button>
          <button type="button" className="btn" onClick={() => go("find")}>Carry on as a guest</button>
        </div>
        <p className="muted small">There is no "forgot password" e-mail, because the app never sends e-mail. Keep your password somewhere safe; you can always use the app as a guest.</p>
      </form>
      {boot?.google_client_id ? (
        <section className="card stack-sm" aria-label="Google">
          <h2>Or use Google</h2>
          <GoogleSignIn clientId={boot.google_client_id} onError={setGoogleError}
            onCredential={(c) => { setGoogleError(null); signInWithGoogle(c).catch((e: Error) => setGoogleError(e.message)); }} />
          {googleError ? <Notice kind="warn"><p>{googleError}</p></Notice> : null}
        </section>
      ) : null}
    </div>
  );
}

function ClaimDeviceReports() {
  const { refreshMyReports } = useApp();
  const [message, setMessage] = useState<string | null>(null);
  const [count, setCount] = useState(() => savedReports().length);
  const act = useAction(async () => {
    let added = 0;
    for (const r of savedReports()) {
      try { await api.claimComplaint(r.reference, r.code); forgetReport(r.reference); added += 1; } catch { /* leave it remembered on this device */ }
    }
    return added;
  }, (n) => { setCount(savedReports().length); setMessage(n ? `Added ${n} report${n === 1 ? "" : "s"} to your account.` : "None could be added."); void refreshMyReports(); });
  if (count === 0 && !message) return null;
  return (
    <section className="card stack-sm">
      <h2>Reports remembered on this device</h2>
      <p className="muted">{count} report{count === 1 ? " is" : "s are"} saved in this browser from when you were a guest. Add them to your account to see them from anywhere.</p>
      <div><button type="button" className="btn" disabled={act.busy || count === 0} onClick={() => void act.run()}>{act.busy ? "Adding…" : "Add them to my account"}</button></div>
      {message ? <Notice kind="ok"><p>{message}</p></Notice> : null}
    </section>
  );
}

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const act = useAction(() => api.changePassword(current, next), () => { setCurrent(""); setNext(""); });
  return (
    <section className="card stack-sm">
      <h2>Change password</h2>
      <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); void act.run(); }} noValidate>
        <Field label="Current password" error={act.error?.fieldMessage("current_password")}>{(f) => <input type="password" {...f} value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />}</Field>
        <Field label="New password" error={act.error?.fieldMessage("new_password")} help="Your other devices will be signed out.">{(f) => <input type="password" {...f} value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />}</Field>
        {act.error && !act.error.failures.length ? <ErrorNotice error={act.error} /> : null}
        {act.result ? <Notice kind="ok"><p>{act.result.message}</p></Notice> : null}
        <div><button type="submit" className="btn" disabled={act.busy || !current || !next}>{act.busy ? "Saving…" : "Change password"}</button></div>
      </form>
    </section>
  );
}
