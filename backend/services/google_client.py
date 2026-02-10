import httpx
import json
import os

TOKENS_FILE = os.path.join(os.path.dirname(__file__), "..", "storage", "tokens.json")
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "storage", "settings.json")


class GoogleClient:
    def __init__(self):
        self.client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        self.tokens = self._load_tokens()
    
    def _load_tokens(self):
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE) as f:
                return json.load(f)
        return {}
    
    def _save_tokens(self, tokens):
        os.makedirs(os.path.dirname(TOKENS_FILE), exist_ok=True)
        with open(TOKENS_FILE, "w") as f:
            json.dump(tokens, f)
        self.tokens = tokens
    
    async def refresh_token_if_needed(self):
        """Refresh access token using refresh token."""
        if not self.tokens.get("refresh_token"):
            return False
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.tokens["refresh_token"],
                    "grant_type": "refresh_token",
                }
            )
            new_tokens = response.json()
            if "access_token" in new_tokens:
                self.tokens["access_token"] = new_tokens["access_token"]
                self._save_tokens(self.tokens)
                return True
        return False
    
    async def get_headers(self):
        """Get auth headers, refreshing token if needed."""
        if not self.tokens.get("access_token"):
            self.tokens = self._load_tokens()
        return {"Authorization": f"Bearer {self.tokens.get('access_token', '')}"}
    
    def is_connected(self):
        return bool(self.tokens.get("access_token"))


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {}


def save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)
