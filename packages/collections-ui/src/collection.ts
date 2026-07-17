// Collection-level presentation is schema-driven too: an optional `x-collection`
// block sets the home-page icon (an emoji) and an accent colour. Like `x-card`, it
// is a custom keyword ignored by JSON Schema validators.
//
//   "x-collection": { "icon": "📚", "color": "#4f46e5" }

import type { JsonSchema } from "./types";

export interface CollectionMeta {
  /** An emoji shown in place of the auto-generated monogram. */
  icon?: string;
  /** Accent colour for the avatar, restricted to a hex value (CSS-injection safe). */
  color?: string;
}

const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

export function resolveCollectionMeta(schema: JsonSchema): CollectionMeta {
  const raw = schema["x-collection"];
  if (!raw || typeof raw !== "object") return {};
  const r = raw as { icon?: unknown; color?: unknown };
  return {
    icon: typeof r.icon === "string" && r.icon.trim() ? r.icon.trim() : undefined,
    // Only accept a hex colour: it is interpolated into an inline style, so an
    // arbitrary string could otherwise inject CSS.
    color: typeof r.color === "string" && HEX.test(r.color) ? r.color : undefined,
  };
}
