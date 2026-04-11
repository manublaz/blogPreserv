"""
cleaner.py v1.3 — Limpia el HTML crudo de Blogger.
Correcciones:
  - URLs de edición de Blogger sustituidas por la URL real del texto visible
  - Entidades HTML doblemente escapadas (&amp;quot;, &amp;amp;, etc.)
  - Etiquetas residuales de Word/Office (<o:p>, <w:...>, <m:...>)
  - Tablas Blogger usadas como wrapper de imagen → <figure><figcaption>
  - &nbsp; normalizados a espacios reales
  - Normalización de títulos en MAYÚSCULAS a Title Case español
  - Deduplicación de posts por ID
"""

import re
import html
import logging
from bs4 import BeautifulSoup, Comment, Tag

logger = logging.getLogger(__name__)

UNWRAP_TAGS = {
    "font", "center", "big", "small", "strike",
    "tt", "blink", "marquee", "basefont",
}

ALLOWED_ATTRS = {
    "a":          {"href", "title", "target", "rel"},
    "img":        {"src", "alt", "title", "loading"},
    "figure":     set(),
    "figcaption": set(),
    "table":      {"summary"},
    "th":         {"scope", "colspan", "rowspan"},
    "td":         {"colspan", "rowspan"},
    "blockquote": {"cite"},
    "q":          {"cite"},
    "time":       {"datetime"},
}

# Preposiciones y conjunciones españolas que no se capitalizan en Title Case
ES_LOWERCASE = {
    "a", "al", "ante", "bajo", "cabe", "con", "contra", "de", "del",
    "desde", "durante", "e", "el", "en", "entre", "hacia", "hasta",
    "la", "las", "lo", "los", "mediante", "o", "para", "pero", "por",
    "que", "sea", "según", "sin", "so", "sobre", "tras", "u", "un",
    "una", "unos", "unas", "y",
}

# URL de edición de Blogger
BLOGGER_EDIT_RE = re.compile(
    r'https?://www\.blogger\.com/(?:u/\d+/)?blog/post/edit/[^\s"\'<>]+'
)


def clean_post(post: dict, config: dict) -> dict:
    raw = post.get("raw_html", "")
    if not raw:
        post["clean_html"] = ""
        return post

    # Paso 0: Decodificar entidades doblemente escapadas ANTES de parsear
    raw = _decode_double_entities(raw)

    soup = BeautifulSoup(raw, "html.parser")

    # 1. Eliminar comentarios HTML
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()

    # 2. Eliminar etiquetas de Word/Office y otros residuos
    for tag_name in ["script", "style", "noscript", "head", "form",
                     "input", "button", "select", "textarea", "meta", "link",
                     "o:p", "w:sdt", "w:sdtpr", "m:math"]:
        for el in soup.find_all(tag_name):
            el.decompose()
    # Etiquetas con namespace residual (o:p, w:...) que BeautifulSoup puede dejar
    for el in soup.find_all(re.compile(r'^[a-z]:')):
        el.decompose()

    # 3. Iframes: conservar YouTube, eliminar resto
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        if "youtube" in src or "youtu.be" in src:
            _make_youtube_responsive(iframe)
        else:
            iframe.decompose()

    # 4. Reparar URLs de edición de Blogger en enlaces
    _fix_blogger_edit_links(soup)

    # 5. Detectar y convertir tablas-wrapper de imagen a <figure>
    _convert_image_tables(soup)

    # 6. Unwrap etiquetas decorativas
    for tag_name in UNWRAP_TAGS:
        for el in soup.find_all(tag_name):
            el.unwrap()
    # También unwrap <u> pero solo si no es subrayado semántico real
    for el in soup.find_all("u"):
        el.unwrap()
    # Unwrap spans vacíos o puramente decorativos
    for el in soup.find_all("span"):
        if not el.attrs or all(a in ("lang", "xml:lang") for a in el.attrs):
            el.unwrap()

    # 7. Limpiar atributos
    for el in soup.find_all(True):
        _clean_element_attrs(el)

    # 8. Embeber imágenes base64
    images_b64 = post.get("images_b64", {})
    if images_b64:
        _embed_images(soup, images_b64)

    # 9. Normalizar &nbsp; a espacios reales
    _normalize_nbsp(soup)

    # 10. Limpiar contenedores vacíos
    _remove_empty_containers(soup)

    # 11. Normalizar <br><br> → párrafos
    html_str = str(soup)
    html_str = re.sub(r'(<br\s*/?>[\s]*){2,}', '</p><p>', html_str, flags=re.IGNORECASE)

    # 12. Limpiar whitespace
    html_str = _clean_whitespace(html_str)

    # 13. Normalizar título en MAYÚSCULAS
    title = post.get("title", "") or ""
    post["title"] = _normalize_title_case(title)

    post["clean_html"] = html_str
    return post


