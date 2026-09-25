// The seeded event with enough sessions to scroll, fold and filter against.
export const DENSE_EVENT_URL = "/event/kapitularz-2025-anonymized/";

// The root domain the server runs on, which bootstrap_data.py seeds as the
// root sphere's site.
export const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:8000";

// A sphere of its own that bootstrap_data.py leaves empty, so no other spec's
// fixtures show up on it.
export const EMPTY_SPHERE = "http://another.localhost:8000";
