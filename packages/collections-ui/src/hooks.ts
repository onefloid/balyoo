import { useEffect, useState } from "react";

import type { ViewMode } from "./card";

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** The list/card view for a collection: the user's stored choice if any, else the
 * schema's default (`x-card.default`). The choice is remembered per collection, so
 * different collections can open in different views. */
export function useViewPreference(
  collection: string,
  schemaDefault: ViewMode,
): [ViewMode, (value: ViewMode) => void] {
  const key = `collections-ui:view:${collection}`;
  const [stored, setStored] = useState<string | null>(() => readStored(key));

  // Re-read when navigating to another collection.
  useEffect(() => {
    setStored(readStored(key));
  }, [key]);

  const view: ViewMode = stored === "list" || stored === "cards" ? stored : schemaDefault;
  const set = (next: ViewMode) => {
    setStored(next);
    try {
      localStorage.setItem(key, next);
    } catch {
      /* ignore: private mode / disabled storage */
    }
  };
  return [view, set];
}

export interface AsyncState<T> {
  data?: T;
  error?: Error;
  loading: boolean;
}

/** Run an async loader on mount / when `deps` change, ignoring stale results. */
export function useAsync<T>(
  loader: () => Promise<T>,
  deps: React.DependencyList,
): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ loading: true });

  useEffect(() => {
    let active = true;
    setState({ loading: true });
    loader().then(
      (data) => active && setState({ data, loading: false }),
      (error: Error) => active && setState({ error, loading: false }),
    );
    return () => {
      active = false;
    };
  }, deps);

  return state;
}
