"use client";

import { useRef, useState } from "react";

const EMPTY_HINT_ID = "composer-empty-hint";

export function Composer({
  onSubmit,
}: {
  onSubmit: (content: string) => void;
}) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const canSubmit = value.trim().length > 0;

  function submit() {
    if (!canSubmit) return;
    onSubmit(value.trim());
    setValue("");
    inputRef.current?.focus();
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
        ref={inputRef}
        className="composer-input"
        rows={3}
        value={value}
        placeholder="Ask the Copilot…"
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing || event.keyCode === 229) {
            return;
          }
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
      />
      <button
        type="submit"
        disabled={!canSubmit}
        aria-describedby={canSubmit ? undefined : EMPTY_HINT_ID}
      >
        Send
      </button>
      <span id={EMPTY_HINT_ID} className="composer-hint">
        Message is empty
      </span>
    </form>
  );
}
