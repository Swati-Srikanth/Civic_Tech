import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError } from "./api";

export interface Resource<T> {
  data: T | null;
  error: ApiRequestError | null;
  loading: boolean;
  reload: () => void;
}

/** Fetch on mount and whenever deps change. Ignores answers that arrive out of order. */
export function useResource<T>(fetcher: () => Promise<T>, deps: unknown[], enabled = true): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiRequestError | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [n, setN] = useState(0);
  const seq = useRef(0);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const mine = ++seq.current;
    setLoading(true);
    fetchRef
      .current()
      .then((d) => {
        if (mine !== seq.current) return;
        setData(d);
        setError(null);
      })
      .catch((e: ApiRequestError) => {
        if (mine !== seq.current) return;
        setError(e);
      })
      .finally(() => {
        if (mine === seq.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n, enabled]);

  return { data, error, loading, reload: useCallback(() => setN((x) => x + 1), []) };
}

export interface Action<A extends unknown[], R> {
  run: (...a: A) => Promise<R | null>;
  busy: boolean;
  error: ApiRequestError | null;
  result: R | null;
  clear: () => void;
}

/** One server action. While pending it ignores extra clicks; the backend's idempotency is the real guard. */
export function useAction<A extends unknown[], R>(fn: (...a: A) => Promise<R>, onDone?: (r: R) => void): Action<A, R> {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiRequestError | null>(null);
  const [result, setResult] = useState<R | null>(null);
  const pending = useRef(false);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  const run = useCallback(async (...a: A): Promise<R | null> => {
    if (pending.current) return null;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      const r = await fnRef.current(...a);
      setResult(r);
      doneRef.current?.(r);
      return r;
    } catch (e) {
      setError(e instanceof ApiRequestError ? e : new ApiRequestError(0, "UNKNOWN", "Something unexpected happened. Please try again."));
      return null;
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }, []);

  return { run, busy, error, result, clear: () => { setError(null); setResult(null); } };
}
