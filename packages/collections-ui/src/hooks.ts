import { useEffect, useState } from "react";

/** State mirrored to localStorage, so a preference (e.g. list vs card view)
 * survives reloads. Falls back to in-memory state if storage is unavailable. */
export function usePersistentState(
  key: string,
  initial: string,
): [string, (value: string) => void] {
  const [value, setValue] = useState<string>(() => {
    try {
      return localStorage.getItem(key) ?? initial;
    } catch {
      return initial;
    }
  });
  const set = (next: string) => {
    setValue(next);
    try {
      localStorage.setItem(key, next);
    } catch {
      /* ignore: private mode / disabled storage */
    }
  };
  return [value, set];
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
