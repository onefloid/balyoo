// Card (tile) presentation is schema-driven. A collection may declare an optional
// `x-card` block in its JSON Schema to choose what each tile shows; when absent we
// derive a sensible layout from the schema. `x-card` is a custom keyword, ignored
// by JSON Schema validators, so it never affects data validation.
//
//   "x-card": {
//     "title": "title",          // property shown as the tile heading
//     "subtitle": "author",      // optional secondary line
//     "image": "cover",          // optional property holding an image URL
//     "badges": ["tags"],        // optional: fields rendered as chips
//     "fields": ["year", "pages"]// optional: key/value rows on the tile
//   }

import type { JsonSchema } from "./types";

export interface CardConfig {
  /** Property name for the heading, or the sentinel "id" to use the item id. */
  title: string;
  subtitle?: string;
  image?: string;
  badges: string[];
  fields: string[];
}

interface RawCard {
  title?: unknown;
  subtitle?: unknown;
  image?: unknown;
  badges?: unknown;
  fields?: unknown;
}

const IMAGE_HINTS = ["image", "cover", "thumbnail", "photo", "picture"];

type Props = Record<string, { type?: string }>;

function properties(schema: JsonSchema): Props {
  const p = schema.properties;
  return p && typeof p === "object" ? (p as Props) : {};
}

const asStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];

const asName = (value: unknown, names: string[]): string | undefined =>
  typeof value === "string" && names.includes(value) ? value : undefined;

/** Resolve the tile layout for a collection: explicit `x-card` or a derived default. */
export function resolveCardConfig(schema: JsonSchema): CardConfig {
  const props = properties(schema);
  const names = Object.keys(props);
  const raw = schema["x-card"];
  return raw && typeof raw === "object"
    ? fromExplicit(raw as RawCard, props, names)
    : fromSchema(props, names);
}

function fromExplicit(raw: RawCard, props: Props, names: string[]): CardConfig {
  const fallback = fromSchema(props, names);
  return {
    title: asName(raw.title, names) ?? fallback.title,
    subtitle: asName(raw.subtitle, names),
    image: asName(raw.image, names),
    badges: asStringArray(raw.badges).filter((n) => names.includes(n)),
    fields: asStringArray(raw.fields).filter((n) => names.includes(n)),
  };
}

function fromSchema(props: Props, names: string[]): CardConfig {
  const isType = (n: string, t: string) => props[n]?.type === t;
  const firstString = names.find((n) => isType(n, "string"));

  const title =
    (names.includes("title") && "title") ||
    (names.includes("name") && "name") ||
    firstString ||
    "id";
  const image = IMAGE_HINTS.find((h) => names.includes(h));
  const badges = names.filter((n) => isType(n, "array")).slice(0, 2);

  const used = new Set([title, image, ...badges].filter(Boolean) as string[]);
  const subtitle = names.find((n) => !used.has(n) && isType(n, "string"));
  if (subtitle) used.add(subtitle);

  const fields = names
    .filter((n) => !used.has(n) && !isType(n, "array") && !isType(n, "object"))
    .slice(0, 3);

  return { title, subtitle, image, badges, fields };
}