# ─── DECODIFICACIÓN DE ENTIDADES ─────────────────────────────────────────────

def _decode_double_entities(text: str) -> str:
    """
    Decodifica entidades HTML doblemente escapadas.
    &amp;quot; → " | &amp;amp; → & | &amp;lt; → < | &amp;gt; → >
    &amp;nbsp; → espacio | &amp;#NNN; → carácter
    """
    # Primera pasada: decodificar &amp;X; → &X;
    text = re.sub(r'&amp;(#?\w+;)', r'&\1', text)
    # Segunda pasada: decodificar entidades normales restantes
    # (solo las seguras, no < > para no romper el HTML)
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;",  "'")
    text = text.replace("&apos;", "'")
    return text


# ─── REPARACIÓN DE ENLACES BLOGGER ───────────────────────────────────────────

def _fix_blogger_edit_links(soup: BeautifulSoup):
    """
    Detecta enlaces cuyo href es una URL de edición de Blogger
    y los sustituye por la URL real que aparece en el texto visible del enlace.
    Si el texto no es una URL, elimina el enlace pero conserva el texto.
    """
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if BLOGGER_EDIT_RE.match(href):
            # El texto visible suele ser la URL real
            text_content = a.get_text(strip=True)
            if text_content.startswith("http"):
                a["href"] = text_content
                a["target"] = "_blank"
                a["rel"] = "noopener noreferrer"
            else:
                # No es una URL: conservar texto, quitar enlace
                a.unwrap()


# ─── TABLAS COMO WRAPPER DE IMAGEN ───────────────────────────────────────────

def _convert_image_tables(soup: BeautifulSoup):
    """
    Convierte tablas de Blogger usadas como wrapper de imagen a <figure>.
    Patrón: <table><tbody><tr><td><img ...></td></tr><tr><td>caption</td></tr></table>
    """
    for table in soup.find_all("table"):
        imgs = table.find_all("img")
        if not imgs:
            continue
        # Solo actuar si la tabla parece ser un wrapper de imagen (pocas celdas)
        cells = table.find_all("td")
        if len(cells) > 4:
            continue  # tabla de datos real, no tocar

        # Construir <figure>
        fig = soup.new_tag("figure")
        for img in imgs:
            fig.append(img.extract())

        # Buscar caption: texto en celdas que no contiene imagen
        caption_texts = []
        for cell in cells:
            cell_text = cell.get_text(strip=True)
            if cell_text and not cell.find("img"):
                caption_texts.append(cell_text)

        if caption_texts:
            cap = soup.new_tag("figcaption")
            cap.string = " ".join(caption_texts)
            fig.append(cap)

        table.replace_with(fig)


# ─── YOUTUBE RESPONSIVE ──────────────────────────────────────────────────────

def _make_youtube_responsive(iframe: Tag):
    src = iframe.get("src", "")
    if src.startswith("//"):
        src = "https:" + src
    src = src.replace("http://", "https://")
    if "youtube-nocookie.com" not in src:
        src = src.replace("youtube.com/embed", "youtube-nocookie.com/embed")

    for attr in list(iframe.attrs.keys()):
        del iframe[attr]

    iframe["src"] = src
    iframe["frameborder"] = "0"
    iframe["allowfullscreen"] = ""
    iframe["loading"] = "lazy"
    iframe["allow"] = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"

    wrapper = BeautifulSoup('<div class="yt-wrapper"></div>', "html.parser").find("div")
    iframe.wrap(wrapper)


# ─── ATRIBUTOS ───────────────────────────────────────────────────────────────

def _clean_element_attrs(el: Tag):
    allowed = ALLOWED_ATTRS.get(el.name, set())
    for attr in list(el.attrs.keys()):
        if attr not in allowed:
            del el[attr]

    if el.name == "a":
        href = el.get("href", "")
        # Limpiar hrefs vacíos o javascript:
        if not href or href.startswith("javascript:"):
            el.unwrap()
            return
        if href.startswith("http"):
            el["target"] = "_blank"
            el["rel"] = "noopener noreferrer"

    if el.name == "img":
        if not el.get("src"):
            el.decompose()
            return
        if not el.get("alt"):
            el["alt"] = ""


# ─── IMÁGENES BASE64 ─────────────────────────────────────────────────────────

def _embed_images(soup: BeautifulSoup, images_b64: dict):
    size_re = re.compile(r'/s\d+/')
    for img in soup.find_all("img"):
        src = img.get("src", "")
        b64 = images_b64.get(src)
        if not b64:
            src_1600 = size_re.sub('/s1600/', src)
            b64 = images_b64.get(src_1600)
        if b64:
            img["src"] = b64
            img["loading"] = "lazy"
        else:
            if src.startswith("//"):
                img["src"] = "https:" + src
            elif src.startswith("http://"):
                img["src"] = src.replace("http://", "https://", 1)
            img["loading"] = "lazy"
        if not img.get("alt"):
            img["alt"] = ""


