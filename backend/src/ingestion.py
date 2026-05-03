import asyncio
import time
from typing import Dict, Tuple
from datetime import datetime, timezone
import json
import logging
from src.config import settings
from src.db import db_manager, write_with_retry
from src.alerting import generate_alert
from src.ws import manager

logger = logging.getLogger(__name__)

signal_queue = asyncio.Queue(maxsize=settings.QUEUE_MAX_SIZE)

# In-memory dictionary for debouncing:
debounce_store: Dict[str, dict] = {}
debounce_lock = asyncio.Lock()

# In-memory cache for dashboard
dashboard_cache = []

# In-memory sliding window rate limiter
rate_limit_store: Dict[str, list] = {}
rate_limit_lock = asyncio.Lock()

async def rate_limiter(ip: str) -> bool:
    """In-memory sliding window rate limiter."""
    current_time = time.time()
    
    async with rate_limit_lock:
        if ip not in rate_limit_store:
            rate_limit_store[ip] = []
            
        # Clean up old timestamps (older than 1 second)
        rate_limit_store[ip] = [ts for ts in rate_limit_store[ip] if current_time - ts <= 1.0]
        
        if len(rate_limit_store[ip]) >= settings.RATE_LIMIT_PER_SECOND:
            return False
            
        rate_limit_store[ip].append(current_time)
        return True

async def create_work_item(component_id: str, signals: list):
    """Creates a Work Item and links signals in Postgres."""
    if not signals:
        return

    first_signal = signals[0]
    severity = first_signal["severity"]
    component_type = first_signal["component_type"]
    start_time = min([s["timestamp"] for s in signals])
    
    mock_work_item = {
        "id": "temp",
        "component_id": component_id,
        "component_type": component_type,
        "severity": severity
    }
    alert = generate_alert(mock_work_item)
    alert_type = alert.alert_type

    work_item_id = None
    async def _insert_pg():
        nonlocal work_item_id
        async with db_manager.pg_pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("""
                    INSERT INTO work_items 
                    (component_id, component_type, severity, status, alert_type, signal_count, start_time) 
                    VALUES ($1, $2, $3, 'OPEN', $4, $5, $6)
                    RETURNING id
                """, component_id, component_type, severity, alert_type, len(signals), start_time)
                work_item_id = str(row['id'])

                # Prepare signals for bulk insert
                records = []
                for s in signals:
                    records.append((
                        s["signal_id"], work_item_id, s["component_id"], 
                        s["component_type"], s["severity"], s["error_code"], 
                        s["message"], json.dumps(s.get("metadata", {})), s["timestamp"]
                    ))

                await conn.executemany("""
                    INSERT INTO signals 
                    (signal_id, work_item_id, component_id, component_type, severity, error_code, message, metadata, timestamp)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (signal_id) DO NOTHING
                """, records)

    try:
        await write_with_retry(_insert_pg)
        await update_dashboard_cache()
    except Exception as e:
        logger.error(f"Failed to create Work Item in PG: {e}")

async def update_dashboard_cache():
    global dashboard_cache
    if not db_manager.pg_pool:
        return
    
    try:
        async with db_manager.pg_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, component_id, component_type, severity, status, alert_type, signal_count, start_time, mttr_seconds
                FROM work_items
                WHERE status IN ('OPEN', 'INVESTIGATING')
                ORDER BY 
                    CASE severity 
                        WHEN 'P0' THEN 1 
                        WHEN 'P1' THEN 2 
                        WHEN 'P2' THEN 3 
                        WHEN 'P3' THEN 4 
                        ELSE 5 
                    END, start_time DESC
            """)
            
            data = []
            for row in rows:
                r = dict(row)
                r["id"] = str(r["id"])
                r["start_time"] = r["start_time"].isoformat()
                data.append(r)
                
            dashboard_cache = data
            payload = json.dumps(data)
            await manager.broadcast(payload)
    except Exception as e:
        logger.error(f"Failed to update dashboard cache: {e}")

# Metrics Tracking
metrics = {
    "signals_ingested_total": 0,
    "signals_ingested_last_5s": 0,
    "db_write_errors": 0,
}

async def process_signals_batch():
    while True:
        try:
            signal = await signal_queue.get()
            metrics["signals_ingested_total"] += 1
            metrics["signals_ingested_last_5s"] += 1
            
            comp_id = signal["component_id"]
            current_time = time.time()
            
            async with debounce_lock:
                if comp_id not in debounce_store:
                    debounce_store[comp_id] = {
                        "count": 0,
                        "window_start": current_time,
                        "signals": []
                    }
                
                store = debounce_store[comp_id]
                
                if current_time - store["window_start"] > 10.0:
                    store = {
                        "count": 0,
                        "window_start": current_time,
                        "signals": []
                    }
                    debounce_store[comp_id] = store
                
                store["count"] += 1
                store["signals"].append(signal)
                
                if store["count"] >= 100:
                    asyncio.create_task(create_work_item(comp_id, list(store["signals"])))
                    del debounce_store[comp_id]

            signal_queue.task_done()
        except Exception as e:
            logger.error(f"Worker error: {e}")
            await asyncio.sleep(1)

async def start_workers(num_workers: int = 4):
    for _ in range(num_workers):
        asyncio.create_task(process_signals_batch())

async def metrics_task():
    while True:
        await asyncio.sleep(5)
        
        ingested = metrics["signals_ingested_last_5s"]
        metrics["signals_ingested_last_5s"] = 0
        rate = ingested / 5.0
        qsize = signal_queue.qsize()
        
        open_items = 0
        if db_manager.pg_pool:
            try:
                async with db_manager.pg_pool.acquire() as conn:
                    open_items = await conn.fetchval("SELECT count(*) FROM work_items WHERE status IN ('OPEN', 'INVESTIGATING')")
                    
                    await conn.execute("""
                        INSERT INTO signal_metrics (time, signal_count) VALUES ($1, $2)
                    """, datetime.now(timezone.utc), ingested)
            except Exception as e:
                logger.error(f"Metrics DB error: {e}")
                metrics["db_write_errors"] += 1
        
        logger.info(f"[METRICS] signals_ingested={metrics['signals_ingested_total']} signals_per_sec={rate} queue_depth={qsize} work_items_open={open_items} db_write_errors={metrics['db_write_errors']}")
