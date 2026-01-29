import os
from dotenv import load_dotenv
load_dotenv()

from typing import Optional, Literal
from datetime import datetime, timezone
from uuid import UUID

import jwt
from fastapi import FastAPI, Header, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/tbank_case")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALG = "HS256"

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

bearer_scheme = HTTPBearer(auto_error=False)

class Principal(BaseModel):
    sub: str
    roles: list[str] = []

async def get_principal(token: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> Principal:
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        payload = jwt.decode(token.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return Principal(sub=str(payload.get("sub", "unknown")), roles=payload.get("roles", []))

def require_roles(*required: str):
    def checker(principal: Principal = Depends(get_principal)):
        if not any(r in principal.roles for r in required):
            raise HTTPException(status_code=403, detail="Forbidden: insufficient role")
        return principal
    return checker

class CreateHoldBody(BaseModel):
    type: Literal["FRAUD_SUSPECT", "INCORRECT_BENEFICIARY_DETAILS"]
    comment: Optional[str] = None
    source: Optional[str] = None
    expiresAt: Optional[datetime] = Field(default=None)

class ReleaseBody(BaseModel):
    reason: Optional[str] = None
    comment: Optional[str] = None

class HoldModel(BaseModel):
    holdId: UUID
    clientId: UUID
    type: Literal["FRAUD_SUSPECT", "INCORRECT_BENEFICIARY_DETAILS"]
    status: Literal["ACTIVE", "RELEASED", "EXPIRED"]
    comment: Optional[str]
    source: Optional[str]
    createdAt: datetime
    createdBy: str
    expiresAt: Optional[datetime]
    releasedAt: Optional[datetime]
    releasedBy: Optional[str]
    releaseReason: Optional[str]
    idempotencyKey: str

class ErrorModel(BaseModel):
    code: str
    message: str

app = FastAPI(title="T-Bank Payments Hold API (JWT/RBAC)")

def _now():
    return datetime.now(timezone.utc)

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS pgcrypto;'))

@app.post("/v1/clients/{clientId}/payment-holds", status_code=201, response_model=HoldModel)
async def create_hold(
    clientId: UUID,
    body: CreateHoldBody,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles("ops.block:create")),
):
    if body.expiresAt and body.expiresAt <= _now():
        raise HTTPException(status_code=422, detail="expiresAt must be in future")
    async with async_session() as session:
        q_exists = text("SELECT 1 FROM client WHERE client_id = CAST(:cid AS uuid)")
        res = await session.execute(q_exists, {"cid": str(clientId)})
        if res.scalar() is None:
            raise HTTPException(status_code=422, detail="Client does not exist")

        q_idem = text("SELECT * FROM payment_hold WHERE idempotency_key = :ik LIMIT 1")
        row = (await session.execute(q_idem, {"ik": idempotency_key})).mappings().first()
        if row:
            return _row_to_hold(row)

        q_ins = text("""
            INSERT INTO payment_hold
                (client_id, type, status, comment, source, created_by, expires_at, idempotency_key)
            VALUES
            (CAST(:client_id AS uuid), :type, 'ACTIVE',
                :comment, :source, :created_by, :expires_at, :ik)
            RETURNING *
        """)

        r = await session.execute(q_ins, {
            "client_id": str(clientId),
            "type": body.type,
            "comment": body.comment,
            "source": body.source,
            "created_by": principal.sub,
            "expires_at": body.expiresAt,
            "ik": idempotency_key,
        })
        await session.commit()
        return _row_to_hold(r.mappings().first())

@app.get("/v1/clients/{clientId}/payment-holds")
async def list_holds(
    clientId: UUID,
    status: Literal["ACTIVE", "RELEASED", "ALL"] = "ACTIVE",
    principal: Principal = Depends(require_roles("ops.block:read")),
):
    async with async_session() as session:
        if status == "ALL":
            q = text("SELECT * FROM payment_hold WHERE client_id = CAST(:cid AS uuid) ORDER BY created_at DESC")
            res = await session.execute(q, {"cid": str(clientId)})
        else:
            q = text("""
                SELECT * FROM payment_hold
                WHERE client_id = CAST(:cid AS uuid) AND status = :st
                ORDER BY created_at DESC
            """)
            res = await session.execute(q, {"cid": str(clientId), "st": status})
        items = [_row_to_hold(m) for m in res.mappings().all()]
        return {"items": items}

@app.get("/v1/clients/{clientId}/payment-holds:check")
async def check_hold(clientId: UUID, principal: Principal = Depends(require_roles("ops.block:read"))):
    async with async_session() as session:
        q = text("""
            SELECT * FROM payment_hold
            WHERE client_id = CAST(:cid AS uuid) AND status = 'ACTIVE'
        """)
        res = await session.execute(q, {"cid": str(clientId)})
        rows = res.mappings().all()
        blocked = len(rows) > 0
        kind = "NONE"
        if blocked:
            types = {r["type"] for r in rows}
            kind = "FRAUD" if "FRAUD_SUSPECT" in types else "NON_FRAUD"
        return {"blocked": blocked, "kind": kind, "activeHolds": [_row_to_hold(r) for r in rows]}

@app.get("/v1/clients/{clientId}/payment-holds/{holdId}", response_model=HoldModel)
async def get_hold(clientId: UUID, holdId: UUID, principal: Principal = Depends(require_roles("ops.block:read"))):
    async with async_session() as session:
        q = text("""
            SELECT * FROM payment_hold
            WHERE client_id = CAST(:cid AS uuid) AND hold_id = CAST(:hid AS uuid)
        """)
        row = (await session.execute(q, {"cid": str(clientId), "hid": str(holdId)})).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return _row_to_hold(row)

@app.post("/v1/clients/{clientId}/payment-holds/{holdId}:release", response_model=HoldModel)
async def release_hold(
    clientId: UUID,
    holdId: UUID,
    body: ReleaseBody | None = None,
    principal: Principal = Depends(require_roles("ops.block:release")),
):
    async with async_session() as session:
        q_sel = text("""
            SELECT * FROM payment_hold
            WHERE client_id = CAST(:cid AS uuid) AND hold_id = CAST(:hid AS uuid)
        """)
        row = (await session.execute(q_sel, {"cid": str(clientId), "hid": str(holdId)})).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        if row["status"] != "ACTIVE":
            raise HTTPException(status_code=409, detail="Already closed")

        q_upd = text("""
            UPDATE payment_hold
            SET status='RELEASED', released_at=now(), released_by=:by, release_reason=:reason
            WHERE hold_id = CAST(:hid AS uuid)
            RETURNING *
        """)
        r = await session.execute(q_upd, {
            "hid": str(holdId),
            "reason": (body.reason if body else None),
            "by": principal.sub
        })
        await session.commit()
        return _row_to_hold(r.mappings().first())

def _row_to_hold(m):
    return {
        "holdId": m["hold_id"],
        "clientId": m["client_id"],
        "type": m["type"],
        "status": m["status"],
        "comment": m["comment"],
        "source": m["source"],
        "createdAt": m["created_at"],
        "createdBy": m["created_by"],
        "expiresAt": m["expires_at"],        
        "releasedAt": m["released_at"],
        "releasedBy": m["released_by"],
        "releaseReason": m["release_reason"],
        "idempotencyKey": m["idempotency_key"],
    }