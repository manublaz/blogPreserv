let currentSource = null;
let totalPosts = 0;
let doneBlogs  = 0;
let errorBlogs = 0;

// --- CONFIG ---------------------------------------------------
async function saveConfig() {
  const yaml = document.getElementById('config-yaml').value;
  const resp = await fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({yaml})
  });
  const data = await resp.json();
  if (data.ok) {
    showToast('\u2713 Configuraci\u00f3n guardada');
    refreshBlogList();
  } else {
    showToast('\u2717 Error: ' + data.error, true);
  }
}

async function validateConfig() {
  const yaml = document.getElementById('config-yaml').value;
  const resp = await fetch('/api/validate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({yaml})
  });
  const data = await resp.json();
  if (data.ok) showToast('\u2714 YAML v\u00e1lido (' + data.blogs + ' blogs configurados)');
  else showToast('\u2717 YAML inv\u00e1lido: ' + data.error, true);
}

async function refreshBlogList() {
  const resp = await fetch('/api/config');
  const data = await resp.json();
  if (!data.ok) return;
  const blogs = data.config.blogs || [];
  document.getElementById('stat-blogs').textContent = blogs.filter(b => b.enabled !== false).length;
  renderBlogList(blogs);
}

function renderBlogList(blogs) {
  const list = document.getElementById('blog-list');
  list.innerHTML = blogs.map((b, i) => {
    const enabled = b.enabled !== false;
    const outputFile = slugify(b.title || 'blog') + '.html';
    return `<div class="blog-item" id="blog-item-${i}">
      <div class="blog-status" id="blog-status-${i}"></div>
      <div style="flex:1">
        <div class="blog-name" style="${!enabled ? 'opacity:.4' : ''}">
          ${b.title || b.url}
          ${!enabled ? '<span style="font-size:.7rem;color:var(--muted)"> (deshabilitado)</span>' : ''}
        </div>
        <div class="blog-url">${b.url}</div>
      </div>
      <span class="blog-count" id="blog-count-${i}"></span>
      <a href="/output/${outputFile}" target="_blank" class="blog-link"
         id="blog-link-${i}" style="display:none">\u2197 Ver</a>
      ${enabled ? `<button class="btn btn-secondary" onclick="runSingle(${i})"
                    style="padding:.25rem .6rem;font-size:.72rem">\u25b6</button>` : ''}
    </div>`;
  }).join('');
}

function slugify(text) {
  return text.toLowerCase()
    .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

// --- PIPELINE --------------------------------------------------
async function runAll() {
  await saveConfig();
  const force = document.getElementById('chk-force').checked;
  const resp = await fetch('/api/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({force})
  });
  const data = await resp.json();
  if (data.ok) startListening(data.job_id);
  else showToast('\u2717 No se pudo iniciar: ' + data.error, true);
}

async function runSingle(idx) {
  await saveConfig();
  const force = document.getElementById('chk-force').checked;
  const resp = await fetch('/api/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({force, blog_index: idx})
  });
  const data = await resp.json();
  if (data.ok) startListening(data.job_id);
  else showToast('\u2717 No se pudo iniciar: ' + data.error, true);
}

