import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";

export type PinKind = "work" | "complaint" | "urgent" | "fixed" | "pick";

export interface MapMarker {
  id: string;
  lat: number;
  lng: number;
  kind: PinKind;
  label: string;
}

interface Props {
  /** Accessible name for the map region. */
  label: string;
  user?: { lat: number; lng: number; accuracy?: number } | null;
  markers?: MapMarker[];
  /** A pin the person placed (reporting a problem, registering a street). */
  pick?: { lat: number; lng: number } | null;
  /** When set, clicking the map places the pin. */
  onPick?: (lat: number, lng: number) => void;
  height?: number;
}

const SYMBOL: Record<PinKind, string> = { work: "W", complaint: "!", urgent: "!", fixed: "✓", pick: "+" };

function pinIcon(kind: PinKind | "user"): L.DivIcon {
  const sym = kind === "user" ? "●" : SYMBOL[kind];
  return L.divIcon({
    className: "",
    html: `<span class="ws-pin ws-pin--${kind}" aria-hidden="true">${sym}</span>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
    popupAnchor: [0, -14],
  });
}

function popup(text: string): HTMLElement {
  const el = document.createElement("div");
  el.textContent = text;                       // text only: never HTML from the data
  return el;
}

/**
 * A live OpenStreetMap map (Leaflet). It is a visual aid: everything it shows is also listed as text beside it.
 * Map tiles are requested from tile.openstreetmap.org, which can tell roughly which area is being viewed.
 */
export function MapView({ label, user, markers = [], pick, onPick, height = 320 }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const pickHandler = useRef(onPick);
  const fitted = useRef("");
  const refit = useRef<(() => void) | null>(null);
  pickHandler.current = onPick;

  useEffect(() => {
    if (!host.current) return;
    const m = L.map(host.current, { zoomControl: true, scrollWheelZoom: false }).setView([20.5937, 78.9629], 4);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    m.on("click", (e: L.LeafletMouseEvent) => pickHandler.current?.(e.latlng.lat, e.latlng.lng));
    map.current = m;
    // A map framed before its box had a real size ends up zoomed far out: re-frame whenever the size changes.
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => { m.invalidateSize(); refit.current?.(); }) : null;
    ro?.observe(host.current);
    return () => {
      ro?.disconnect();
      m.remove();
      map.current = null;
      layer.current = null;
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    const g = layer.current;
    if (!m || !g) return;
    g.clearLayers();
    const points: L.LatLngExpression[] = [];
    if (user) {
      if (user.accuracy && user.accuracy > 0 && user.accuracy < 5000) {
        L.circle([user.lat, user.lng], { radius: user.accuracy, color: "#1d4ed8", weight: 1, fillOpacity: 0.08 }).addTo(g);
      }
      L.marker([user.lat, user.lng], { icon: pinIcon("user"), title: "You are here", keyboard: true }).bindPopup(popup("You are here")).addTo(g);
      points.push([user.lat, user.lng]);
    }
    for (const mk of markers) {
      L.marker([mk.lat, mk.lng], { icon: pinIcon(mk.kind), title: mk.label, keyboard: true }).bindPopup(popup(mk.label)).addTo(g);
      points.push([mk.lat, mk.lng]);
    }
    if (pick) {
      L.marker([pick.lat, pick.lng], { icon: pinIcon("pick"), title: "Chosen place", keyboard: true }).bindPopup(popup("Chosen place")).addTo(g);
    }
    // Re-frame only when the set of things shown changes, so panning and zooming is never fought.
    const around = points.length ? points : pick ? [[pick.lat, pick.lng] as L.LatLngExpression] : [];
    const frame = () => {
      if (!map.current) return;
      map.current.invalidateSize();
      if (around.length > 1) map.current.fitBounds(L.latLngBounds(around), { padding: [30, 30], maxZoom: 16 });
      else if (around.length === 1) map.current.setView(around[0], 15);
    };
    const key = [user ? `${user.lat.toFixed(4)},${user.lng.toFixed(4)}` : "", markers.map((x) => x.id).join("|"), user || markers.length ? "" : pick ? "p" : ""].join("#");
    if (key !== fitted.current) {
      fitted.current = key;
      frame();
      refit.current = frame;
      window.setTimeout(() => { if (refit.current === frame) frame(); }, 250);   // once layout has settled
    }
  }, [user, markers, pick]);

  return (
    <div className="ws-map-wrap">
      <div ref={host} className="ws-map" style={{ height }} role="region" aria-label={label} />
      <p className="ws-map-legend muted small">
        <span className="ws-pin ws-pin--user ws-pin--sm" aria-hidden="true">●</span> You ·{" "}
        <span className="ws-pin ws-pin--work ws-pin--sm" aria-hidden="true">W</span> Road works ·{" "}
        <span className="ws-pin ws-pin--complaint ws-pin--sm" aria-hidden="true">!</span> Reported problems ·{" "}
        <span className="ws-pin ws-pin--fixed ws-pin--sm" aria-hidden="true">✓</span> Fixed
      </p>
    </div>
  );
}
