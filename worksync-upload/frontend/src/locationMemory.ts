import type { Place } from "./geo";

/**
 * The last location the person chose during this visit, so "Report a problem" can start from the same place.
 * It lives only in memory (gone on reload) and is never stored or sent anywhere by itself.
 */
export const locationMemory: { place: Place | null } = { place: null };
