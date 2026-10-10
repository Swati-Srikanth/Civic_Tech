import { useCallback, useEffect, useState } from "react";
import { currentPosition, geocode, type Place } from "./geo";

/**
 * The person's location for this visit. It lives only in memory. If the browser has already been given
 * permission, the location is found automatically; otherwise nothing is requested until they press a button.
 */
export function useLocation(autoIfGranted = true) {
  const [place, setPlace] = useState<Place | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [hits, setHits] = useState<Place[] | null>(null);

  const locate = useCallback(async () => {
    setMessage(null);
    setHits(null);
    setBusy(true);
    try {
      setPlace(await currentPosition());
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  const search = useCallback(async (query: string) => {
    setMessage(null);
    setBusy(true);
    try {
      const found = await geocode(query);
      setHits(found);
      if (!found.length) setMessage("No place matched that. Try a street, area or town name.");
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  const choose = useCallback((p: Place) => {
    setPlace(p);
    setHits(null);
    setMessage(null);
  }, []);

  useEffect(() => {
    if (!autoIfGranted || typeof navigator === "undefined" || !navigator.permissions?.query) return;
    let live = true;
    navigator.permissions
      .query({ name: "geolocation" as PermissionName })
      .then((s) => { if (live && s.state === "granted") void locate(); })
      .catch(() => { /* not supported: wait for a button press */ });
    return () => { live = false; };
  }, [autoIfGranted, locate]);

  return { place, setPlace: choose, busy, message, hits, locate, search, clearHits: () => setHits(null) };
}
