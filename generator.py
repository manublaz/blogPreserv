"""
generator.py — Genera el HTML final autocontenido a partir de los posts limpios.
Incluye: índice, buscador full-text, metadatos Dublin Core / Open Graph / METS, 
iframes YouTube responsive, imágenes base64, diseño minimalista.
"""

import json
import re
import logging
from datetime import datetime
from pathlib import Path
from slugify import slugify

logger = logging.getLogger(__name__)


def generate_site(posts: list, blog_cfg: dict, config: dict, output_dir: Path) -> Path:
    """
    Genera el sitio HTML completo para un blog.
    Devuelve la ruta al archivo generado.
    """
    design   = config.get("design", {})
    author   = config.get("author", {})
    blog_title = blog_cfg.get("title", "Blog")
    slug     = slugify(blog_title)

    # Ordenar posts por fecha descendente
    posts_sorted = sorted(
        posts, key=lambda p: p.get("published", ""), reverse=True
    )

    # Construir índice de búsqueda (texto plano por post)
    search_index = _build_search_index(posts_sorted)

    # Construir índice cronológico
    timeline = _build_timeline(posts_sorted)

    html = _render_page(
        posts=posts_sorted,
        search_index=search_index,
        timeline=timeline,
        blog_title=blog_title,
        blog_url=blog_cfg.get("url", ""),
        author=author,
        design=design,
    )

    out_path = output_dir / f"{slug}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    logger.info(f"Sitio generado: {out_path}")
    return out_path


def _build_search_index(posts: list) -> list:
    """Construye el índice de búsqueda full-text embebido como JSON."""
    from bs4 import BeautifulSoup
    index = []
    for i, post in enumerate(posts):
        soup = BeautifulSoup(post.get("clean_html", ""), "html.parser")
        text = soup.get_text(" ", strip=True)
        text = re.sub(r'\s+', ' ', text)[:2000]  # máximo 2000 chars por post
        index.append({
            "id":      i,
            "title":   post.get("title", ""),
            "date":    post.get("published", "")[:10],
            "month":   post.get("published", "")[:7],
            "tags":    post.get("tags", []),
            "categories": post.get("categories", []),
            "excerpt": post.get("excerpt", ""),
            "text":    text,
        })
    return index


MESES_ES = {
    1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
    7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre",
}

def _build_timeline(posts: list) -> dict:
    """Organiza posts por año → mes para el índice lateral con claves ISO."""
    timeline = {}
    for i, post in enumerate(posts):
        date = post.get("published", "")
        if not date:
            continue
        try:
            dt        = datetime.strptime(date[:10], "%Y-%m-%d")
            year      = dt.year
            month_key = dt.strftime("%Y-%m")
            month_lbl = f"{MESES_ES[dt.month]} {dt.year}"
        except Exception:
            year, month_key, month_lbl = "Sin fecha", "sin-fecha", "Sin fecha"
        if year not in timeline:
            timeline[year] = {}
        if month_key not in timeline[year]:
            timeline[year][month_key] = {"label": month_lbl, "items": []}
        timeline[year][month_key]["items"].append({"idx": i, "title": post.get("title","Sin título"), "date": date[:10]})
    return timeline


