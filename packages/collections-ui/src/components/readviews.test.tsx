import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "../App";
import type { ApiClient } from "../api";
import { ApiProvider } from "../apiContext";
import type { Capabilities } from "../types";

const readOnlyCaps: Capabilities = {
  supports_read: true,
  supports_write: false,
  supports_delete: false,
  supports_search: true,
  supports_transactions: false,
};

const fake: ApiClient = {
  canWrite: false,
  listCollections: async () => [
    { name: "books", capabilities: readOnlyCaps, item_count: 2 },
  ],
  getCollection: async () => ({
    name: "books",
    capabilities: readOnlyCaps,
    item_count: 2,
  }),
  getSchema: async () => ({
    title: "Book",
    properties: { title: { type: "string" }, author: { type: "string" } },
  }),
  listItems: async () => ({
    items: [
      { id: "dune", data: { title: "Dune", author: "Herbert" } },
      { id: "lotr", data: { title: "The Lord of the Rings", author: "Tolkien" } },
    ],
    total: 2,
    limit: 2,
    offset: 0,
  }),
  getItem: async (_c, id) => ({ id, data: { title: "Dune" } }),
  createItem: async () => {
    throw new Error("unsupported");
  },
  updateItem: async () => {
    throw new Error("unsupported");
  },
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

describe("read views", () => {
  it("shows collections and a read-only badge for a read-only deployment", async () => {
    renderAt("/");
    expect(await screen.findByText("books")).toBeInTheDocument();
    expect(screen.getByText("read-only")).toBeInTheDocument();
  });

  it("lists items and filters them with the client-side search box", async () => {
    renderAt("/c/books");
    expect(await screen.findByText("Dune")).toBeInTheDocument();
    expect(screen.getByText("The Lord of the Rings")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "lord" } });

    expect(screen.queryByText("Dune")).not.toBeInTheDocument();
    expect(screen.getByText("The Lord of the Rings")).toBeInTheDocument();
  });
});
