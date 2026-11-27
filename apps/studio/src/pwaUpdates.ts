import { emitPwaServiceWorkerError } from "./pwaDiagnostics";

type UpdateWorker = () => Promise<void>;

export type PwaUpdateSnapshot = {
  visible: boolean;
  applying: boolean;
  error: boolean;
};

const HIDDEN: PwaUpdateSnapshot = { visible: false, applying: false, error: false };
const RETURN_CHECK_INTERVAL_MS = 60_000;
const ACTIVATION_TIMEOUT_MS = 15_000;

export class PwaUpdateController {
  private snapshot: PwaUpdateSnapshot = HIDDEN;
  private listeners = new Set<() => void>();
  private registration: ServiceWorkerRegistration | undefined;
  private updateWorker: UpdateWorker | undefined;
  private available = false;
  private deferred = false;
  private controllerChanged = false;
  private checking = false;
  private lastCheckAt = Number.NEGATIVE_INFINITY;
  private activationTimer: number | undefined;

  constructor(
    private readonly reloadPage: () => void = () => window.location.reload(),
    private readonly reportError: () => void = emitPwaServiceWorkerError,
  ) {}

  getSnapshot = (): PwaUpdateSnapshot => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private publish(next: PwaUpdateSnapshot) {
    this.snapshot = next;
    this.listeners.forEach((listener) => listener());
  }

  setRegistration(registration: ServiceWorkerRegistration | undefined) {
    this.registration = registration;
    if (registration?.waiting) this.announceAvailable();
  }

  setUpdateWorker(updateWorker: UpdateWorker) {
    this.updateWorker = updateWorker;
  }

  announceAvailable() {
    this.available = true;
    if (!this.deferred && !this.snapshot.applying) {
      this.publish({ visible: true, applying: false, error: false });
    }
  }

  defer() {
    if (this.snapshot.applying) return;
    this.deferred = true;
    this.publish(HIDDEN);
  }

  async apply() {
    if (!this.available || this.snapshot.applying) return;
    this.deferred = false;
    this.publish({ visible: true, applying: true, error: false });
    if (this.controllerChanged) {
      this.reloadPage();
      return;
    }
    if (!this.updateWorker) {
      this.publish({ visible: true, applying: false, error: true });
      return;
    }
    this.activationTimer = window.setTimeout(() => {
      this.activationTimer = undefined;
      if (this.snapshot.applying) {
        this.publish({ visible: true, applying: false, error: true });
      }
    }, ACTIVATION_TIMEOUT_MS);
    try {
      await this.updateWorker();
    } catch {
      this.clearActivationTimer();
      this.reportError();
      this.publish({ visible: true, applying: false, error: true });
    }
  }

  onControllerChange(isReplacement = true) {
    if (!isReplacement && !this.available) return;
    this.controllerChanged = true;
    this.available = true;
    this.clearActivationTimer();
    if (this.snapshot.applying) {
      this.reloadPage();
    } else if (!this.deferred) {
      this.publish({ visible: true, applying: false, error: false });
    }
  }

  async checkOnReturn() {
    if (document.visibilityState === "hidden") return;
    if (this.available || this.controllerChanged || this.registration?.waiting) {
      this.deferred = false;
      this.announceAvailable();
      return;
    }
    if (!this.registration || navigator.onLine === false || this.checking) return;
    const now = Date.now();
    if (now - this.lastCheckAt < RETURN_CHECK_INTERVAL_MS) return;
    this.lastCheckAt = now;
    this.checking = true;
    try {
      await this.registration.update();
      if (this.registration.waiting) this.announceAvailable();
    } catch {
      this.reportError();
    } finally {
      this.checking = false;
    }
  }

  private clearActivationTimer() {
    if (this.activationTimer !== undefined) window.clearTimeout(this.activationTimer);
    this.activationTimer = undefined;
  }
}

export const pwaUpdates = new PwaUpdateController();

export function installPwaReturnChecks(controller: PwaUpdateController = pwaUpdates) {
  const check = () => { void controller.checkOnReturn(); };
  window.addEventListener("focus", check);
  window.addEventListener("online", check);
  document.addEventListener("visibilitychange", check);
  return () => {
    window.removeEventListener("focus", check);
    window.removeEventListener("online", check);
    document.removeEventListener("visibilitychange", check);
  };
}
