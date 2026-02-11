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
| `reply_to_email` | Reply to email thread | `thread_id`, `body` |

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
│   ├── storage/                # Persisted data
│   │   ├── tokens.json         # OAuth tokens
│   │   └── settings.json       # User settings
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

## Google OAuth Setup (for local run)

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

---

## Data Architecture & Persistence

### Current vs Planned Storage

```
┌─────────────────────────────────────────────────────────────────┐
│                      PERSISTENT STORAGE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  CURRENTLY IMPLEMENTED:                                          │
│  ├── tokens.json        → OAuth tokens (survives restart)       │
│  └── settings.json      → School name, teacher list             │
│                                                                  │
│  PLANNED (not yet implemented):                                  │
│  ├── contacts.json      → Name → email mappings                 │
│  ├── preferences.json   → Meeting duration, email style         │
│  ├── facts.json         → User context (kids, timezone)         │
│  └── history.json       → Conversation history                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### How Persistent Data Feeds Into the System

| Data Type | Used By | Purpose | Example |
|-----------|---------|---------|---------|
| **Contacts** | Orchestrator | Skip "what's their email?" | `sarah → sarah@example.com` |
| **Preferences** | Orchestrator | Default values for tools | `meeting_duration: 30min` |
| **User Facts** | Conversation | Personalize responses | `2 kids: Emma (3rd), Liam (K)` |
| **Chat History** | Conversation | Reference previous messages | `"like I mentioned earlier..."` |

### Data Flow: Orchestrator vs Conversation Use

```
┌─────────────────────────────────────────────────────────────────┐
│                        PROCESS FLOW                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. User: "email sarah about tomorrow's meeting"                │
│                                                                  │
│  2. _plan_action():                                             │
│     ├── Load contacts.json          ◄── ORCHESTRATOR USE        │
│     ├── Find: sarah → sarah@example.com                         │
│     └── Plan: send_email(to="sarah@example.com", ...)           │
│                                                                  │
│  3. _execute_tool():                                            │
│     ├── Load preferences.json       ◄── ORCHESTRATOR USE        │
│     └── Use: email_style = "concise"                            │
│                                                                  │
│  4. Generate response:                                          │
│     ├── Load facts.json             ◄── CONVERSATION USE        │
│     ├── Load history.json (last 5 messages)                     │
│     └── Inject into system prompt for personalization           │
│                                                                  │
│  5. LLM response personalized to user context                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Conversation Memory (Current Implementation)

```python
# In orchestrator_new.py - IN-MEMORY ONLY (lost on restart)
conversation_memory = {
    "pending_request": None,  # Stores incomplete request needing clarification
    "last_context": None      # Stores last retrieved context for follow-ups
}
```

**Example Flow:**
1. User: "send email to sarah" → LLM returns `needs_clarification`
2. System stores `pending_request = {"original_prompt": "send email to sarah"}`
3. System asks: "What is Sarah's email address?"
4. User: "sarah@example.com"
5. System detects email, merges: "send email to sarah to sarah@example.com"
6. Executes send_email tool

### Future Enhancements

