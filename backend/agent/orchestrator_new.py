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
        "description": "Search user's Gmail inbox for emails. Use for finding emails from teachers, school, recruiters, or any sender. Also use to find info about events, deadlines, permission slips.",
        "parameters": {
            "query": {"type": "string", "description": "Gmail search query. Examples: 'from:teacher', 'subject:field trip', 'from:school newer_than:7d', 'permission slip'"},
            "max_results": {"type": "integer", "description": "Max emails to return", "default": 5}
        },
        "required": ["query"]
    },
    "list_calendar_events": {
        "description": "List/search calendar events. Use for checking schedule, finding when something is, checking availability, or looking up existing events. ALWAYS use this for 'when is' or 'do I have' questions.",
        "parameters": {
            "date_range": {"type": "string", "description": "Time range: 'today', 'tomorrow', 'week', 'month'", "default": "week"},
            "search_term": {"type": "string", "description": "Filter events containing this text (e.g., 'dentist', 'soccer', 'dinner sarah')", "default": ""}
        },
        "required": []
    },
    "create_calendar_event": {
        "description": "Create/add/schedule a new calendar event. Use for appointments, meetings, playdates, activities, reminders.",
        "parameters": {
            "title": {"type": "string", "description": "Event title (e.g., 'Dentist appointment', 'Soccer practice', 'Dinner with Sarah')"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "start_time": {"type": "string", "description": "Start time in HH:MM 24-hour format"},
            "end_time": {"type": "string", "description": "End time in HH:MM 24-hour format"},
            "location": {"type": "string", "description": "Location (optional)", "default": ""},
            "description": {"type": "string", "description": "Notes/description (optional)", "default": ""}
        },
        "required": ["title", "date", "start_time", "end_time"]
    },
    "send_email": {
        "description": "Send/compose an email. Use for contacting teachers, parents, confirming appointments, RSVPs, sending info.",
        "parameters": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Email body - be helpful and write a complete, friendly message"}
        },
        "required": ["to", "subject", "body"]
    },
    "reply_to_email": {
        "description": "Reply to an email thread. Use when user wants to respond to a specific email.",
        "parameters": {
            "thread_id": {"type": "string", "description": "The thread ID to reply to"},
            "body": {"type": "string", "description": "Reply message body"}
        },
        "required": ["thread_id", "body"]
    }
}


