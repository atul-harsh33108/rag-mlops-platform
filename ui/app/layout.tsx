import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "RAG Knowledge-Base",
  description: "Grounded answers with citations over your document corpus.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider appearance={{ variables: { borderRadius: "0.5rem" } }}>
      <html lang="en">
        <body>
          <div className="min-h-full flex flex-col">
            <header className="border-b border-[var(--color-border)] bg-[var(--color-surface)]">
              <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
                <Link href="/" className="font-semibold tracking-tight">
                  RAG&nbsp;KB
                </Link>
                <div className="flex items-center gap-3">
                  {/* Organization = tenant (Clerk org id maps to Qdrant group_id server-side).
                      Switching org re-scopes every retrieval; no client-side filter needed. */}
                  <OrganizationSwitcher
                    hidePersonal
                    afterSelectOrganizationUrl="/"
                    afterLeaveOrganizationUrl="/"
                  />
                  <Link
                    href="/keys"
                    className="text-sm text-[oklch(0.45_0.01_250)] hover:text-[var(--color-accent)]"
                  >
                    API&nbsp;keys
                  </Link>
                  <UserButton afterSignOutUrl="/" />
                </div>
              </div>
            </header>
            <main className="flex-1">{children}</main>
          </div>
        </body>
      </html>
    </ClerkProvider>
  );
}