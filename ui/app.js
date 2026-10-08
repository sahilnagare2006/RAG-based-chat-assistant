/* ── app.js — RAG Chat Assistant v2 ──────────────────────────────
   ChatGPT-style UI with: sidebar, model selector, knowledge graph,
   vector RAG citations, markdown rendering, code copy, API key mgmt
──────────────────────────────────────────────────────────────── */

const API = '/api/chatbot';
const USER_ID = 'user-' + (localStorage.getItem('rag_uid') || (() => {
  const id = Math.random().toString(36).slice(2);
  localStorage.setItem('rag_uid', id);
  return id;
})());

// ─── State ────────────────────────────────────────────────────
let activeDocId = null;
let activeDocName = null;
let selectedModel = localStorage.getItem('rag_model') || 'nvidia/nemotron-3-ultra-550b-a55b:free';
let apiKey = localStorage.getItem('rag_apikey') || '';
let chatHistory = [];
let graphData = null;
let graphOpen = false;
let uploadInProgress = false;
let models = [];

// ─── DOM Refs ──────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const heroState      = $('hero-state');
const messages       = $('messages');
const chatInput      = $('chat-input');
const sendBtn        = $('send-btn');
const docList        = $('doc-list');
const docCount       = $('docs-count');
const modelPillBtn   = $('model-pill-btn');
const modelName      = $('selected-model-name');
const modelDropdown  = $('model-dropdown');
const graphPanel     = $('graph-panel');
const graphCanvas    = $('graph-canvas');
const graphStats     = $('graph-stats');
const nodeInspector  = $('node-inspector');
const sidebarEl      = $('sidebar');
const mainLayout     = $('main-layout');
const activeDocBadge = $('active-doc-badge');
const activeDocNameEl= $('active-doc-name');
const fileInput      = $('file-input');
const apiKeyInput    = $('api-key-input');
const keyStatus      = $('key-status');

// Graph canvas context
const ctx = graphCanvas ? graphCanvas.getContext('2d') : null;

// ─── Init ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await loadModels();
  await loadDocuments();
  setupEventListeners();
  if (apiKey) {
    apiKeyInput.value = apiKey;
    keyStatus.textContent = '✓ API key loaded from storage';
  }
});

// ─── Models ───────────────────────────────────────────────────
async function loadModels() {
  try {
    const res = await fetch(`${API}/models`);
    const data = await res.json();
    models = data.models || [];
  } catch {
    models = [];
  }
  renderModelDropdown();
}

function renderModelDropdown() {
  modelDropdown.innerHTML = '';
  if (!models.length) {
    modelDropdown.innerHTML = '<div style="padding:16px;color:var(--text-muted);font-size:13px">Failed to load models</div>';
    return;
  }
  models.forEach(m => {
    const item = document.createElement('div');
    item.className = 'model-option' + (m.id === selectedModel ? ' active' : '');
    item.innerHTML = `
      <div class="model-option-info">
        <div class="model-option-name">${m.name}</div>
        <div class="model-option-desc">${m.description}</div>
      </div>
      <span class="model-badge${m.free ? ' free' : ''}">${m.badge}</span>
    `;
    item.addEventListener('click', () => {
      selectedModel = m.id;
      localStorage.setItem('rag_model', m.id);
      modelName.textContent = m.name;
      modelDropdown.classList.remove('open');
      document.querySelectorAll('.model-option').forEach(el => el.classList.remove('active'));
      item.classList.add('active');
    });
    modelDropdown.appendChild(item);
  });

  // Set initial display name
  const active = models.find(m => m.id === selectedModel) || models[0];
  if (active) { modelName.textContent = active.name; selectedModel = active.id; }
}

// ─── Documents ────────────────────────────────────────────────
async function loadDocuments() {
  try {
    const res = await fetch(`${API}/documents?userId=${USER_ID}`);
    const data = await res.json();
    renderDocList(data.documents || []);
  } catch {
    renderDocList([]);
  }
}

