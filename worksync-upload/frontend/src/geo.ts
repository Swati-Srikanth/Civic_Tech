// Location helpers. A resident's position is used only in the browser to sort roads by distance;
// it is never sent to the WorkSync server. Typed place names go to OpenStreetMap's public Nominatim
// search service (no account or key) and nowhere else.

export interface Place {
  lat: number;
  lng: number;
  label: string;
  /** Metres, when the browser reports it. */
  accuracy?: number;
}

const EARTH_KM = 6371.0088;
const rad = (d: number) => (d * Math.PI) / 180;

/** Great-circle (haversine) distance in kilometres. */
export function distanceKm(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function sortByDistance<T extends { lat: number; lng: number }>(items: T[], from: { lat: number; lng: number }): (T & { distanceKm: number })[] {
  return items
    .map((i) => ({ ...i, distanceKm: distanceKm(from, i) }))
    .sort((x, y) => x.distanceKm - y.distanceKm);
}

export function formatKm(km: number): string {
  if (km < 0.1) return "under 100 m";
  if (km < 1) return `${Math.round(km * 10) * 100} m`;
  return `${km < 10 ? km.toFixed(1) : Math.round(km)} km`;
}

/** "under 100 m away" / "about 3.1 km away". */
export function awayText(km: number): string {
  return km < 0.1 ? "under 100 m away" : `about ${formatKm(km)} away`;
}

export const NOMINATIM_URL = "https://nominatim.openstreetmap.org/search";

interface NominatimHit {
  lat: string;
  lon: string;
  display_name: string;
}

export async function geocode(query: string): Promise<Place[]> {
  const q = query.trim();
  if (q.length < 3) throw new Error("Type at least three characters of a place, street or area.");
  const url = `${NOMINATIM_URL}?format=jsonv2&limit=5&q=${encodeURIComponent(q)}`;
  let res: Response;
  try {
    res = await fetch(url, { headers: { Accept: "application/json" } });
  } catch {
    throw new Error("The place search could not be reached. Check your connection, or use your current location instead.");
  }
  if (!res.ok) throw new Error("The place search is busy right now. Please try again in a moment.");
  const hits = (await res.json()) as NominatimHit[];
  return hits
    .map((h) => ({ lat: Number(h.lat), lng: Number(h.lon), label: h.display_name }))
    .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lng));
}

/** Ask the browser for the current position. Only runs when the person presses the button. */
export function currentPosition(): Promise<Place> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      reject(new Error("This browser cannot share a location. Type a place instead."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude, label: "Your current location", accuracy: pos.coords.accuracy }),
      (err) => {
        const msg =
          err.code === 1 ? "Location access was not allowed. You can type a place instead."
          : err.code === 3 ? "Finding your location took too long. Try again, or type a place."
          : "Your location is not available right now. You can type a place instead.";
        reject(new Error(msg));
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    );
  });
}
