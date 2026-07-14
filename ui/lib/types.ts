/** Shared client types for the UI. Backend contracts are mirrored here so the proxy routes
 * stay in sync with the FastAPI schemas (see app/api/{chat,keys}.py). */

export interface Citation {
  source: string;
  doc_id: string;
  chunk_idx: number;
  score?: number;
}

export interface KeyView {
  id: number;
  tenant_id: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface CreatedKey {
  key_id: number;
  key: string; // plaintext, shown once
}