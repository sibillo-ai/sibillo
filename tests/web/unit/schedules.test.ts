// A task's schedule said in words, in the forms people use (UX-031, TSK-003, ADR-0109).
import { describe, expect, it } from "vitest";

import i18n from "../../../src/web/src/i18n";
import { describeSchedule } from "../../../src/web/src/schedules";

const t = i18n.getFixedT("en");
const words = (start: string, ...recurrence: string[]) => describeSchedule(t, "en", start, recurrence);

describe("describeSchedule", () => {
  it("says a schedule without a recurrence is once", () => {
    expect(words("2099-03-01T09:30")).toMatch(/^Once, on .*2099.* at 09:30$/);
  });

  it("says the nth weekday of every month, and how many times", () => {
    expect(words("2099-03-01T09:30", "RRULE:FREQ=MONTHLY;BYDAY=1MO;COUNT=2")).toBe(
      "At 09:30, on the first Monday of every month, 2 times",
    );
  });

  it("says every other week on a day, until a date", () => {
    expect(words("2099-03-01T09:30", "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=SA;UNTIL=20991231T235959Z")).toMatch(
      /^At 09:30, every 2 weeks on Saturday, until .+$/,
    );
  });

  it("says weekdays, and leaves a recurrence it does not know as written", () => {
    expect(words("2099-03-01T07:00", "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR")).toBe("At 07:00, Monday to Friday");
    expect(words("2099-03-01T07:00", "RRULE:FREQ=SECONDLY")).toBeNull();
    expect(words("not a date")).toBeNull();
  });
});
