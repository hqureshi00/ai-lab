import httpx
from datetime import datetime, timedelta
from services.google_client import GoogleClient


class CalendarTool:
    def __init__(self, google_client: GoogleClient):
        self.client = google_client
        self.base_url = "https://www.googleapis.com/calendar/v3"
    
    async def list_events(self, days_ahead: int = 30, include_past_today: bool = False) -> list[dict]:
        """List upcoming calendar events."""
        headers = await self.client.get_headers()
        
        now = datetime.utcnow()
        if include_past_today:
            # Start from beginning of today (midnight UTC)
            time_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
        else:
            time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/calendars/primary/events",
                headers=headers,
                params={
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "singleEvents": True,
                    "orderBy": "startTime",
                    "maxResults": 50
                }
            )
            data = response.json()
            
            events = []
            for event in data.get("items", []):
                events.append({
                    "id": event.get("id"),
                    "title": event.get("summary", "No title"),
                    "start": event.get("start", {}).get("dateTime") or event.get("start", {}).get("date"),
                    "end": event.get("end", {}).get("dateTime") or event.get("end", {}).get("date"),
                    "location": event.get("location", ""),
                    "description": event.get("description", "")[:300]
                })
            return events
    
    async def create_event(self, title: str, start: str, end: str, description: str = "", location: str = "") -> dict:
        """Create a calendar event."""
        headers = await self.client.get_headers()
        
        event = {
            "summary": title,
            "start": {"dateTime": start, "timeZone": "America/Los_Angeles"},
            "end": {"dateTime": end, "timeZone": "America/Los_Angeles"},
            "description": description,
            "location": location
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/calendars/primary/events",
                headers=headers,
                json=event
            )
            return response.json()
