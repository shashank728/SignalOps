# Mission-Critical Incident Management System (IMS)

A production-grade Incident Management System that monitors distributed stacks (APIs, MCP Hosts, Caches, Databases) and manages the full incident workflow from signal ingestion to root cause analysis.

Built to handle **10,000+ signals/second** utilizing robust backpressure mechanisms and optimized async connection pools.

## 🏗 Architecture Diagram

```text
+----------------+      +-------------------+      +-------------------------+
|                | POST |  Sliding Window   |      | In-Memory Bounded Queue |
| Client/Sensors |----->|  Rate Limiter     |----->| (max 50,000 items)      |
|                |      |  (In-Memory)      |      +-------------------------+
+----------------+      +-------------------+                  |
                                                               | Drained by
                                                               | Async Workers
                                                               v
+------------------+     +------------------+       +------------------------+
| Live Dashboard   |     | WebSocket        |       | PostgreSQL Sink        |
| (React UI)       |<----| Push Manager     |<------| (Supabase Hosted)      |
+------------------+     +------------------+       +------------------------+
```

## 🚀 Non-Functional Enhancements (SRE Focus)

This system was engineered with site reliability principles in mind, going beyond functional requirements to ensure extreme resilience under heavy load:

### Performance & Resilience
1. **Backpressure Handling**: Uses an `asyncio.Queue` acting as a bounded buffer (max 50,000 items). If the queue is saturated during a massive surge, the API explicitly rejects requests with a `503 Service Unavailable` and a `retry_after_ms` header, pushing backpressure down to the clients instead of crashing the server or exhausting DB connection pools.
2. **In-Memory Rate Limiting**: An ultra-fast, lock-protected sliding window algorithm limits clients to 500 requests/second per IP. Rejecting abusive traffic early saves CPU cycles.
3. **Connection Pooling**: Utilizes `asyncpg` pools. Instead of opening a new DB connection for every incoming signal, background workers batch write signals to PostgreSQL securely utilizing minimal persistent connections.
4. **In-Memory Caching**: The dashboard API serves the latest incidents from a global in-memory cache variable, bypassing the database entirely on rapid `GET /dashboard` requests.

### Security
1. **SSL Required**: The `POSTGRES_DSN` is configured with `sslmode=require`, ensuring all telemetry data sent to the Supabase backend is encrypted over the network.
2. **CORS Middleware**: The FastAPI backend implements strict CORS policies, restricting which frontend domains can connect to the websocket and REST endpoints.
3. **Env Separation**: No secrets are hardcoded. Database connection strings and API keys must be passed via environment variables during container startup.

## 🛠 Tech Stack
- **Backend:** Python, FastAPI, `asyncpg` (Pure Async PostgreSQL driver)
- **Database:** Supabase PostgreSQL
- **Frontend:** React, Vite, Tailwind CSS, TanStack Query
- **Deployment:** Docker, Docker Compose

## 📦 How to Run (Docker)

1. **Set your Supabase Connection String**:
   ```bash
   export POSTGRES_DSN="postgresql://postgres.[project-id]:[password]@aws-0.pooler.supabase.com:6543/postgres?sslmode=require"
   ```

2. **Spin up the stack**:
   ```bash
   docker-compose up --build -d
   ```

3. **Access the application**:
   - **Frontend UI:** `http://localhost:3000`
   - **Backend API Docs:** `http://localhost:8000/docs`

## 🧪 Simulating Incidents

Once the system is running, you can use the built-in seed script to fire thousands of concurrent signals to simulate a massive network outage:

```bash
python3 backend/scripts/seed.py --url http://localhost:8000
```

Watch the React dashboard as it populates incidents dynamically in real-time via WebSockets!
