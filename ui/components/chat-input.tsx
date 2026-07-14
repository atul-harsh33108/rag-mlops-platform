"use client";

import { type FormEvent, useRef } from "react";

interface Props {
  busy: boolean;
  onSubmit: (text: string) => void;
  onStop: () => void;
  onRegenerate: () => void;
}

export function ChatInput({ busy, onSubmit, onStop, onRegenerate }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    const v = ref.current?.value.trim();
    if (!v || busy) return;
    onSubmit(v);
    if (ref.current) ref.current.value = "";
  }

  // Ctrl/Cmd+Enter to send, Enter for newline (long questions are common in support).
  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      submit(e as unknown as FormEvent);
    }
  }

  return (
    <form onSubmit={submit} className="flex items-end gap-2">
      <textarea
        ref={ref}
        rows={2}
        placeholder="Ask about the knowledge base…  (Ctrl+Enter to send)"
        onKeyDown={onKey}
        className="flex-1 resize-none rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm focus:outline-none focus:border-[var(--color-accent)]"
      />
      {busy ? (
        <button
          type="button"
          onClick={onStop}
          className="h-10 px-4 rounded-xl border border-[var(--color-border)] text-sm hover:bg-[var(--color-bg)]"
        >
          Stop
        </button>
      ) : (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onRegenerate}
            title="Regenerate last answer"
            className="h-10 px-3 rounded-xl border border-[var(--color-border)] text-sm hover:bg-[var(--color-bg)]"
          >
            ↻
          </button>
          <button
            type="submit"
            className="h-10 px-4 rounded-xl bg-[var(--color-accent)] text-[var(--color-accent-fg)] text-sm font-medium"
          >
            Send
          </button>
        </div>
      )}
    </form>
  );
}