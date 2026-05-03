from fastapi import APIRouter, Request, HTTPException, status, Query
from fastapi.responses import JSONResponse
import time
import json
import uuid
from typing import Optional, List
from datetime import datetime, timezone

from src.models import SignalPayload, WorkItemStatusUpdate, RCAPayload
from src.ingestion import signal_queue, rate_limiter, update_dashboard_cache
from src.db import db_manager, write_with_retry
from src.config import settings
from src.state_machine import WorkItemStateMachine, InvalidTransitionError, RCAIncompleteError

router = APIRouter(prefix="/api/v1")

@router.post("/signals", status_code=status.HTTP_202_ACCEPTED)
async def ingest_signal(signal: SignalPayload, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    
    # 1. Rate Limiting
    allowed = await rate_limiter(client_ip)
    if not allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"error": "Rate limit exceeded"},
            headers={"Retry-After": "1"}
        )

    # 2. Add to Queue
    try:
        # Don't use put() to avoid blocking if full, use put_nowait()
        signal_queue.put_nowait(signal.model_dump())
    except asyncio.QueueFull:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "backpressure", "retry_after_ms": 200}
        )

    return {"status": "accepted"}

@router.get("/work-items")
async def list_work_items(
    status_filter: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = None,
    component_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    sort: str = Query("created_at"),
    order: str = Query("desc")
):
    if not db_manager.pg_pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    offset = (page - 1) * limit
    
    query = "SELECT * FROM work_items WHERE 1=1"
    params = []
    
    if status_filter:
        params.append(status_filter)
        query += f" AND status = ${len(params)}"
    if severity:
        params.append(severity)
        query += f" AND severity = ${len(params)}"
    if component_type:
        params.append(component_type)
        query += f" AND component_type = ${len(params)}"
        
    order_col = "severity" if sort == "severity" else "created_at"
    order_dir = "ASC" if order.lower() == "asc" else "DESC"
    
    query += f" ORDER BY {order_col} {order_dir} LIMIT ${len(params)+1} OFFSET ${len(params)+2}"
    params.extend([limit, offset])
    
    async with db_manager.pg_pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
        
    result = []
    for row in rows:
        r = dict(row)
        r["id"] = str(r["id"])
        r["start_time"] = r["start_time"].isoformat()
        if r.get("end_time"): r["end_time"] = r["end_time"].isoformat()
        r["created_at"] = r["created_at"].isoformat()
        r["updated_at"] = r["updated_at"].isoformat()
        result.append(r)
        
    return {"data": result, "page": page, "limit": limit}

@router.get("/work-items/{item_id}")
async def get_work_item(item_id: str):
    async with db_manager.pg_pool.acquire() as conn:
        try:
            uuid.UUID(item_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid UUID")
            
        row = await conn.fetchrow("SELECT * FROM work_items WHERE id = $1", item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Work item not found")
            
        r = dict(row)
        r["id"] = str(r["id"])
        r["start_time"] = r["start_time"].isoformat()
        if r.get("end_time"): r["end_time"] = r["end_time"].isoformat()
        r["created_at"] = r["created_at"].isoformat()
        r["updated_at"] = r["updated_at"].isoformat()
        return r

@router.patch("/work-items/{item_id}/status")
async def update_work_item_status(item_id: str, update: WorkItemStatusUpdate):
    try:
        uuid_val = uuid.UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    async def _tx():
        async with db_manager.pg_pool.acquire() as conn:
            async with conn.transaction():
                # Lock row
                row = await conn.fetchrow("SELECT * FROM work_items WHERE id = $1 FOR UPDATE NOWAIT", str(uuid_val))
                if not row:
                    raise HTTPException(status_code=404, detail="Work item not found")
                
                work_item = dict(row)
                
                # Fetch RCA if it exists
                rca_row = await conn.fetchrow("SELECT * FROM rca_records WHERE work_item_id = $1", str(uuid_val))
                rca_record = dict(rca_row) if rca_row else None
                
                try:
                    await WorkItemStateMachine.transition(work_item, update.status, conn, rca_record)
                except InvalidTransitionError as e:
                    raise HTTPException(status_code=409, detail=str(e))
                except RCAIncompleteError as e:
                    raise HTTPException(status_code=422, detail={"message": str(e), "fields": e.fields})
    try:
        await write_with_retry(_tx)
        await update_dashboard_cache()
    except asyncpg.exceptions.LockNotAvailableError:
        raise HTTPException(status_code=409, detail="Concurrent transition attempt. Try again.")

    return await get_work_item(item_id)

@router.get("/work-items/{item_id}/signals")
async def get_work_item_signals(item_id: str, page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200)):
    if not db_manager.pg_pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
        
    try:
        uuid_val = uuid.UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    skip = (page - 1) * limit
    
    async with db_manager.pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM signals WHERE work_item_id = $1 ORDER BY timestamp DESC LIMIT $2 OFFSET $3",
            str(uuid_val), limit, skip
        )
    
    signals = []
    for row in rows:
        s = dict(row)
        s["_id"] = str(s["id"])
        s["signal_id"] = str(s["signal_id"])
        s["work_item_id"] = str(s["work_item_id"])
        if isinstance(s.get("timestamp"), datetime):
            s["timestamp"] = s["timestamp"].isoformat()
        if isinstance(s.get("created_at"), datetime):
            s["created_at"] = s["created_at"].isoformat()
        signals.append(s)
        
    return {"data": signals, "page": page, "limit": limit}

@router.post("/work-items/{item_id}/rca")
async def submit_rca(item_id: str, rca: RCAPayload):
    try:
        uuid_val = uuid.UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    async def _tx():
        async with db_manager.pg_pool.acquire() as conn:
            # Check if work item exists and is not CLOSED
            row = await conn.fetchrow("SELECT status FROM work_items WHERE id = $1", str(uuid_val))
            if not row:
                raise HTTPException(status_code=404, detail="Work item not found")
            if row["status"] == "CLOSED":
                raise HTTPException(status_code=409, detail="Work item already closed")

            # Try insert
            try:
                await conn.execute("""
                    INSERT INTO rca_records 
                    (work_item_id, incident_start, incident_end, root_cause_category, fix_applied, prevention_steps)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, str(uuid_val), rca.incident_start, rca.incident_end, rca.root_cause_category, 
                rca.fix_applied, rca.prevention_steps)
            except asyncpg.exceptions.UniqueViolationError:
                raise HTTPException(status_code=409, detail="RCA already submitted for this work item")

    await write_with_retry(_tx)
    return await get_rca(item_id)

@router.get("/work-items/{item_id}/rca")
async def get_rca(item_id: str):
    try:
        uuid_val = uuid.UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    async with db_manager.pg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM rca_records WHERE work_item_id = $1", str(uuid_val))
        if not row:
            raise HTTPException(status_code=404, detail="RCA not found")
            
        r = dict(row)
        r["id"] = str(r["id"])
        r["work_item_id"] = str(r["work_item_id"])
        r["incident_start"] = r["incident_start"].isoformat()
        r["incident_end"] = r["incident_end"].isoformat()
        r["submitted_at"] = r["submitted_at"].isoformat()
        return r

from src import ingestion
@router.get("/dashboard")
async def get_dashboard():
    return ingestion.dashboard_cache
@router.get("/metrics")
async def get_metrics():
    return {
        "signals_ingested_total": metrics["signals_ingested_total"],
        "signals_ingested_last_5s": metrics["signals_ingested_last_5s"],
        "queue_depth": signal_queue.qsize(),
        "queue_capacity": settings.QUEUE_MAX_SIZE,
        "db_write_errors": metrics["db_write_errors"]
    }
