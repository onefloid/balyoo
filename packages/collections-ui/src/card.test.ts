import { describe, expect, it } from "vitest";

import { resolveCardConfig } from "./card";

describe("resolveCardConfig", () => {
  it("uses an explicit x-card block", () => {
    const config = resolveCardConfig({
      properties: {
        title: { type: "string" },
        author: { type: "string" },
        year: { type: "integer" },
        tags: { type: "array" },
      },
      "x-card": {
        title: "title",
        subtitle: "author",
        badges: ["tags"],
        fields: ["year"],
      },
    });
    expect(config).toEqual({
      defaultView: "list",
      title: "title",
      subtitle: "author",
      image: undefined,
      badges: ["tags"],
      fields: ["year"],
    });
  });

  it("reads the default view from x-card, defaulting to list", () => {
    const props = { properties: { title: { type: "string" } } };
    expect(resolveCardConfig({ ...props, "x-card": { default: "cards" } }).defaultView).toBe(
      "cards",
    );
    expect(resolveCardConfig({ ...props, "x-card": { default: "list" } }).defaultView).toBe(
      "list",
    );
    // Unknown/absent -> list.
    expect(resolveCardConfig({ ...props, "x-card": {} }).defaultView).toBe("list");
    expect(resolveCardConfig(props).defaultView).toBe("list");
  });

  it("drops x-card references to unknown properties", () => {
    const config = resolveCardConfig({
      properties: { title: { type: "string" } },
      "x-card": { title: "nope", badges: ["ghost"], fields: ["missing"] },
    });
    expect(config.title).toBe("title"); // falls back to a real property
    expect(config.badges).toEqual([]);
    expect(config.fields).toEqual([]);
  });

  it("derives a sensible layout when x-card is absent", () => {
    const config = resolveCardConfig({
      properties: {
        title: { type: "string" },
        author: { type: "string" },
        year: { type: "integer" },
        pages: { type: "integer" },
        tags: { type: "array" },
      },
    });
    expect(config.title).toBe("title");
    expect(config.subtitle).toBe("author"); // next string field
    expect(config.badges).toEqual(["tags"]); // array fields become chips
    expect(config.fields).toEqual(["year", "pages"]); // remaining scalars
  });

  it("falls back to the first string field, then to the item id", () => {
    expect(resolveCardConfig({ properties: { label: { type: "string" } } }).title).toBe(
      "label",
    );
    expect(resolveCardConfig({ properties: { count: { type: "integer" } } }).title).toBe(
      "id",
    );
    expect(resolveCardConfig({}).title).toBe("id");
  });
});
