"use client";

import type { SourceInfo } from "@/components/source-pane";

interface Props {
  // source-document parts from the AI SDK message.
  sources: { type: "source-document"; sourceId: string; title?: string; mediaType?: string }[];
  onSourceClick: (s: SourceInfo) => void;
}

/**
 * Citation chips rendered above the assistant answer. Each chip is keyed by the backend
 * citation id (doc_id:chunk_idx). Clicking opens the source pane (no navigation).
 */
export function CitationChips({ sources, onSourceClick }: Props) {
  if (sources.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {sources.map((s, i) => (
        <button
          key={s.sourceId + i}
          type="button"
          onClick={() =>
            onSourceClick({
              sourceId: s.sourceId,
              title: s.title ?? s.sourceId,
              mediaType: s.mediaType ?? "text",
            })
          }
          className="text-xs px-2 py-0.5 rounded-full border border-[var(--color-border)] bg-[var(--color-bg)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] transition-colors"
          title={s.title ?? s.sourceId}
        >
          [{i + 1}] {s.title ?? s.sourceId}
        </button>
      ))}
    </div>
  );
}