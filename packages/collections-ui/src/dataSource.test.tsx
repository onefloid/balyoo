import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useApi } from "./apiContext";
import { DataSourceProvider, useDataSource } from "./dataSource";
import {
  DataSourceBanner,
  DataSourceControls,
} from "./components/DataSourceControls";
import type { AppConfig } from "./config";
import type { CollectionInfo } from "./types";

const caps = {
  supports_read: true,
  supports_write: false,
  supports_delete: false,
  supports_search: true,
  supports_transactions: true,
};
// Two collections live, one in the static mirror — so the rendered count tells
// us which source actually served the data.
const live: CollectionInfo[] = [
  { name: "books", capabilities: caps, item_count: 2 },
  { name: "movies", capabilities: caps, item_count: 2 },
];
const mirror: CollectionInfo[] = [{ name: "books", capabilities: caps, item_count: 2 }];

const dualConfig: AppConfig = {
  apiBase: "https://balyoo.fly.dev/",
  static: false,
  staticBase: "api/",
};

/** Fetch stub: `.json` paths are the static mirror; everything else is live. */
function stubFetch({ liveOk }: { liveOk: boolean }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (String(url).includes(".json")) {
        return { ok: true, status: 200, json: async () => mirror };
      }
      if (!liveOk) throw new TypeError("network down");
      return { ok: true, status: 200, json: async () => live };
    }),
  );
}

function Harness() {
  const api = useApi();
  const { mode } = useDataSource();
  const [count, setCount] = useState<string>("loading");
  useEffect(() => {
    let active = true;
    api.listCollections().then(
      (cs) => active && setCount(String(cs.length)),
      () => active && setCount("error"),
    );
    return () => {
      active = false;
    };
  }, [api]);
  return (
    <>
      <DataSourceControls />
      <DataSourceBanner />
      <div data-testid="mode">{mode}</div>
      <div data-testid="count">{count}</div>
    </>
  );
}

function renderDual() {
  return render(
    <DataSourceProvider config={dualConfig}>
      <Harness />
    </DataSourceProvider>,
  );
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("DataSourceProvider (dual mode)", () => {
  it("defaults to live and shows no banner when live works", async () => {
    stubFetch({ liveOk: true });
    renderDual();
    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("2"));
    expect(screen.getByTestId("mode").textContent).toBe("live");
    expect(screen.queryByText(/Retry live/)).toBeNull();
  });

  it("falls back to the static mirror and shows the notice when live is unreachable", async () => {
    stubFetch({ liveOk: false });
    renderDual();
    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("1"));
    expect(screen.getByTestId("mode").textContent).toBe("static");
    expect(screen.getByText(/unreachable/i)).toBeTruthy();
  });

  it("switches source when the user picks Static", async () => {
    stubFetch({ liveOk: true });
    renderDual();
    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("2"));

    fireEvent.click(screen.getByRole("button", { name: "Static" }));
    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("1"));
    expect(screen.getByTestId("mode").textContent).toBe("static");
    // A deliberate static choice is not a fallback, so no notice.
    expect(screen.queryByText(/unreachable/i)).toBeNull();
  });

  it("retries live from the fallback notice", async () => {
    stubFetch({ liveOk: false });
    renderDual();
    await waitFor(() => expect(screen.getByText(/unreachable/i)).toBeTruthy());

    // Live recovers, then the user retries.
    stubFetch({ liveOk: true });
    fireEvent.click(screen.getByRole("button", { name: "Retry live" }));
    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("2"));
    expect(screen.getByTestId("mode").textContent).toBe("live");
    expect(screen.queryByText(/unreachable/i)).toBeNull();
  });
});

describe("DataSourceProvider (single mode)", () => {
  it("renders no source toggle for a pure static deployment", async () => {
    stubFetch({ liveOk: true });
    render(
      <DataSourceProvider config={{ apiBase: "api/", static: true }}>
        <Harness />
      </DataSourceProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("1"));
    expect(screen.queryByRole("button", { name: "Live" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Static" })).toBeNull();
  });
});
