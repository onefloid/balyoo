import { Link } from "react-router-dom";

/** Render an arbitrary item value as a table/detail cell string (ported from the
 * previous vanilla UI). */
export function formatCell(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function Loading() {
  return <p className="muted">Loading…</p>;
}

export function ErrorBox({ error }: { error: Error }) {
  return <p className="error">Failed to load: {error.message}</p>;
}

export function ReadOnlyBadge({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span className="badge" title="This deployment is read-only">
      read-only
    </span>
  );
}

export type Crumb = { label: string; to?: string };

export function Breadcrumb({ parts }: { parts: Crumb[] }) {
  return (
    <div className="breadcrumb">
      {parts.map((part, i) => (
        <span key={i}>
          {i > 0 && " / "}
          {part.to ? <Link to={part.to}>{part.label}</Link> : part.label}
        </span>
      ))}
    </div>
  );
}
