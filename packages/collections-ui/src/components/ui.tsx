import type { CSSProperties } from "react";
import { Link } from "react-router-dom";

/** Render an arbitrary item value as a table/detail cell string (ported from the
 * previous vanilla UI). */
export function formatCell(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Deterministic hue (0–359) from a string, so a given label/name always gets the
 * same accent colour — used to give tags and collection avatars tasteful variety. */
export function hueFor(value: string): number {
  let h = 0;
  for (let i = 0; i < value.length; i++) h = (h * 31 + value.charCodeAt(i)) % 360;
  return h;
}

const hueStyle = (value: string) => ({ "--h": hueFor(value) }) as CSSProperties;

/** A coloured pill; its hue is derived from the label. */
export function Chip({ label }: { label: string }) {
  return (
    <span className="chip" style={hueStyle(label)}>
      {label}
    </span>
  );
}

/** A small collection avatar: a schema-provided emoji icon, else a coloured
 * monogram. An optional hex `color` overrides the name-derived hue. */
export function Avatar({
  name,
  icon,
  color,
}: {
  name: string;
  icon?: string;
  color?: string;
}) {
  const style: CSSProperties = color ? { background: color } : hueStyle(name);
  if (icon) {
    return (
      <span className="avatar avatar-icon" style={style} aria-hidden="true">
        {icon}
      </span>
    );
  }
  const initial = name.trim().charAt(0).toUpperCase() || "?";
  return (
    <span className="avatar" style={style} aria-hidden="true">
      {initial}
    </span>
  );
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
