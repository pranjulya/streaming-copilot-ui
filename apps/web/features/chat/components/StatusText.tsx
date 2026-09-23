export type RunStatus = "queued" | "streaming" | "cancelling";

const LABELS: Record<string, string> = {
  queued: "Waiting to start…",
  streaming: "Generating a response…",
  cancelling: "Stopping…",
};

export function StatusText({ status }: { status: RunStatus | null }) {
  const text = status === null ? "" : (LABELS[status] ?? "");
  return (
    <p className="status-text" role="status">
      {text}
    </p>
  );
}
