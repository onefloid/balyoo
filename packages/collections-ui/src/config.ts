// Runtime configuration: one build serves every deployment. `config.json` sits
// next to index.html and says where the API is and whether it is the static JSON
// mirror (read-only, `.json` suffixed) or the live REST API (full CRUD).
//
//   static export -> {"apiBase": "api/", "static": true}
//   live server   -> {"apiBase": "",     "static": false}
//   live + static fallback (GitHub Pages against fly.io) ->
//     {"apiBase": "https://…/", "static": false, "staticBase": "api/"}
//
// When both a live `apiBase` and a `staticBase` are present, the UI runs in
// "dual" mode: it defaults to live but can fall back to (or be switched to) the
// bundled static mirror — see dataSource.tsx.

export interface AppConfig {
  /** Base for API requests, resolved relative to document.baseURI. */
  apiBase: string;
  /** True for the static JSON mirror (GET-only, paths suffixed with `.json`). */
  static: boolean;
  /**
   * Optional base of a bundled static JSON mirror to fall back to / toggle to
   * when `apiBase` is a live server. Present only in the dual-mode deployment.
   */
  staticBase?: string;
}

// If config.json is missing/unreadable, assume the safest deployment: the
// read-only static mirror. A misconfigured host then degrades to read-only rather
// than exposing write controls that cannot work.
const FALLBACK: AppConfig = { apiBase: "api/", static: true };

export async function loadConfig(): Promise<AppConfig> {
  try {
    const res = await fetch(new URL("config.json", document.baseURI));
    if (!res.ok) return FALLBACK;
    const raw = (await res.json()) as Partial<AppConfig>;
    return {
      apiBase: typeof raw.apiBase === "string" ? raw.apiBase : FALLBACK.apiBase,
      static: typeof raw.static === "boolean" ? raw.static : FALLBACK.static,
      ...(typeof raw.staticBase === "string" ? { staticBase: raw.staticBase } : {}),
    };
  } catch {
    return FALLBACK;
  }
}
