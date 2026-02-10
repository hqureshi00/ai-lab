from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, RedirectResponse, HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import asyncio
import json
import os
import httpx

load_dotenv()

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
    "https://www.googleapis.com/auth/calendar.readonly"
]
TOKENS_FILE = "tokens.json"


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


async def generate_response(prompt: str):
    """Simulate agentic AI with status updates."""
    
    # Step 1: Thinking
    yield event("status", "Analyzing your request...")
    await asyncio.sleep(0.8)
    
    # Step 2: Searching
    yield event("status", "Searching knowledge base...")
    await asyncio.sleep(1.0)
    
    # Step 3: Processing
    yield event("status", "Processing information...")
    await asyncio.sleep(0.6)
    
    # Step 4: Generating response
    yield event("status", "Generating response...")
    await asyncio.sleep(0.4)
    
    # Stream the actual response
    response = f"Based on your question about '{prompt[:30]}{'...' if len(prompt) > 30 else ''}', here's what I found: This is a simulated response demonstrating real-time streaming updates."
    
    for word in response.split():
        yield event("text", word + " ")
        await asyncio.sleep(0.05)
    
    yield event("done", "")


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
