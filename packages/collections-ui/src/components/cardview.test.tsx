import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { App } from "../App";
import type { ApiClient } from "../api";
import { ApiProvider } from "../apiContext";
import type { Capabilities } from "../types";

const caps: Capabilities = {
  supports_read: true,
  supports_write: false,
  supports_delete: false,
  supports_search: true,
  supports_transactions: false,
};

const fake: ApiClient = {
  canWrite: false,
  listCollections: async () => [{ name: "books", capabilities: caps, item_count: 1 }],
  getCollection: async () => ({ name: "books", capabilities: caps, item_count: 1 }),
  getSchema: async () => ({
    title: "Book",
    properties: {
      title: { type: "string" },
      author: { type: "string" },
      year: { type: "integer" },
      tags: { type: "array" },
    },
    "x-card": {
      default: "cards",
      title: "title",
      subtitle: "author",
      badges: ["tags"],
      fields: ["year"],
    },
  }),
  listItems: async () => ({
    items: [
      { id: "dune", data: { title: "Dune", author: "Herbert", year: 1965, tags: ["sci-fi"] } },
    ],
    total: 1,
    limit: 1,
    offset: 0,
  }),
  getItem: async (_c, id) => ({ id, data: { title: "Dune" } }),
  createItem: async () => ({ id: "x", data: {} }),
  updateItem: async () => ({ id: "x", data: {} }),
  deleteItem: async () => {},
};

function renderAt(path: string) {
  return render(
    <ApiProvider value={fake}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </ApiProvider>,
  );
}

afterEach(() => localStorage.clear());

describe("card view", () => {
  it("opens in the schema's default view (cards) with schema-driven tile content", async () => {
    renderAt("/c/books");
    const card = await screen.findByRole("link", { name: /Dune/ });
    expect(screen.queryByRole("table")).not.toBeInTheDocument(); // default is cards
    expect(within(card).getByText("Dune")).toBeInTheDocument(); // title
    expect(within(card).getByText("Herbert")).toBeInTheDocument(); // subtitle
    expect(within(card).getByText("sci-fi")).toBeInTheDocument(); // badge from tags
    expect(within(card).getByText("1965")).toBeInTheDocument(); // field value
  });

  it("toggles to the list (table) view", async () => {
    renderAt("/c/books");
    await screen.findByRole("link", { name: /Dune/ });
    fireEvent.click(screen.getByRole("button", { name: "List" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });

  it("navigates to the detail page when a card is clicked", async () => {
    renderAt("/c/books");
    fireEvent.click(await screen.findByRole("link", { name: /Dune/ }));
    // Detail page heading is the item id.
    expect(await screen.findByRole("heading", { name: "dune" })).toBeInTheDocument();
  });

  it("remembers a user override per collection, beating the schema default", async () => {
    const first = renderAt("/c/books");
    // Schema default is cards; user switches to list.
    fireEvent.click(await first.findByRole("button", { name: "List" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    first.unmount();

    renderAt("/c/books");
    // The stored "list" choice wins over the schema's "cards" default.
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });
});
