// Initialize Mermaid.js
mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  themeVariables: {
    darkMode: true,
    background: '#090e17',
    primaryColor: '#0284c7',
    primaryTextColor: '#f8fafc',
    primaryBorderColor: '#38bdf8',
    lineColor: '#38bdf8',
    secondaryColor: '#1e293b',
    tertiaryColor: '#0f172a'
  },
  flowchart: { curve: 'basis' }
});

let currentRecapData = null;

// DOM Elements
const dropzone = document.getElementById('pdf-dropzone');
const fileInput = document.getElementById('pdf-file-input');
const pipelineSection = document.getElementById('pipeline-section');
const resultsSection = document.getElementById('results-section');
const toast = document.getElementById('toast-notification');
const toastMsg = document.getElementById('toast-message');

// Dropzone Events
dropzone.addEventListener('click', () => fileInput.click());

dropzone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropzone.classList.add('dragover');
});

dropzone.addEventListener('dragleave', () => {
  dropzone.classList.remove('dragover');
});

dropzone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropzone.classList.remove('dragover');
  if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
    const file = e.dataTransfer.files[0];
    if (file.type === 'application/pdf' || file.name.endsWith('.pdf')) {
      uploadPdf(file);
    } else {
      showToast('⚠️ Please upload a valid PDF slide deck');
    }
  }
});

fileInput.addEventListener('change', (e) => {
  if (e.target.files && e.target.files.length > 0) {
    uploadPdf(e.target.files[0]);
  }
});

// Toast Helper
function showToast(message) {
  toastMsg.textContent = message;
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
  }, 3000);
}

// Stepper Progress Animator
function animateStepper(stageIndex, totalStages = 4) {
  const steps = ['step-mcp', 'step-skill', 'step-subagent', 'step-output'];
  steps.forEach((id, idx) => {
    const el = document.getElementById(id);
    if (idx < stageIndex) {
      el.className = 'step-card completed';
      el.querySelector('.step-indicator').textContent = '✓';
    } else if (idx === stageIndex) {
      el.className = 'step-card active';
      el.querySelector('.step-indicator').textContent = '';
    } else {
      el.className = 'step-card';
      el.querySelector('.step-indicator').textContent = (idx + 1).toString();
    }
  });
}

// API Call: Process Sample
async function loadSample(sampleId) {
  startProcessingUI();
  try {
    animateStepper(0);
    const res = await fetch('/api/process-sample', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sample_id: sampleId })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to process sample');
    }

    const data = await res.json();
    completeProcessingUI(data);
  } catch (err) {
    console.error(err);
    showToast(`❌ Error: ${err.message}`);
    pipelineSection.classList.remove('active');
  }
}

