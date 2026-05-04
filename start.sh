#!/bin/bash
echo "Starting IMS locally without Docker..."

if [ -z "$POSTGRES_DSN" ]; then
    echo "Warning: POSTGRES_DSN is not set!"
    echo "You must set your Supabase connection string for the backend to work."
    echo "Example: export POSTGRES_DSN='postgresql://postgres.xxx:password@aws-0.pooler.supabase.com:6543/postgres'"
fi

# Start backend in background
cd backend
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --port 8000 &
BACKEND_PID=$!

# Start frontend in foreground
cd ../frontend
npm install
npm run dev &
FRONTEND_PID=$!

# Handle shutdown
trap "kill $BACKEND_PID $FRONTEND_PID" EXIT

# Wait forever
wait
