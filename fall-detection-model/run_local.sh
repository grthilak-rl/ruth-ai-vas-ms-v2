#!/bin/bash
# Run fall detection model locally for testing
# Requires: Python 3.9+, pip

cd "$(dirname "$0")"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies if not already installed
if ! pip show fastapi &>/dev/null; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

# Set environment variables
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

echo "Starting Fall Detection Model Service on port 8000..."
echo "Health check: http://localhost:8000/health"
echo "Detection endpoint: POST http://localhost:8000/detect"
echo ""

# Run the server
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
