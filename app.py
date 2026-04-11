"""
app.py — Interfaz Flask para BlogPreservationSuite.
Panel de control para editar la configuración y observar el progreso en tiempo real.
"""

import threading
import queue
import json
import yaml
import time
import logging
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, send_file, Response

from pipeline        import load_config, run_all, run_blog
from ai_enricher     import test_connection, CONTROLLED_VOCABULARY
from oai_pmh         import OAIPMHProvider
from quality_metrics import compute_metrics
from slugify import slugify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

app = Flask(__name__)
CONFIG_PATH = Path("config.yaml")

# Cola de mensajes de progreso por job_id
progress_queues = {}
job_results     = {}

# ─── HTML DE LA INTERFAZ ──────────────────────────────────────────────────────

INTERFACE_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>BlogPreservationSuite</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --accent:   #1d4ed8;
      --accent-h: #1e40af;
      --ok:       #16a34a;
      --warn:     #d97706;
      --err:      #dc2626;
      --bg:       #f8fafc;
      --surface:  #ffffff;
      --border:   #e2e8f0;
      --text:     #0f172a;
      --muted:    #64748b;
      --mono:     'IBM Plex Mono', monospace;
      --sans:     'IBM Plex Sans', system-ui, sans-serif;
    }
    body {
      font-family: var(--sans); font-size: 14px;
      background: var(--bg); color: var(--text);
      -webkit-font-smoothing: antialiased;
    }

    /* ─── HEADER ─── */
    header {
      background: var(--accent); color: #fff;
      padding: .9rem 1.5rem;
      display: flex; align-items: center; gap: 1rem;
      position: sticky; top: 0; z-index: 100;
      box-shadow: 0 2px 8px rgba(0,0,0,.12);
    }
    header h1 { font-size: 1rem; font-weight: 600; }
    header span { font-family: var(--mono); font-size: .75rem; opacity: .7; }
    .header-badge {
      margin-left: auto; font-size: .7rem;
      background: rgba(255,255,255,.15);
      border: 1px solid rgba(255,255,255,.3);
      border-radius: 4px; padding: .2rem .6rem;
      font-family: var(--mono);
    }

    /* ─── LAYOUT ─── */
    .layout {
      display: grid;
      grid-template-columns: 1fr 1fr;
      grid-template-rows: auto auto 1fr;
      gap: 1px; background: var(--border);
      min-height: calc(100vh - 50px);
    }
    .panel {
      background: var(--surface);
      padding: 1.25rem 1.5rem;
      overflow: auto;
    }
    .panel-header {
      display: flex; align-items: center; gap: .6rem;
      margin-bottom: 1rem; padding-bottom: .75rem;
      border-bottom: 1px solid var(--border);
    }
    .panel-title {
      font-size: .8rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: .08em;
      color: var(--muted); font-family: var(--mono);
    }
    .panel-icon { font-size: 1rem; }

    /* ─── CONFIG EDITOR ─── */
    .config-editor {
      grid-column: 1; grid-row: 1 / 2;
    }
    textarea#config-yaml {
      width: 100%; height: calc(100vh - 160px);
      font-family: var(--mono); font-size: .8rem;
      border: 1px solid var(--border); border-radius: 6px;
      padding: 1rem; resize: none; outline: none;
      background: #fafafa; color: var(--text);
      line-height: 1.7;
      transition: border-color .15s;
    }
    textarea#config-yaml:focus { border-color: var(--accent); }

    /* ─── BUTTONS ─── */
    .btn-row { display: flex; gap: .5rem; margin-top: .75rem; flex-wrap: wrap; }
    .btn {
      font-family: var(--mono); font-size: .8rem;
      padding: .45rem .9rem; border-radius: 5px;
      border: none; cursor: pointer;
      display: inline-flex; align-items: center; gap: .4rem;
      transition: all .15s; font-weight: 500;
    }
    .btn-primary { background: var(--accent); color: #fff; }
    .btn-primary:hover { background: var(--accent-h); }
    .btn-primary:disabled { background: #93c5fd; cursor: not-allowed; }
    .btn-secondary { background: var(--bg); color: var(--text); border: 1px solid var(--border); }
    .btn-secondary:hover { border-color: var(--accent); color: var(--accent); }
    .btn-save { background: var(--ok); color: #fff; }
    .btn-save:hover { background: #15803d; }
    .spinner {
      width: 12px; height: 12px; border: 2px solid rgba(255,255,255,.3);
      border-top-color: #fff; border-radius: 50%;
      animation: spin .7s linear infinite; display: none;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* ─── BLOG LIST ─── */
    .blog-list { display: flex; flex-direction: column; gap: .5rem; }
    .blog-item {
      border: 1px solid var(--border); border-radius: 6px;
      padding: .7rem 1rem;
      display: flex; align-items: center; gap: .75rem;
      font-size: .85rem;
    }
    .blog-item.running { border-color: var(--accent); background: #eff6ff; }
    .blog-item.done    { border-color: var(--ok);    background: #f0fdf4; }
    .blog-item.error   { border-color: var(--err);   background: #fef2f2; }
    .blog-status {
      width: 8px; height: 8px; border-radius: 50%;
      flex-shrink: 0; background: var(--border);
    }
    .blog-status.running { background: var(--accent); animation: pulse 1.2s infinite; }
    .blog-status.done    { background: var(--ok); }
    .blog-status.error   { background: var(--err); }
    @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:.4; } }
    .blog-name { flex: 1; font-weight: 500; }
    .blog-url  { font-family: var(--mono); font-size: .72rem; color: var(--muted); }
    .blog-count { font-family: var(--mono); font-size: .75rem; color: var(--muted); }
    .blog-link {
      font-size: .75rem; color: var(--accent);
      text-decoration: none; font-family: var(--mono);
    }
    .blog-link:hover { text-decoration: underline; }

    /* ─── LOG PANEL ─── */
    .log-panel { grid-column: 2; grid-row: 2 / 4; }
    #log-output {
      font-family: var(--mono); font-size: .75rem;
      height: calc(100vh - 310px);
      overflow-y: auto; overflow-x: hidden;
      background: #0f172a; color: #94a3b8;
      border-radius: 6px; padding: 1rem;
      line-height: 1.8; white-space: pre-wrap; word-break: break-all;
    }
    .log-line { display: block; }
    .log-line.info    { color: #94a3b8; }
    .log-line.ok      { color: #86efac; }
    .log-line.error   { color: #fca5a5; }
    .log-line.warn    { color: #fde68a; }
    .log-line.phase   { color: #7dd3fc; font-weight: 500; }
    .log-line.sep     { color: #334155; }

    /* ─── SUMMARY ─── */
    .summary-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: .75rem; margin-bottom: 1rem;
    }
    .stat-card {
      border: 1px solid var(--border); border-radius: 6px;
      padding: .75rem 1rem; background: var(--bg);
    }
    .stat-label { font-size: .7rem; color: var(--muted); font-family: var(--mono); margin-bottom: .25rem; }
    .stat-value { font-size: 1.4rem; font-weight: 600; font-family: var(--mono); color: var(--accent); }

    /* ─── SAVED TOAST ─── */
    #toast {
      position: fixed; bottom: 1.5rem; right: 1.5rem;
      background: #1e293b; color: #fff;
      padding: .75rem 1.25rem; border-radius: 8px;
      font-family: var(--mono); font-size: .82rem;
      transform: translateY(12px); opacity: 0;
      transition: opacity .25s ease, transform .25s ease;
      pointer-events: none;
      z-index: 9999;
      box-shadow: 0 4px 16px rgba(0,0,0,.25);
      max-width: 380px;
    }
    #toast.show { transform: translateY(0); opacity: 1; }

    /* ─── RESPONSIVE ─── */
    @media (max-width: 900px) {
      .layout { grid-template-columns: 1fr; grid-template-rows: auto; }
      .config-editor { grid-column: 1; grid-row: auto; }
      .log-panel { grid-column: 1; }
      textarea#config-yaml { height: 40vh; }
      #log-output { height: 30vh; }
    }
  </style>
</head>
<body>

<header>
  <div>
    <h1>BlogPreservationSuite</h1>
  </div>
  <span>para Alfonso López Yepes · UCM</span>
  <span class="header-badge">v1.0</span>
</header>

<div class="layout">

  <!-- ── PANEL IZQUIERDO: CONFIG ── -->
  <div class="panel config-editor">
    <div class="panel-header">
      <span class="panel-icon">⚙️</span>
      <span class="panel-title">config.yaml</span>
      <button class="btn btn-save" onclick="saveConfig()" style="margin-left:auto">
        💾 Guardar
      </button>
    </div>
    <textarea id="config-yaml" spellcheck="false"></textarea>
    <div class="btn-row">
      <button class="btn btn-primary" id="btn-run-all" onclick="runAll()">
        <span class="spinner" id="spin-all"></span>
        ▶ Procesar todos los blogs
      </button>
      <button class="btn btn-secondary" onclick="validateConfig()">
        ✓ Validar YAML
      </button>
      <button class="btn btn-secondary" onclick="clearLog()">
        🗑 Limpiar log
      </button>
      <label style="display:flex;align-items:center;gap:.4rem;font-size:.8rem;
                    font-family:var(--mono);color:var(--muted);cursor:pointer;">
        <input type="checkbox" id="chk-force"> Re-descargar
      </label>
    </div>
  </div>

  <!-- ── PANEL DERECHO SUPERIOR: BLOGS ── -->
  <div class="panel" style="grid-column:2;grid-row:1">
    <div class="panel-header">
      <span class="panel-icon">📚</span>
      <span class="panel-title">Blogs configurados</span>
    </div>
    <div class="summary-grid" id="summary-grid">
      <div class="stat-card">
        <div class="stat-label">TOTAL BLOGS</div>
        <div class="stat-value" id="stat-blogs">—</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">POSTS EXTRAÍDOS</div>
        <div class="stat-value" id="stat-posts">—</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">COMPLETADOS</div>
        <div class="stat-value" id="stat-done">—</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">ERRORES</div>
        <div class="stat-value" id="stat-errors" style="color:var(--err)">—</div>
      </div>
    </div>
    <div class="blog-list" id="blog-list">
      <div style="color:var(--muted);font-size:.85rem">
        Guarda la configuración para ver los blogs.
      </div>
    </div>
    <div class="btn-row" style="margin-top:1rem">
      <button class="btn btn-secondary" onclick="openOutputDir()">📂 Ver archivos</button>
      <button class="btn btn-secondary" onclick="refreshBlogList()">↺ Actualizar lista</button>
    </div>
  </div>

  <!-- ── PANEL IA ── -->
  <div class="panel" id="ai-panel" style="grid-column:1;grid-row:2">
    <div class="panel-header">
      <span class="panel-icon">🤖</span>
      <span class="panel-title">Enriquecimiento IA (LM Studio)</span>
      <button class="btn btn-secondary" onclick="testAI()"
              style="margin-left:auto;padding:.3rem .7rem;font-size:.75rem">
        🔌 Probar conexión
      </button>
    </div>

    <div id="ai-status" style="margin-bottom:1rem;padding:.6rem .9rem;
         border-radius:5px;font-size:.8rem;font-family:var(--mono);
         background:var(--bg);border:1px solid var(--border);color:var(--muted)">
      Estado: no verificado — pulsa "Probar conexión"
    </div>

    <div style="display:flex;flex-wrap:wrap;gap:1rem;margin-bottom:1rem">
      <div style="flex:1;min-width:200px">
        <div style="font-size:.75rem;font-family:var(--mono);color:var(--muted);
                    margin-bottom:.4rem;text-transform:uppercase;letter-spacing:.06em">
          Tareas activas
        </div>
        <div id="ai-tasks" style="display:flex;flex-direction:column;gap:.3rem">
          <label class="ai-task-row">
            <input type="checkbox" id="task-generate_tags" value="generate_tags" onchange="syncAITasks()">
            <span>🏷 Generar etiquetas</span>
          </label>
          <label class="ai-task-row">
            <input type="checkbox" id="task-summarize" value="summarize" onchange="syncAITasks()">
            <span>📝 Resumir (excerpt)</span>
          </label>
          <label class="ai-task-row">
            <input type="checkbox" id="task-classify" value="classify" onchange="syncAITasks()">
            <span>🗂 Clasificar (vocabulario controlado)</span>
          </label>
          <label class="ai-task-row">
            <input type="checkbox" id="task-reformat" value="reformat" onchange="syncAITasks()">
            <span>✍️ Reformatear texto sin estructura <span style="color:var(--warn)">(recomendado)</span></span>
          </label>
          <label class="ai-task-row">
            <input type="checkbox" id="task-clean_html" value="clean_html" onchange="syncAITasks()">
            <span>🧹 Reparar HTML muy degradado <span style="color:var(--warn)">(lento)</span></span>
          </label>
        </div>
      </div>
      <div style="flex:1;min-width:200px">
        <div style="display:flex;align-items:center;gap:.5rem;
                    margin-bottom:.4rem;">
          <span style="font-size:.75rem;font-family:var(--mono);color:var(--muted);
                    text-transform:uppercase;letter-spacing:.06em">Vocabulario controlado</span>
          <button class="btn btn-secondary" onclick="editVocab()"
                  style="padding:.15rem .5rem;font-size:.7rem;margin-left:auto">✏️ Editar</button>
          <button class="btn btn-save" onclick="saveVocab()"
                  id="btn-save-vocab" style="padding:.15rem .5rem;font-size:.7rem;display:none">💾</button>
        </div>
        <div id="vocab-list" style="font-size:.75rem;color:var(--muted);
             font-family:var(--mono);max-height:160px;overflow-y:auto;
             line-height:1.8;border:1px solid var(--border);border-radius:5px;
             padding:.5rem .75rem;background:var(--bg)">
          Cargando…
        </div>
        <textarea id="vocab-editor" style="display:none;width:100%;height:160px;
             font-family:var(--mono);font-size:.75rem;resize:vertical;
             border:1px solid var(--accent);border-radius:5px;padding:.5rem;
             background:var(--bg);outline:none;" spellcheck="false"
             placeholder="Una entrada por línea..."></textarea>
      </div>
    </div>

    <div style="font-size:.75rem;font-family:var(--mono);color:var(--muted);
                padding:.5rem .75rem;border:1px solid var(--border);border-radius:5px;
                background:var(--bg)">
      ⚡ Los cambios en las tareas se guardan automáticamente en config.yaml.
      La caché evita reprocesar posts ya enriquecidos.
      Directorio de caché: <code>output/ai_cache/</code>
    </div>
  </div>

  <!-- ── PANEL DERECHO INFERIOR: LOG ── -->
  <div class="panel log-panel">
    <div class="panel-header">
      <span class="panel-icon">📋</span>
      <span class="panel-title">Log de progreso</span>
      <span id="log-status" style="margin-left:auto;font-family:var(--mono);
            font-size:.75rem;color:var(--muted)">Inactivo</span>
    </div>
    <div id="log-output"></div>
  </div>

</div>

<div id="toast"></div>

<script src="/static/app.js"></script>
</body>
</html>"""


# ─── RUTAS FLASK ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(INTERFACE_HTML)

@app.route("/api/config/raw", methods=["GET"])
def api_config_raw():
    """Devuelve el YAML como texto plano sin escapado HTML ni JSON."""
    from flask import Response
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else ""
        return Response(text, mimetype="text/plain; charset=utf-8")
    except Exception:
        return Response("", mimetype="text/plain; charset=utf-8")


@app.route("/api/config", methods=["GET"])
def api_get_config():
    try:
        cfg = load_config(str(CONFIG_PATH))
        return jsonify({"ok": True, "config": cfg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/config", methods=["POST"])
def api_save_config():
    data = request.get_json()
    yaml_text = data.get("yaml", "")
    try:
        # Validar primero
        yaml.safe_load(yaml_text)
        CONFIG_PATH.write_text(yaml_text, encoding="utf-8")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/validate", methods=["POST"])
def api_validate():
    data = request.get_json()
    yaml_text = data.get("yaml", "")
    try:
        cfg = yaml.safe_load(yaml_text)
        blogs = cfg.get("blogs", [])
        return jsonify({"ok": True, "blogs": len(blogs)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/run", methods=["POST"])
def api_run():
    data        = request.get_json()
    force       = data.get("force", False)
    blog_index  = data.get("blog_index", None)

    try:
        cfg = load_config(str(CONFIG_PATH))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

    job_id = f"job_{int(time.time() * 1000)}"
    q = queue.Queue()
    progress_queues[job_id] = q
    job_results[job_id]     = []

    def worker():
        blogs = cfg.get("blogs", [])

        if blog_index is not None:
            # Solo un blog
            selected = [blogs[blog_index]] if blog_index < len(blogs) else []
        else:
            selected = [b for b in blogs if b.get("enabled", True)]

        # Obtener índices originales para el UI
        orig_indices = {}
        for i, b in enumerate(blogs):
            orig_indices[b.get("url", "")] = i

        for blog_cfg in selected:
            url = blog_cfg.get("url", "")
            ui_idx = orig_indices.get(url, 0)

            q.put(json.dumps({
                "type": "blog_start",
                "idx":  ui_idx,
                "title": blog_cfg.get("title", url)
            }))

            def cb(msg, _idx=ui_idx):
                q.put(json.dumps({"type": "log", "msg": msg}))

            res = run_blog(blog_cfg, cfg, progress_cb=cb, force_extract=force)
            q.put(json.dumps({
                "type":    "blog_done",
                "idx":     ui_idx,
                "success": res["success"],
                "count":   res.get("post_count", 0),
                "path":    res.get("output_path", ""),
            }))

        q.put(json.dumps({"type": "done"}))

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/stream/<job_id>")
def api_stream(job_id):
    q = progress_queues.get(job_id)
    if not q:
        return jsonify({"error": "job not found"}), 404

    def event_stream():
        while True:
            try:
                msg = q.get(timeout=30)
                yield f"data: {msg}\n\n"
                data = json.loads(msg)
                if data.get("type") == "done":
                    break
            except queue.Empty:
                yield "data: {\"type\":\"ping\"}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


@app.route("/output/")
def output_index():
    """Lista los archivos HTML generados en el directorio output."""
    output_dir = Path(load_config(str(CONFIG_PATH)).get("output", {}).get("dir", "./output"))
    if not output_dir.exists():
        return "<h2>Sin archivos generados aún.</h2>", 404

    files = sorted(output_dir.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
    items = "".join(
        f'<li style="margin:.5rem 0"><a href="/output/{f.name}" '
        f'style="font-family:monospace;color:#1d4ed8">{f.name}</a> '
        f'<span style="color:#64748b;font-size:.85rem">({f.stat().st_size // 1024} KB)</span></li>'
        for f in files
    )
    return f"""<html><body style="font-family:system-ui;padding:2rem;max-width:600px;margin:0 auto">
    <h2 style="margin-bottom:1rem">📁 Archivos generados</h2>
    <ul style="list-style:none;padding:0">{items}</ul>
    <p style="margin-top:1rem"><a href="/" style="color:#1d4ed8">← Volver al panel</a></p>
    </body></html>"""


@app.route("/output/<filename>")
def serve_output(filename):
    output_dir = Path(load_config(str(CONFIG_PATH)).get("output", {}).get("dir", "./output"))
    file_path  = output_dir / filename
    if file_path.exists():
        return send_file(str(file_path.absolute()))
    return "Archivo no encontrado", 404


@app.route("/api/ai/test", methods=["GET"])
def api_ai_test():
    try:
        cfg = load_config(str(CONFIG_PATH))
        result = test_connection(cfg)
        # Usar vocabulario personalizado si existe en config, si no el por defecto
        custom_vocab = cfg.get("ai", {}).get("vocabulary", None)
        result["vocabulary"] = custom_vocab if custom_vocab else CONTROLLED_VOCABULARY
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "models": [], "message": str(e), "vocabulary": CONTROLLED_VOCABULARY})


@app.route("/api/vocab", methods=["POST"])
def api_save_vocab():
    """Guarda el vocabulario controlado en config.yaml."""
    data = request.get_json()
    vocabulary = data.get("vocabulary", [])
    try:
        cfg = load_config(str(CONFIG_PATH))
        cfg.setdefault("ai", {})["vocabulary"] = vocabulary
        # Guardar manteniendo el resto del YAML intacto
        import yaml
        CONFIG_PATH.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False,
                                         sort_keys=False), encoding="utf-8")
        return jsonify({"ok": True, "count": len(vocabulary)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/oai")
def oai_endpoint():
    """Endpoint OAI-PMH dinámico."""
    from flask import request as freq, Response
    try:
        cfg      = load_config(str(CONFIG_PATH))
        if not cfg.get("oai_pmh", {}).get("enabled", False):
            return Response("OAI-PMH no está habilitado en config.yaml. "
                           "Activa oai_pmh.enabled: true para usar este endpoint.",
                           mimetype="text/plain", status=503)
        params   = dict(freq.args)
        slug     = params.pop("slug", "")
        # Si no se pasa slug, usar el primero habilitado
        if not slug:
            blogs = cfg.get("blogs", [])
            enabled = [b for b in blogs if b.get("enabled", True)]
            if enabled:
                from slugify import slugify
                slug = slugify(enabled[0].get("title", "blog"))
        output_dir = Path(cfg.get("output", {}).get("dir", "./output"))
        provider   = OAIPMHProvider(cfg, output_dir)
        xml        = provider.handle_request(params, slug)
        return Response(xml, mimetype="text/xml; charset=utf-8")
    except Exception as e:
        return Response(f"Error OAI-PMH: {e}", mimetype="text/plain", status=500)


@app.route("/api/quality/<slug>")
def api_quality(slug):
    """Devuelve el informe de calidad más reciente para un blog."""
    try:
        cfg        = load_config(str(CONFIG_PATH))
        output_dir = Path(cfg.get("output", {}).get("dir", "./output"))
        report_path= output_dir / "quality_reports" / f"{slug}_quality.json"
        if not report_path.exists():
            return jsonify({"ok": False, "error": "Informe no disponible. Ejecuta el pipeline primero."})
        with open(report_path, encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"ok": True, "report": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


if __name__ == "__main__":
    print("\n" + "═" * 50)
    print("  BlogPreservationSuite — Panel de control")
    print("  http://localhost:5000")
    print("═" * 50 + "\n")
    app.run(debug=False, port=5000, threaded=True)
