# AI Assistant Demo

Agentic-style chat with real-time status updates.

## Quick Start

```bash
# Terminal 1 - Backend
pip install fastapi uvicorn pydantic
python backend/main.py

# Terminal 2 - Frontend  
cd frontend && python -m http.server 3000
```

Open http://localhost:3000

## How It Works

The backend streams JSON events:
- `status` - Shows what the AI is doing (analyzing, searching, etc.)
- `text` - Streams response word-by-word
- `done` - Signals completion

Frontend displays status updates with a spinner, then streams the response.