function renderDocList(docs) {
  docCount.textContent = docs.length;
  if (!docs.length) {
    docList.innerHTML = '<div class="doc-empty">No documents yet. Upload a PDF to get started.</div>';
    return;
  }
  docList.innerHTML = '';
  docs.forEach(doc => {
    const item = document.createElement('div');
    item.className = 'doc-item' + (doc.pdfId === activeDocId ? ' active' : '');
    item.dataset.id = doc.pdfId;
    item.innerHTML = `
      <div class="doc-icon">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/></svg>
      </div>
      <div class="doc-info">
        <div class="doc-name" title="${doc.fileName}">${doc.fileName}</div>
        <div class="doc-meta">${doc.pages || '?'} pages · ${doc.chunkCount || '?'} chunks</div>
      </div>
      <button class="delete-doc-btn" data-id="${doc.pdfId}" title="Delete">×</button>
    `;
    item.addEventListener('click', (e) => {
      if (e.target.classList.contains('delete-doc-btn')) return;
      selectDocument(doc.pdfId, doc.fileName);
    });
    item.querySelector('.delete-doc-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      deleteDocument(doc.pdfId);
    });
    docList.appendChild(item);
  });
}

async function deleteDocument(pdfId) {
  if (!confirm('Delete this document?')) return;
  try {
    await fetch(`${API}/delete`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pdfId, userId: USER_ID}),
    });
    if (pdfId === activeDocId) clearDoc();
    await loadDocuments();
    showToast('Document deleted');
  } catch { showToast('Delete failed', 'error'); }
}

function selectDocument(pdfId, fileName) {
  activeDocId = pdfId;
  activeDocName = fileName;
  activeDocBadge.style.display = 'flex';
  activeDocNameEl.textContent = fileName;
  // Highlight in sidebar
  document.querySelectorAll('.doc-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === pdfId);
  });
  heroState.classList.add('hidden');
  updateSendBtn();
  showToast(`📄 ${fileName} selected`);

  // Load graph in background
  if (graphOpen) fetchAndDrawGraph(pdfId);
}

function clearDoc() {
  activeDocId = null;
  activeDocName = null;
  activeDocBadge.style.display = 'none';
  document.querySelectorAll('.doc-item').forEach(el => el.classList.remove('active'));
  updateSendBtn();
}

// ─── Upload ───────────────────────────────────────────────────
fileInput.addEventListener('change', handleFileUpload);

async function handleFileUpload() {
  const file = fileInput.files[0];
  if (!file || uploadInProgress) return;
  if (!file.name.toLowerCase().endsWith('.pdf')) { showToast('Only PDF files are supported', 'error'); return; }
  if (file.size > 50 * 1024 * 1024) { showToast('File exceeds 50MB limit', 'error'); return; }

  uploadInProgress = true;
  const progressEl = showUploadProgress(file.name);

  try {
    const form = new FormData();
    form.append('file', file);
    form.append('userId', USER_ID);

    const res = await fetch(`${API}/upload`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Upload failed');
    }
    const data = await res.json();
    hideUploadProgress(progressEl);
    await loadDocuments();
    selectDocument(data.pdfId, data.fileName);
    showToast(`✅ Uploaded: ${data.fileName} (${data.totalChunks} chunks)`);
  } catch (e) {
    hideUploadProgress(progressEl);
    showToast(e.message || 'Upload failed', 'error');
  } finally {
    uploadInProgress = false;
    fileInput.value = '';
  }
}

