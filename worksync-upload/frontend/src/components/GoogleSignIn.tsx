import { useEffect, useRef, useState } from "react";

interface GoogleId {
  initialize: (cfg: { client_id: string; callback: (r: { credential: string }) => void }) => void;
  renderButton: (el: HTMLElement, opts: Record<string, unknown>) => void;
}
declare global {
  interface Window { google?: { accounts: { id: GoogleId } } }
}

const SRC = "https://accounts.google.com/gsi/client";

/**
 * Optional "Sign in with Google" for residents. It appears only when the server has a Google client id configured.
 * Google's script is loaded only then, and only when this component is on screen. Guests never need it.
 */
export function GoogleSignIn({ clientId, onCredential, onError }: { clientId: string; onCredential: (c: string) => void; onError: (m: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(typeof window !== "undefined" && !!window.google?.accounts);
  const cb = useRef(onCredential);
  cb.current = onCredential;

  useEffect(() => {
    if (ready) return;
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${SRC}"]`);
    const script = existing ?? Object.assign(document.createElement("script"), { src: SRC, async: true, defer: true });
    const ok = () => setReady(true);
    const bad = () => onError("Google sign-in could not be loaded. You can carry on as a guest.");
    script.addEventListener("load", ok);
    script.addEventListener("error", bad);
    if (!existing) document.head.appendChild(script);
    return () => { script.removeEventListener("load", ok); script.removeEventListener("error", bad); };
  }, [ready, onError]);

  useEffect(() => {
    if (!ready || !box.current || !window.google) return;
    window.google.accounts.id.initialize({ client_id: clientId, callback: (r) => cb.current(r.credential) });
    window.google.accounts.id.renderButton(box.current, { theme: "outline", size: "large", text: "signin_with", shape: "pill" });
  }, [ready, clientId]);

  return <div ref={box} aria-label="Sign in with Google" />;
}
