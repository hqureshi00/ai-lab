import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AsyncOpenAI
from tools.gmail import GmailTool
from tools.calendar import CalendarTool
from services.google_client import GoogleClient, load_settings


SYSTEM_PROMPT = """You are a helpful email and calendar assistant. You can answer questions about ANY emails - school, work, personal, recruiters, etc.

CRITICAL RULES:
1. READ THE FULL EMAIL BODY - extract relevant information
2. ANSWER THE USER'S SPECIFIC QUESTION directly
3. Be concise but complete
4. Format dates as: Mon Feb 10 (not "February 10th, 2026")
5. Skip fluff - no "I hope this helps" or lengthy intros

FOR EVENT-RELATED QUESTIONS:

📅 **Event Title Here**

• When: Mon Feb 10, 6:30 PM
• Where: Location
• ⚠️ Action: What to do

FOR GENERAL EMAIL QUESTIONS (recruiters, work, personal):

📧 **Subject Line**

• From: Sender Name
• Date: Mon Feb 10
• Summary: Brief summary of the email content
• Key Details: Important points, next steps, or requests

FORMATTING RULES:
- Each bullet on its own line
- Blank line between sections
- If asking about a specific sender, focus ONLY on their emails
- Quote relevant parts if the user asks "what did they say"
- If no matching emails found, say so clearly

Keep responses under 250 words unless more detail is needed."""


