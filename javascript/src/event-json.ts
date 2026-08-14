const MAX_EVENT_STRING_CHARS = 30_000;

/** Encode a bounded Pi event for JSONL logs and telemetry ingestion. */
export function eventJsonLine(event: unknown): string {
  return `${JSON.stringify(sanitizeEvent(event))}\n`;
}

/** Encode the public result without clipping the user's final deliverable. */
export function resultJsonLine(result: unknown): string {
  return `${JSON.stringify({ type: "browser_use_js_result", result })}\n`;
}

function sanitizeEvent(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitizeEvent);
  if (!value || typeof value !== "object") {
    return typeof value === "string" && value.length > MAX_EVENT_STRING_CHARS
      ? `${value.slice(0, MAX_EVENT_STRING_CHARS)}... <${value.length - MAX_EVENT_STRING_CHARS} chars omitted>`
      : value;
  }
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    result[key] = key === "data" && typeof item === "string" && item.length > 10_000
      ? `<image:${item.length} chars>`
      : sanitizeEvent(item);
  }
  return result;
}
