from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, RedirectResponse, HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import asyncio
import json
import os
import sys
import httpx

# Add backend to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env from backend directory
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Create storage directory
os.makedirs(os.path.join(os.path.dirname(__file__), "storage"), exist_ok=True)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Google OAuth Config - Load from environment variables
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8000/auth/callback"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]
TOKENS_FILE = os.path.join(os.path.dirname(__file__), "storage", "tokens.json")
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "storage", "settings.json")


def load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE) as f:
            return json.load(f)
    return {}


def save_tokens(tokens):
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f)


class ChatRequest(BaseModel):
    prompt: str


def event(type: str, content: str) -> str:
    """Format a server-sent event."""
    return f"data: {json.dumps({'type': type, 'content': content})}\n\n"


@app.get("/auth/google")
async def auth_google():
    """Start Google OAuth flow."""
    scope = " ".join(SCOPES)
    url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"response_type=code&"
        f"scope={scope}&"
        f"access_type=offline&"
        f"prompt=consent"
    )
    return RedirectResponse(url)


@app.get("/auth/callback")
async def auth_callback(code: str = Query(None), error: str = Query(None)):
    """Handle OAuth callback."""
    if error:
        return HTMLResponse(f"""
            <html><body>
            <h2>Authorization Failed</h2>
            <p>Error: {error}</p>
            <p>Make sure you're added as a test user in Google Cloud Console.</p>
            </body></html>
        """)
    
    if not code:
        return HTMLResponse("""
            <html><body>
            <h2>Authorization Failed</h2>
            <p>No authorization code received.</p>
            </body></html>
        """)
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
            }
        )
        tokens = response.json()
    
    if "access_token" in tokens:
        save_tokens(tokens)
        return HTMLResponse("""
            <html><body><script>
                window.opener.postMessage({type: 'google-auth-success'}, '*');
                window.close();
            </script><p>Connected! You can close this window.</p></body></html>
        """)
    else:
        return HTMLResponse(f"<html><body><p>Error: {tokens}</p></body></html>")


@app.get("/auth/status")
async def auth_status():
    """Check if Google is connected."""
    tokens = load_tokens()
    connected = "access_token" in tokens
    return {"connected": connected, "gmail": connected, "calendar": connected}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {"school_name": "", "teacher_names": []}


def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)


@app.get("/settings")
async def get_settings():
    """Get user settings."""
    return load_settings()


class SettingsRequest(BaseModel):
    school_name: str
    teacher_names: list[str] = []


@app.post("/settings")
async def update_settings(request: SettingsRequest):
    """Update user settings."""
    settings = {
        "school_name": request.school_name,
        "teacher_names": request.teacher_names
    }
    save_settings(settings)
    return {"success": True, "settings": settings}


async def generate_response(prompt: str):
    """Process request using AI Agent."""
    from agent.orchestrator_new import Agent
    
    agent = Agent()
    
    async for event_data in agent.process(prompt):
        yield event("status" if event_data["type"] == "status" else event_data["type"], event_data["content"])


@app.post("/chat")
async def chat(request: ChatRequest):
    """Streaming chat endpoint."""
    return StreamingResponse(
        generate_response(request.prompt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
