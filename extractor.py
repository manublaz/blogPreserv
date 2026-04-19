"""
extractor.py — Descarga todos los posts de blogs Blogspot via Atom Feed.
v1.2 — Logging detallado, redimensionado de imágenes grandes, mejor manejo de errores.
"""

import requests
import base64
import time
import re
import json
import logging
import urllib3
from io import BytesIO
from xml.etree import ElementTree as ET
from urllib.parse import urljoin, urlparse
from datetime import datetime
from pathlib import Path

# Suprimir advertencias SSL para blogs con certificados mal configurados
# (habitual en blogs de Blogger con dominios personalizados antiguos)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

ATOM_NS = "http://www.w3.org/2005/Atom"

YOUTUBE_PATTERNS = [
    r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([\w-]+)",
    r"(?:https?://)?(?:www\.)?youtu\.be/([\w-]+)",
    r"(?:https?://)?(?:www\.)?youtube\.com/embed/([\w-]+)",
]

BLOGGER_SIZE_LADDER = ["s1600", "s1280", "s800", "s640", "s400"]


def _tag(ns, name):
    return f"{{{ns}}}{name}"


def _log(progress_cb, msg: str):
    logger.info(msg)
    if progress_cb:
        progress_cb(msg)


def _short_url(url: str, max_len: int = 70) -> str:
    if len(url) <= max_len:
        return url
    return url[:max_len // 2] + "..." + url[-(max_len // 2):]


def fetch_all_posts(blog_url: str, config: dict, progress_cb=None,
                    blog_cfg: dict = None) -> list:
    """
    Descarga todos los posts de un blog Blogger via Atom Feed.

    Estrategia de resolución del feed (en orden de prioridad):
      1. feed_url explícita en blog_cfg (config.yaml)  → uso directo, sin cálculo
      2. URL del blog con /feeds/posts/default          → comportamiento anterior
      3. Si el feed redirige a un dominio personalizado muerto:
         se intenta el feed desde la URL blogspot.com nativa (si es posible inferirla)
      4. Fallback a Wayback Machine para el último snapshot del feed
    """
    delay      = config.get("scraping", {}).get("delay_between_requests", 1.5)
    timeout    = config.get("scraping", {}).get("timeout", 30)
    max_p      = config.get("scraping", {}).get("max_posts_per_blog", 0)
    verify_ssl = config.get("scraping", {}).get("verify_ssl", False)
    batch_size = 25
    headers    = {"User-Agent": config.get("scraping", {}).get(
        "user_agent", "Mozilla/5.0 (compatible; BlogPreservationBot/1.0)")}

    # ── Resolver la URL base del feed ────────────────────────────────────────
    # Prioridad 1: feed_url explícita en config.yaml
    explicit_feed = (blog_cfg or {}).get("feed_url", "").strip()
    if explicit_feed:
        feed_base = explicit_feed.rstrip("?").rstrip("&")
        # Quitar parámetros si el usuario pegó la URL con ?start-index=...
        if "?" in feed_base:
            feed_base = feed_base.split("?")[0]
        _log(progress_cb, f"  Feed (explícito): {feed_base}")
    else:
        feed_base = _build_feed_url(blog_url)
        # Prioridad 2: comprobar si el feed resuelve o redirige a un dominio muerto
        feed_base = _resolve_feed_url(feed_base, blog_url, headers, timeout,
                                      verify_ssl, progress_cb)
        _log(progress_cb, f"  Feed: {feed_base}")

    _log(progress_cb, f"  Delay: {delay}s  Timeout: {timeout}s  Max posts: {max_p or 'sin limite'}")

    posts       = []
    start_index = 1
    page        = 1

    while True:
        url = f"{feed_base}?start-index={start_index}&max-results={batch_size}"
        _log(progress_cb, f"  -- Pagina {page}: entradas {start_index}-{start_index + batch_size - 1}")

        try:
            t0   = time.time()
            resp = requests.get(url, headers=headers, timeout=timeout, verify=verify_ssl)
            resp.raise_for_status()
            elapsed = time.time() - t0
            _log(progress_cb, f"     HTTP {resp.status_code} en {elapsed:.1f}s ({len(resp.content)//1024} KB)")
        except requests.exceptions.Timeout:
            _log(progress_cb, f"     ERROR: Timeout ({timeout}s) en pagina {page}")
            break
        except requests.exceptions.HTTPError as e:
            _log(progress_cb, f"     ERROR HTTP: {e}")
            break
        except Exception as e:
            _log(progress_cb, f"     ERROR de red: {e}")
            break

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            _log(progress_cb, f"     ERROR parseando XML: {e}")
            break

        entries = root.findall(_tag(ATOM_NS, "entry"))
        if not entries:
            _log(progress_cb, f"     Sin mas entradas - fin de paginacion")
            break

        _log(progress_cb, f"     {len(entries)} entradas en esta pagina")

        for entry in entries:
            post = _parse_entry(entry, blog_url, headers, config, progress_cb)
            posts.append(post)
            title_short = (post.get("title") or "Sin titulo")[:55]
            _log(progress_cb, f"     [{len(posts):03d}] {post.get('published','????-??-??')} | {title_short}")

            if max_p and len(posts) >= max_p:
                _log(progress_cb, f"  Limite de {max_p} posts alcanzado")
                return posts

        next_link = None
        for link in root.findall(_tag(ATOM_NS, "link")):
            if link.get("rel") == "next":
                next_link = link.get("href")
                break

        if not next_link:
            _log(progress_cb, f"  Paginacion completa - no hay mas paginas")
            break

        start_index += batch_size
        page        += 1
        _log(progress_cb, f"  Pausa {delay}s...")
        time.sleep(delay)

    _log(progress_cb, f"  TOTAL EXTRAIDOS: {len(posts)} posts")
    return posts


def _resolve_feed_url(feed_url: str, blog_url: str, headers: dict,
                      timeout: int, verify_ssl: bool, progress_cb=None) -> str:
    """
    Verifica que el feed URL es accesible y devuelve Atom XML.
    Estrategia de resolución en orden de prioridad:

    1. Normalizar ccTLD (.blogspot.com.es → .blogspot.com)
    2. Comprobar accesibilidad directa
    3. Si falla: descargar una primera página del feed desde blogger.com/feeds/ID
       extrayendo el blog ID del feed <link rel='self'> (la URL interna permanente
       de Blogger que funciona aunque el dominio personalizado esté caído)
    4. Si falla: inferir subdominio blogspot.com nativo desde el dominio
    5. Fallback a Wayback Machine
    """
    import re as _re

    # ── 1. Normalizar ccTLD de Blogger (.blogspot.com.XX → .blogspot.com) ────
    ccTLD_pattern = _re.compile(
        r'(https?://[^/]*\.blogspot\.com)\.[a-z]{2,3}(/.*)?$', _re.IGNORECASE
    )
    m = ccTLD_pattern.match(feed_url)
    if m:
        normalized = m.group(1) + (m.group(2) or "")
        _log(progress_cb, f"  ℹ ccTLD detectado — normalizando feed a: {normalized}")
        feed_url = normalized

    # ── Helper: comprobar accesibilidad con HEAD ───────────────────────────
    def _is_alive(url: str) -> tuple:
        """Devuelve (accessible: bool, final_url: str, error: str)"""
        try:
            r = requests.head(url, headers=headers, timeout=min(timeout, 15),
                              verify=verify_ssl, allow_redirects=True)
            if r.status_code < 400:
                return True, r.url, ""
            return False, r.url, f"HTTP {r.status_code}"
        except requests.exceptions.ConnectionError as e:
            return False, url, f"DNS/conexión: {str(e)[:80]}"
        except requests.exceptions.Timeout:
            return False, url, "timeout"
        except Exception as e:
            return False, url, str(e)[:80]

    # ── Helper: extraer el blog ID de un Atom feed ya descargado ──────────
    def _extract_blogger_id_from_feed(xml_bytes: bytes) -> str:
        """
        Busca <link rel='self' href='http://www.blogger.com/feeds/ID/posts/default'/>
        en el XML del feed y devuelve el ID numérico del blog, o "" si no lo encuentra.
        """
        # Búsqueda por regex sobre bytes (no hace falta parsear el XML completo)
        m = _re.search(
            rb'<link[^>]*rel=[\'"]self[\'"][^>]*href=[\'"]'
            rb'https?://(?:www\.)?blogger\.com/feeds/(\d+)/posts/default[\'"]',
            xml_bytes, _re.IGNORECASE
        )
        if m:
            return m.group(1).decode("ascii")
        # Intentar también el orden inverso href antes que rel
        m2 = _re.search(
            rb'<link[^>]*href=[\'"]https?://(?:www\.)?blogger\.com/feeds/(\d+)/posts/default[\'"]'
            rb'[^>]*rel=[\'"]self[\'"]',
            xml_bytes, _re.IGNORECASE
        )
        return m2.group(1).decode("ascii") if m2 else ""

    # ── 2. Comprobar accesibilidad directa ────────────────────────────────
    alive, final_url, err = _is_alive(feed_url)

    if alive:
        final_feed = _build_feed_url(final_url) if "/feeds/posts/default" not in final_url else final_url
        if final_feed != feed_url:
            _log(progress_cb, f"  ℹ Redirigido a: {final_feed}")
        return final_feed

    # ── 3. Intentar obtener el ID interno de Blogger ──────────────────────
    # Si el dominio personalizado falla en HEAD pero el servidor de Blogger
    # tiene caché del feed, a veces un GET a www.blogger.com/feeds/ID funciona.
    # Para obtener el ID necesitamos descargar aunque sea la primera página del feed
    # desde una URL alternativa (blogger.com directo).
    _log(progress_cb, f"  ⚠ Feed no accesible ({err}) — buscando ID interno de Blogger...")

    # Intentar construir la URL de blogger.com a partir del blog_url
    # Blogger expone siempre: https://www.blogger.com/feeds/<blogID>/posts/default
    # pero no podemos conocer el ID sin haber leído el feed al menos una vez.
    # Intentamos una petición GET a la URL normalizada con blogger.com como host:
    blogger_api_url = None
    parsed_feed = urlparse(feed_url)
    # Si la URL del feed ya apunta a blogspot.com, podemos probar blogger.com
    # con el mismo path
    if "blogspot.com" in parsed_feed.netloc:
        blogger_api_url = f"https://www.blogger.com{parsed_feed.path}"

    if blogger_api_url:
        try:
            r = requests.get(
                f"{blogger_api_url}?start-index=1&max-results=1",
                headers=headers, timeout=min(timeout, 20),
                verify=verify_ssl, allow_redirects=True
            )
            if r.status_code == 200 and (b"<feed" in r.content or b"<?xml" in r.content):
                blog_id = _extract_blogger_id_from_feed(r.content)
                if blog_id:
                    id_feed = f"https://www.blogger.com/feeds/{blog_id}/posts/default"
                    _log(progress_cb, f"  ✓ ID interno encontrado → usando: {id_feed}")
                    return id_feed
        except Exception:
            pass

    # ── 4. Inferir subdominio blogspot.com nativo ─────────────────────────
    parsed_blog = urlparse(blog_url)
    blog_host   = parsed_blog.netloc.lower().replace("www.", "")

    if blog_host.endswith(".blogspot.com"):
        blogspot_subdomain = blog_host
    else:
        domain_base = blog_host.split(".")[0]
        blogspot_subdomain = f"{domain_base}.blogspot.com"
        _log(progress_cb, f"  ℹ Probando subdominio inferido: {blogspot_subdomain}")

    native_feed = f"https://{blogspot_subdomain}/feeds/posts/default"
    alive2, _, err2 = _is_alive(native_feed)

    if alive2:
        # Intentar extraer el ID interno desde esta URL nativa también
        try:
            r2 = requests.get(
                f"{native_feed}?start-index=1&max-results=1",
                headers=headers, timeout=min(timeout, 20),
                verify=verify_ssl, allow_redirects=True
            )
            if r2.status_code == 200:
                blog_id = _extract_blogger_id_from_feed(r2.content)
                if blog_id:
                    id_feed = f"https://www.blogger.com/feeds/{blog_id}/posts/default"
                    _log(progress_cb, f"  ✓ ID interno extraído del feed nativo → usando: {id_feed}")
                    return id_feed
        except Exception:
            pass
        _log(progress_cb, f"  ✓ URL nativa accesible: {native_feed}")
        return native_feed

    # ── 5. Fallback: Wayback Machine ──────────────────────────────────────
    _log(progress_cb, f"  ⚠ URL nativa también falla ({err2}) — intentando Wayback Machine...")
    wayback_feed = f"https://web.archive.org/web/2if_/{feed_url}"
    alive3, _, _ = _is_alive(wayback_feed)
    if alive3:
        _log(progress_cb, f"  ✓ Usando snapshot de Wayback Machine: {wayback_feed}")
        return wayback_feed

    # Nada funcionó — devolver la URL original con diagnóstico claro
    _log(progress_cb, f"  ✗ No se pudo resolver el feed automáticamente.")
    _log(progress_cb, f"    Solución manual: añade en config.yaml para este blog:")
    _log(progress_cb, f"    feed_url: \"https://www.blogger.com/feeds/<ID>/posts/default\"")
    _log(progress_cb, f"    El ID lo encuentras en el XML del feed: <link rel='self' href='...blogger.com/feeds/ID/...'/>")
    return feed_url


def _build_feed_url(blog_url: str) -> str:
    parsed = urlparse(blog_url)
    base   = f"{parsed.scheme}://{parsed.netloc}"
    return f"{base}/feeds/posts/default"


def _parse_entry(entry, blog_url: str, headers: dict, config: dict, progress_cb=None) -> dict:
    def text(tag_name, ns=ATOM_NS):
        el = entry.find(_tag(ns, tag_name))
        return el.text.strip() if el is not None and el.text else ""

    title     = text("title")
    published = text("published")
    updated   = text("updated")
    pub_date  = _parse_date(published or updated)

    author_el = entry.find(_tag(ATOM_NS, "author"))
    author    = ""
    if author_el is not None:
        name_el = author_el.find(_tag(ATOM_NS, "name"))
        author  = name_el.text.strip() if name_el is not None and name_el.text else ""

    canonical = ""
    for link in entry.findall(_tag(ATOM_NS, "link")):
        if link.get("rel") == "alternate":
            canonical = link.get("href", "")
            break

    content_el = entry.find(_tag(ATOM_NS, "content"))
    if content_el is None:
        content_el = entry.find(_tag(ATOM_NS, "summary"))
    raw_html = content_el.text if content_el is not None and content_el.text else ""

    tags = []
    for cat in entry.findall(_tag(ATOM_NS, "category")):
        term = cat.get("term", "")
        if term and "schemas.google.com" not in term:
            tags.append(term)

    post_id = text("id")

    img_count = len(re.findall(r'<img[^>]+src=', raw_html, re.IGNORECASE))
    yt_count  = sum(len(re.findall(p, raw_html)) for p in YOUTUBE_PATTERNS)
    if img_count or yt_count:
        parts = []
        if img_count: parts.append(f"{img_count} imagen(es)")
        if yt_count:  parts.append(f"{yt_count} video(s) YouTube")
        _log(progress_cb, f"          Multimedia: {', '.join(parts)}")

    embed_images = config.get("output", {}).get("embed_images", True)
    max_kb       = config.get("output", {}).get("max_image_size_kb", 500)
    images_b64   = {}
    if embed_images and raw_html and img_count > 0:
        images_b64 = _download_images(raw_html, blog_url, headers, max_kb,
                                      config.get("scraping", {}).get("verify_ssl", False),
                                      progress_cb)

    return {
        "id":         post_id,
        "title":      title,
        "published":  pub_date,
        "updated":    updated,
        "author":     author,
        "url":        canonical,
        "raw_html":   raw_html,
        "tags":       tags,
        "images_b64": images_b64,
    }


def _parse_date(date_str: str) -> str:
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return date_str[:10]


def _blogger_size_variants(url: str) -> list:
    size_re  = re.compile(r'/(s\d+|w\d+(?:-h\d+)?|[wh]\d+)/')
    variants = []
    if size_re.search(url):
        for size in BLOGGER_SIZE_LADDER:
            variants.append(size_re.sub(f'/{size}/', url))
        variants.append(url)
    else:
        variants.append(url)
    seen = set()
    return [v for v in variants if not (v in seen or seen.add(v))]


def _download_images(html: str, base_url: str, headers: dict,
                     max_kb: int, verify_ssl: bool = False,
                     progress_cb=None) -> dict:
    img_pattern = re.compile(r'<img[^>]+src=["\']([^"\'>\s]+)["\']', re.IGNORECASE)
    urls        = list(dict.fromkeys(img_pattern.findall(html)))
    result      = {}
    ok_count = skip_count = fail_count = 0

    for img_url in urls:
        if img_url.startswith("data:"):
            continue
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        elif img_url.startswith("/"):
            img_url = urljoin(base_url, img_url)
        elif not img_url.startswith("http"):
            img_url = urljoin(base_url, img_url)

        is_blogger = "googleusercontent.com" in img_url or "blogspot.com" in img_url
        variants   = _blogger_size_variants(img_url) if is_blogger else [img_url]

        downloaded = False
        for variant_url in variants:
            try:
                resp = requests.get(variant_url, headers=headers, timeout=15, verify=verify_ssl)
                if resp.status_code != 200:
                    continue

                content = resp.content
                size_kb = len(content) / 1024
                ct      = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()

                if size_kb > max_kb:
                    resized = _try_resize(content, max_kb, ct)
                    if resized:
                        content = resized
                        size_kb = len(content) / 1024
                        _log(progress_cb, f"          Imagen redimensionada a {size_kb:.0f}KB: {_short_url(variant_url)}")
                    elif is_blogger and variant_url != variants[-1]:
                        continue  # probar tamano mas pequeno
                    else:
                        _log(progress_cb, f"          OMITIDA {size_kb:.0f}KB>{max_kb}KB: {_short_url(img_url)}")
                        skip_count += 1
                        break

                b64      = base64.b64encode(content).decode("ascii")
                data_uri = f"data:{ct};base64,{b64}"
                result[img_url]     = data_uri
                result[variant_url] = data_uri
                ok_count   += 1
                downloaded  = True
                break

            except requests.exceptions.ConnectionError as e:
                _log(progress_cb, f"          ERROR conexion: {_short_url(img_url)}")
                logger.warning("Conexion rechazada: %s | %s", img_url, e)
                fail_count += 1
                break
            except requests.exceptions.Timeout:
                _log(progress_cb, f"          ERROR timeout: {_short_url(img_url)}")
                fail_count += 1
                break
            except Exception as e:
                logger.warning("Error descargando %s: %s", img_url, e)
                fail_count += 1
                break

    if urls:
        _log(progress_cb, f"          Resultado imagenes: {ok_count} ok, {skip_count} omitidas, {fail_count} errores / {len(urls)} total")

    return result


def _try_resize(content: bytes, max_kb: int, content_type: str):
    try:
        from PIL import Image
        img    = Image.open(BytesIO(content))
        factor = (max_kb * 1024 / len(content)) ** 0.5 * 0.9
        new_w  = max(100, int(img.width  * factor))
        new_h  = max(100, int(img.height * factor))
        img    = img.resize((new_w, new_h), Image.LANCZOS)

        fmt = "PNG" if content_type in ("image/png", "image/gif", "image/webp") else "JPEG"
        if fmt == "JPEG" and img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif fmt == "PNG" and img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA")

        buf = BytesIO()
        quality = 82
        while True:
            buf.seek(0); buf.truncate()
            img.save(buf, format=fmt, quality=quality, optimize=True)
            if len(buf.getvalue()) <= max_kb * 1024 or quality <= 40:
                break
            quality -= 10

        result = buf.getvalue()
        return result if len(result) <= max_kb * 1024 else None
    except Exception:
        return None


def extract_youtube_ids(html: str) -> list:
    ids = []
    for pattern in YOUTUBE_PATTERNS:
        ids.extend(re.findall(pattern, html))
    return list(set(ids))


def save_raw(posts: list, output_dir: Path, blog_slug: str):
    raw_dir  = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / f"{blog_slug}_raw.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    logger.info("Posts crudos guardados en %s", out_path)
    return out_path


def load_raw(output_dir: Path, blog_slug: str) -> list:
    raw_path = output_dir / "raw" / f"{blog_slug}_raw.json"
    if raw_path.exists():
        with open(raw_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []
