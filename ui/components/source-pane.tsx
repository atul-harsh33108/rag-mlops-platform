"use client";

export interface SourceInfo {
  sourceId: string;
  title: string;
  mediaType?: string;
}

interface Props {
  source: SourceInfo | null;
  sources: SourceInfo[];
  onSelect: (s: SourceInfo) => void;
}

/**
 * Right-hand source pane: lists every citation surfaced across the conversation and shows
 * the detail of the selected one. In M6 this is metadata only (title + id + media type);
 * M7 will deep-link into the source document viewer (doc_id + chunk highlight).
 */
export function SourcePane({ source, sources, onSelect }: Props) {
  return (
    <div className="sticky top-6 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-[oklch(0.45_0.01_250)] mb-2">
        Sources
      </h2>
      {sources.length === 0 ? (
        <p className="text-sm text-[oklch(0.55_0.01_250)]">
          Citations from the grounded answer appear here.
        </p>
      ) : (
        <ul className="space-y-1 mb-3">
          {sources.map((s, i) => (
            <li key={s.sourceId + i}>
              <button
                type="button"
                onClick={() => onSelect(s)}
                className={
                  "w-full text-left text-sm px-2 py-1 rounded-md truncate " +
                  (source?.sourceId === s.sourceId
                    ? "bg-[var(--color-bg)] text-[var(--color-accent)]"
                    : "hover:bg-[var(--color-bg)]")
                }
                title={s.title}
              >
                <span className="text-[oklch(0.5_0.01_250)]">[{i + 1}]</span> {s.title}
              </button>
            </li>
          ))}
        </ul>
      )}
      {source && (
        <div className="border-t border-[var(--color-border)] pt-3 text-sm">
          <p className="font-medium truncate">{source.title}</p>
          <p className="text-xs text-[oklch(0.5_0.01_250)] mt-1 font-mono break-all">
            {source.sourceId}
          </p>
          <p className="text-xs text-[oklch(0.5_0.01_250)] mt-1">type: {source.mediaType}</p>
        </div>
      )}
    </div>
  );
}