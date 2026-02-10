# AI Assistant Demo

Agentic AI assistant with Gmail/Calendar integration, real-time status updates, and conversation memory.

## Quick Start

```bash
# Terminal 1 - Backend (with auto-reload)
cd /path/to/ai-lab
PYTHONPATH=. uvicorn backend.main:app --reload --port 8000

# Terminal 2 - Frontend  
cd frontend && python -m http.server 3000
```

Open http://localhost:3000

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (port 3000)                           │
│                          index.html / app.js / styles.css                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ HTTP POST /chat (SSE streaming)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND (port 8000)                            │
│                              FastAPI / Uvicorn                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                        AGENT ORCHESTRATOR                             │  │
│  │                    (Plan-then-Execute Architecture)                   │  │
│  │                                                                       │  │
│  │  1. _plan_action() ─── LLM decides: ask question? execute tools?     │  │
│  │  2. _execute_plan() ── Run tools sequentially                        │  │
│  │  3. _generate_response() ── LLM formats final answer                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                      │                                      │
│              ┌───────────────────────┼───────────────────────┐              │
│              ▼                       ▼                       ▼              │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐        │
│  │   GmailTool     │     │  CalendarTool   │     │   OpenAI LLM    │        │
│  │  - search       │     │  - list_events  │     │  - gpt-4o-mini  │        │
│  │  - send_email   │     │  - create_event │     │                 │        │
│  └─────────────────┘     └─────────────────┘     └─────────────────┘        │
│              │                       │                                      │
│              └───────────────────────┘                                      │
│                          │                                                  │
│                          ▼                                                  │
│              ┌─────────────────────┐                                        │
│              │    GoogleClient     │                                        │
│              │  - OAuth 2.0 tokens │                                        │
│              │  - Token refresh    │                                        │
│              └─────────────────────┘                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │         Google APIs             │
                    │   Gmail API / Calendar API      │
                    └─────────────────────────────────┘
```

---

## Orchestrator Design: Plan-then-Execute

The AI agent uses a **Plan-then-Execute** architecture where an LLM decides what actions to take.

### Flow

```
User Message
     │
     ▼
┌─────────────────┐
│  _plan_action() │  ◄── LLM analyzes request, returns JSON
└────────┬────────┘
         │
         ├──► needs_clarification ──► Ask user question (with memory)
         │
         ├──► conversation ──► Direct response (no tools needed)
         │
         └──► ready ──► Execute plan
                            │
                            ▼
                   ┌─────────────────┐
                   │ _execute_plan() │  ◄── Run tools sequentially
                   └────────┬────────┘
                            │
                            ▼
                   ┌─────────────────────┐
                   │ _generate_response()│  ◄── LLM formats results
                   └─────────────────────┘
                            │
                            ▼
                      Stream to user
```

### Available Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `search_emails` | Search Gmail inbox | `query`, `max_results` |
| `list_calendar_events` | List/search calendar | `date_range`, `search_term` |
| `create_calendar_event` | Add calendar event | `title`, `date`, `start_time`, `end_time` |
| `send_email` | Send email | `to`, `subject`, `body` |

### Key Features

1. **Multi-step Plans**: "Send email about dinner at 6pm" → Creates calendar event AND sends email
2. **Conversation Memory**: Remembers pending requests when asking for clarification
3. **Email Validation**: Always asks for email address if not explicitly provided
4. **Smart Date Parsing**: Understands "today", "tomorrow", "next Monday", etc.

---

## Streaming Response Types

The backend streams JSON events via Server-Sent Events (SSE):

| Type | Purpose | Example |
|------|---------|---------|
| `status` | Progress updates | `{"type": "status", "content": "Searching emails..."}` |
| `question` | Needs user input | `{"type": "question", "content": "What is Sarah's email?"}` |
| `text` | Response content | `{"type": "text", "content": "Found 3 emails..."}` |
| `done` | Completion signal | `{"type": "done", "content": ""}` |

---

## Project Structure

```
ai-lab/
├── backend/
│   ├── main.py                 # FastAPI app, endpoints
│   ├── agent/
│   │   ├── orchestrator_new.py # Plan-then-Execute agent (active)
│   │   └── orchestrator.py     # Legacy rule-based agent
│   ├── tools/
│   │   ├── gmail.py            # Gmail search/send
│   │   └── calendar.py         # Calendar list/create
│   ├── services/
│   │   └── google_client.py    # OAuth token management
│   └── .env                    # Secrets (GOOGLE_CLIENT_ID, OPENAI_API_KEY)
├── frontend/
│   ├── index.html
│   ├── app.js                  # Chat UI, SSE handling
│   └── styles.css              # Dark theme styles
└── README.md
```

---

## Environment Variables

Create `backend/.env`:

```env
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
OPENAI_API_KEY=sk-...
```

---

## Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create OAuth 2.0 credentials (Web application)
3. Add authorized redirect URI: `http://localhost:8000/auth/callback`
4. Enable Gmail API and Calendar API
5. Add test users in OAuth consent screen

---

## Example Prompts

| Prompt | What Happens |
|--------|--------------|
| "Send email to Junaid saying hello" | Asks for email → Sends email |
| "When is dinner with Sarah?" | Searches calendar for matching events |
| "Any emails from school about field trips?" | Searches Gmail inbox |
| "Add dentist tomorrow at 3pm for an hour" | Creates calendar event |
| "What's on my calendar this week?" | Lists upcoming events |
| "Email john@test.com about the meeting tomorrow" | Creates event + sends invite |
