"use client";

import { useState } from "react";

export function Composer({
  onSubmit,
}: {
  onSubmit: (content: string) => void;
}) {
  const [value, setValue] = useState("");
  const canSubmit = value.trim().length > 0;

  function submit() {
    if (!canSubmit) return;
    onSubmit(value.trim());
    setValue("");
  }

  return (
    <form
      className="composer"
      aria-label="Message composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label className="composer-label" htmlFor="composer-input">
        Message
      </label>
      <textarea
        id="composer-input"
        className="composer-input"
        rows={3}
        value={value}
        placeholder="Ask the Copilot…"
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
      />
      <button type="submit" disabled={!canSubmit}>
        Send
      </button>
    </form>
  );
}
