"""API key management (M6). All paths require a Principal (JWT only — you mint keys via
your Clerk-authed session, not with another key). M7 adds plan scoping + spend caps.

  POST   /keys          {label}        -> {key_id, key}          (key shown once)
  GET    /keys                          -> [{id, label, created_at, last_used_at, ...}]
  DELETE /keys/{key_id}                 -> {revoked: bool}
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import Principal, require_principal
from app.auth.apikey import create_key, list_keys, revoke_key
from app.db import session_context

router = APIRouter(prefix="/keys", tags=["keys"])


class CreateKeyRequest(BaseModel):
    label: str = Field(default="default", max_length=64)


class CreateKeyResponse(BaseModel):
    key_id: int
    key: str  # shown once


class KeyView(BaseModel):
    id: int
    tenant_id: str
    label: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


@router.post("", response_model=CreateKeyResponse)
async def issue_key(
    req: CreateKeyRequest, principal: Principal = Depends(require_principal)
) -> CreateKeyResponse:
    async with session_context() as session:
        plaintext, key_id = await create_key(session, principal.tenant_id, req.label)
    return CreateKeyResponse(key_id=key_id, key=plaintext)


@router.get("", response_model=list[KeyView])
async def my_keys(principal: Principal = Depends(require_principal)) -> list[KeyView]:
    async with session_context() as session:
        rows = await list_keys(session, principal.tenant_id)
    return [
        KeyView(
            id=r["id"],
            tenant_id=r["tenant_id"],
            label=r["label"],
            created_at=r["created_at"].isoformat() if r["created_at"] else "",
            last_used_at=r["last_used_at"].isoformat() if r["last_used_at"] else None,
            revoked_at=r["revoked_at"].isoformat() if r["revoked_at"] else None,
        )
        for r in rows
    ]


@router.delete("/{key_id}")
async def revoke(key_id: int, principal: Principal = Depends(require_principal)) -> dict:
    async with session_context() as session:
        ok = await revoke_key(session, principal.tenant_id, key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="key not found or already revoked")
    return {"revoked": True}