function startListening(jobId) {
  if (currentSource) currentSource.close();

  totalPosts = 0; doneBlogs = 0; errorBlogs = 0;
  document.getElementById('stat-posts').textContent  = '0';
  document.getElementById('stat-done').textContent   = '0';
  document.getElementById('stat-errors').textContent = '0';
  document.getElementById('log-status').textContent  = '\u23f3 Ejecutando...';

  const btn = document.getElementById('btn-run-all');
  btn.disabled = true;
  document.getElementById('spin-all').style.display = 'inline-block';

  clearLog();

  currentSource = new EventSource(`/api/stream/${jobId}`);

  currentSource.onmessage = (e) => {
    const data = JSON.parse(e.data);

    if (data.type === 'log') {
      appendLog(data.msg);
    } else if (data.type === 'blog_start') {
      const el = document.getElementById(`blog-status-${data.idx}`);
      const card = document.getElementById(`blog-item-${data.idx}`);
      if (el) el.className = 'blog-status running';
      if (card) card.className = 'blog-item running';
    } else if (data.type === 'blog_done') {
      const el = document.getElementById(`blog-status-${data.idx}`);
      const card = document.getElementById(`blog-item-${data.idx}`);
      const cnt  = document.getElementById(`blog-count-${data.idx}`);
      const link = document.getElementById(`blog-link-${data.idx}`);
      if (el) el.className = 'blog-status ' + (data.success ? 'done' : 'error');
      if (card) card.className = 'blog-item ' + (data.success ? 'done' : 'error');
      if (cnt)  cnt.textContent = data.success ? data.count + ' posts' : 'Error';
      if (link && data.success) link.style.display = 'inline';
      if (data.success) { totalPosts += data.count; doneBlogs++; }
      else errorBlogs++;
      document.getElementById('stat-posts').textContent  = totalPosts;
      document.getElementById('stat-done').textContent   = doneBlogs;
      document.getElementById('stat-errors').textContent = errorBlogs;
    } else if (data.type === 'done') {
      currentSource.close();
      currentSource = null;
      btn.disabled = false;
      document.getElementById('spin-all').style.display = 'none';
      document.getElementById('log-status').textContent = '\u2713 Completado';
      appendLog('', 'sep');
      appendLog('=== PROCESO COMPLETADO ===', 'ok');
      showToast('\u2713 Proceso completado');
    }
  };

  currentSource.onerror = () => {
    btn.disabled = false;
    document.getElementById('spin-all').style.display = 'none';
    document.getElementById('log-status').textContent = 'Error de conexi\u00f3n';
  };
}

// --- LOG -------------------------------------------------------
function appendLog(msg, forceClass) {
  const el = document.getElementById('log-output');
  const line = document.createElement('span');
  line.className = 'log-line ' + (forceClass || classifyLog(msg));
  line.textContent = msg + '\\n';
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

function classifyLog(msg) {
  const m = msg.trim();
  if (m.startsWith('\u25b6 FASE') || m.startsWith('Blog ') || m.startsWith('===')
      || m.startsWith('--') || m.startsWith('TOTAL'))
    return 'phase';
  if (m.includes('ok') || m.includes('completado') || m.includes('generado')
      || m.includes('LISTO') || m.includes('Extraccion finalizada'))
    return 'ok';
  if (m.includes('ERROR') || m.toLowerCase().includes('error')
      || m.startsWith('\u2717') || m.includes('Conexion rechazada'))
    return 'error';
  if (m.includes('OMITIDA') || m.includes('omitida') || m.includes('AVISO')
      || m.includes('Timeout') || m.includes('limite') || m.includes('redimensionada'))
    return 'warn';
  if (m.startsWith('=') || m.startsWith('-'))
    return 'sep';
  if (m.startsWith('[') || m.includes('|'))   // lineas de post individual
    return 'info';
  return 'info';
}

function clearLog() {
  document.getElementById('log-output').innerHTML = '';
}

function openOutputDir() {
  window.open('/output/', '_blank');
}

// --- TOAST -----------------------------------------------------
let toastTimer;
function showToast(msg, isError) {
  const t = document.getElementById('toast');
  // Reiniciar animaci\u00f3n: quitar clase, forzar reflow, volver a a\u00f1adir
  t.classList.remove('show');
  void t.offsetHeight; // fuerza reflow del navegador
  t.textContent = msg;
  t.style.background = isError ? '#991b1b' : '#16a34a';
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3500);
}