class Agent:
    def __init__(self):
        self.google = GoogleClient()
        self.gmail = GmailTool(self.google)
        self.calendar = CalendarTool(self.google)
        self.llm = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.settings = load_settings()
    
    async def process(self, prompt: str):
        """Process user request and yield status updates."""
        
        # Check if connected
        if not self.google.is_connected():
            yield {"type": "text", "content": "⚠️ Please connect your Google account first (click the Google card on the right)."}
            yield {"type": "done", "content": ""}
            return
        
        # Determine intent
        yield {"type": "status", "content": "Understanding your request..."}
        intent = self._classify_intent(prompt)
        
        context = ""
        school = self.settings.get("school_name", "")
        teachers = self.settings.get("teacher_names", [])
        
        if intent == "email_search":
            yield {"type": "status", "content": "Searching your emails..."}
            
            # Extract topic keywords from the prompt
            topic_keywords = self._extract_topic_keywords(prompt)
            
            # Build search query
            query = self._build_email_query(prompt, school, teachers, topic_keywords)
            
            try:
                emails = await self.gmail.search_emails(query, max_results=5)
                context = self._format_emails(emails)
            except Exception as e:
                yield {"type": "text", "content": f"❌ Error accessing Gmail: {str(e)}. Try reconnecting Google."}
                yield {"type": "done", "content": ""}
                return
        
        elif intent == "calendar_read":
            yield {"type": "status", "content": "Checking your calendar..."}
            try:
                events = await self.calendar.list_events(days_ahead=14)
                context = self._format_events(events)
            except Exception as e:
                yield {"type": "text", "content": f"❌ Error accessing Calendar: {str(e)}"}
                yield {"type": "done", "content": ""}
                return
        
        else:
            # General - search both, but extract topic keywords first
            yield {"type": "status", "content": "Searching emails and calendar..."}
            try:
                topic_keywords = self._extract_topic_keywords(prompt)
                query = self._build_email_query(prompt, school, teachers, topic_keywords)
                
                emails = await self.gmail.search_emails(query, max_results=5)
                events = await self.calendar.list_events(days_ahead=14)
                context = "EMAILS:\n" + self._format_emails(emails) + "\n\nCALENDAR:\n" + self._format_events(events)
            except Exception as e:
                context = f"Error fetching data: {e}"
        
        # Generate response
        yield {"type": "status", "content": "Generating response..."}
        
        school_context = f"for {school}" if school else ""
        teacher_context = f"Teachers: {', '.join(teachers)}" if teachers else ""
        
        full_prompt = f"""USER'S QUESTION: {prompt}

School: {school_context}
{teacher_context}

EMAIL/CALENDAR CONTENT TO SEARCH:
{context}

CRITICAL INSTRUCTIONS:
1. ANSWER THE USER'S SPECIFIC QUESTION - don't just list all events
2. If they ask "how to sign up" - look for registration links, email addresses, or instructions in the email body
3. If they ask about a specific event/topic - focus ONLY on information about that topic
4. Look for: URLs, email addresses, phone numbers, deadlines, instructions
5. If the answer is in the email body, quote or paraphrase the relevant part
6. If no answer found, say "I couldn't find specific information about [topic] in your emails"

FORMATTING:
- Each bullet on its own line
- Blank line between sections
- Highlight action items with ⚠️"""

        try:
            response = await self.llm.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": full_prompt}
                ],
                stream=True,
                max_tokens=500
            )
            
            async for chunk in response:
                if chunk.choices[0].delta.content:
                    yield {"type": "text", "content": chunk.choices[0].delta.content}
            
            yield {"type": "done", "content": ""}
            
        except Exception as e:
            yield {"type": "text", "content": f"❌ Error generating response: {str(e)}"}
            yield {"type": "done", "content": ""}
    
    def _classify_intent(self, prompt: str) -> str:
        """Classify user intent."""
        prompt_lower = prompt.lower()
        
        # Patterns that indicate email search
        email_patterns = [
            "email", "inbox", "ptsa", "pta", "newsletter", "message", 
            "sent", "received", "event", "events", "upcoming", "happening",
            "from", "recruiter", "last", "recent", "latest"
        ]
        question_words = [
            "how", "where", "when", "what time", "sign up", "register", 
            "rsvp", "cost", "price", "deadline", "what was", "what did",
            "show me", "find", "search"
        ]
        calendar_words = ["calendar", "schedule", "busy", "free", "meeting", "appointment"]
        
        # Follow-up questions or email queries
        if any(word in prompt_lower for word in question_words):
            return "email_search"
        if any(word in prompt_lower for word in email_patterns):
            return "email_search"
        elif any(word in prompt_lower for word in calendar_words):
            return "calendar_read"
        
        return "general"
    
    def _extract_topic_keywords(self, prompt: str) -> list[str]:
        """Extract topic-specific keywords from user's question."""
        prompt_lower = prompt.lower()
        
        # Common stop words to ignore
        stop_words = {
            "how", "do", "i", "to", "the", "a", "an", "is", "are", "what", "when", 
            "where", "can", "could", "would", "should", "about", "for", "up", "sign",
            "tell", "me", "my", "more", "info", "information", "details", "find",
            "get", "show", "list", "any", "there", "this", "that", "it", "of", "in",
            "on", "at", "with", "from", "by", "and", "or", "but", "if", "then"
        }
        
        # Extract words that might be topics
        words = prompt_lower.replace("?", "").replace("!", "").replace(",", "").split()
        topic_words = []
        
        for word in words:
            # Skip short words and stop words
            if len(word) > 3 and word not in stop_words:
                topic_words.append(word)
        
        # Also look for multi-word phrases
        phrases = []
        if "cooking class" in prompt_lower:
            phrases.append("cooking")
        if "field trip" in prompt_lower:
            phrases.append("field trip")
        if "book fair" in prompt_lower:
            phrases.append("book fair")
        if "parent night" in prompt_lower or "parents night" in prompt_lower:
            phrases.append("parent")
        if "science fair" in prompt_lower:
            phrases.append("science fair")
        if "picture day" in prompt_lower:
            phrases.append("picture")
        if "spirit week" in prompt_lower:
            phrases.append("spirit")
        
        return list(set(topic_words + phrases))
    
    def _extract_sender(self, prompt: str) -> str:
        """Extract sender name/company from 'from X' patterns."""
        import re
        prompt_lower = prompt.lower()
        
        # Common patterns for sender queries
        patterns = [
            r"from\s+([a-zA-Z0-9]+(?:\s+[a-zA-Z0-9]+)?)",  # "from meta" or "from meta recruiter"
            r"([a-zA-Z0-9]+)\s+recruiter",  # "meta recruiter"
            r"([a-zA-Z0-9]+)\s+email",  # "amazon email"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, prompt_lower)
            if match:
                sender = match.group(1).strip()
                # Filter out common words that aren't senders
                skip_words = {"the", "my", "last", "latest", "recent", "an", "a", "any", "what", "was", "their"}
                if sender.lower() not in skip_words:
                    return sender
        
        return ""
    
    def _build_email_query(self, prompt: str, school: str, teachers: list, topic_keywords: list) -> str:
        """Build Gmail search query from prompt and settings."""
        prompt_lower = prompt.lower()
        search_parts = []
        
        # Detect "from X" pattern - most important for sender-specific queries
        sender = self._extract_sender(prompt_lower)
        if sender:
            search_parts.append(f"from:{sender}")
            # For sender queries, just return with minimal filters
            if "last" in prompt_lower or "latest" in prompt_lower or "recent" in prompt_lower:
                return f"from:{sender}"
        
        # Only add school context if this seems like a school query
        school_words = ["school", "ptsa", "pta", "teacher", "class", "homework", "event", "events"]
        is_school_query = any(word in prompt_lower for word in school_words)
        
        if is_school_query:
            # Add topic keywords for topic-specific searches
            if topic_keywords:
                keyword_query = " OR ".join(topic_keywords[:5])
                search_parts.append(f"({keyword_query})")
            
            if school:
                search_parts.append(school)
            
            if "ptsa" in prompt_lower or "pta" in prompt_lower:
                search_parts.append("(PTSA OR PTA)")
            
            if "teacher" in prompt_lower and teachers:
                teacher_query = " OR ".join(teachers)
                search_parts.append(f"({teacher_query})")
        elif topic_keywords and not sender:
            # Non-school query with topic keywords
            keyword_query = " OR ".join(topic_keywords[:5])
            search_parts.append(f"({keyword_query})")
        
        # Build final query
        if search_parts:
            query = " ".join(search_parts)
        else:
            query = "school OR PTSA OR newsletter"
        
        # Add time filter
        query += " newer_than:30d"
        
        return query
    
    def _format_emails(self, emails: list) -> str:
        if not emails:
            return "No emails found matching your search."
        
        formatted = []
        for e in emails:
            # Use body if available, otherwise use snippet
            body = e.get('body', '').strip()
            snippet = e.get('snippet', '').strip()
            
            if not body and snippet:
                body = snippet
            elif not body:
                body = "(no body content found)"
            else:
                body = body[:3000]  # Limit size
            
            formatted.append(f"""
========== EMAIL ==========
From: {e['from']}
Date: {e['date']}
Subject: {e['subject']}
Preview: {snippet[:200] if snippet else 'N/A'}

FULL EMAIL BODY (read this carefully for dates/events/action items):
{body}
========== END EMAIL ==========""")
        return "\n\n".join(formatted)
    
    def _format_events(self, events: list) -> str:
        if not events:
            return "No upcoming events found."
        
        formatted = []
        for e in events:
            formatted.append(f"• {e['title']} | {e['start']} | {e['location']}")
        return "\n".join(formatted)
