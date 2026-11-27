import React from "react";
import ReactDOM from "react-dom/client";
import { registerSW } from "virtual:pwa-register";
import App from "./App";
import { RealtimeOverlay } from "./RealtimeOverlay";
import { PwaErrorBoundary } from "./PwaErrorBoundary";
import { PwaConnectivityNotice, PwaUpdateNotice } from "./PwaUpdateNotice";
import { emitPwaServiceWorkerError, installPwaGlobalErrorHandlers } from "./pwaDiagnostics";
import { installPwaReturnChecks, pwaUpdates } from "./pwaUpdates";
import { initializeStudioTheme } from "./theme";

let pwaRuntimeInitialized = false;
let appRendered = false;

export function initializePwaRuntime(enableServiceWorker = import.meta.env.PROD && "serviceWorker" in navigator) {
  installPwaGlobalErrorHandlers();
  if (pwaRuntimeInitialized || !enableServiceWorker) return;
  pwaRuntimeInitialized = true;
  const workers = navigator.serviceWorker;
  let previousController = workers?.controller ?? null;
  workers?.addEventListener("controllerchange", () => {
    const nextController = workers.controller;
    if (!nextController || nextController === previousController) return;
    const isReplacement = previousController !== null;
    previousController = nextController;
    pwaUpdates.onControllerChange(isReplacement);
  });
  const updateSW = registerSW({
    immediate: true,
    onNeedRefresh: () => pwaUpdates.announceAvailable(),
    // Prevent Workbox's default reload. Studio applies the user's choice on controllerchange.
    onNeedReload: () => {},
    onRegisteredSW: (_url, registration) => pwaUpdates.setRegistration(registration),
    onRegisterError: () => emitPwaServiceWorkerError(),
  });
  pwaUpdates.setUpdateWorker(updateSW);
  installPwaReturnChecks();
  navigator.serviceWorker?.addEventListener?.("messageerror", () => emitPwaServiceWorkerError());
}

export function renderStudioApp() {
  if (appRendered) return;
  const root = document.getElementById("root");
  if (!root) return;
  appRendered = true;
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <PwaErrorBoundary>
        <PwaConnectivityNotice />
        {window.location.pathname === "/realtime-overlay" ? <RealtimeOverlay /> : <App />}
        <PwaUpdateNotice />
      </PwaErrorBoundary>
    </React.StrictMode>,
  );
}

initializeStudioTheme();
initializePwaRuntime();
renderStudioApp();
