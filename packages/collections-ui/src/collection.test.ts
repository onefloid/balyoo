import { describe, expect, it } from "vitest";

import { resolveCollectionMeta } from "./collection";

describe("resolveCollectionMeta", () => {
  it("reads icon and a hex colour from x-collection", () => {
    expect(
      resolveCollectionMeta({ "x-collection": { icon: "📚", color: "#4f46e5" } }),
    ).toEqual({ icon: "📚", color: "#4f46e5" });
  });

  it("accepts short hex and ignores case", () => {
    expect(resolveCollectionMeta({ "x-collection": { color: "#ABC" } }).color).toBe(
      "#ABC",
    );
  });

  it("rejects a non-hex colour (CSS-injection safe)", () => {
    expect(
      resolveCollectionMeta({ "x-collection": { color: "red; background:url(x)" } })
        .color,
    ).toBeUndefined();
    expect(resolveCollectionMeta({ "x-collection": { color: "rebeccapurple" } }).color)
      .toBeUndefined();
  });

  it("returns empty when x-collection is missing or malformed", () => {
    expect(resolveCollectionMeta({})).toEqual({});
    expect(resolveCollectionMeta({ "x-collection": "nope" })).toEqual({});
    expect(resolveCollectionMeta({ "x-collection": { icon: "  " } })).toEqual({});
  });
});
