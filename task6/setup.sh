#!/usr/bin/env bash
# ── Setup script ──────────────────────────────────────────────
# Usage:
#   DATABASE_URL=postgresql://user:pass@host:5432/fakegen ./setup.sh
# Or just:
#   ./setup.sh   (uses localhost defaults)
set -e

DB="${DATABASE_URL:-postgresql://postgres:w3soox1mm@localhost:5432/fakegen}"

echo ">>> Creating database objects..."
psql "$DB" -f db/01_schema.sql
psql "$DB" -f db/02_procedures.sql
psql "$DB" -f db/03_seed_data.sql

echo ">>> Done! Starting Flask app..."
pip install -r requirements.txt -q
python app.py
