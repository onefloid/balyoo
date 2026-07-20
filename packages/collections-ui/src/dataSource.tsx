// Runtime data-source state for the "dual" deployment (a live server plus a
// bundled static mirror, e.g. GitHub Pages against the fly.io REST API). It
// defaults to live, transparently falls back to the static mirror when the live
// server can't be reached, and lets the user switch sources by hand. In every
// other deployment (pure static export, or a single live server) there is only
// one source and this provider just hands that client straight through.

import { createContext, useContext, useMemo, useState } from "react";

import {
  FallbackClient,
  RestClient,
  StaticJsonClient,
  makeClient,
  type ApiClient,
} from "./api";
import { ApiProvider } from "./apiContext";
import type { AppConfig } from "./config";

export type SourcePreference = "live" | "static";

export interface DataSourceState {
  /** Whether a live/static choice exists at all (both sources are configured). */
  dual: boolean;
  /** The user's chosen source. */
  preference: SourcePreference;
  /** The source actually serving data right now (differs from preference on fallback). */
  mode: SourcePreference;
  /** True when the user prefers live but the live server was unreachable. */
  fellBack: boolean;
  /** Changes React subtree identity so views reload when the source changes. */
  reloadKey: string;
  setPreference: (next: SourcePreference) => void;
  /** Re-select live and retry it (e.g. after a fallback). */
  retryLive: () => void;
}

// Default for when no provider wraps the tree (single-source deployments and
// component tests that mount views directly): one source, no toggle, stable key.
const SINGLE_SOURCE: DataSourceState = {
  dual: false,
  preference: "live",
  mode: "live",
  fellBack: false,
  reloadKey: "single",
  setPreference: () => {},
  retryLive: () => {},
};

const DataSourceContext = createContext<DataSourceState>(SINGLE_SOURCE);

export function useDataSource(): DataSourceState {
  return useContext(DataSourceContext);
}

const STORAGE_KEY = "collections-ui:source";

function readPreference(fallback: SourcePreference): SourcePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "live" || stored === "static" ? stored : fallback;
  } catch {
    return fallback;
  }
}

function storePreference(value: SourcePreference): void {
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    /* ignore: private mode / disabled storage */
  }
}

export function DataSourceProvider({
  config,
  children,
}: {
  config: AppConfig;
  children: React.ReactNode;
}) {
  // Dual mode requires both a live server (apiBase, static:false) and a bundled
  // static mirror (staticBase). Any other config keeps the single-source behaviour.
  const dual =
    !config.static && typeof config.staticBase === "string" && config.staticBase !== "";
  const defaultPreference: SourcePreference = config.static ? "static" : "live";

  const [preference, setPreferenceState] = useState<SourcePreference>(() =>
    dual ? readPreference(defaultPreference) : defaultPreference,
  );
  const [fellBack, setFellBack] = useState(false);
  // Bumped on every explicit source change so a re-selection (even to the same
  // value, e.g. "retry live") remounts the content and re-runs its loaders.
  const [nonce, setNonce] = useState(0);

  const select = (next: SourcePreference) => {
    setFellBack(false);
    setNonce((n) => n + 1);
    setPreferenceState(next);
    storePreference(next);
  };

  const client = useMemo<ApiClient>(() => {
    if (!dual) return makeClient(config);
    const staticClient = new StaticJsonClient(config.staticBase as string);
    // Once we've fallen back (or the user picked static) serve the mirror
    // directly, so we don't re-hit an unreachable live server on every request.
    if (preference === "static" || fellBack) return staticClient;
    return new FallbackClient(new RestClient(config.apiBase), staticClient, () =>
      setFellBack(true),
    );
    // `nonce` forces a fresh client (and thus a retry) on an explicit re-selection.
  }, [dual, config, preference, fellBack, nonce]);

  const mode: SourcePreference = !dual
    ? defaultPreference
    : preference === "static" || fellBack
      ? "static"
      : "live";

  const state: DataSourceState = {
    dual,
    preference,
    mode,
    fellBack,
    reloadKey: `${mode}:${nonce}`,
    setPreference: select,
    retryLive: () => select("live"),
  };

  return (
    <DataSourceContext.Provider value={state}>
      <ApiProvider value={client}>{children}</ApiProvider>
    </DataSourceContext.Provider>
  );
}
