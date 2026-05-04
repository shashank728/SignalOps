# IMS Architecture

## Technology Stack Justification

### Backend
- **Python (FastAPI + asyncio)**: Chosen for its native async capabilities and robust ecosystem for rapid API development. FastAPI's built-in Pydantic integration ensures strict request validation out of the box.
- **In-memory Buffer**: `asyncio.Queue` provides a safe, bounded buffer for our backpressure mechanism.
- **Data Persistence**:
  - **MongoDB**: Used as the raw signal sink. Its flexible schema and high write throughput are ideal for dumping thousands of unstructured signals per second.
  - **PostgreSQL**: Serves as the source of truth for Work Items and RCA records. ACID transactions are essential here to prevent race conditions during state transitions.
  - **TimescaleDB**: An extension for PostgreSQL, perfect for storing and querying our 5-second metrics aggregations efficiently.
  - **Redis**: Acts as our hot-path cache for the live dashboard and supports our sliding window rate limiter.

### Frontend
- **React + TypeScript + Vite**: Provides a component-based architecture with strong typing. React Query is used for data fetching, caching, and background polling.

## Component Architecture
1. **Signal Ingestion**: HTTP `POST /api/v1/signals` handles incoming traffic. It first passes through a Redis-backed sliding window rate limiter.
2. **Buffer & Worker Pool**: Signals enter a bounded `asyncio.Queue`. A pool of async workers drains the queue, batches/debounces the signals, and writes to MongoDB and Postgres.
3. **State Machine**: Work Items follow a strict state machine pattern (OPEN -> INVESTIGATING -> RESOLVED -> CLOSED) with business rules enforced on transitions (e.g., RCA is mandatory before closing).
4. **Metrics Collection**: An isolated asyncio task collects metrics and persists them to TimescaleDB every 5 seconds.
