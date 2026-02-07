#!/usr/bin/env bash
# Run BillTrim Desktop frontend (points to localhost:8765)
cd "$(dirname "$0")/frontend"
if [ ! -d "node_modules" ]; then
  npm install
fi
if [ ! -f ".env" ]; then
  cp .env.example .env
fi
npm run dev