def _render_page(posts, search_index, timeline, blog_title, blog_url, author, design) -> str:
    """Renderiza el HTML completo de la página."""

    accent    = design.get("accent_color", "#1d4ed8")
    secondary = design.get("secondary_color", "#475569")
    bg        = design.get("background_color", "#ffffff")
    text_col  = design.get("text_color", "#1e293b")
    font_size = design.get("font_size_base", "17px")
    font_body = design.get("font_family", "Georgia, serif")
    font_ui   = design.get("font_family_ui", "'IBM Plex Sans', system-ui, sans-serif")
    font_mono = design.get("font_family_mono", "'IBM Plex Mono', monospace")

    author_name = author.get("name", "")
    author_role = author.get("role", "")
    author_inst = author.get("institution", "")

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    year_now = datetime.now().year

    # Posts HTML
    posts_html = "\n".join(_render_post(p, i) for i, p in enumerate(posts))

    # Índice lateral HTML
    sidebar_html = _render_sidebar(timeline)

    # Search index JSON
    search_json = json.dumps(search_index, ensure_ascii=False)

    # Tags únicos
    all_tags = sorted(set(t for p in posts for t in p.get("tags", [])))
    tags_html = " ".join(
        f'<button class="tag-btn" onclick="filterTag(\'{t}\')">{t}</button>'
        for t in all_tags[:50]
    )

    # Metadatos Dublin Core
    dc_meta = _render_dublin_core(blog_title, blog_url, author_name, posts)

    # Metadatos METS (como comentario estructurado)
    mets_comment = _render_mets_comment(blog_title, blog_url, author_name, author_inst, posts, now)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="robots" content="index, follow">
  <title>{blog_title} — Archivo Digital</title>
  <meta name="description" content="Archivo digital preservado de {blog_title}. {author_name}.">
  <meta name="author" content="{author_name}">
  <meta name="generator" content="BlogPreservationSuite v1.0">

  <!-- Open Graph -->
  <meta property="og:title" content="{blog_title} — Archivo Digital">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{blog_url}">
  <meta property="og:description" content="Archivo digital preservado de {blog_title}.">
  <meta property="og:locale" content="es_ES">

  <!-- Dublin Core -->
{dc_meta}

  <!-- Schema.org -->
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Blog",
    "name": "{blog_title}",
    "url": "{blog_url}",
    "author": {{
      "@type": "Person",
      "name": "{author_name}",
      "jobTitle": "{author_role}",
      "affiliation": "{author_inst}"
    }},
    "dateModified": "{now}",
    "inLanguage": "es"
  }}
  </script>

  <!-- Google Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Lora:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">

  <style>
    /* ─── RESET & BASE ─────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --accent:    {accent};
      --accent-light: color-mix(in srgb, {accent} 15%, white);
      --secondary: {secondary};
      --bg:        {bg};
      --surface:   #f8fafc;
      --border:    #e2e8f0;
      --text:      {text_col};
      --text-muted: #64748b;
      --font-body: {font_body};
      --font-ui:   {font_ui};
      --font-mono: {font_mono};
      --font-size: {font_size};
      --radius:    6px;
      --shadow:    0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06);
      --shadow-md: 0 4px 6px rgba(0,0,0,.07), 0 2px 4px rgba(0,0,0,.06);
    }}

    html {{ scroll-behavior: smooth; }}

    body {{
      font-family:    var(--font-ui);
      font-size:      var(--font-size);
      color:          var(--text);
      background:     var(--bg);
      line-height:    1.65;
      -webkit-font-smoothing: antialiased;
    }}

    /* ─── LAYOUT ───────────────────────────────────── */
    #app {{ display: flex; flex-direction: column; min-height: 100vh; }}

    header.site-header {{
      background: var(--accent);
      color: #fff;
      padding: 1.25rem 2rem;
      position: sticky; top: 0; z-index: 100;
      box-shadow: var(--shadow-md);
    }}
    .header-inner {{
      max-width: 1400px; margin: 0 auto;
      display: flex; align-items: center; gap: 1.5rem;
      flex-wrap: wrap;
    }}
    .site-title {{ font-size: 1.25rem; font-weight: 600; letter-spacing: -.01em; flex: 1; }}
    .site-subtitle {{ font-size: .8rem; opacity: .8; margin-top: .1rem; font-family: var(--font-mono); }}

    .search-bar {{
      display: flex; align-items: center; gap: .5rem;
      background: rgba(255,255,255,.15);
      border: 1px solid rgba(255,255,255,.3);
      border-radius: var(--radius);
      padding: .4rem .75rem;
      flex: 0 0 320px;
    }}
    .search-bar input {{
      background: transparent; border: none; outline: none;
      color: #fff; font-size: .9rem; font-family: var(--font-ui);
      width: 100%;
    }}
    .search-bar input::placeholder {{ color: rgba(255,255,255,.6); }}
    .search-icon {{ opacity: .7; flex-shrink: 0; }}

    .main-layout {{
      display: flex; flex: 1;
      max-width: 1400px; margin: 0 auto;
      width: 100%; padding: 0 1rem;
      gap: 2rem; align-items: flex-start;
    }}

    /* ─── SIDEBAR ──────────────────────────────────── */
    aside.sidebar {{
      flex: 0 0 260px; position: sticky; top: 72px;
      max-height: calc(100vh - 80px); overflow-y: auto;
      padding: 1.5rem 0; scrollbar-width: thin;
    }}
    .sidebar-section {{ margin-bottom: 1.5rem; }}
    .sidebar-heading {{
      font-size: .7rem; font-weight: 600; letter-spacing: .1em;
      text-transform: uppercase; color: var(--text-muted);
      margin-bottom: .75rem; font-family: var(--font-mono);
    }}
    .sidebar-year {{
      font-size: .85rem; font-weight: 600; color: var(--accent);
      cursor: pointer; padding: .25rem 0;
      display: flex; align-items: center; gap: .5rem;
    }}
    .sidebar-year::before {{ content: "▶"; font-size: .6rem; transition: transform .2s; }}
    .sidebar-year.open::before {{ transform: rotate(90deg); }}
    .sidebar-months {{ display: none; padding-left: 1rem; }}
    .sidebar-year.open + .sidebar-months {{ display: block; }}
    .sidebar-month {{
      font-size: .8rem; color: var(--text-muted);
      margin-bottom: .25rem; cursor: pointer;
    }}
    .sidebar-month:hover {{ color: var(--accent); }}
    .sidebar-month.active-month {{
      color: var(--accent); font-weight: 600;
      background: var(--accent-light); border-radius: 3px;
      padding-left: .3rem; margin-left: -.3rem;
    }}
    .post-count {{
      font-size: .7rem; background: var(--border);
      border-radius: 9px; padding: .1rem .4rem;
      font-family: var(--font-mono);
    }}

    .tag-cloud {{ display: flex; flex-wrap: wrap; gap: .35rem; }}
    .tag-btn {{
      font-size: .75rem; padding: .2rem .55rem;
      border: 1px solid var(--border); border-radius: 99px;
      background: var(--surface); color: var(--text-muted);
      cursor: pointer; font-family: var(--font-ui);
      transition: all .15s;
    }}
    .tag-btn:hover, .tag-btn.active {{
      background: var(--accent); color: #fff;
      border-color: var(--accent);
    }}

    /* ─── MAIN CONTENT ─────────────────────────────── */
    main.content {{ flex: 1; min-width: 0; padding: 2rem 0; }}

    /* Stats bar */
    .stats-bar {{
      display: flex; gap: 1.5rem; align-items: center;
      margin-bottom: 1.5rem; padding-bottom: 1rem;
      border-bottom: 1px solid var(--border);
      font-size: .85rem; color: var(--text-muted);
      font-family: var(--font-mono);
    }}
    .stats-bar strong {{ color: var(--text); }}

    /* Search results info */
    #search-info {{
      padding: .6rem 1rem; background: var(--accent-light);
      border-left: 3px solid var(--accent);
      border-radius: 0 var(--radius) var(--radius) 0;
      font-size: .875rem; margin-bottom: 1.25rem;
      display: none;
    }}

    /* ─── POST CARDS ───────────────────────────────── */
    .post-card {{
      border: 1px solid var(--border);
      border-radius: var(--radius);
      margin-bottom: 1.5rem;
      background: var(--bg);
      box-shadow: var(--shadow);
      overflow: hidden;
      transition: box-shadow .2s;
    }}
    .post-card:hover {{ box-shadow: var(--shadow-md); }}
    .post-card.hidden {{ display: none; }}

    .post-header {{
      padding: 1.25rem 1.5rem .75rem;
      border-bottom: 1px solid var(--border);
      cursor: pointer;
      display: flex; align-items: flex-start; gap: 1rem;
    }}
    .post-header:hover .post-title {{ color: var(--accent); }}

    .post-meta-col {{ flex: 0 0 90px; text-align: right; }}
    .post-date {{
      font-size: .75rem; font-family: var(--font-mono);
      color: var(--text-muted); white-space: nowrap;
    }}
    .post-num {{
      font-size: .7rem; font-family: var(--font-mono);
      color: var(--border); margin-top: .2rem;
    }}

    .post-title-col {{ flex: 1; }}
    .post-title {{
      font-family: Lora, Georgia, serif;
      font-size: 1.15rem; font-weight: 600;
      line-height: 1.35; color: var(--text);
      transition: color .15s;
      margin-bottom: .35rem;
    }}
    .post-tags {{ display: flex; flex-wrap: wrap; gap: .3rem; }}
    .post-tag {{
      font-size: .7rem; padding: .15rem .45rem;
      background: var(--accent-light); color: var(--accent);
      border-radius: 99px; font-family: var(--font-ui);
    }}
    .post-excerpt {{
      font-size: .875rem; color: var(--text-muted);
      margin-top: .4rem; line-height: 1.5;
    }}

    .post-toggle {{
      font-size: .75rem; font-family: var(--font-mono);
      color: var(--accent); padding: .25rem .5rem;
      flex-shrink: 0; align-self: flex-start;
      margin-top: .2rem;
    }}

    .post-body {{
      display: none; padding: 1.5rem;
      border-top: 1px solid var(--border);
    }}
    .post-body.open {{ display: block; }}

    /* ─── BODY TYPOGRAPHY ──────────────────────────── */
    .post-body {{ font-family: var(--font-body); }}
    .post-body p  {{ margin-bottom: 1.1em; }}
    .post-body h1, .post-body h2, .post-body h3,
    .post-body h4, .post-body h5, .post-body h6 {{
      font-family: var(--font-ui); font-weight: 600;
      margin: 1.5em 0 .5em; line-height: 1.3;
      color: var(--text);
    }}
    .post-body h2 {{ font-size: 1.25rem; }}
    .post-body h3 {{ font-size: 1.1rem; }}
    .post-body a  {{ color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }}
    .post-body a:hover {{ text-decoration: none; }}
    .post-body blockquote {{
      border-left: 3px solid var(--accent);
      padding: .75rem 1.25rem; margin: 1.25rem 0;
      background: var(--surface); border-radius: 0 var(--radius) var(--radius) 0;
      font-style: italic; color: var(--secondary);
    }}
    .post-body ul, .post-body ol {{ padding-left: 1.5rem; margin-bottom: 1em; }}
    .post-body li {{ margin-bottom: .35em; }}
    .post-body table {{
      width: 100%; border-collapse: collapse;
      margin: 1.25rem 0; font-size: .9rem;
    }}
    .post-body th, .post-body td {{
      border: 1px solid var(--border);
      padding: .5rem .75rem; text-align: left;
    }}
    .post-body th {{ background: var(--surface); font-family: var(--font-ui); }}
    .post-body img {{
      max-width: 100%; height: auto; border-radius: var(--radius);
      display: block; margin: 1rem auto;
    }}
    .post-body pre, .post-body code {{
      font-family: var(--font-mono); font-size: .875rem;
      background: var(--surface); border-radius: var(--radius);
    }}
    .post-body pre {{ padding: 1rem; overflow-x: auto; margin: 1em 0; }}
    .post-body code {{ padding: .15em .35em; }}

    /* ─── YOUTUBE RESPONSIVE ───────────────────────── */
    .yt-wrapper {{
      position: relative; width: 100%;
      padding-top: 56.25%; /* 16:9 */
      margin: 1.25rem 0; border-radius: var(--radius); overflow: hidden;
      background: #000;
    }}
    .yt-wrapper iframe {{
      position: absolute; top: 0; left: 0;
      width: 100% !important; height: 100% !important;
      border: none;
    }}

    /* ─── POST FOOTER ──────────────────────────────── */
    .post-footer {{
      padding: .75rem 1.5rem;
      border-top: 1px solid var(--border);
      font-size: .8rem; color: var(--text-muted);
      font-family: var(--font-mono);
      display: flex; gap: 1rem; flex-wrap: wrap;
      align-items: center;
    }}
    .post-original-link {{ color: var(--accent); text-decoration: none; }}
    .post-original-link:hover {{ text-decoration: underline; }}

    /* ─── FOOTER ───────────────────────────────────── */
    footer.site-footer {{
      border-top: 1px solid var(--border);
      padding: 2rem;
      text-align: center;
      font-size: .8rem;
      color: var(--text-muted);
      font-family: var(--font-mono);
    }}

    /* ─── RESPONSIVE ───────────────────────────────── */
    @media (max-width: 900px) {{
      .main-layout {{ flex-direction: column; }}
      aside.sidebar {{ position: static; max-height: none; flex: none; width: 100%; }}
      .search-bar {{ flex: 0 0 100%; }}
    }}
    @media (max-width: 600px) {{
      header.site-header {{ padding: 1rem; }}
      .post-header {{ padding: 1rem; flex-wrap: wrap; }}
      .post-meta-col {{ flex: 0 0 100%; text-align: left; order: -1; }}
      .post-body {{ padding: 1rem; }}
    }}

    /* ─── PRINT ────────────────────────────────────── */
    @media print {{
      aside.sidebar, .search-bar {{ display: none; }}
      .post-body {{ display: block !important; }}
      .post-card {{ break-inside: avoid; box-shadow: none; border: 1px solid #ddd; }}
    }}

    /* ─── HIGHLIGHT SEARCH ─────────────────────────── */
    mark {{
      background: color-mix(in srgb, {accent} 20%, white);
      color: var(--text);
      border-radius: 2px;
      padding: 0 2px;
    }}
  </style>
</head>
<body>
{mets_comment}
<div id="app">

  <!-- HEADER -->
  <header class="site-header">
    <div class="header-inner">
      <div>
        <div class="site-title">{blog_title}</div>
        <div class="site-subtitle">{author_name} · Archivo Digital Preservado</div>
      </div>
      <div class="search-bar">
        <svg class="search-icon" width="16" height="16" fill="none" stroke="white" stroke-width="2"
             viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
        <input type="text" id="search-input" placeholder="Buscar en todos los artículos…"
               oninput="doSearch(this.value)" autocomplete="off" spellcheck="false">
      </div>
      <button id="clear-search" onclick="clearSearch()"
              style="background:rgba(255,255,255,.15);border:none;color:#fff;
                     border-radius:var(--radius);padding:.4rem .75rem;
                     cursor:pointer;font-size:.85rem;display:none;">✕ Limpiar</button>
    </div>
  </header>

  <!-- MAIN -->
  <div class="main-layout">

    <!-- SIDEBAR -->
    <aside class="sidebar">
      {sidebar_html}
      <div class="sidebar-section">
        <div class="sidebar-heading">Etiquetas</div>
        <div class="tag-cloud">{tags_html}</div>
      </div>
    </aside>

    <!-- CONTENT -->
    <main class="content" id="main-content">
      <div class="stats-bar">
        <span><strong id="visible-count">{len(posts)}</strong> entradas</span>
        <span>·</span>
        <span>Archivo preservado {year_now}</span>
        <span>·</span>
        <button onclick="expandAll()"
                style="background:none;border:none;color:var(--accent);
                       cursor:pointer;font-family:var(--font-mono);
                       font-size:.85rem;padding:0;">Expandir todo</button>
        <span>·</span>
        <button onclick="collapseAll()"
                style="background:none;border:none;color:var(--accent);
                       cursor:pointer;font-family:var(--font-mono);
                       font-size:.85rem;padding:0;">Colapsar todo</button>
      </div>
      <div id="search-info"></div>
      <div id="posts-container">
{posts_html}
      </div>
      <div id="no-results" style="display:none;text-align:center;
           padding:3rem;color:var(--text-muted);font-family:var(--font-mono);">
        Sin resultados para esta búsqueda.
      </div>
    </main>

  </div>

  <!-- FOOTER -->
  <footer class="site-footer">
    <p><strong>{blog_title}</strong> — Archivo digital preservado</p>
    <p>{author_name} · {author_role} · {author_inst}</p>
    <p style="margin-top:.5rem;opacity:.6;">
      Generado con BlogPreservationSuite · {datetime.now().strftime("%d/%m/%Y")} ·
      Fuente original: <a href="{blog_url}" target="_blank" rel="noopener"
                          style="color:var(--accent)">{blog_url}</a>
    </p>
  </footer>

</div>

<!-- SEARCH ENGINE -->
<script>
const SEARCH_INDEX = {search_json};

function doSearch(query) {{
  query = query.trim().toLowerCase();
  const cards   = document.querySelectorAll('.post-card');
  const info    = document.getElementById('search-info');
  const noRes   = document.getElementById('no-results');
  const clearBtn= document.getElementById('clear-search');
  const counter = document.getElementById('visible-count');

  // Limpiar highlights previos
  clearHighlights();

  if (!query) {{
    cards.forEach(c => c.classList.remove('hidden'));
    info.style.display = 'none';
    clearBtn.style.display = 'none';
    counter.textContent = cards.length;
    noRes.style.display = 'none';
    return;
  }}

  clearBtn.style.display = 'inline-block';
  const terms = query.split(/\\s+/).filter(Boolean);
  let visible = 0;

  cards.forEach((card, idx) => {{
    const entry   = SEARCH_INDEX[idx];
    if (!entry) return;
    const haystack = (entry.title + ' ' + entry.text + ' ' + entry.tags.join(' ')).toLowerCase();
    const match = terms.every(t => haystack.includes(t));
    if (match) {{
      card.classList.remove('hidden');
      visible++;
      // Highlight en título y excerpt
      highlightCard(card, terms);
    }} else {{
      card.classList.add('hidden');
    }}
  }});

  counter.textContent = visible;
  noRes.style.display = visible === 0 ? 'block' : 'none';
  info.style.display  = 'block';
  info.textContent    = `${{visible}} resultado${{visible !== 1 ? 's' : ''}} para "${{query}}"`;
}}

function highlightCard(card, terms) {{
  const titleEl   = card.querySelector('.post-title');
  const excerptEl = card.querySelector('.post-excerpt');
  [titleEl, excerptEl].forEach(el => {{
    if (!el) return;
    let html = el.getAttribute('data-original') || el.innerHTML;
    el.setAttribute('data-original', html);
    terms.forEach(t => {{
      const re = new RegExp(`(${{t.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&')}})`, 'gi');
      html = html.replace(re, '<mark>$1</mark>');
    }});
    el.innerHTML = html;
  }});
}}

function clearHighlights() {{
  document.querySelectorAll('[data-original]').forEach(el => {{
    el.innerHTML = el.getAttribute('data-original');
    el.removeAttribute('data-original');
  }});
}}

function clearSearch() {{
  const input = document.getElementById('search-input');
  input.value = '';
  doSearch('');
  document.querySelectorAll('.tag-btn.active').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.sidebar-month.active-month').forEach(m => m.classList.remove('active-month'));
}}

function filterTag(tag) {{
  const input = document.getElementById('search-input');
  const btn   = document.querySelector(`.tag-btn[onclick="filterTag('${{tag}}')"]`);
  const isActive = btn && btn.classList.contains('active');

  document.querySelectorAll('.tag-btn').forEach(b => b.classList.remove('active'));

  if (!isActive) {{
    input.value = tag;
    if (btn) btn.classList.add('active');
    doSearch(tag);
  }} else {{
    input.value = '';
    doSearch('');
  }}
}}

function filterByMonth(monthKey) {{
  // Filtra posts cuyo campo "month" (YYYY-MM) coincide exactamente
  const cards   = document.querySelectorAll('.post-card');
  const info    = document.getElementById('search-info');
  const noRes   = document.getElementById('no-results');
  const counter = document.getElementById('visible-count');
  const clearBtn= document.getElementById('clear-search');

  // Desactivar filtro si ya estaba activo
  const activeMonth = document.querySelector('.sidebar-month.active-month');
  if (activeMonth && activeMonth.dataset.month === monthKey) {{
    // Deseleccionar — mostrar todo
    activeMonth.classList.remove('active-month');
    cards.forEach(c => c.classList.remove('hidden'));
    info.style.display = 'none';
    clearBtn.style.display = 'none';
    counter.textContent = cards.length;
    noRes.style.display = 'none';
    document.getElementById('search-input').value = '';
    return;
  }}

  // Marcar mes activo
  document.querySelectorAll('.sidebar-month').forEach(m => m.classList.remove('active-month'));
  const clickedEl = document.querySelector(`.sidebar-month[data-month="${{monthKey}}"]`);
  if (clickedEl) clickedEl.classList.add('active-month');

  clearHighlights();
  let visible = 0;
  cards.forEach((card, idx) => {{
    const entry = SEARCH_INDEX[idx];
    if (!entry) return;
    if (entry.month === monthKey) {{
      card.classList.remove('hidden');
      visible++;
    }} else {{
      card.classList.add('hidden');
    }}
  }});

  counter.textContent = visible;
  noRes.style.display  = visible === 0 ? 'block' : 'none';
  info.style.display   = 'block';
  // Buscar el label del mes para mostrarlo
  const monthEl = document.querySelector(`.sidebar-month[data-month="${{monthKey}}"]`);
  const label   = monthEl ? monthEl.textContent.trim().replace(/\\d+$/, '').trim() : monthKey;
  info.textContent = `${{visible}} entrada${{visible !== 1 ? 's' : ''}} en ${{label}}`;
  clearBtn.style.display = 'inline-block';
  document.getElementById('search-input').value = '';
}}

function togglePost(idx) {{
  const body   = document.getElementById('post-body-' + idx);
  const header = document.getElementById('post-header-' + idx);
  if (!body) return;
  body.classList.toggle('open');
  const toggle = header.querySelector('.post-toggle');
  if (toggle) toggle.textContent = body.classList.contains('open') ? '[ − ]' : '[ + ]';
}}

function expandAll() {{
  document.querySelectorAll('.post-body').forEach(b => b.classList.add('open'));
  document.querySelectorAll('.post-toggle').forEach(t => t.textContent = '[ − ]');
}}

function collapseAll() {{
  document.querySelectorAll('.post-body').forEach(b => b.classList.remove('open'));
  document.querySelectorAll('.post-toggle').forEach(t => t.textContent = '[ + ]');
}}

// Sidebar accordion
document.querySelectorAll('.sidebar-year').forEach(el => {{
  el.addEventListener('click', () => el.classList.toggle('open'));
}});

// Abrir post si viene hash en URL
window.addEventListener('DOMContentLoaded', () => {{
  const hash = window.location.hash;
  if (hash) {{
    const target = document.querySelector(hash);
    if (target) {{
      const idx = target.dataset.idx;
      if (idx !== undefined) togglePost(idx);
      setTimeout(() => target.scrollIntoView({{behavior: 'smooth', block: 'start'}}), 100);
    }}
  }}
}});
</script>

</body>
</html>"""


def _render_post(post: dict, idx: int) -> str:
    """Renderiza el HTML de una sola tarjeta de post."""
    title   = post.get("title", "Sin título") or "Sin título"
    date    = post.get("published", "") or ""
    url     = post.get("url", "") or ""
    tags    = post.get("tags", []) or []
    excerpt = post.get("excerpt", "") or ""
    body    = post.get("clean_html", "") or ""
    author  = post.get("author", "") or ""

    # Formatear fecha
    date_display = ""
    if date:
        try:
            dt = datetime.strptime(date[:10], "%Y-%m-%d")
            date_display = dt.strftime("%-d %b %Y")
        except Exception:
            date_display = date[:10]

    tags_html = "".join(f'<span class="post-tag">{t}</span>' for t in tags[:8])
    url_html  = (f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
                 f'class="post-original-link">↗ Ver original</a>') if url else ""
    author_html = f"<span>{author}</span>" if author else ""

    # Sanitizar ID para HTML
    safe_title = re.sub(r'[^a-z0-9-]', '-', title.lower())[:40]

    return f"""        <article class="post-card" data-idx="{idx}" id="post-{safe_title}-{idx}">
          <div class="post-header" id="post-header-{idx}" onclick="togglePost({idx})">
            <div class="post-meta-col">
              <div class="post-date">{date_display}</div>
              <div class="post-num">#{idx + 1:03d}</div>
            </div>
            <div class="post-title-col">
              <div class="post-title">{_escape(title)}</div>
              <div class="post-tags">{tags_html}</div>
              <div class="post-excerpt">{_escape(excerpt)}</div>
            </div>
            <span class="post-toggle">[ + ]</span>
          </div>
          <div class="post-body" id="post-body-{idx}">
            {body}
          </div>
          <div class="post-footer">
            {author_html}
            {url_html}
            <span style="margin-left:auto">{date}</span>
          </div>
        </article>"""


def _render_sidebar(timeline: dict) -> str:
    """Renderiza el HTML del índice cronológico en el sidebar con filtrado por fecha real."""
    html_parts = ['<div class="sidebar-section">',
                  '<div class="sidebar-heading">Índice cronológico</div>']
    for year in sorted(timeline.keys(), reverse=True):
        months = timeline[year]
        total  = sum(len(v["items"]) for v in months.values())
        html_parts.append(
            f'<div class="sidebar-year">{year} '
            f'<span class="post-count">{total}</span></div>'
            f'<div class="sidebar-months">'
        )
        for month_key, month_data in sorted(months.items(), reverse=True):
            label = month_data["label"]
            count = len(month_data["items"])
            html_parts.append(
                f'<div class="sidebar-month" data-month="{month_key}" '
                f'onclick="filterByMonth(\'{month_key}\')">{label} '
                f'<span class="post-count">{count}</span></div>'
            )
        html_parts.append('</div>')
    html_parts.append('</div>')
    return "\n".join(html_parts)


def _render_dublin_core(title, url, author, posts) -> str:
    """Genera las meta-etiquetas Dublin Core."""
    dates = sorted([p.get("published", "") for p in posts if p.get("published")])
    date_start = dates[0][:10] if dates else ""
    date_end   = dates[-1][:10] if dates else ""
    return f"""  <link rel="schema.DC" href="http://purl.org/dc/elements/1.1/">
  <meta name="DC.title"       content="{title} — Archivo Digital">
  <meta name="DC.creator"     content="{author}">
  <meta name="DC.subject"     content="Blog; Documentación; Archivo Digital">
  <meta name="DC.description" content="Archivo digital preservado de {title}.">
  <meta name="DC.publisher"   content="{author}">
  <meta name="DC.date"        content="{date_end}">
  <meta name="DC.type"        content="Collection">
  <meta name="DC.format"      content="text/html">
  <meta name="DC.identifier"  content="{url}">
  <meta name="DC.language"    content="es">
  <meta name="DC.coverage"    content="{date_start}/{date_end}">
  <meta name="DC.rights"      content="© {author}. Todos los derechos reservados.">"""


def _render_mets_comment(title, url, author, institution, posts, now) -> str:
    """Genera un bloque METS como comentario HTML estructurado."""
    total = len(posts)
    dates = sorted([p.get("published", "") for p in posts if p.get("published")])
    date_start = dates[0][:10] if dates else ""
    date_end   = dates[-1][:10] if dates else ""

    return f"""<!--
METS: Metadata Encoding and Transmission Standard
=====================================================
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
           xmlns:mods="http://www.loc.gov/mods/v3"
           xmlns:xlink="http://www.w3.org/1999/xlink"
           OBJID="{url}"
           LABEL="{title} — Archivo Digital"
           TYPE="Blog Archive">

  <mets:metsHdr CREATEDATE="{now}">
    <mets:agent ROLE="CREATOR" TYPE="INDIVIDUAL">
      <mets:name>{author}</mets:name>
      <mets:note>{institution}</mets:note>
    </mets:agent>
    <mets:agent ROLE="ARCHIVIST" TYPE="ORGANIZATION">
      <mets:name>BlogPreservationSuite v1.0</mets:name>
    </mets:agent>
  </mets:metsHdr>

  <mets:dmdSec ID="DMD001">
    <mets:mdWrap MDTYPE="MODS">
      <mets:xmlData>
        <mods:mods>
          <mods:titleInfo><mods:title>{title}</mods:title></mods:titleInfo>
          <mods:name type="personal">
            <mods:namePart>{author}</mods:namePart>
            <mods:role><mods:roleTerm type="text">author</mods:roleTerm></mods:role>
          </mods:name>
          <mods:originInfo>
            <mods:dateIssued point="start">{date_start}</mods:dateIssued>
            <mods:dateIssued point="end">{date_end}</mods:dateIssued>
            <mods:dateCaptured>{now[:10]}</mods:dateCaptured>
          </mods:originInfo>
          <mods:typeOfResource>text</mods:typeOfResource>
          <mods:genre>blog</mods:genre>
          <mods:language><mods:languageTerm type="code">spa</mods:languageTerm></mods:language>
          <mods:location><mods:url>{url}</mods:url></mods:location>
          <mods:note>Total de entradas archivadas: {total}</mods:note>
        </mods:mods>
      </mets:xmlData>
    </mets:mdWrap>
  </mets:dmdSec>

</mets:mets>
-->"""


def _escape(text: str) -> str:
    """Escapa caracteres HTML especiales."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
