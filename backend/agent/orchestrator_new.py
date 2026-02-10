"""
AI Agent Orchestrator - Plan-then-Execute Architecture

This orchestrator uses an LLM to:
1. Understand user intent and plan required actions
2. Ask clarifying questions when information is missing
3. Execute the plan using available tools
4. Generate a final response
"""

import os
import sys
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AsyncOpenAI
from tools.gmail import GmailTool
from tools.calendar import CalendarTool
from services.google_client import GoogleClient, load_settings


# Tool registry - describes available tools for the LLM planner
TOOLS = {
    "search_emails": {
        "description": "Search user's Gmail inbox for emails matching a query",
        "parameters": {
            "query": {"type": "string", "description": "Gmail search query (e.g., 'from:recruiter', 'subject:meeting', 'newer_than:7d')"},
            "max_results": {"type": "integer", "description": "Max emails to return (default 5)", "default": 5}
        },
        "required": ["query"]
    },
    "list_calendar_events": {
        "description": "List calendar events for a time period",
        "parameters": {
            "days_ahead": {"type": "integer", "description": "Number of days to look ahead (default 7)", "default": 7},
            "include_today": {"type": "boolean", "description": "Include all of today's events, even past ones", "default": True}
        },
        "required": []
    },
    "create_calendar_event": {
        "description": "Create a new calendar event",
        "parameters": {
            "title": {"type": "string", "description": "Event title/name"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "start_time": {"type": "string", "description": "Start time in HH:MM 24-hour format"},
            "end_time": {"type": "string", "description": "End time in HH:MM 24-hour format"},
            "location": {"type": "string", "description": "Event location (optional)", "default": ""},
            "description": {"type": "string", "description": "Event description (optional)", "default": ""}
        },
        "required": ["title", "date", "start_time", "end_time"]
    },
    "send_email": {
        "description": "Send an email",
        "parameters": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Email body content"}
        },
        "required": ["to", "subject", "body"]
    }
}


PLANNER_SYSTEM_PROMPT = """You are an AI assistant that helps users with email and calendar tasks.

Your job is to:
1. Understand what the user wants to do
2. Determine if you have enough information to proceed
3. Create an action plan using available tools

AVAILABLE TOOLS:
{tools_description}

TODAY'S DATE: {today}

RESPOND WITH JSON ONLY. Choose one of these response types:

TYPE 1 - Need more information:
{{
    "status": "needs_clarification",
    "question": "What time should I schedule the meeting?"
}}

TYPE 2 - Ready to execute:
{{
    "status": "ready",
    "plan": [
        {{
            "tool": "tool_name",
            "params": {{"param1": "value1"}},
            "purpose": "Brief description of what this step does"
        }}
    ],
    "response_hint": "Brief hint about how to summarize results to user"
}}

TYPE 3 - Just conversation (no tools needed):
{{
    "status": "conversation",
    "response": "Your direct response to the user"
}}

IMPORTANT:
- For calendar events, ALWAYS ask for time if not provided
- For emails, ALWAYS ask for recipient if not provided  
- Be smart about inferring: "tomorrow" = {tomorrow}, "next week" = 7 days from now
- If user says "today at 3pm for 2 hours", calculate end_time as "17:00"
- Parse durations: "for 3 hours" means add 3 hours to start time"""


RESPONSE_SYSTEM_PROMPT = """You are a helpful assistant. Given the user's request and the data retrieved, provide a clear and concise response.

FORMATTING RULES:
- Use markdown formatting
- Format dates as: Mon Feb 10 (not "February 10th, 2026")  
- Use bullet points for lists
- Be concise - under 200 words unless more detail needed
- No fluff like "I hope this helps"

FOR CALENDAR EVENTS:
📅 **Event Title**
• When: Day, Date at Time
• Location: (if available)

FOR EMAILS:
📧 **Subject**
• From: Sender
• Date: Day, Date
• Summary: Brief content summary"""


