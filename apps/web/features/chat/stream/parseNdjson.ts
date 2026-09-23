export type StreamEvent = {
  protocol_version: string;
  sequence: number;
  event_id: string;
  type: string;
  occurred_at: string;
  conversation_id: string;
  run_id: string;
  data: Record<string, unknown>;
};

export type ParseResult =
  | { kind: "event"; event: StreamEvent }
  | { kind: "invalid"; reason: string }
  | { kind: "protocol"; reason: string };

const SUPPORTED_MAJOR = "1";

export async function* parseNdjson(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
): AsyncGenerator<ParseResult> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  const onAbort = () => {
    void reader.cancel().catch(() => {});
  };
  signal.addEventListener("abort", onAbort, { once: true });
  try {
    while (true) {
      if (signal.aborted) return;
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch {
        if (signal.aborted) return;
        yield { kind: "invalid", reason: "stream read failed" };
        return;
      }
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      let newline = buffer.indexOf("\n");
      while (newline !== -1) {
        const line = buffer.slice(0, newline).replace(/\r$/, "");
        buffer = buffer.slice(newline + 1);
        if (line.trim().length > 0) {
          yield parseLine(line);
        }
        newline = buffer.indexOf("\n");
      }
    }
    buffer += decoder.decode();
    const tail = buffer.replace(/\r$/, "");
    if (tail.trim().length > 0) {
      yield parseLine(tail);
    }
  } finally {
    signal.removeEventListener("abort", onAbort);
    try {
      reader.releaseLock();
    } catch {
      // Reader already released by cancellation.
    }
  }
}

function parseLine(line: string): ParseResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(line);
  } catch {
    return { kind: "invalid", reason: "line is not valid JSON" };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { kind: "invalid", reason: "envelope is not an object" };
  }
  const envelope = parsed as Partial<StreamEvent>;
  if (typeof envelope.protocol_version !== "string") {
    return { kind: "invalid", reason: "missing protocol_version" };
  }
  const [major] = envelope.protocol_version.split(".");
  if (major !== SUPPORTED_MAJOR) {
    return {
      kind: "protocol",
      reason: `unsupported protocol major version ${envelope.protocol_version}`,
    };
  }
  if (
    typeof envelope.sequence !== "number" ||
    typeof envelope.event_id !== "string" ||
    typeof envelope.type !== "string" ||
    typeof envelope.occurred_at !== "string" ||
    typeof envelope.conversation_id !== "string" ||
    typeof envelope.run_id !== "string" ||
    typeof envelope.data !== "object" ||
    envelope.data === null
  ) {
    return { kind: "invalid", reason: "envelope is missing required fields" };
  }
  return { kind: "event", event: envelope as StreamEvent };
}
