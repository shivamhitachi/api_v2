#!/bin/bash

echo "  Starting Stormcast Weather API...  "



if [ -d "venv" ]; then
    echo "-> Activating virtual environment (venv)..."
    source venv/bin/activate
elif [ -d ".venv" ]; then
    echo "-> Activating virtual environment (.venv)..."
    source .venv/bin/activate
else
    echo "-> Warning: No virtual environment found. Using system Python."
fi

echo "-> Launching Uvicorn server..."
echo "-> API will be available at: http://127.0.0.1:8000"
echo "-> Press Ctrl+C to stop the server."
echo ""

uvicorn fast_api:app --reload --host 127.0.0.1 --port 8000