import { ClientError } from "./client";
import { parseNdjson, type ParseResult } from "../stream/parseNdjson";

export type StartResponseOptions = {
  conversationId: string;
  content: string;
  clientMessageId: string;
  idempotencyKey: string;
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  signal: AbortSignal;
  onResult: (result: ParseResult) => void;
};

function requestIdempotencyKey(): string {
  return crypto.randomUUID();
}

export async function startResponse(
  options: StartResponseOptions,
): Promise<void> {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const response = await fetchImpl(
    `${options.baseUrl ?? ""}/v1/conversations/${options.conversationId}/responses`,
    {
      method: "POST",
      headers: {
        Accept: "application/x-ndjson",
        "Content-Type": "application/json",
        "Idempotency-Key": options.idempotencyKey ?? requestIdempotencyKey(),
      },
      body: JSON.stringify({
        client_message_id: options.clientMessageId,
        content: options.content,
      }),
      signal: options.signal,
    },
  );
  if (!response.ok) {
    let code = "internal_error";
    let diagnosticId: string | null = null;
    let title = "Request failed";
    try {
      const problem = (await response.json()) as {
        code?: string;
        diagnostic_id?: string;
        title?: string;
      };
      code = problem.code ?? code;
      diagnosticId = problem.diagnostic_id ?? null;
      title = problem.title ?? title;
    } catch {
      // Non-JSON error body.
    }
    throw new ClientError(response.status, code, title, diagnosticId);
  }
  if (response.body === null) {
    throw new ClientError(
      response.status,
      "stream_protocol_error",
      "Empty stream",
      null,
    );
  }
  for await (const result of parseNdjson(response.body, options.signal)) {
    options.onResult(result);
  }
}
