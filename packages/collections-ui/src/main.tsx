import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";

import { App } from "./App";
import { makeClient } from "./api";
import { ApiProvider } from "./apiContext";
import { loadConfig } from "./config";
import "./styles.css";

async function bootstrap() {
  const config = await loadConfig();
  const client = makeClient(config);
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <ApiProvider value={client}>
        <HashRouter>
          <App />
        </HashRouter>
      </ApiProvider>
    </StrictMode>,
  );
}

void bootstrap();