class Agent:
    def __init__(self):
        self.google = GoogleClient()
        self.gmail = GmailTool(self.google)
        self.calendar = CalendarTool(self.google)
        self.llm = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.settings = load_settings()
        self.pending_plan = None  # Store plan when waiting for clarification
    
    def _get_tools_description(self) -> str:
        """Format tools for the planner prompt."""
        lines = []
        for name, tool in TOOLS.items():
            params = ", ".join([
                f"{p}: {info['type']}" + (" (required)" if p in tool["required"] else " (optional)")
                for p, info in tool["parameters"].items()
            ])
            lines.append(f"- {name}({params}): {tool['description']}")
        return "\n".join(lines)
    
    async def _plan_action(self, prompt: str) -> dict:
        """Use LLM to create an action plan."""
        today = datetime.now()
        tomorrow = today + timedelta(days=1)
        
        system_prompt = PLANNER_SYSTEM_PROMPT.format(
            tools_description=self._get_tools_description(),
            today=today.strftime("%A, %B %d, %Y"),
            tomorrow=tomorrow.strftime("%Y-%m-%d")
        )
        
        response = await self.llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        
        try:
            return json.loads(response.choices[0].message.content)
        except json.JSONDecodeError:
            return {"status": "error", "message": "Failed to parse plan"}
    
    async def _execute_tool(self, tool_name: str, params: dict) -> dict:
        """Execute a single tool and return results."""
        try:
            if tool_name == "search_emails":
                query = params.get("query", "")
                max_results = params.get("max_results", 5)
                emails = await self.gmail.search_emails(query, max_results=max_results)
                return {"success": True, "data": emails, "type": "emails"}
            
            elif tool_name == "list_calendar_events":
                days_ahead = params.get("days_ahead", 7)
                include_today = params.get("include_today", True)
                events = await self.calendar.list_events(
                    days_ahead=days_ahead, 
                    include_past_today=include_today
                )
                return {"success": True, "data": events, "type": "events"}
            
            elif tool_name == "create_calendar_event":
                start_dt = f"{params['date']}T{params['start_time']}:00"
                end_dt = f"{params['date']}T{params['end_time']}:00"
                result = await self.calendar.create_event(
                    title=params["title"],
                    start=start_dt,
                    end=end_dt,
                    description=params.get("description", ""),
                    location=params.get("location", "")
                )
                if result.get("id"):
                    return {"success": True, "data": {"event": params, "id": result["id"]}, "type": "event_created"}
                else:
                    return {"success": False, "error": result.get("error", {}).get("message", "Unknown error")}
            
            elif tool_name == "send_email":
                result = await self.gmail.send_email(
                    to=params["to"],
                    subject=params["subject"],
                    body=params["body"]
                )
                return {"success": True, "data": result, "type": "email_sent"}
            
            else:
                return {"success": False, "error": f"Unknown tool: {tool_name}"}
        
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _execute_plan(self, plan: list) -> list:
        """Execute all steps in the plan and collect results."""
        results = []
        for step in plan:
            result = await self._execute_tool(step["tool"], step.get("params", {}))
            result["purpose"] = step.get("purpose", "")
            results.append(result)
        return results
    
    def _format_results_for_llm(self, results: list) -> str:
        """Format execution results for the response LLM."""
        formatted = []
        for i, result in enumerate(results):
            formatted.append(f"Step {i+1}: {result.get('purpose', 'Action')}")
            if result["success"]:
                if result["type"] == "emails":
                    emails = result["data"]
                    if emails:
                        for email in emails:
                            formatted.append(f"  Email: {email.get('subject', 'No subject')}")
                            formatted.append(f"    From: {email.get('from', 'Unknown')}")
                            formatted.append(f"    Date: {email.get('date', 'Unknown')}")
                            formatted.append(f"    Body: {email.get('body', '')[:500]}")
                    else:
                        formatted.append("  No emails found")
                
                elif result["type"] == "events":
                    events = result["data"]
                    if events:
                        for event in events:
                            formatted.append(f"  Event: {event.get('title', 'No title')}")
                            formatted.append(f"    Start: {event.get('start', 'Unknown')}")
                            formatted.append(f"    Location: {event.get('location', 'Not specified')}")
                    else:
                        formatted.append("  No events found")
                
                elif result["type"] == "event_created":
                    event = result["data"]["event"]
                    formatted.append(f"  Created: {event['title']} on {event['date']} at {event['start_time']}")
                
                elif result["type"] == "email_sent":
                    formatted.append("  Email sent successfully")
            else:
                formatted.append(f"  Error: {result.get('error', 'Unknown error')}")
        
        return "\n".join(formatted)
    
    async def _generate_response(self, prompt: str, results: list, response_hint: str = "") -> str:
        """Generate final response using LLM."""
        context = self._format_results_for_llm(results)
        
        user_message = f"""User's request: {prompt}

Results from actions:
{context}

{f"Hint: {response_hint}" if response_hint else ""}

Provide a helpful response to the user based on these results."""

        response = await self.llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": RESPONSE_SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            stream=True,
            max_tokens=500
        )
        
        return response
    
    async def process(self, prompt: str, is_followup: bool = False):
        """
        Process user request and yield status updates.
        
        Yields:
            {"type": "status", "content": "..."} - Progress updates
            {"type": "question", "content": "..."} - Clarifying question (pause for user)
            {"type": "text", "content": "..."} - Response text (streamed)
            {"type": "done", "content": ""} - Completion signal
        """
        
        # Check if connected
        if not self.google.is_connected():
            yield {"type": "text", "content": "⚠️ Please connect your Google account first (click the Google card on the right)."}
            yield {"type": "done", "content": ""}
            return
        
        # Step 1: Plan the action
        yield {"type": "status", "content": "Understanding your request..."}
        plan_result = await self._plan_action(prompt)
        
        # Handle different plan statuses
        if plan_result.get("status") == "needs_clarification":
            # Ask user for more information
            yield {"type": "question", "content": plan_result.get("question", "Could you provide more details?")}
            yield {"type": "done", "content": ""}
            return
        
        elif plan_result.get("status") == "conversation":
            # Direct response, no tools needed
            yield {"type": "text", "content": plan_result.get("response", "")}
            yield {"type": "done", "content": ""}
            return
        
        elif plan_result.get("status") == "ready":
            # Execute the plan
            plan = plan_result.get("plan", [])
            
            if not plan:
                yield {"type": "text", "content": "I understood your request but couldn't determine the right actions. Could you rephrase?"}
                yield {"type": "done", "content": ""}
                return
            
            # Execute each step
            for i, step in enumerate(plan):
                yield {"type": "status", "content": f"Step {i+1}: {step.get('purpose', 'Processing')}..."}
            
            yield {"type": "status", "content": "Executing plan..."}
            results = await self._execute_plan(plan)
            
            # Check for errors
            errors = [r for r in results if not r["success"]]
            if errors:
                error_msg = errors[0].get("error", "Unknown error")
                yield {"type": "text", "content": f"❌ Error: {error_msg}"}
                yield {"type": "done", "content": ""}
                return
            
            # Generate response
            yield {"type": "status", "content": "Generating response..."}
            response_hint = plan_result.get("response_hint", "")
            
            response_stream = await self._generate_response(prompt, results, response_hint)
            
            async for chunk in response_stream:
                if chunk.choices[0].delta.content:
                    yield {"type": "text", "content": chunk.choices[0].delta.content}
            
            yield {"type": "done", "content": ""}
        
        else:
            # Unknown status or error
            yield {"type": "text", "content": f"❌ Planning error: {plan_result.get('message', 'Unknown error')}"}
            yield {"type": "done", "content": ""}
