import asyncio
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from src.db import db_manager
from src.api import router as api_router
from src.ingestion import start_workers, metrics_task, signal_queue, update_dashboard_cache
from src.config import settings
from src.ws import manager

app = FastAPI(title="Incident Management System", version="1.0.0")

@app.websocket("/api/v1/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Configure via env in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

start_time = time.time()

@app.on_event("startup")
async def startup_event():
    await db_manager.connect()
    await db_manager.init_schema()
    await update_dashboard_cache()
    
    # Start background workers
    await start_workers(num_workers=4)
    asyncio.create_task(metrics_task())

@app.on_event("shutdown")
async def shutdown_event():
    await db_manager.close()

@app.get("/health")
async def health_check():
    checks = {
        "postgres": "ok" if db_manager.pg_pool else "error",
        "queue_depth": signal_queue.qsize(),
        "queue_capacity": settings.QUEUE_MAX_SIZE
    }
    
    status = "healthy"
    if any(v == "error" for v in checks.values()):
        status = "degraded" # Or unhealthy depending on strictly required components
        # If pg is down, we might want to return 503
        
    response = {
        "status": status,
        "checks": checks,
        "uptime_seconds": int(time.time() - start_time)
    }
    
    # Let's say if Postgres is error, it's a 503
    if checks["postgres"] == "error":
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content=response)
        
    return response
