import { ClientError, problemFromResponse } from "./client";
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
        "Idempotency-Key": options.idempotencyKey,
      },
      body: JSON.stringify({
        client_message_id: options.clientMessageId,
        content: options.content,
      }),
      signal: options.signal,
    },
  );
  if (!response.ok) {
    throw await problemFromResponse(response);
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

export async function followResponse(options: {
  runId: string;
  afterSequence: number;
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  signal: AbortSignal;
  onResult: (result: ParseResult) => void;
}): Promise<void> {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const response = await fetchImpl(
    `${options.baseUrl ?? ""}/v1/response-runs/${options.runId}/stream`,
    {
      method: "POST",
      headers: {
        Accept: "application/x-ndjson",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ after_sequence: options.afterSequence }),
      signal: options.signal,
    },
  );
  if (!response.ok) {
    throw await problemFromResponse(response, "Follow failed");
  }
  if (response.body === null) return;
  for await (const result of parseNdjson(response.body, options.signal)) {
    options.onResult(result);
  }
}
