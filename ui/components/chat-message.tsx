"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { UIMessage } from "ai";
import { CitationChips } from "@/components/citations";
import type { SourceInfo } from "@/components/source-pane";

interface Props {
  message: UIMessage;
  onSourceClick: (s: SourceInfo) => void;
}

export function ChatMessage({ message, onSourceClick }: Props) {
  const isUser = message.role === "user";
  const textParts = (message.parts ?? []).filter((p) => p.type === "text");
  const sources = (message.parts ?? []).filter((p) => p.type === "source-document");

  return (
    <article className={isUser ? "flex justify-end" : ""}>
      <div
        className={
          isUser
            ? "max-w-[80%] rounded-2xl rounded-br-sm bg-[var(--color-accent)] text-[var(--color-accent-fg)] px-4 py-2.5"
            : "max-w-[88%] rounded-2xl rounded-bl-sm bg-[var(--color-surface)] border border-[var(--color-border)] px-4 py-3"
        }
      >
        {!isUser && sources.length > 0 && (
          <div className="mb-2">
            <CitationChips sources={sources} onSourceClick={onSourceClick} />
          </div>
        )}
        <div className={isUser ? "" : "prose-rag"}>
          {textParts.length === 0 && !isUser && (message as { status?: string }).status === "streaming" ? (
            <span className="inline-flex gap-1">
              <Dot /> <Dot delay={120} /> <Dot delay={240} />
            </span>
          ) : (
            textParts.map((p, i) =>
              p.type === "text" ? (
                isUser ? (
                  <p key={i} className="whitespace-pre-wrap">
                    {p.text}
                  </p>
                ) : (
                  <ReactMarkdown key={i} remarkPlugins={[remarkGfm]}>
                    {p.text}
                  </ReactMarkdown>
                )
              ) : null,
            )
          )}
        </div>
      </div>
    </article>
  );
}

function Dot({ delay = 0 }: { delay?: number }) {
  return (
    <span
      className="w-1.5 h-1.5 rounded-full bg-current opacity-40 animate-pulse"
      style={{ animationDelay: `${delay}ms` }}
    />
  );
}