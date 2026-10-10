import { useState, type FormEvent } from "react";
import { ApiRequestError } from "../api";
import { Field } from "../components/Field";
import { Notice } from "../components/Notice";
import { useApp } from "../state";

/** Staff only. Residents never need this. The server checks the username and password. */
export function Login() {
  const { signIn, sessionNotice, go } = useApp();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiRequestError | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(username, password);
    } catch (err) {
      setError(err instanceof ApiRequestError ? err : new ApiRequestError(0, "UNKNOWN", "Something unexpected happened. Please try again."));
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack" style={{ maxWidth: 480 }}>
      <div className="page-head">
        <h1>Staff sign in</h1>
        <p className="muted">For municipal departments, contractors, inspectors and coordinators. Residents do not need to sign in.</p>
      </div>
      {sessionNotice ? <Notice kind="warn"><p>{sessionNotice}</p></Notice> : null}
      <form className="card stack" onSubmit={submit} noValidate aria-label="Staff sign in">
        <Field label="Username">
          {(p) => <input type="text" {...p} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} />}
        </Field>
        <Field label="Password">
          {(p) => <input type="password" {...p} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />}
        </Field>
        {error ? (
          <Notice kind="bad" title={error.status === 429 ? "Please wait" : "Could not sign you in"}><p>{error.message}</p></Notice>
        ) : null}
        <div className="row">
          <button type="submit" className="btn btn--primary" disabled={busy || !username.trim() || !password}>{busy ? "Signing in…" : "Sign in"}</button>
          <button type="button" className="btn" onClick={() => go("find")}>Back to the public page</button>
        </div>
      </form>
    </div>
  );
}
