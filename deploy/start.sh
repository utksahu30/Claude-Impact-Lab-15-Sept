#!/bin/sh
set -e

echo "========================================================"
echo " Starting CivicTrace Bhopal - Municipal Triage Engine   "
echo "========================================================"

PORT="${PORT:-7860}"
DB_PATH="${DATABASE_URL:-sqlite:///bhopal_triage.db}"

echo "[INFO] Target Port: $PORT"
echo "[INFO] Database Target: $DB_PATH"

# Run database table initialization and auto-seed if clean database
python -c "
import os
from pathlib import Path
from sqlmodel import Session, select
from app.db import init_db, engine
from app.models import Ticket
from app.main import reset_demo_data

init_db()
with Session(engine) as session:
    ticket_count = len(session.exec(select(Ticket)).all())
    if ticket_count == 0:
        print('[INFO] Fresh database detected. Auto-seeding baseline Bhopal complaints...')
        reset_demo_data(session)
        print('[INFO] Baseline demo data seeded successfully.')
    else:
        print(f'[INFO] Database already contains {ticket_count} existing tickets.')
"

echo "[INFO] Launching Uvicorn production server on 0.0.0.0:$PORT..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
