// A run's steps in compact lines: the argument a step's line previews, how a block folds, and what its folded line
// says (UX-043, ADR-0140).
import { describe, expect, it } from "vitest";

import { folded, previewOf, tally } from "../../../src/web/src/steps";

describe("previewOf", () => {
  it("shows the argument that tells a call apart", () => {
    expect(previewOf("web_search", { query: "tomato blight" })).toBe("tomato blight");
    expect(previewOf("read_page", { url: "https://example.org/garden" })).toBe("https://example.org/garden");
    expect(previewOf("browser_goto", { url: "https://example.org/a", wait_until: "load" })).toBe("https://example.org/a");
    expect(previewOf("read_file", { path: "/workspace/notes.md", offset: 3 })).toBe("/workspace/notes.md");
    expect(previewOf("browser_fill", { selector: "#q", value: "Riverside" })).toBe("Riverside");
    expect(previewOf("browser_click", { selector: "button.search" })).toBe("button.search");
  });

  it("shows a long address by its host", () => {
    const long = `https://shop.example.com/it/campaign/black-friday?${"tracking=abc&".repeat(10)}`;
    expect(previewOf("browser_goto", { url: long })).toBe("shop.example.com");
  });

  it("shows a command's first line", () => {
    expect(previewOf("run_command", { command: "ls -la\necho more", description: "Look around" })).toBe("ls -la");
  });

  it("never shows a script", () => {
    expect(previewOf("browser_evaluate", { script: "(() => { const links = [...document.links]; })()" })).toBe("");
    expect(previewOf("browser_run", { script: "const page = new Page();" })).toBe("");
  });

  it("falls back to the first argument that is a string", () => {
    expect(previewOf("garden__plant", { count: 3, crop: "basil" })).toBe("basil");
    expect(previewOf("garden__water", { litres: 2 })).toBe("");
  });
});

describe("folded", () => {
  const steps = ["a", "b", "c", "d", "e"];

  it("shows every step of a short block", () => {
    expect(folded(["a", "b", "c"], { running: false, open: false })).toEqual({ hidden: 0, shown: ["a", "b", "c"] });
  });

  it("folds a long block once the answer has ended", () => {
    expect(folded(steps, { running: false, open: false })).toEqual({ hidden: 5, shown: [] });
  });

  it("shows the last three steps of a long block while the run works", () => {
    expect(folded(steps, { running: true, open: false })).toEqual({ hidden: 2, shown: ["c", "d", "e"] });
  });

  it("shows every step of an opened block", () => {
    expect(folded(steps, { running: false, open: true })).toEqual({ hidden: 0, shown: steps });
    expect(folded(steps, { running: true, open: true })).toEqual({ hidden: 0, shown: steps });
  });
});

describe("tally", () => {
  it("counts each label in the order it first came", () => {
    expect(tally(["Searched the web", "Reasoning", "Used the browser", "Searched the web", "Used the browser"])).toEqual([
      { label: "Searched the web", count: 2 },
      { label: "Reasoning", count: 1 },
      { label: "Used the browser", count: 2 },
    ]);
  });
});
