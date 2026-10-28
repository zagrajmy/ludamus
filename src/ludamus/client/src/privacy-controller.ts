const readPrivacyRevision = (): string | undefined =>
  document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("ludamus.privacy="))
    ?.slice("ludamus.privacy=".length);

const STORAGE_KEY = "prologue.consent";

type Choice = "accepted" | "declined";
export type PrivacyState = "ineligible" | Choice | null;

type PrivacyOptions = {
  clear: () => Promise<void>;
  render: (state: PrivacyState) => void;
  revision: string | null;
  start: () => Promise<void>;
  stop: () => void;
};

export class PrivacyController {
  private readonly options: PrivacyOptions;
  private captureState: "failed" | "idle" | "loading" | "running" = "idle";
  private rendered: PrivacyState | undefined;
  private revoked = false;

  constructor(options: PrivacyOptions) {
    this.options = options;
  }

  private eligible(): boolean {
    return (
      !this.revoked &&
      this.options.revision !== null &&
      readPrivacyRevision() === this.options.revision
    );
  }

  private readChoice(revision: string | null = this.options.revision): Choice | null {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "declined") return "declined";
    if (!stored) return null;
    try {
      const record: unknown = JSON.parse(stored);
      if (typeof record !== "object" || record === null || !("choice" in record)) return null;
      if (record.choice === "declined") return "declined";
      if (
        record.choice === "accepted" &&
        "revision" in record &&
        typeof record.revision === "string" &&
        record.revision === revision
      ) {
        return "accepted";
      }
    } catch {
      return null;
    }
    return null;
  }

  canCapture = (): boolean => this.eligible() && this.readChoice() === "accepted";

  choose(choice: Choice): void {
    if (this.eligible()) {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ choice, revision: this.options.revision }),
      );
      if (this.captureState === "failed") this.captureState = "idle";
    }
    this.reconcile();
  }

  private reconcile = (): void => {
    if (this.revoked) return;
    const state = this.eligible() ? this.readChoice() : "ineligible";
    const newerAcceptance =
      state === "ineligible" && this.readChoice(readPrivacyRevision() ?? null) === "accepted";
    if (newerAcceptance) {
      this.revoked = true;
      this.options.render("ineligible");
      if (this.options.revision !== null) globalThis.location.reload();
      return;
    }
    if (state === "ineligible" || state === null) localStorage.removeItem(STORAGE_KEY);
    if (state !== "accepted" && this.captureState !== "idle") {
      this.options.stop();
      if (this.captureState !== "loading") this.captureState = "idle";
    }
    if (state === "ineligible") {
      this.revoked = true;
      void this.options.clear().catch((error: unknown) => {
        console.error("Optional analytics storage could not be cleared", error);
      });
    }
    if (state !== this.rendered) {
      this.rendered = state;
      this.options.render(state);
    }
    if (state !== "accepted" || this.captureState !== "idle") return;
    this.captureState = "loading";
    void this.options
      .start()
      .then(() => {
        if (this.revoked) return;
        this.captureState = "running";
        this.reconcile();
      })
      .catch((error: unknown) => {
        this.captureState = "failed";
        console.error("Optional analytics could not start", error);
      });
  };

  init(): void {
    this.reconcile();
    if (this.options.revision === null) return;
    globalThis.addEventListener("storage", (event) => {
      if (event.key === STORAGE_KEY || event.key === null) this.reconcile();
    });
    globalThis.cookieStore?.addEventListener("change", this.reconcile);
    globalThis.addEventListener("focus", this.reconcile);
    globalThis.addEventListener("pageshow", this.reconcile);
    document.addEventListener("visibilitychange", this.reconcile);
    globalThis.setInterval(this.reconcile, 500);
  }
}