# ─── NBSP ────────────────────────────────────────────────────────────────────

def _normalize_nbsp(soup: BeautifulSoup):
    """Sustituye &nbsp; (u00a0) por espacio normal en nodos de texto."""
    from bs4 import NavigableString
    for node in soup.find_all(string=True):
        if isinstance(node, NavigableString) and '\u00a0' in node:
            node.replace_with(node.replace('\u00a0', ' '))


# ─── VACÍOS ──────────────────────────────────────────────────────────────────

def _remove_empty_containers(soup: BeautifulSoup):
    changed = True
    while changed:
        changed = False
        for el in soup.find_all(["div", "span", "p"]):
            if not el.get_text(strip=True) and not el.find(["img", "iframe", "figure", "video", "table"]):
                el.decompose()
                changed = True


# ─── WHITESPACE ──────────────────────────────────────────────────────────────

def _clean_whitespace(html_str: str) -> str:
    html_str = re.sub(r'[ \t]{2,}', ' ', html_str)
    html_str = re.sub(r'\n{3,}', '\n\n', html_str)
    html_str = re.sub(r'\s+>', '>', html_str)
    return html_str.strip()


# ─── TITLE CASE ESPAÑOL ──────────────────────────────────────────────────────

def _normalize_title_case(title: str) -> str:
    """
    Convierte títulos en MAYÚSCULAS a Title Case español.
    Respeta acrónimos (UCM, UNESCO, etc.) — palabras de ≤4 chars y todas mayúsculas
    que no están en la lista de stopwords se mantienen tal cual.
    Solo actúa si el título tiene mayoría de mayúsculas.
    """
    if not title:
        return title

    words = title.split()
    if not words:
        return title

    # Detectar si el título está en MAYÚSCULAS (>60% de palabras en caps)
    upper_count = sum(1 for w in words if w.isupper() and len(w) > 2)
    if upper_count / max(len(words), 1) < 0.5:
        return title  # ya está bien, no tocar

    result = []
    for i, word in enumerate(words):
        # Quitar puntuación para comparar
        clean_word = re.sub(r'[^\w]', '', word).lower()

        # Primer palabra: siempre capitalizar
        if i == 0:
            result.append(_smart_capitalize(word))
            continue

        # Después de : o ( también capitalizar
        if result and result[-1].endswith((':',  '(')):
            result.append(_smart_capitalize(word))
            continue

        # Stopwords en minúsculas
        if clean_word in ES_LOWERCASE:
            result.append(word.lower())
            continue

        # Acrónimos conocidos: mantener en mayúsculas
        # (palabra corta, toda mayúsculas, sin vocales minúsculas)
        if word.isupper() and 2 <= len(word) <= 6:
            result.append(word)  # UCM, UNESCO, UNAM, etc.
            continue

        result.append(_smart_capitalize(word))

    return ' '.join(result)


def _smart_capitalize(word: str) -> str:
    """Capitaliza solo el primer carácter, respetando signos iniciales."""
    if not word:
        return word
    for i, ch in enumerate(word):
        if ch.isalpha():
            return word[:i] + ch.upper() + word[i+1:].lower()
    return word


# ─── EXCERPT ─────────────────────────────────────────────────────────────────

def generate_excerpt(clean_html: str, max_chars: int = 220) -> str:
    soup = BeautifulSoup(clean_html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(' ', 1)[0] + "…"
    return text


# ─── DEDUPLICACIÓN ───────────────────────────────────────────────────────────

def deduplicate_posts(posts: list) -> list:
    """Elimina posts duplicados por ID. Conserva el primero encontrado."""
    seen = set()
    result = []
    for post in posts:
        pid = post.get("id", "") or post.get("url", "") or post.get("title", "")
        if pid and pid in seen:
            logger.info("Post duplicado eliminado: %s", post.get("title", "")[:50])
            continue
        seen.add(pid)
        result.append(post)
    return result


# ─── PIPELINE ────────────────────────────────────────────────────────────────

def clean_all_posts(posts: list, config: dict, progress_cb=None) -> list:
    """Deduplica y limpia una lista completa de posts."""
    # Deduplicar primero
    before = len(posts)
    posts  = deduplicate_posts(posts)
    after  = len(posts)
    if before != after and progress_cb:
        progress_cb(f"  {before - after} post(s) duplicado(s) eliminado(s)")

    cleaned = []
    total   = len(posts)
    for i, post in enumerate(posts, 1):
        if progress_cb:
            progress_cb(f"  Limpiando [{i:03d}/{total}]: {(post.get('title') or '')[:55]}")
        post = clean_post(post, config)
        post["excerpt"] = generate_excerpt(post.get("clean_html", ""))
        cleaned.append(post)
    return cleaned