PLANNER_SYSTEM_PROMPT = """You are a smart assistant for busy parents. You help with emails, calendar, scheduling, and family coordination.

TODAY'S DATE: {today}
TOMORROW: {tomorrow}

AVAILABLE TOOLS:
{tools_description}

COMMON PARENT TASKS YOU HANDLE:
- Check/add calendar events (appointments, activities, playdates)
- Search emails from school, teachers, coaches
- Send emails to teachers, other parents, for RSVPs
- Find info about events, deadlines, permission slips
- Coordinate schedules and send invites

RESPOND WITH JSON ONLY:

TYPE 1 - Need more information:
{{
    "status": "needs_clarification", 
    "question": "What time should I schedule the dentist appointment?"
}}

TYPE 2 - Ready to execute (can have MULTIPLE steps):
{{
    "status": "ready",
    "plan": [
        {{"tool": "create_calendar_event", "params": {{...}}, "purpose": "Add dinner to calendar"}},
        {{"tool": "send_email", "params": {{...}}, "purpose": "Send invite to Sarah"}}
    ],
    "response_hint": "Summarize what was done"
}}

TYPE 3 - Just conversation:
{{
    "status": "conversation",
    "response": "Your response here"
}}

CRITICAL RULES:

1. MULTI-STEP: If user wants to "send email about event" or "invite someone to dinner", do BOTH calendar + email

2. SMART PARSING:
   - "today at 6pm" → date={today_iso}, start_time="18:00"
   - "tomorrow at 2pm for 1 hour" → end_time="15:00"
   - "next Monday" → calculate the actual date
   - "in 30 minutes" → calculate from current time

3. **WHEN/FIND/CHECK QUESTIONS - ALWAYS SEARCH, NEVER ASK FOR DATES:**
   - "when is X?" → list_calendar_events with search_term=X, date_range="week" (search upcoming week)
   - "do I have any X?" → list_calendar_events with search_term=X
   - "is there a X scheduled?" → list_calendar_events with search_term=X
   - "what time is X?" → list_calendar_events with search_term=X
   - These are LOOKUP questions - the user doesn't know the date, that's why they're asking!

4. **EMAIL ADDRESS REQUIRED - NEVER ASSUME OR GUESS:**
   - MANDATORY: The "to" parameter for send_email MUST be a valid email address with @ symbol
   - If user says "send email to Sarah" or "email Junaid", you MUST ask for the email address first!
   - NEVER put a name like "Sarah" or "Junaid" as the "to" field - this will fail
   - Only proceed with send_email if the user EXPLICITLY provided something like "sarah@email.com" or "junaid@gmail.com"
   - Example: "email my teacher" → {{"status": "needs_clarification", "question": "What is your teacher's email address?"}}
   - Example: "announce to Junaid that..." → {{"status": "needs_clarification", "question": "What is Junaid's email address?"}}
   - Example: "send to john@gmail.com" → OK to proceed, address was given

5. **EMAIL CONTENT - NO PLACEHOLDERS:**
   - Write natural, complete emails without any placeholder text
   - NEVER use [Your Name], [Your Email], [Date], or any bracketed placeholders
   - If you don't know the sender's name, just end with "Thanks!" or similar
   - If you don't know specific details, omit them rather than using placeholders
   - Keep emails friendly and conversational

6. For "send email to X about Y" - compose a helpful email body, don't just say the subject

7. ONLY ASK FOR CLARIFICATION when you need info the user didn't provide:
   - ASK: User says "add dentist appointment" but no time/date given
   - ASK: User says "email Sarah" but no email address given
   - DON'T ASK: User says "when is the party?" - just search for it!

EXAMPLES:

User: "Send email to sarah at sarah@email.com about dinner tonight at 6"
→ Create event "Dinner with Sarah" at 18:00 today AND send email inviting her

User: "When is dinner with Sarah?"
→ {{"status": "ready", "plan": [{{"tool": "list_calendar_events", "params": {{"search_term": "dinner sarah", "date_range": "week"}}}}]}}

User: "When's my dentist appointment?"
→ {{"status": "ready", "plan": [{{"tool": "list_calendar_events", "params": {{"search_term": "dentist", "date_range": "month"}}}}]}}

User: "Do I have anything scheduled tomorrow?"
→ {{"status": "ready", "plan": [{{"tool": "list_calendar_events", "params": {{"date_range": "tomorrow"}}}}]}}

User: "Any emails from the school about field trips?"
→ {{"status": "ready", "plan": [{{"tool": "search_emails", "params": {{"query": "from:school field trip"}}}}]}}

User: "Add dentist tomorrow at 3pm"
→ {{"status": "needs_clarification", "question": "How long is the appointment?"}}

User: "Email Sarah about the party"
→ {{"status": "needs_clarification", "question": "What is Sarah's email address?"}}

User: "Send email to my teacher about Tommy being sick"
→ {{"status": "needs_clarification", "question": "What is your teacher's email address?"}}

User: "Schedule soccer practice every Tuesday at 4pm"
→ Create one event (recurring events not yet supported, mention this)

User: "What's on my calendar this week?"
→ List events with date_range="week"

User: "Email john@example.com about the meeting tomorrow"
→ Proceed with send_email since address was explicitly provided"""


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


# Simple session store for pending requests (single user for now)
_pending_request = {
    "original_prompt": None,
    "question_asked": None
}


