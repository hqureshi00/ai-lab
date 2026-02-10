const API = 'http://localhost:8000';
const chat = document.getElementById('chat');
const form = document.getElementById('form');
const input = document.getElementById('input');
const btn = document.getElementById('btn');

let busy = false;

// Auto-resize
input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 100) + 'px';
});

// Enter to send
input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !busy) {
        e.preventDefault();
        form.dispatchEvent(new Event('submit'));
    }
});

function scroll() {
    chat.scrollTop = chat.scrollHeight;
}

function formatMarkdown(text) {
    // Escape HTML first
    let html = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    
    // Bold: **text**
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    
    // Newlines to <br>
    html = html.replace(/\n/g, '<br>');
    
    // Style bullet points
    html = html.replace(/•/g, '<span style="color: #60a5fa;">•</span>');
    
    // Style warning emoji
    html = html.replace(/⚠️/g, '<span style="color: #fbbf24;">⚠️</span>');
    
    return html;
}

async function send(prompt) {
    busy = true;
    btn.disabled = true;
    
    // Add user message
    const userMsg = document.createElement('div');
    userMsg.className = 'message user';
    userMsg.textContent = prompt;
    chat.appendChild(userMsg);
    scroll();
    
    // Add assistant message container
    const assistantMsg = document.createElement('div');
    assistantMsg.className = 'message assistant';
    
    const status = document.createElement('div');
    status.className = 'status active';
    status.innerHTML = '<div class="spinner"></div><span>Thinking...</span>';
    
    const response = document.createElement('div');
    response.className = 'response';
    
    assistantMsg.appendChild(status);
    assistantMsg.appendChild(response);
    chat.appendChild(assistantMsg);
    scroll();
    
    try {
        const res = await fetch(`${API}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt })
        });
        
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let text = '';
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            for (const line of decoder.decode(value).split('\n')) {
                if (!line.startsWith('data: ')) continue;
                
                try {
                    const data = JSON.parse(line.slice(6));
                    
                    if (data.type === 'status') {
                        status.innerHTML = `<div class="spinner"></div><span>${data.content}</span>`;
                    } else if (data.type === 'text') {
                        text += data.content;
                        response.innerHTML = formatMarkdown(text);
                    } else if (data.type === 'done') {
                        status.className = 'status done';
                        status.innerHTML = 'Complete';
                        response.innerHTML = formatMarkdown(text);
                    }
                    scroll();
                } catch (e) {}
            }
        }
        
        status.className = 'status done';
        status.innerHTML = 'Complete';
        
    } catch (e) {
        status.className = 'status error';
        status.innerHTML = 'Failed to connect. Is the backend running?';
    }
    
    busy = false;
    btn.disabled = false;
    input.focus();
}

form.addEventListener('submit', (e) => {
    e.preventDefault();
    const prompt = input.value.trim();
    if (!prompt || busy) return;
    input.value = '';
    input.style.height = 'auto';
    send(prompt);
});

// Google OAuth
function connectGoogle() {
    window.open(`${API}/auth/google`, 'google-auth', 'width=500,height=600');
}

window.addEventListener('message', (event) => {
    if (event.data.type === 'google-auth-success') {
        const card = document.getElementById('google-card');
        const status = document.getElementById('google-status');
        card.classList.add('connected');
        status.className = 'card-status connected';
        status.innerHTML = '<span class="dot"></span> Connected';
    }
});

async function checkConnection() {
    try {
        const res = await fetch(`${API}/auth/status`);
        const data = await res.json();
        if (data.connected) {
            document.getElementById('google-card').classList.add('connected');
            const status = document.getElementById('google-status');
            status.className = 'card-status connected';
            status.innerHTML = '<span class="dot"></span> Connected';
        }
    } catch (e) {}
}

async function loadSettings() {
    try {
        const res = await fetch(`${API}/settings`);
        const data = await res.json();
        if (data.school_name) {
            document.getElementById('school-input').value = data.school_name;
        }
        if (data.teacher_names && data.teacher_names.length > 0) {
            document.getElementById('teachers-input').value = data.teacher_names.join(', ');
        }
        if (data.school_name || (data.teacher_names && data.teacher_names.length > 0)) {
            const status = document.getElementById('school-status');
            status.className = 'card-status connected';
            const teacherCount = data.teacher_names?.length || 0;
            status.innerHTML = `<span class="dot"></span> ${data.school_name || 'No school'}${teacherCount ? ` • ${teacherCount} teacher(s)` : ''}`;
        }
    } catch (e) {}
}

async function saveSettings() {
    const schoolName = document.getElementById('school-input').value.trim();
    const teachersInput = document.getElementById('teachers-input').value.trim();
    const teacherNames = teachersInput ? teachersInput.split(',').map(t => t.trim()).filter(t => t) : [];
    
    try {
        const res = await fetch(`${API}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ school_name: schoolName, teacher_names: teacherNames })
        });
        const data = await res.json();
        if (data.success) {
            const status = document.getElementById('school-status');
            status.className = 'card-status connected';
            const teacherCount = teacherNames.length;
            status.innerHTML = `<span class="dot"></span> ${schoolName || 'No school'}${teacherCount ? ` • ${teacherCount} teacher(s)` : ''}`;
        }
    } catch (e) {
        console.error('Failed to save settings', e);
    }
}

checkConnection();
loadSettings();