function showUploadProgress(name) {
  let el = document.querySelector('.upload-progress');
  if (!el) {
    el = document.createElement('div');
    el.className = 'upload-progress';
    el.innerHTML = `
      <div>Uploading <strong>${name}</strong>...</div>
      <div class="upload-progress-bar"><div class="upload-progress-fill" id="uprog"></div></div>
    `;
    document.body.appendChild(el);
  }
  el.classList.add('active');
  // Fake progress animation
  let prog = 0;
  const fill = el.querySelector('.upload-progress-fill');
  const iv = setInterval(() => {
    prog = Math.min(prog + Math.random() * 15, 90);
    fill.style.width = prog + '%';
  }, 250);
  el._interval = iv;
  return el;
}

function hideUploadProgress(el) {
  if (!el) return;
  clearInterval(el._interval);
  const fill = el.querySelector('.upload-progress-fill');
  if (fill) fill.style.width = '100%';
  setTimeout(() => el.classList.remove('active'), 500);
}

// ─── Chat ──────────────────────────────────────────────────────
async function sendMessage(text) {
  text = (text || chatInput.value).trim();
  if (!text || !activeDocId) return;
  chatInput.value = '';
  resizeInput();
  updateSendBtn();
  heroState.classList.add('hidden');

  // User message
  appendMessage('user', text);
  chatHistory.push({ role: 'user', content: text });

  // Assistant thinking
  const thinkingId = appendThinking();
  sendBtn.disabled = true;

  try {
    const body = {
      pdfId: activeDocId,
      query: text,
      userId: USER_ID,
      model: selectedModel,
      topK: 4,
      chatHistory: chatHistory.slice(-8),
      ...(apiKey ? { apiKey } : {}),
    };

    const res = await fetch(`${API}/chat`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });

    const data = await res.json();
    removeThinking(thinkingId);

    if (!res.ok) throw new Error(data.detail || 'Request failed');

    appendMessage('assistant', data.answer, data.sources || [], data.model);
    chatHistory.push({ role: 'assistant', content: data.answer });
  } catch (e) {
    removeThinking(thinkingId);
    appendError(e.message);
  } finally {
    sendBtn.disabled = !chatInput.value.trim() || !activeDocId;
  }
}

function appendMessage(role, text, sources = [], model = null) {
  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.innerHTML = `
    <div class="msg-avatar ${role}">${role === 'user' ? 'U' : '✦'}</div>
    <div class="msg-content">
      <div class="msg-bubble">${renderMarkdown(text)}</div>
      ${sources.length ? renderSources(sources) : ''}
    </div>
  `;
  messages.appendChild(div);
  scrollToBottom();
}

function renderSources(sources) {
  const pills = sources.map((s, i) => {
    const excerpt = (s.excerpt || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const score = (s.score * 100).toFixed(0);
    return `<button class="source-pill" onclick="showSourceModal(${i},'Page ${s.page}',\`${excerpt.slice(0, 800)}\`)">
      📄 Page ${s.page} &middot; ${score}% match
    </button>`;
  }).join('');
  return `<div class="source-pills">${pills}</div>`;
}

let _thinkingCount = 0;
function appendThinking() {
  const id = 'thinking-' + (++_thinkingCount);
  const div = document.createElement('div');
  div.className = 'message assistant';
  div.id = id;
  div.innerHTML = `
    <div class="msg-avatar assistant">✦</div>
    <div class="msg-content"><div class="msg-bubble"><div class="typing-indicator">
      <div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>
    </div></div></div>
  `;
  messages.appendChild(div);
  scrollToBottom();
  return id;
}

function removeThinking(id) {
  const el = $(id);
  if (el) el.remove();
}

function appendError(msg) {
  const div = document.createElement('div');
  div.className = 'message assistant';
  div.innerHTML = `
    <div class="msg-avatar assistant">✦</div>
    <div class="msg-content"><div class="msg-bubble">
      <div class="error-msg">⚠️ ${msg || 'An error occurred. Please try again.'}</div>
    </div></div>
  `;
  messages.appendChild(div);
  scrollToBottom();
}

function scrollToBottom() {
  const cw = $('chat-window');
  cw.scrollTop = cw.scrollHeight;
}

// ─── Markdown Renderer (lightweight) ──────────────────────────
function renderMarkdown(text) {
  let html = escapeHtml(text);

  // Code blocks
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const id = 'cb' + Math.random().toString(36).slice(2);
    return `<div class="code-block-wrap">
      <div class="code-block-header">
        <span class="code-lang">${lang || 'code'}</span>
        <button class="copy-code-btn" onclick="copyCode('${id}')">Copy</button>
      </div>
      <pre id="${id}"><code>${code}</code></pre>
    </div>`;
  });

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Italic
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  // H1-H3
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  // UL/OL (simple)
  html = html.replace(/^\- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>[\s\S]+?<\/li>)/g, '<ul>$1</ul>');
  // Paragraphs
  html = html.replace(/\n\n/g, '</p><p>');
  html = '<p>' + html + '</p>';
  html = html.replace(/<p><(h[123]|ul|ol|div|pre)/g, '<$1');
  html = html.replace(/<\/(h[123]|ul|ol|div|pre)><\/p>/g, '</$1>');

  return html;
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

