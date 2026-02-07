#!/usr/bin/env bash
# Run BillTrim Desktop backend (SQLite, no Redis)
cd "$(dirname "$0")/backend"
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate
pip install -q -r requirements.txt
if [ ! -f "data/billtrim.db" ]; then
  python3 -m scripts.init_db
fi
uvicorn app.main:app --host 127.0.0.1 --port 8765
