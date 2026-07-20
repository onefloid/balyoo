import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";

import { App } from "./App";
import { DataSourceProvider } from "./dataSource";
import { loadConfig } from "./config";
import "./styles.css";

async function bootstrap() {
  const config = await loadConfig();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <DataSourceProvider config={config}>
        <HashRouter>
          <App />
        </HashRouter>
      </DataSourceProvider>
    </StrictMode>,
  );
}

void bootstrap();
