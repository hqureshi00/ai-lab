import httpx
import base64
from services.google_client import GoogleClient


class GmailTool:
    def __init__(self, google_client: GoogleClient):
        self.client = google_client
        self.base_url = "https://gmail.googleapis.com/gmail/v1/users/me"
    
    async def search_emails(self, query: str, max_results: int = 10) -> list[dict]:
        """Search emails with Gmail query syntax."""
        headers = await self.client.get_headers()
        
        async with httpx.AsyncClient() as client:
            # Search for message IDs
            response = await client.get(
                f"{self.base_url}/messages",
                headers=headers,
                params={"q": query, "maxResults": max_results}
            )
            data = response.json()
            
            if "messages" not in data:
                return []
            
            # Fetch each message
            emails = []
            for msg in data["messages"][:max_results]:
                msg_response = await client.get(
                    f"{self.base_url}/messages/{msg['id']}",
                    headers=headers,
                    params={"format": "full"}
                )
                msg_data = msg_response.json()
                emails.append(self._parse_email(msg_data))
            
            return emails
    
    def _parse_email(self, msg: dict) -> dict:
        """Extract useful fields from Gmail message."""
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        
        # Get body - try multiple methods
        body = self._extract_body(msg.get("payload", {}))
        
        # Fallback to snippet if no body found
        if not body.strip():
            body = msg.get("snippet", "")
        
        return {
            "id": msg.get("id", ""),
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
            "body": body[:4000]  # Limit body size for context
        }
    
    def _extract_body(self, payload: dict) -> str:
        """Recursively extract text body from payload."""
        body = ""
        
        # Direct body data
        if "body" in payload and payload["body"].get("data"):
            try:
                body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
            except:
                pass
        
        # Check parts (including nested multipart)
        if "parts" in payload:
            for part in payload["parts"]:
                mime_type = part.get("mimeType", "")
                
                # Prefer text/plain
                if mime_type == "text/plain" and part.get("body", {}).get("data"):
                    try:
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
                        if body.strip():
                            return body
                    except:
                        pass
                
                # Recurse into nested multipart
                if mime_type.startswith("multipart/") or "parts" in part:
                    nested_body = self._extract_body(part)
                    if nested_body.strip():
                        return nested_body
            
            # If no text/plain found, try text/html as fallback
            for part in payload["parts"]:
                if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
                    try:
                        html = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
                        # Strip HTML tags for basic text
                        import re
                        body = re.sub(r'<[^>]+>', ' ', html)
                        body = re.sub(r'\s+', ' ', body).strip()
                        if body:
                            return body
                    except:
                        pass
        
        return body
    
    async def send_email(self, to: str, subject: str, body: str) -> bool:
        """Send an email."""
        headers = await self.client.get_headers()
        
        message = f"To: {to}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}"
        raw = base64.urlsafe_b64encode(message.encode()).decode()
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/messages/send",
                headers=headers,
                json={"raw": raw}
            )
            return response.status_code == 200
