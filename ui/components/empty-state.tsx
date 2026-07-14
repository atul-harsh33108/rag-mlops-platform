export function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center py-20">
      <h1 className="text-2xl font-semibold tracking-tight mb-2">
        Ask anything about your knowledge base
      </h1>
      <p className="text-[oklch(0.45_0.01_250)] max-w-md mb-6">
        Answers are grounded in your indexed documents with inline citations. Switch
        organization above to query a different tenant&apos;s corpus.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-lg w-full">
        {[
          "How do I reset my password?",
          "What does the SLA say about incident response?",
          "Summarize the latest product release notes.",
        ].map((q) => (
          <div
            key={q}
            className="text-sm text-left rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-[oklch(0.4_0.01_250)]"
          >
            {q}
          </div>
        ))}
      </div>
    </div>
  );
}