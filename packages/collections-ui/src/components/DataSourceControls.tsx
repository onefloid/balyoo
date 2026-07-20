// The live/static source switch (shown in the header) and the fallback notice
// banner. Both render nothing unless the deployment is dual-source.

import { useDataSource } from "../dataSource";

/** Header control: a segmented Live/Static toggle plus a "live unavailable" hint. */
export function DataSourceControls() {
  const { dual, preference, fellBack, setPreference } = useDataSource();
  if (!dual) return null;

  return (
    <div className="source-controls">
      <div className="view-toggle" role="group" aria-label="Data source">
        <button
          type="button"
          className="btn"
          aria-pressed={preference === "live"}
          onClick={() => setPreference("live")}
        >
          Live
        </button>
        <button
          type="button"
          className="btn"
          aria-pressed={preference === "static"}
          onClick={() => setPreference("static")}
        >
          Static
        </button>
      </div>
      {fellBack && (
        <span className="badge badge-warn" title="The live server could not be reached">
          live unavailable
        </span>
      )}
    </div>
  );
}

/** Full-width notice shown when a live preference has fallen back to the mirror. */
export function DataSourceBanner() {
  const { fellBack, retryLive } = useDataSource();
  if (!fellBack) return null;

  return (
    <div className="notice" role="status">
      <span>
        The live data source is unreachable — showing the bundled static snapshot
        instead. It may be out of date.
      </span>
      <button type="button" className="btn" onClick={retryLive}>
        Retry live
      </button>
    </div>
  );
}
