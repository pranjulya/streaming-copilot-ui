import { ClientError } from "../api/client";
import type { ConversationClient, RunSnapshot } from "../api/client";
import { followResponse, startResponse } from "../api/stream";
import { parseNdjson } from "../stream/parseNdjson";
import type { ParseResult } from "../stream/parseNdjson";

export type TurnKind =
  | { kind: "create"; conversationId: string; content: string }
  | { kind: "retry"; runId: string }
  | { kind: "regenerate"; userMessageId: string };

export type StreamedTurn =
  | { outcome: "streamed" }
  | { outcome: "incomplete"; runId: string | null }
  | { outcome: "aborted" }
  | { outcome: "rejected"; error: unknown }
  | { outcome: "network-unknown"; error: unknown };

const TERMINAL_EVENTS = new Set([
  "response.completed",
  "response.cancelled",
  "response.failed",
]);

export function supportsStreaming(): boolean {
  if (
    typeof ReadableStream === "undefined" ||
    typeof Response === "undefined"
  ) {
    return false;
  }
  return (
    Object.getOwnPropertyDescriptor(Response.prototype, "body") !== undefined
  );
}

export function isUserAbort(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { name?: string }).name === "AbortError"
  );
}

export function isNetworkFailure(error: unknown): boolean {
  if (isUserAbort(error)) return false;
  if (error instanceof ClientError) return false;
  if (error instanceof TypeError) return true;
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { name?: string }).name === "NetworkError"
  );
}

export function busyActiveRunId(error: unknown): string | null {
  if (!(error instanceof ClientError) || error.code !== "conversation_busy")
    return null;
  const active = error.extensions.active_run_id;
  return typeof active === "string" ? active : null;
}

export function terminalStatus(status: string): boolean {
  return (
    status === "completed" || status === "cancelled" || status === "failed"
  );
}

export async function streamTurn(options: {
  client: ConversationClient;
  turn: TurnKind;
  clientMessageId: string;
  idempotencyKey: string;
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  signal: AbortSignal;
  onResult: (result: ParseResult) => void;
}): Promise<StreamedTurn> {
  const { turn } = options;
  let sawTerminal = false;
  let runId: string | null = turn.kind === "retry" ? turn.runId : null;
  const onResult = (result: ParseResult) => {
    if (result.kind === "event") {
      runId = result.event.run_id;
      if (TERMINAL_EVENTS.has(result.event.type)) sawTerminal = true;
    }
    options.onResult(result);
  };
  try {
    if (turn.kind === "create") {
      await startResponse({
        conversationId: turn.conversationId,
        content: turn.content,
        clientMessageId: options.clientMessageId,
        idempotencyKey: options.idempotencyKey,
        baseUrl: options.baseUrl,
        fetchImpl: options.fetchImpl,
        signal: options.signal,
        onResult,
      });
    } else {
      const path =
        turn.kind === "retry"
          ? `/v1/response-runs/${turn.runId}/retry`
          : `/v1/messages/${turn.userMessageId}/regenerations`;
      await streamFrom(
        `${options.baseUrl ?? ""}${path}`,
        options.idempotencyKey,
        options.fetchImpl,
        options.signal,
        onResult,
      );
    }
    if (!sawTerminal) {
      return { outcome: "incomplete", runId };
    }
    return { outcome: "streamed" };
  } catch (error) {
    if (isUserAbort(error)) {
      return { outcome: "aborted" };
    }
    if (isNetworkFailure(error)) {
      return { outcome: "network-unknown", error };
    }
    return { outcome: "rejected", error };
  }
}

async function streamFrom(
  url: string,
  idempotencyKey: string,
  fetchImpl: typeof fetch | undefined,
  signal: AbortSignal,
  onResult: (result: ParseResult) => void,
): Promise<void> {
  const doFetch = fetchImpl ?? globalThis.fetch.bind(globalThis);
  const response = await doFetch(url, {
    method: "POST",
    headers: {
      Accept: "application/x-ndjson",
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({}),
    signal,
  });
  if (!response.ok) {
    throw await problemFromResponse(response);
  }
  if (response.body === null) return;
  for await (const result of parseNdjson(response.body, signal)) {
    onResult(result);
  }
}

async function problemFromResponse(response: Response): Promise<ClientError> {
  let code = "internal_error";
  let diagnosticId: string | null = null;
  let extensions: Record<string, unknown> = {};
  try {
    const problem = (await response.json()) as {
      code?: string;
      diagnostic_id?: string;
      [key: string]: unknown;
    };
    const {
      code: problemCode,
      diagnostic_id: problemDiagnostic,
      ...rest
    } = problem;
    code = problemCode ?? code;
    diagnosticId = problemDiagnostic ?? null;
    extensions = rest;
  } catch {
    // Non-streaming error bodies are reported with default code.
  }
  return new ClientError(
    response.status,
    code,
    "Request failed",
    diagnosticId,
    extensions,
  );
}

export async function pollRunUntilTerminal(
  client: ConversationClient,
  runId: string,
  options: { delayMs?: number; attempts?: number } = {},
): Promise<RunSnapshot | null> {
  const delayMs = options.delayMs ?? 200;
  const attempts = options.attempts ?? 150;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const run = await client.getRun(runId);
    if (terminalStatus(run.status)) return run;
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  return null;
}

export async function followActiveRun(options: {
  runId: string;
  afterSequence: number;
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  signal: AbortSignal;
  onResult: (result: ParseResult) => void;
}): Promise<void> {
  await followResponse(options);
}