window.copyCode = function(id) {
  const el = $(id);
  if (!el) return;
  navigator.clipboard.writeText(el.innerText).then(() => showToast('Copied!'));
};

// ─── Source Modal ─────────────────────────────────────────────
window.showSourceModal = function(idx, title, text) {
  $('source-modal-title').textContent = title;
  $('source-modal-body').textContent = text;
  $('source-modal').style.display = 'flex';
};

$('source-modal-close').addEventListener('click', () => {
  $('source-modal').style.display = 'none';
});
$('source-modal').addEventListener('click', (e) => {
  if (e.target === $('source-modal')) $('source-modal').style.display = 'none';
});

// ─── Suggestion Pills ──────────────────────────────────────────
window.sendSuggestion = function(text) {
  if (!activeDocId) { showToast('Please upload or select a document first', 'error'); return; }
  chatInput.value = text;
  sendMessage(text);
};

// ─── Knowledge Graph ──────────────────────────────────────────
async function fetchAndDrawGraph(pdfId) {
  graphStats.textContent = 'Loading graph…';
  nodeInspector.innerHTML = '<p class="node-inspector-placeholder">Loading…</p>';
  try {
    const res = await fetch(`${API}/graph/${pdfId}`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    graphData = data;
    graphStats.textContent = `${data.entity_count} concepts · ${data.link_count} relationships`;
    drawGraph(data);
  } catch (e) {
    graphStats.textContent = 'Graph unavailable';
    nodeInspector.innerHTML = `<div class="error-msg">${e.message}</div>`;
  }
}

const CATEGORY_COLORS = {
  algorithm: '#6366f1',
  architecture: '#2563eb',
  tool: '#10b981',
  concept: '#f59e0b',
  process: '#ec4899',
  general: '#64748b',
};

let graphNodes = [], graphLinks = [];
let graphOffset = { x: 0, y: 0 };
let graphScale = 1;
let isDragging = false, lastMouse = {};

function drawGraph(data) {
  if (!ctx) return;
  const W = graphCanvas.offsetWidth || 380;
  const H = graphCanvas.offsetHeight || 520;
  graphCanvas.width = W;
  graphCanvas.height = H;

  const cx = W / 2, cy = H / 2;
  const n = data.nodes.length;

  // Assign positions using force-like initial circle layout
  graphNodes = data.nodes.map((node, i) => {
    const angle = (2 * Math.PI * i) / n;
    const radius = Math.min(W, H) * 0.32;
    return {
      ...node,
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
      vx: 0, vy: 0,
    };
  });
  graphLinks = data.links;

  // Run force-directed layout for 80 ticks
  for (let t = 0; t < 80; t++) simulateForces();

  renderGraph();
}

function simulateForces() {
  const k = 80;
  const idMap = {};
  graphNodes.forEach(n => idMap[n.id] = n);

  // Repulsion
  for (let i = 0; i < graphNodes.length; i++) {
    for (let j = i + 1; j < graphNodes.length; j++) {
      const a = graphNodes[i], b = graphNodes[j];
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (k * k) / d;
      a.vx -= f * dx / d; a.vy -= f * dy / d;
      b.vx += f * dx / d; b.vy += f * dy / d;
    }
  }

  // Attraction along edges
  graphLinks.forEach(l => {
    const src = idMap[l.source], tgt = idMap[l.target];
    if (!src || !tgt) return;
    const dx = tgt.x - src.x, dy = tgt.y - src.y;
    const d = Math.sqrt(dx * dx + dy * dy) || 1;
    const f = (d * d) / (k * 2);
    src.vx += f * dx / d; src.vy += f * dy / d;
    tgt.vx -= f * dx / d; tgt.vy -= f * dy / d;
  });

  // Apply velocity + center gravity
  const W = graphCanvas.width, H = graphCanvas.height;
  graphNodes.forEach(n => {
    n.x += n.vx * 0.4; n.y += n.vy * 0.4;
    n.vx *= 0.5; n.vy *= 0.5;
    // Gravity toward center
    n.vx += (W / 2 - n.x) * 0.005;
    n.vy += (H / 2 - n.y) * 0.005;
    // Clamp
    n.x = Math.max(n.size + 10, Math.min(W - n.size - 10, n.x));
    n.y = Math.max(n.size + 10, Math.min(H - n.size - 10, n.y));
  });
}

function renderGraph() {
  if (!ctx) return;
  const W = graphCanvas.width, H = graphCanvas.height;
  ctx.clearRect(0, 0, W, H);
  ctx.save();
  ctx.translate(graphOffset.x, graphOffset.y);
  ctx.scale(graphScale, graphScale);

  const idMap = {};
  graphNodes.forEach(n => idMap[n.id] = n);

  // Draw edges
  graphLinks.forEach(l => {
    const src = idMap[l.source], tgt = idMap[l.target];
    if (!src || !tgt) return;
    ctx.beginPath();
    ctx.moveTo(src.x, src.y);
    ctx.lineTo(tgt.x, tgt.y);
    ctx.strokeStyle = 'rgba(255,255,255,0.07)';
    ctx.lineWidth = 1;
    ctx.stroke();
  });

  // Draw nodes
  graphNodes.forEach(n => {
    const color = CATEGORY_COLORS[n.category] || CATEGORY_COLORS.general;
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.size, 0, 2 * Math.PI);
    ctx.fillStyle = color + '33';
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Label
    ctx.fillStyle = 'rgba(255,255,255,0.75)';
    ctx.font = `${Math.max(9, Math.min(12, n.size))}px Inter, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const maxLabelW = n.size * 2.5;
    const label = truncateLabel(n.label, maxLabelW, ctx);
    ctx.fillText(label, n.x, n.y);
  });

  ctx.restore();
}

function truncateLabel(text, maxW, ctx) {
  if (ctx.measureText(text).width <= maxW) return text;
  while (text.length > 3 && ctx.measureText(text + '…').width > maxW) text = text.slice(0, -1);
  return text + '…';
}

// Canvas interactions
graphCanvas.addEventListener('click', (e) => {
  const rect = graphCanvas.getBoundingClientRect();
  const mx = (e.clientX - rect.left - graphOffset.x) / graphScale;
  const my = (e.clientY - rect.top - graphOffset.y) / graphScale;
  const hit = graphNodes.find(n => {
    const dx = n.x - mx, dy = n.y - my;
    return Math.sqrt(dx * dx + dy * dy) <= n.size + 4;
  });
  if (hit) showNodeInspector(hit);
});

graphCanvas.addEventListener('mousedown', (e) => {
  isDragging = true;
  lastMouse = { x: e.clientX, y: e.clientY };
  graphCanvas.style.cursor = 'grabbing';
});
graphCanvas.addEventListener('mousemove', (e) => {
  if (!isDragging) return;
  graphOffset.x += e.clientX - lastMouse.x;
  graphOffset.y += e.clientY - lastMouse.y;
  lastMouse = { x: e.clientX, y: e.clientY };
  renderGraph();
});
graphCanvas.addEventListener('mouseup', () => { isDragging = false; graphCanvas.style.cursor = 'grab'; });
graphCanvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  graphScale = Math.max(0.3, Math.min(4, graphScale * factor));
  renderGraph();
}, { passive: false });

function showNodeInspector(node) {
  nodeInspector.innerHTML = `
    <div class="node-inspector-content">
      <h4>${node.label}</h4>
      <div class="ni-meta">Appears ${node.frequency}× — Pages: ${(node.pages || []).join(', ')}</div>
      <span class="ni-badge">${node.category}</span>
    </div>
  `;
}

// ─── UI Event Listeners ───────────────────────────────────────
function setupEventListeners() {
  // Sidebar toggle
  $('sidebar-toggle').addEventListener('click', () => {
    sidebarEl.classList.toggle('collapsed');
  });

  // New chat
  $('new-chat-btn').addEventListener('click', () => {
    messages.innerHTML = '';
    chatHistory = [];
    heroState.classList.remove('hidden');
  });

  // Model dropdown
  modelPillBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    modelDropdown.classList.toggle('open');
  });
  document.addEventListener('click', () => modelDropdown.classList.remove('open'));

  // Knowledge graph toggle
  $('graph-toggle-btn').addEventListener('click', () => {
    graphOpen = !graphOpen;
    graphPanel.classList.toggle('open', graphOpen);
    $('graph-toggle-btn').classList.toggle('active', graphOpen);
    if (graphOpen && activeDocId && !graphData) fetchAndDrawGraph(activeDocId);
    else if (graphOpen && graphData) renderGraph();
  });

  $('graph-close-btn').addEventListener('click', () => {
    graphOpen = false;
    graphPanel.classList.remove('open');
    $('graph-toggle-btn').classList.remove('active');
  });

  // Attach / upload
  $('attach-btn').addEventListener('click', () => fileInput.click());

  // Clear document
  $('clear-doc-btn').addEventListener('click', clearDoc);

  // Send button
  sendBtn.addEventListener('click', () => sendMessage());

  // Input auto-resize + Enter to send
  chatInput.addEventListener('input', () => {
    resizeInput();
    updateSendBtn();
  });
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!sendBtn.disabled) sendMessage();
    }
  });

  // Settings modal
  $('settings-btn').addEventListener('click', () => {
    $('settings-modal').style.display = 'flex';
  });
  $('settings-close-btn').addEventListener('click', () => {
    $('settings-modal').style.display = 'none';
  });
  $('settings-modal').addEventListener('click', (e) => {
    if (e.target === $('settings-modal')) $('settings-modal').style.display = 'none';
  });
  $('save-key-btn').addEventListener('click', () => {
    apiKey = apiKeyInput.value.trim();
    localStorage.setItem('rag_apikey', apiKey);
    keyStatus.textContent = apiKey ? '✓ Key saved' : '✗ Key cleared';
    setTimeout(() => { keyStatus.textContent = ''; }, 3000);
  });
}

function resizeInput() {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + 'px';
}

function updateSendBtn() {
  sendBtn.disabled = !chatInput.value.trim() || !activeDocId;
}

// ─── Toast ────────────────────────────────────────────────────
function showToast(msg, type = 'default') {
  let toast = document.querySelector('.toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.className = 'toast';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.style.borderColor = type === 'error' ? 'rgba(239,68,68,0.4)' : 'var(--border)';
  toast.style.color = type === 'error' ? '#fca5a5' : 'var(--text)';
  toast.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => toast.classList.remove('show'), 2800);
}
