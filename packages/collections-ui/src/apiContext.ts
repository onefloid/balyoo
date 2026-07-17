import { createContext, useContext } from "react";

import type { ApiClient } from "./api";

const ApiContext = createContext<ApiClient | null>(null);

export const ApiProvider = ApiContext.Provider;

export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (!client) throw new Error("useApi must be used within an ApiProvider");
  return client;
}
