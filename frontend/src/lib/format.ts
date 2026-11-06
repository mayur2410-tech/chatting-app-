/**
 * All dates and times in the app are shown in India Standard Time (IST, UTC+05:30) with a
 * 12-hour clock, regardless of the device's own time zone.
 */
export const APP_TIME_ZONE = "Asia/Kolkata";

const timeFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: APP_TIME_ZONE,
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});
const dayKeyFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: APP_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const dayLabelFormatter = new Intl.DateTimeFormat("en-IN", {
  timeZone: APP_TIME_ZONE,
  weekday: "short",
  day: "numeric",
  month: "short",
});
const dateFormatter = new Intl.DateTimeFormat("en-IN", {
  timeZone: APP_TIME_ZONE,
  day: "numeric",
  month: "short",
});
const dateWithYearFormatter = new Intl.DateTimeFormat("en-IN", {
  timeZone: APP_TIME_ZONE,
  day: "numeric",
  month: "short",
  year: "numeric",
});

const DAY_MS = 86_400_000;

/** e.g. "3:45 PM" (IST). */
export function formatTime(ts: number): string {
  return timeFormatter.format(ts);
}

/** Calendar day in IST as "YYYY-MM-DD", for comparing days. */
function dayKey(ts: number): string {
  return dayKeyFormatter.format(ts);
}

export function isSameDay(a: number, b: number): boolean {
  return dayKey(a) === dayKey(b);
}

/** "Today", "Yesterday", or e.g. "Mon, 3 Nov" (IST). IST has no daylight saving, so 24 h steps are exact. */
export function formatDayLabel(ts: number, now = Date.now()): string {
  const key = dayKey(ts);
  if (key === dayKey(now)) return "Today";
  if (key === dayKey(now - DAY_MS)) return "Yesterday";
  return dayLabelFormatter.format(ts);
}

/**
 * WhatsApp-style last seen, IST, 12-hour:
 * "last seen today at 3:45 PM", "last seen yesterday at 9:10 PM",
 * "last seen 28 Oct at 11:02 AM", "last seen 14 Dec 2025 at 8:00 AM".
 */
export function formatLastSeen(ts: number, now = Date.now()): string {
  const key = dayKey(ts);
  const time = formatTime(ts);
  if (key === dayKey(now)) return `last seen today at ${time}`;
  if (key === dayKey(now - DAY_MS)) return `last seen yesterday at ${time}`;
  const sameYear = key.slice(0, 4) === dayKey(now).slice(0, 4);
  return `last seen ${(sameYear ? dateFormatter : dateWithYearFormatter).format(ts)} at ${time}`;
}
