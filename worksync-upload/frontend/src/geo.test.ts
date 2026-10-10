import { afterEach, describe, expect, it, vi } from "vitest";
import { awayText, distanceKm, formatKm, geocode, sortByDistance, NOMINATIM_URL } from "./geo";

afterEach(() => vi.unstubAllGlobals());

describe("distance helpers", () => {
  it("computes great-circle distance (Chennai Central to Marina Beach is about 3 km)", () => {
    const d = distanceKm({ lat: 13.0827, lng: 80.2757 }, { lat: 13.0500, lng: 80.2824 });
    expect(d).toBeGreaterThan(3.3);
    expect(d).toBeLessThan(4.1);
    expect(distanceKm({ lat: 1, lng: 2 }, { lat: 1, lng: 2 })).toBe(0);
    expect(distanceKm({ lat: 0, lng: 0 }, { lat: 0, lng: 1 })).toBeCloseTo(111.19, 1);
  });

  it("sorts roads nearest first without mutating the input", () => {
    const roads = [{ id: "far", lat: 13.2, lng: 80.3 }, { id: "near", lat: 13.001, lng: 80.0 }, { id: "mid", lat: 13.05, lng: 80.0 }];
    const out = sortByDistance(roads, { lat: 13.0, lng: 80.0 });
    expect(out.map((r) => r.id)).toEqual(["near", "mid", "far"]);
    expect(roads[0].id).toBe("far");
  });

  it("formats short distances in metres and longer ones in km", () => {
    expect(formatKm(0.4)).toBe("400 m");
    expect(formatKm(0.0003)).toBe("under 100 m");
    expect(awayText(0.0003)).toBe("under 100 m away");
    expect(awayText(3.14)).toBe("about 3.1 km away");
    expect(formatKm(2.34)).toBe("2.3 km");
    expect(formatKm(48.6)).toBe("49 km");
  });
});

describe("geocode", () => {
  it("asks the public Nominatim search with the typed text only and parses results", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify([
      { lat: "13.0827", lon: "80.2707", display_name: "Chennai, Tamil Nadu, India" },
      { lat: "bad", lon: "80", display_name: "broken" },
    ]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const places = await geocode("  Chennai ");
    expect(places).toEqual([{ lat: 13.0827, lng: 80.2707, label: "Chennai, Tamil Nadu, India" }]);
    const url = String((fetchMock.mock.calls[0] as unknown[])[0]);
    expect(url.startsWith(NOMINATIM_URL)).toBe(true);
    expect(url).toContain("q=Chennai");
    expect(url).not.toContain("version");
  });

  it("refuses very short input without calling out, and explains network failures", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(geocode("ab")).rejects.toThrow(/three characters/);
    expect(fetchMock).not.toHaveBeenCalled();
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    await expect(geocode("Chennai")).rejects.toThrow(/could not be reached/);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 429 })));
    await expect(geocode("Chennai")).rejects.toThrow(/busy/);
  });
});
