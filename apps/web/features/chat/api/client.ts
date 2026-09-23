export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  active_run_id: string | null;
};

export type Message = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  status: "complete" | "partial" | "cancelled" | "failed";
  client_message_id: string | null;
  in_reply_to_id: string | null;
  version: number;
  is_visible: boolean;
  created_at: string;
};

export type RunSnapshot = {
  id: string;
  conversation_id: string;
  user_message_id: string;
  assistant_message_id: string;
  status:
    | "queued"
    | "streaming"
    | "cancelling"
    | "completed"
    | "cancelled"
    | "failed";
  attempt: number;
  last_sequence: number;
  cancel_requested_at: string | null;
  error_code: string | null;
  diagnostic_id: string | null;
  partial_content: string;
  created_at: string;
  completed_at: string | null;
};

export type PaginationEnvelope<T> = {
  items: T[];
  next_cursor: string | null;
};

export type ConversationSnapshot = {
  conversation: Conversation;
  messages: PaginationEnvelope<Message>;
  active_run: RunSnapshot | null;
};

export class ClientError extends Error {
  readonly status: number;
  readonly code: string;
  readonly diagnosticId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    diagnosticId: string | null,
  ) {
    super(message);
    this.name = "ClientError";
    this.status = status;
    this.code = code;
    this.diagnosticId = diagnosticId;
  }
}

type ProblemBody = {
  code?: string;
  title?: string;
  diagnostic_id?: string;
};

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH";
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
};

export type ClientOptions = {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
};

export class ConversationClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? "";
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  private async request<T>(
    path: string,
    options: RequestOptions = {},
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (options.body !== undefined)
      headers["Content-Type"] = "application/json";
    if (options.idempotencyKey !== undefined)
      headers["Idempotency-Key"] = options.idempotencyKey;
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method: options.method ?? "GET",
      headers,
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
    if (!response.ok) {
      let problem: ProblemBody = {};
      try {
        problem = (await response.json()) as ProblemBody;
      } catch {
        problem = {};
      }
      throw new ClientError(
        response.status,
        problem.code ?? "internal_error",
        problem.title ?? "Request failed",
        problem.diagnostic_id ?? null,
      );
    }
    return (await response.json()) as T;
  }

  listConversations(
    options: {
      cursor?: string | null;
      limit?: number;
      includeArchived?: boolean;
      signal?: AbortSignal;
    } = {},
  ): Promise<PaginationEnvelope<Conversation>> {
    const params = new URLSearchParams();
    if (options.cursor) params.set("cursor", options.cursor);
    if (options.limit !== undefined) params.set("limit", String(options.limit));
    if (options.includeArchived) params.set("include_archived", "true");
    const query = params.toString();
    return this.request(`/v1/conversations${query ? `?${query}` : ""}`, {
      signal: options.signal,
    });
  }

  getConversation(
    id: string,
    options: {
      cursor?: string | null;
      limit?: number;
      signal?: AbortSignal;
    } = {},
  ): Promise<ConversationSnapshot> {
    const params = new URLSearchParams();
    if (options.cursor) params.set("cursor", options.cursor);
    if (options.limit !== undefined) params.set("limit", String(options.limit));
    const query = params.toString();
    return this.request(`/v1/conversations/${id}${query ? `?${query}` : ""}`, {
      signal: options.signal,
    });
  }

  createConversation(
    title?: string,
    options: { idempotencyKey?: string; signal?: AbortSignal } = {},
  ): Promise<Conversation> {
    return this.request("/v1/conversations", {
      method: "POST",
      body: title === undefined ? {} : { title },
      idempotencyKey: options.idempotencyKey ?? newIdempotencyKey(),
      signal: options.signal,
    });
  }

  patchConversation(
    id: string,
    patch: { title?: string; archived?: boolean },
    options: { idempotencyKey?: string; signal?: AbortSignal } = {},
  ): Promise<Conversation> {
    return this.request(`/v1/conversations/${id}`, {
      method: "PATCH",
      body: patch,
      idempotencyKey: options.idempotencyKey ?? newIdempotencyKey(),
      signal: options.signal,
    });
  }
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export function newClientMessageId(): string {
  return crypto.randomUUID();
}
