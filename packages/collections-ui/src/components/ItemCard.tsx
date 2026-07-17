import { Link } from "react-router-dom";

import type { CardConfig } from "../card";
import type { Item } from "../types";
import { formatCell } from "./ui";

function badgeValues(item: Item, fields: string[]): string[] {
  const chips: string[] = [];
  for (const field of fields) {
    const value = item.data[field];
    if (Array.isArray(value)) {
      for (const v of value) if (v != null && v !== "") chips.push(String(v));
    } else if (value != null && value !== "") {
      chips.push(formatCell(value));
    }
  }
  return chips;
}

export function ItemCard({
  collection,
  item,
  config,
}: {
  collection: string;
  item: Item;
  config: CardConfig;
}) {
  const title =
    config.title === "id" ? item.id : formatCell(item.data[config.title]) || item.id;
  const subtitle = config.subtitle ? formatCell(item.data[config.subtitle]) : "";
  const image = config.image ? item.data[config.image] : undefined;
  const imageUrl = typeof image === "string" && image ? image : undefined;
  const badges = badgeValues(item, config.badges);
  const fields = config.fields
    .map((name) => ({ name, value: formatCell(item.data[name]) }))
    .filter((f) => f.value !== "");

  return (
    <Link
      className="item-card"
      to={`/c/${encodeURIComponent(collection)}/${encodeURIComponent(item.id)}`}
    >
      {imageUrl && (
        <div className="item-card-thumb">
          <img src={imageUrl} alt="" loading="lazy" />
        </div>
      )}
      <div className="item-card-body">
        <div className="item-card-title">{title}</div>
        {subtitle && <div className="item-card-subtitle">{subtitle}</div>}
        {badges.length > 0 && (
          <div className="item-card-badges">
            {badges.map((b, i) => (
              <span key={i} className="chip">
                {b}
              </span>
            ))}
          </div>
        )}
        {fields.length > 0 && (
          <dl className="item-card-fields">
            {fields.map((f) => (
              <div key={f.name} className="item-card-field">
                <dt>{f.name}</dt>
                <dd>{f.value}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </Link>
  );
}
