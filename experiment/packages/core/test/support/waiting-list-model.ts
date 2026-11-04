import type { PromotionMode } from "../../src/proposal-category.js";

export interface View {
  readonly seated: readonly number[];
  readonly offered: readonly number[];
  readonly queue: readonly number[];
}

export class Model {
  seated: number[] = [];
  offered: number[] = [];
  queue: number[] = [];

  private readonly limit: number;
  private readonly mode: PromotionMode;

  constructor(limit: number, mode: PromotionMode) {
    this.limit = limit;
    this.mode = mode;
  }

  has(user: number): boolean {
    return [...this.seated, ...this.offered, ...this.queue].includes(user);
  }

  full(): boolean {
    return this.seated.length + this.offered.length >= this.limit;
  }

  refill(): void {
    while (!this.full() && this.queue.length > 0) {
      const [next, ...rest] = this.queue;
      this.queue = rest;

      if (next !== undefined) {
        (this.mode === "auto" ? this.seated : this.offered).push(next);
      }
    }
  }

  view(): View {
    return {
      offered: this.offered.toSorted((a, b) => a - b),
      queue: this.queue,
      seated: this.seated.toSorted((a, b) => a - b),
    };
  }
}