// --- IA --------------------------------------------------------
async function testAI() {
  const statusEl = document.getElementById('ai-status');
  const vocabEl  = document.getElementById('vocab-list');
  statusEl.innerHTML = '\u23f3 Probando conexion con LM Studio...';
  statusEl.style.cssText = 'background:var(--bg);color:var(--muted);border-color:var(--border);border-radius:5px;padding:.6rem .9rem;font-size:.8rem;font-family:var(--mono);margin-bottom:1rem;border:1px solid var(--border)';

  try {
    const resp = await fetch('/api/ai/test');
    const data = await resp.json();

    if (data.vocabulary) {
      vocabEl.innerHTML = data.vocabulary.map(v => '\u2022 ' + v).join('<br>');
    }

    if (!data.ok) {
      statusEl.innerHTML = '<strong>SERVIDOR NO DISPONIBLE</strong><br>' + data.message;
      statusEl.style.background = '#fef2f2';
      statusEl.style.color = 'var(--err)';
      statusEl.style.borderColor = 'var(--err)';
    } else if (!data.ready) {
      const models = data.models && data.models.length > 0
        ? '<br>Modelos detectados: ' + data.models.join(', ')
        : '<br>Ningun modelo cargado todavia.';
      statusEl.innerHTML = '<strong>SERVIDOR ACTIVO &mdash; MODELO NO LISTO</strong><br>' + data.message + models;
      statusEl.style.background = '#fffbeb';
      statusEl.style.color = 'var(--warn)';
      statusEl.style.borderColor = '#d97706';
    } else {
      const models = data.models && data.models.length > 0
        ? '<br>Modelos activos: ' + data.models.join(', ')
        : '';
      statusEl.innerHTML = '<strong>LISTO PARA INFERENCIA</strong><br>' + data.message + models;
      statusEl.style.background = '#f0fdf4';
      statusEl.style.color = 'var(--ok)';
      statusEl.style.borderColor = 'var(--ok)';
    }
  } catch(e) {
    statusEl.innerHTML = 'Error contactando con el panel: ' + e.message;
    statusEl.style.background = '#fef2f2';
    statusEl.style.color = 'var(--err)';
  }
}

async function syncAITasks() {
  const tasks = ['generate_tags','summarize','classify','clean_html']
    .filter(t => document.getElementById('task-' + t) && document.getElementById('task-' + t).checked);
  const yamlArea = document.getElementById('config-yaml');
  let yaml = yamlArea.value;
  const enable = tasks.length > 0;
  yaml = yaml.replace(/(\\s*enabled:\\s*)(true|false)/, '$1' + enable);
  yamlArea.value = yaml;
  await saveConfig();
}

let _vocab_data = [];

function editVocab() {
  const list   = document.getElementById('vocab-list');
  const editor = document.getElementById('vocab-editor');
  const saveBtn= document.getElementById('btn-save-vocab');
  editor.value = _vocab_data.join('\n');
  list.style.display   = 'none';
  editor.style.display = 'block';
  saveBtn.style.display = 'inline-block';
  editor.focus();
}

async function saveVocab() {
  const editor = document.getElementById('vocab-editor');
  const list   = document.getElementById('vocab-list');
  const saveBtn= document.getElementById('btn-save-vocab');
  const lines  = editor.value.split('\n').map(l => l.trim()).filter(Boolean);
  _vocab_data  = lines;

  // Guardar en config.yaml via API
  const resp = await fetch('/api/vocab', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({vocabulary: lines})
  });
  const data = await resp.json();
  if (data.ok) {
    showToast('\u2713 Vocabulario guardado (' + lines.length + ' entradas)');
    list.innerHTML = lines.map(v => '\u2022 ' + v).join('<br>');
    list.style.display   = 'block';
    editor.style.display = 'none';
    saveBtn.style.display = 'none';
  } else {
    showToast('\u2717 Error: ' + data.error, true);
  }
}

function loadAITasksFromConfig(yaml) {
  ['generate_tags','summarize','classify','reformat','clean_html'].forEach(t => {
    const el = document.getElementById('task-' + t);
    if (el) el.checked = yaml.includes('- ' + t);
  });
  fetch('/api/ai/test').then(r => r.json()).then(data => {
    if (data.vocabulary) {
      _vocab_data = data.vocabulary;
      const el = document.getElementById('vocab-list');
      if (el) el.innerHTML = data.vocabulary.map(v => '\u2022 ' + v).join('<br>');
    }
  }).catch(() => {});
}

// --- INIT ------------------------------------------------------
(async function() {
  try {
    const r = await fetch('/api/config/raw');
    const t = await r.text();
    document.getElementById('config-yaml').value = t;
    loadAITasksFromConfig(t);
  } catch(e) {}
  refreshBlogList();
})();