| Feature | Storage | Benefit |
|---------|---------|---------|
| **Contacts Memory** | `contacts.json` | No more "what's their email?" |
| **Chat History** | `history.json` | Enables "like I said before" references |
| **User Facts** | `facts.json` | Personalized responses (kids' names, school) |
| **Learning Preferences** | `preferences.json` | Remember meeting length, email style |

---

## GCP Deployment Architecture

### Production Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              GOOGLE CLOUD                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐         ┌─────────────────────────────────────────┐   │
│  │   Cloud CDN     │         │           Cloud Run                     │   │
│  │   (Frontend)    │         │         (Backend API)                   │   │
│  │                 │         │                                         │   │
│  │  - index.html   │ ──────► │  - FastAPI app                         │   │
│  │  - app.js       │   HTTPS │  - Agent orchestrator                  │   │
│  │  - styles.css   │         │  - SSE streaming                       │   │
│  │                 │         │                                         │   │
│  │  Cloud Storage  │         │  Container: python:3.11-slim           │   │
│  │  (static files) │         │  Memory: 512MB-1GB                     │   │
│  │                 │         │  CPU: 1                                │   │
│  └─────────────────┘         └─────────────────────────────────────────┘   │
│                                        │                                    │
│                                        │                                    │
│          ┌─────────────────────────────┼─────────────────────────────┐     │
│          ▼                             ▼                             ▼     │
│  ┌───────────────┐         ┌───────────────────┐         ┌──────────────┐ │
│  │ Secret Manager│         │     Firestore     │         │  Cloud       │ │
│  │               │         │   (User Data)     │         │  Logging     │ │
│  │ - OPENAI_KEY  │         │                   │         │              │ │
│  │ - GOOGLE_     │         │ users/{uid}/      │         │ - Requests   │ │
│  │   CLIENT_ID   │         │   ├── tokens      │         │ - Errors     │ │
│  │ - GOOGLE_     │         │   ├── settings    │         │ - Agent logs │ │
│  │   CLIENT_     │         │   ├── contacts    │         │              │ │
│  │   SECRET      │         │   └── preferences │         │              │ │
│  └───────────────┘         └───────────────────┘         └──────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │         External APIs           │
                    │  - Google Gmail API             │
                    │  - Google Calendar API          │
                    │  - OpenAI API                   │
                    └─────────────────────────────────┘
```

### Secure OAuth Flow (Production)

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  User    │     │ Frontend │     │ Backend  │     │ Google   │
│ Browser  │     │ (CDN)    │     │(CloudRun)│     │  OAuth   │
└────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                │                │
     │ 1. Click       │                │                │
     │    "Connect    │                │                │
     │     Google"    │                │                │
     │───────────────►│                │                │
     │                │                │                │
     │                │ 2. Redirect to │                │
     │                │    /auth/login │                │
     │                │───────────────►│                │
     │                │                │                │
     │◄───────────────┼────────────────│ 3. Redirect   │
     │         302 to Google OAuth     │    to Google  │
     │                │                │───────────────►│
     │                │                │                │
     │─────────────────────────────────────────────────►│
     │                    4. User authorizes            │
     │◄─────────────────────────────────────────────────│
     │         5. Redirect to /auth/callback?code=xxx   │
     │                │                │                │
     │───────────────────────────────►│                │
     │                │                │ 6. Exchange   │
     │                │                │    code for   │
     │                │                │    tokens     │
     │                │                │───────────────►│
     │                │                │◄───────────────│
     │                │                │  access_token │
     │                │                │  refresh_token│
     │                │                │                │
     │                │                │ 7. Store in   │
     │                │                │    Firestore  │
     │                │                │    (encrypted)│
     │                │                │                │
     │◄───────────────┼────────────────│ 8. Redirect  │
     │         Redirect to frontend    │    to app     │
     │                │                │                │
```

### Security Design

#### Token Storage (Firestore)

```
firestore/
└── users/
    └── {user_id}/
        ├── tokens (subcollection)
        │   └── google
        │       ├── access_token: "ya29.xxx" (encrypted)
        │       ├── refresh_token: "1//xxx" (encrypted)
        │       ├── expires_at: timestamp
        │       └── updated_at: timestamp
        │
        ├── settings
        │   ├── school_name: "xyz Elementary"
        │   └── teacher_names: ["Mrs. Smith"]
        │
        └── contacts
            ├── sarah: "sarah@example.com"
            └── jay: "junaid@example.com"
```

#### Secrets Management

```yaml
# Secrets in Google Secret Manager (NOT in code or env vars)
secrets:
  - OPENAI_API_KEY
  - GOOGLE_CLIENT_ID  
  - GOOGLE_CLIENT_SECRET
  - ENCRYPTION_KEY  # For encrypting tokens in Firestore
```

### Cloud Run Configuration

```yaml
# service.yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: ai-assistant-backend
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "0"
        autoscaling.knative.dev/maxScale: "10"
    spec:
      containerConcurrency: 80
      timeoutSeconds: 300  # 5 min for long LLM calls
      containers:
        - image: gcr.io/PROJECT_ID/ai-assistant:latest
          ports:
            - containerPort: 8000
          resources:
            limits:
              memory: 1Gi
              cpu: "1"
          env:
            - name: GOOGLE_CLIENT_ID
              valueFrom:
                secretKeyRef:
                  name: google-client-id
                  key: latest
            - name: OPENAI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: openai-api-key
                  key: latest
```

### Deployment Commands

```bash
# 1. Build and push container
gcloud builds submit --tag gcr.io/PROJECT_ID/ai-assistant

# 2. Deploy to Cloud Run
gcloud run deploy ai-assistant-backend \
  --image gcr.io/PROJECT_ID/ai-assistant \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-secrets="OPENAI_API_KEY=openai-api-key:latest,GOOGLE_CLIENT_ID=google-client-id:latest,GOOGLE_CLIENT_SECRET=google-client-secret:latest"

# 3. Deploy frontend to Cloud Storage + CDN
gsutil -m cp -r frontend/* gs://BUCKET_NAME/
gcloud compute backend-buckets create frontend-bucket --gcs-bucket-name=BUCKET_NAME
```


### Security Checklist (for prod)

- [ ] OAuth tokens encrypted in Firestore (not plain text)
- [ ] Secrets in Secret Manager (not environment variables in code)
- [ ] HTTPS only (Cloud Run default)
- [ ] CORS restricted to frontend domain only
- [ ] Token refresh handled server-side
- [ ] User data scoped by user ID (no cross-user access)
- [ ] Rate limiting on /chat endpoint
- [ ] Input validation on all endpoints
- [ ] Audit logging enabled
- [ ] OAuth consent screen in production mode (not test)
