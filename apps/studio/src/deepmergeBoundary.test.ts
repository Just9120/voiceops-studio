import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const merge = require("deepmerge");

describe("installed deepmerge prototype boundary", () => {
  it.each(["null-target", "nested-null", "own-target", "own-source"])("keeps an ordinary result prototype for %s", (shape) => {
    const payload = JSON.parse('{"__proto__":{"voiceopsPoison":true}}');
    let target: Record<string, unknown> = Object.create(null);
    let source = payload;
    if (shape === "nested-null") {
      target = { nested: null };
      source = { nested: payload };
    } else if (shape === "own-target") {
      target = JSON.parse('{"__proto__":{"old":true}}');
    } else if (shape === "own-source") {
      target = {};
      Object.defineProperty(target, "__proto__", { value: null, enumerable: true });
    }
    const result = merge(target, source);
    const checked = shape === "nested-null" ? result.nested : result;
    expect(Object.getPrototypeOf(checked)).toBe(Object.prototype);
    expect(checked.voiceopsPoison).toBeUndefined();
    expect(({} as { voiceopsPoison?: boolean }).voiceopsPoison).toBeUndefined();
  });

  it("preserves nested objects, arrays, symbols, special values and custom merge", () => {
    const symbol = Symbol("plugin-default");
    const date = new Date("2026-11-04T00:00:00Z");
    const regex = /voiceops/i;
    const target = { nested: { one: true }, items: [1], date, regex, [symbol]: { enabled: true } };
    const source = { nested: { two: true }, items: [2] };
    expect(merge(target, source)).toEqual({ nested: { one: true, two: true }, items: [1, 2], date, regex, [symbol]: { enabled: true } });
    expect(merge(target, source, { arrayMerge: (_old: number[], next: number[]) => next }).items).toEqual([2]);
    expect(merge.all([{ nested: { one: 1 } }, { nested: { two: 2 } }], {
      customMerge: (key: string) => key === "nested" ? () => ({ custom: true }) : undefined,
    }).nested).toEqual({ custom: true });
    expect(target.nested).toEqual({ one: true });
  });
});
