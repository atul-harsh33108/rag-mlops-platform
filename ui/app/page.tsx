"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useState } from "react";
import { ChatMessage } from "@/components/chat-message";
import { SourcePane, type SourceInfo } from "@/components/source-pane";
import { ChatInput } from "@/components/chat-input";
import { EmptyState } from "@/components/empty-state";

export default function ChatPage() {
  const [activeSource, setActiveSource] = useState<SourceInfo | null>(null);

  const { messages, sendMessage, status, error, stop, regenerate } = useChat({
    transport: new DefaultChatTransport({ api: "/api/chat" }),
  });

  // Collect source-document parts across all assistant messages for the side pane.
  const allSources: SourceInfo[] = [];
  for (const m of messages) {
    for (const p of m.parts ?? []) {
      if (p.type === "source-document") {
        allSources.push({
          sourceId: p.sourceId,
          title: p.title ?? p.sourceId,
          mediaType: p.mediaType,
        });
      }
    }
  }

  const busy = status === "submitted" || status === "streaming";

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 grid grid-cols-1 lg:grid-cols-[1fr_18rem] gap-6">
      <section className="flex flex-col min-h-[70vh]">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="flex-1 space-y-6 overflow-y-auto pb-4">
            {messages.map((m) => (
              <ChatMessage key={m.id} message={m} onSourceClick={setActiveSource} />
            ))}
            {error && (
              <div className="text-sm text-red-600 border border-red-200 rounded-lg p-3 bg-red-50">
                {error.message}
              </div>
            )}
          </div>
        )}

        <div className="border-t border-[var(--color-border)] pt-4 mt-auto">
          <ChatInput
            busy={busy}
            onSubmit={(text) => sendMessage({ text })}
            onStop={stop}
            onRegenerate={regenerate}
          />
        </div>
      </section>

      <aside className="hidden lg:block">
        <SourcePane source={activeSource} sources={allSources} onSelect={setActiveSource} />
      </aside>
    </div>
  );
}