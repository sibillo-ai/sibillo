// What the app makes of a share from another app: the text of the message box, and whether a share is still
// offered (UX-006, ADR-0102).
import { describe, expect, it } from "vitest";

import { SHARE_LIFETIME_MS, isFresh, messageOf } from "../../../src/web/src/share";

describe("messageOf", () => {
  it("puts the title, the text and the link each on its own paragraph", () => {
    expect(messageOf({ title: "A recipe", text: "Try this one", url: "https://example.org/recipe" })).toBe(
      "A recipe\n\nTry this one\n\nhttps://example.org/recipe",
    );
  });

  it("leaves out empty parts", () => {
    expect(messageOf({ title: "", text: "  ", url: "https://example.org/" })).toBe("https://example.org/");
    expect(messageOf({ title: "", text: "", url: "" })).toBe("");
  });

  it("leaves out a part already contained in another", () => {
    // Android puts the link of a shared page in its text.
    expect(messageOf({ title: "A recipe", text: "A recipe https://example.org/recipe", url: "https://example.org/recipe" })).toBe(
      "A recipe https://example.org/recipe",
    );
    expect(messageOf({ title: "News", text: "https://example.org/news", url: "" })).toBe("News\n\nhttps://example.org/news");
  });

  it("trims each part", () => {
    expect(messageOf({ title: " Title ", text: "\nText\n", url: "" })).toBe("Title\n\nText");
  });
});

describe("isFresh", () => {
  const now = 1_800_000_000_000;

  it("offers a share for an hour", () => {
    expect(SHARE_LIFETIME_MS).toBe(60 * 60 * 1000);
    expect(isFresh(now - 1000, now)).toBe(true);
    expect(isFresh(now - SHARE_LIFETIME_MS + 1, now)).toBe(true);
  });

  it("discards an older share", () => {
    expect(isFresh(now - SHARE_LIFETIME_MS - 1, now)).toBe(false);
  });

  it("discards a share from the future, as from a clock moved back", () => {
    expect(isFresh(now + 60_000, now)).toBe(false);
  });
});