class Agent:
    def __init__(self):
        self.google = GoogleClient()
        self.gmail = GmailTool(self.google)
        self.calendar = CalendarTool(self.google)
        self.llm = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.settings = load_settings()
    
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
            today_iso=today.strftime("%Y-%m-%d"),
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
                date_range = params.get("date_range", "week")
                search_term = params.get("search_term", "").lower()
                
                from datetime import datetime, timedelta
                today = datetime.now().date()
                
                # Map date_range to days_ahead and filter dates
                if date_range == "today":
                    days_ahead = 1
                    filter_dates = [today]
                elif date_range == "tomorrow":
                    days_ahead = 2
                    filter_dates = [today + timedelta(days=1)]
                elif date_range == "week":
                    days_ahead = 7
                    filter_dates = None  # No date filtering
                elif date_range == "month":
                    days_ahead = 30
                    filter_dates = None
                else:
                    days_ahead = 7
                    filter_dates = None
                
                events = await self.calendar.list_events(
                    days_ahead=days_ahead, 
                    include_past_today=True
                )
                
                # Filter by specific dates if needed (for today/tomorrow)
                if filter_dates:
                    filtered_events = []
                    for e in events:
                        event_date_str = e.get("start", "")[:10]  # Get YYYY-MM-DD part
                        try:
                            event_date = datetime.fromisoformat(event_date_str).date()
                            if event_date in filter_dates:
                                filtered_events.append(e)
                        except:
                            pass
                    events = filtered_events
                
                # Filter by search term if provided (check all words)
                if search_term:
                    search_words = search_term.lower().split()
                    filtered = []
                    for e in events:
                        text = f"{e.get('title', '')} {e.get('description', '')} {e.get('location', '')}".lower()
                        if any(word in text for word in search_words):
                            filtered.append(e)
                    events = filtered
                
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
                to_address = params.get("to", "")
                
                # SAFETY CHECK: Validate email address format
                # Must contain @ and look like a real email, not just a name
                import re
                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                if not re.match(email_pattern, to_address):
                    return {
                        "success": False, 
                        "error": f"Invalid or missing email address. Got: '{to_address}'. Please provide a valid email address.",
                        "needs_clarification": True,
                        "question": f"What is the email address for {to_address}?" if to_address else "What email address should I send this to?"
                    }
                
                result = await self.gmail.send_email(
                    to=to_address,
                    subject=params["subject"],
                    body=params["body"]
                )
                return {"success": True, "data": {"to": to_address, "subject": params["subject"]}, "type": "email_sent"}
            
            elif tool_name == "reply_to_email":
                # For now, reply is not fully implemented - would need thread support
                return {"success": False, "error": "Reply to email not yet implemented. Please compose a new email."}
            
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
                    data = result["data"]
                    formatted.append(f"  Email sent to: {data.get('to', 'recipient')}")
                    formatted.append(f"  Subject: {data.get('subject', 'No subject')}")
                
                elif result["type"] == "shopping_preferences_learned":
                    data = result["data"]
                    formatted.append(f"  Orders found: {data.get('orders_found', 0)}")
                    formatted.append(f"  Items extracted: {data.get('items_extracted', 0)}")
                    formatted.append(f"  Message: {data.get('message', 'Preferences learned')}")
                
                elif result["type"] == "shopping_preference":
                    data = result["data"]
                    item = data.get("item", "item")
                    pref = data.get("preference")
                    if pref:
                        formatted.append(f"  Preference for '{item}': {pref.get('name', 'Unknown')}")
                        formatted.append(f"    Ordered {pref.get('times_ordered', 0)} times before")
                    else:
                        formatted.append(f"  No preference found for '{item}'")
                
                elif result["type"] == "shopping_list":
                    data = result["data"]
                    formatted.append(data.get("formatted", "Shopping list built"))
                
                elif result["type"] == "order_history":
                    orders = result["data"].get("orders", [])
                    if orders:
                        formatted.append(f"  Found {len(orders)} recent orders:")
                        for order in orders[:5]:  # Show first 5
                            formatted.append(f"  Order {order.get('order_id', 'Unknown')} on {order.get('date', 'Unknown')}:")
                            for item in order.get("items", [])[:3]:
                                formatted.append(f"    - {item.get('name', 'Unknown item')}")
                    else:
                        formatted.append("  No order history found. Try running 'learn shopping preferences' first.")
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
        global _pending_request
        
        # Check if connected
        if not self.google.is_connected():
            yield {"type": "text", "content": "⚠️ Please connect your Google account first (click the Google card on the right)."}
            yield {"type": "done", "content": ""}
            return
        
        # Check if this looks like an answer to a pending question
        # (short response, contains email-like text, or is a simple answer)
        if _pending_request["original_prompt"]:
            # User is answering a previous question - combine with original request
            import re
            # Check if response contains an email or is short (likely an answer)
            is_email = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', prompt)
            is_short = len(prompt.split()) <= 10
            
            if is_email or is_short:
                # Combine original prompt with the answer
                original = _pending_request["original_prompt"]
                question = _pending_request["question_asked"]
                prompt = f"{original}\n\n(User was asked: '{question}' and answered: '{prompt}')"
                _pending_request = {"original_prompt": None, "question_asked": None}
        
        # Step 1: Plan the action
        yield {"type": "status", "content": "Understanding your request..."}
        plan_result = await self._plan_action(prompt)
        
        # Handle different plan statuses
        if plan_result.get("status") == "needs_clarification":
            # Store the original request for when user answers
            _pending_request["original_prompt"] = prompt
            _pending_request["question_asked"] = plan_result.get("question", "")
            
            # Ask user for more information
            yield {"type": "question", "content": plan_result.get("question", "Could you provide more details?")}
            yield {"type": "done", "content": ""}
            return
        
        # Clear pending request since we're proceeding
        _pending_request = {"original_prompt": None, "question_asked": None}
        
        if plan_result.get("status") == "conversation":
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
            
            # Check for errors - if needs clarification, ask the question
            errors = [r for r in results if not r["success"]]
            if errors:
                first_error = errors[0]
                if first_error.get("needs_clarification"):
                    # Tool needs more info - ask the user
                    yield {"type": "question", "content": first_error.get("question", "Could you provide more details?")}
                    yield {"type": "done", "content": ""}
                    return
                else:
                    error_msg = first_error.get("error", "Unknown error")
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
