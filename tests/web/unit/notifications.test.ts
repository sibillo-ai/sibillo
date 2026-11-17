// What the service worker makes of a push: only the kind and the identifiers, and the conversation it opens
// (UX-004, ADR-0101).
import { describe, expect, it } from "vitest";

import { notificationOf } from "../../../src/web/src/notifications";

const conversation = "0190b6a2-5d6c-7f00-8000-000000000001";
const run = "0190b6a2-5d6c-7f00-8000-000000000002";

describe("notificationOf", () => {
  it.each(["run_finished", "run_failed", "approval_pending", "question_pending"])("reads %s", (kind) => {
    expect(notificationOf({ kind, conversation_id: conversation, run_id: run })).toEqual({
      kind,
      tag: conversation,
      url: `/c/${conversation}`,
    });
  });

  it("refuses unknown kinds", () => {
    expect(notificationOf({ kind: "something", conversation_id: conversation, run_id: run })).toBeUndefined();
  });

  it("refuses identifiers that are not identifiers", () => {
    expect(notificationOf({ kind: "run_finished", conversation_id: "../settings", run_id: run })).toBeUndefined();
    expect(notificationOf({ kind: "run_finished", conversation_id: 3, run_id: run })).toBeUndefined();
  });

  it("refuses what is not a payload", () => {
    expect(notificationOf(null)).toBeUndefined();
    expect(notificationOf("run_finished")).toBeUndefined();
    expect(notificationOf({ kind: "run_finished" })).toBeUndefined();
  });
});