// API Call: Upload Custom PDF
async function uploadPdf(file) {
  startProcessingUI();
  const formData = new FormData();
  formData.append('file', file);

  try {
    animateStepper(0);
    const res = await fetch('/api/upload', {
      method: 'POST',
      body: formData
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Upload failed');
    }

    const data = await res.json();
    completeProcessingUI(data);
  } catch (err) {
    console.error(err);
    showToast(`❌ Error: ${err.message}`);
    pipelineSection.classList.remove('active');
  }
}

function startProcessingUI() {
  pipelineSection.classList.add('active');
  resultsSection.classList.remove('active');
  document.getElementById('pipeline-status').textContent = 'Executing single clean pass...';
  animateStepper(0);
  pipelineSection.scrollIntoView({ behavior: 'smooth' });
}

async function completeProcessingUI(data) {
  currentRecapData = data;

  // Step animations
  animateStepper(1);
  await new Promise(r => setTimeout(r, 250));
  animateStepper(2);
  await new Promise(r => setTimeout(r, 250));
  animateStepper(3);
  await new Promise(r => setTimeout(r, 250));

  // Mark all completed
  ['step-mcp', 'step-skill', 'step-subagent', 'step-output'].forEach(id => {
    const el = document.getElementById(id);
    el.className = 'step-card completed';
    el.querySelector('.step-indicator').textContent = '✓';
  });

  document.getElementById('pipeline-status').textContent = 'Completed in 1 pass!';
  populateResults(data);
  resultsSection.classList.add('active');
  showToast(`✨ Generated recap for ${data.deck_title}!`);
}

// Populate Dashboard Panels
async function populateResults(data) {
  // Metrics
  document.getElementById('metric-slides').textContent = `${data.total_slides} Slides`;
  document.getElementById('metric-topics').textContent = `${data.topics.length} Topics`;
  document.getElementById('metric-audit').textContent = data.audit.status;
  document.getElementById('metric-budget').textContent = `${data.total_characters} chars (1 Pass)`;

  // 1. Render Diagram
  const target = document.getElementById('mermaid-target');
  target.innerHTML = '';
  try {
    const uniqueId = 'diagram-' + Math.floor(Math.random() * 10000);
    const { svg } = await mermaid.render(uniqueId, data.mermaid_code);
    target.innerHTML = svg;
  } catch (err) {
    console.error('Mermaid render error:', err);
    target.innerHTML = `<pre style="color: #f87171;">Diagram syntax error: ${err.message}</pre>`;
  }

  // 2. Concept Matrix Table
  const tbody = document.getElementById('matrix-tbody');
  tbody.innerHTML = '';
  data.topics.forEach(t => {
    const tr = document.createElement('tr');
    const bullets = t.bullets || [];
    const focus = bullets[0] || 'Core lecture concept';
    const caveat = bullets.length > 1 ? bullets[bullets.length - 1] : 'Follow recommended architecture';

    tr.innerHTML = `
      <td><strong>${escapeHtml(t.title)}</strong></td>
      <td><span class="slide-badge">Slide ${t.slide}</span></td>
      <td>${escapeHtml(focus)}</td>
      <td class="caveat-text">⚠️ ${escapeHtml(caveat)}</td>
    `;
    tbody.appendChild(tr);
  });

  // 3. Command Reference
  const cmdBlock = document.getElementById('commands-code-block');
  if (data.commands && data.commands.length > 0) {
    cmdBlock.textContent = data.commands.map(c => `# From Slide ${c.slide}\n${c.cmd}`).join('\n\n');
  } else {
    cmdBlock.textContent = `# Standard OpenCode Harness Commands\nopencode mcp list\nopencode run --agent recap-reviewer\n./.venv/bin/python recap.py --pdf "${data.filename}"`;
  }

  // 4. Audit Checklist
  const auditContainer = document.getElementById('audit-checklist-container');
  auditContainer.innerHTML = '';
  data.audit.findings.forEach(f => {
    const item = document.createElement('div');
    item.className = 'check-item';
    const icon = f.passed ? '✅' : '⚠️';
    item.innerHTML = `
      <div class="check-icon">${icon}</div>
      <div class="check-content">
        <h4>${escapeHtml(f.category)}</h4>
        <p>${escapeHtml(f.note)}</p>
      </div>
    `;
    auditContainer.appendChild(item);
  });

  // 5. Markdown Preview
  document.getElementById('markdown-preview-box').textContent = data.markdown;
}

// Tab Switching
function switchTab(tabId) {
  const tabs = ['diagram', 'matrix', 'commands', 'audit', 'markdown'];
  tabs.forEach(t => {
    document.getElementById(`tab-btn-${t}`).classList.toggle('active', t === tabId);
    document.getElementById(`pane-${t}`).classList.toggle('active', t === tabId);
  });
}

// Filter Concept Matrix
function filterMatrix(query) {
  const lower = query.toLowerCase();
  const rows = document.querySelectorAll('#matrix-tbody tr');
  rows.forEach(r => {
    const text = r.textContent.toLowerCase();
    r.style.display = text.includes(lower) ? '' : 'none';
  });
}

// Copy & Download Actions
function copyMermaid() {
  if (currentRecapData) {
    navigator.clipboard.writeText(currentRecapData.mermaid_code);
    showToast('📋 Mermaid diagram copied to clipboard!');
  }
}

function downloadDiagram() {
  if (!currentRecapData) return;
  const blob = new Blob([currentRecapData.mermaid_code], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'diagram.mmd';
  a.click();
  URL.revokeObjectURL(url);
  showToast('💾 Downloaded diagram.mmd');
}

function copyCommands() {
  const code = document.getElementById('commands-code-block').textContent;
  navigator.clipboard.writeText(code);
  showToast('📋 Commands copied to clipboard!');
}

function copyMarkdown() {
  if (currentRecapData) {
    navigator.clipboard.writeText(currentRecapData.markdown);
    showToast('📋 Markdown recap copied to clipboard!');
  }
}

function downloadMarkdown() {
  if (!currentRecapData) return;
  const blob = new Blob([currentRecapData.markdown], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'recap.md';
  a.click();
  URL.revokeObjectURL(url);
  showToast('💾 Downloaded recap.md');
}

function escapeHtml(text) {
  if (!text) return '';
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Auto-load Day 6 course slides sample on first visit
window.addEventListener('DOMContentLoaded', () => {
  loadSample('day6');
});
