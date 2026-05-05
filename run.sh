#!/bin/bash
# SchediQ v2 — Quick Start
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "🔧 Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate
echo "📦 Installing dependencies..."
pip install -q -r requirements.txt
echo "🚀 Starting SchediQ v2 on http://localhost:5000"
echo "   Admin: admin / admin123"
echo "   Teachers: <name>@college.edu / teacher123"
python app.py
