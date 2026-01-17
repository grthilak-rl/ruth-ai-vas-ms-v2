#!/bin/bash
# Run PPE detection model locally for testing
# Requires: Python 3.9+, pip

set -e

cd "$(dirname "$0")"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies if not already installed
if ! pip show ultralytics &>/dev/null; then
    echo "Installing dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
fi

# Set environment variables
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
export AI_DEVICE="${AI_DEVICE:-auto}"
export PPE_CONFIDENCE_THRESHOLD="${PPE_CONFIDENCE_THRESHOLD:-0.5}"

echo ""
echo "================================================"
echo "  PPE Detection Model Service"
echo "================================================"
echo ""
echo "Configuration:"
echo "  - Device: ${AI_DEVICE}"
echo "  - Confidence Threshold: ${PPE_CONFIDENCE_THRESHOLD}"
echo ""
echo "Endpoints:"
echo "  - Health:     GET  http://localhost:8011/health"
echo "  - Info:       GET  http://localhost:8011/info"
echo "  - Models:     GET  http://localhost:8011/models"
echo "  - Detect:     POST http://localhost:8011/detect"
echo "  - Batch:      POST http://localhost:8011/detect/batch"
echo "  - Docs:       GET  http://localhost:8011/docs"
echo ""
echo "Detection modes (via query param ?mode=):"
echo "  - presence:  Detect PPE items that are present"
echo "  - violation: Detect missing PPE items"
echo "  - full:      Run both (default)"
echo ""
echo "Starting server..."
echo ""

# Run the server
python -m uvicorn app:app --host 0.0.0.0 --port 8011 --reload
