"""
ai_enricher.py — Enriquecimiento de posts mediante IA local (LM Studio / Gemma 4).

Tareas disponibles (configurables en config.yaml → ai.use_for):
  - generate_tags   : Genera etiquetas temáticas si el post no tiene ninguna o tiene pocas
  - summarize       : Crea un resumen de 2-3 frases para los metadatos y el excerpt
  - clean_html      : Repara HTML muy degradado que la limpieza heurística no pudo limpiar
  - classify        : Asigna categorías temáticas de un vocabulario controlado

El módulo trabaja en modo BATCH: procesa todos los posts de un blog en lotes
para no saturar la RAM del modelo. Incluye caché por post_id para no repetir
trabajo si se re-ejecuta el pipeline.

Compatibilidad: API OpenAI-compatible (LM Studio expone /v1/chat/completions).
"""

import json
import logging
import time
import hashlib
from pathlib import Path
from typing import Callable, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Vocabulario controlado para clasificación ────────────────────────────────
# Adaptado al dominio académico/documental de Alfonso López Yepes

# Vocabulario controlado — ampliado y editable en la interfaz Flask
# Se puede complementar con entradas descubiertas dinámicamente por la IA
CONTROLLED_VOCABULARY = [
    # Disciplinas principales
    "Cine documental",
    "Patrimonio audiovisual",
    "Archivística",
    "Documentación científica",
    "Ciencias de la Información",
    "Biblioteconomía",
    "Preservación digital",
    "Historia del cine",
    "Tecnología educativa",
    "Investigación académica",
    # UCM y entorno académico
    "Universidad Complutense de Madrid",
    "Educación superior",
    "Formación académica",
    "Seminarios y talleres",
    "Postgrado e investigación",
    "Tesis y trabajos académicos",
    # Comunicación y medios
    "Comunicación audiovisual",
    "Medios de comunicación",
    "Periodismo documental",
    "Fotografía y fototeca",
    "Radio y televisión",
    "Cine y vídeo",
    # Gestión de la información
    "Gestión de la información",
    "Recuperación de información",
    "Acceso abierto",
    "Repositorios digitales",
    "Bases de datos",
    "Metadatos y catalogación",
    "Clasificación y tesauros",
    # Patrimonio y cultura
    "Patrimonio cultural",
    "Memoria histórica",
    "Filmotecas y cinetecas",
    "Archivos históricos",
    "Museos y exposiciones",
    "Colecciones especiales",
    # Difusión y eventos
    "Congresos y eventos",
    "Publicaciones científicas",
    "Revistas especializadas",
    "Entrevistas y testimonios",
    "Reseñas y crítica",
    # Iberoamérica
    "Iberoamérica",
    "México y UNAM",
    "Bolivia y Universidad Técnica de Oruro",
    "Cooperación internacional",
    "Redes académicas",
    # Técnica y tecnología
    "Digitalización",
    "Formatos audiovisuales",
    "Derechos de autor y copyright",
    "Legislación y normativa",
    "Proyectos de investigación",
    "Recursos digitales",
]


class AIEnricher:
    """
    Enriquece posts usando un modelo local vía LM Studio.
    Usa caché en disco para evitar reprocesar posts ya enriquecidos.
    """

    def __init__(self, config: dict, output_dir: Path):
        ai_cfg = config.get("ai", {})
        self.enabled   = ai_cfg.get("enabled", False)
        self.endpoint  = ai_cfg.get("endpoint", "http://localhost:1234/v1").rstrip("/")
        self.model     = ai_cfg.get("model", "local-model")
        self.use_for   = set(ai_cfg.get("use_for", []))
        self.timeout   = ai_cfg.get("timeout", 120)
        self.batch_size= ai_cfg.get("batch_size", 5)
        self.temp      = ai_cfg.get("temperature", 0.2)
        self.max_tokens= ai_cfg.get("max_tokens", 512)
        self.delay     = ai_cfg.get("delay_between_calls", 0.5)

        # Caché en disco
        self.cache_dir = output_dir / "ai_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Vocabulario dinámico: usa el del config si existe, si no el por defecto
        config_vocab = config.get("ai", {}).get("vocabulary", None)
        self._dynamic_vocab = list(config_vocab) if config_vocab else list(CONTROLLED_VOCABULARY)
        self._accumulated_tags: list = []  # todas las etiquetas generadas

    # ── API ──────────────────────────────────────────────────────────────────

    def is_available(self) -> tuple:
        """
        Comprueba LM Studio. Devuelve (ok: bool, ready: bool, message: str).
        ok    = servidor activo
        ready = modelo cargado y listo para inferencia
        """
        try:
            resp = requests.get(f"{self.endpoint}/models", timeout=5)
            if resp.status_code != 200:
                return False, False, f"HTTP {resp.status_code}"
            models = [m.get("id","") for m in resp.json().get("data",[])]
            if not models:
                return True, False, "Servidor activo pero sin modelo cargado"
            return True, True, f"Listo — modelo: {models[0]}"
        except requests.exceptions.ConnectionError:
            return False, False, f"No responde en {self.endpoint}"
        except Exception as e:
            return False, False, str(e)

    def _call(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Llama a la API de LM Studio. Devuelve el texto de respuesta o None."""
        url = f"{self.endpoint}/chat/completions"
        payload = {
            "model":       self.model,
            "temperature": self.temp,
            "max_tokens":  self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        }
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except requests.exceptions.ConnectionError:
            logger.error("LM Studio no responde. ¿Está iniciado en %s?", self.endpoint)
            return None
        except Exception as e:
            logger.error("Error en llamada AI: %s", e)
            return None

    # ── CACHÉ ────────────────────────────────────────────────────────────────

    def _cache_key(self, post_id: str, task: str) -> str:
        h = hashlib.md5(f"{post_id}:{task}".encode()).hexdigest()[:12]
        return h

    def _load_cache(self, post_id: str, task: str) -> Optional[dict]:
        key  = self._cache_key(post_id, task)
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def _save_cache(self, post_id: str, task: str, data: dict):
        key  = self._cache_key(post_id, task)
        path = self.cache_dir / f"{key}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # ── TAREAS ───────────────────────────────────────────────────────────────

    def generate_tags(self, post: dict) -> list:
        """Genera etiquetas temáticas para un post."""
        pid = post.get("id", post.get("title", ""))
        cached = self._load_cache(pid, "tags")
        if cached:
            return cached.get("tags", [])

        title   = post.get("title", "")
        excerpt = post.get("excerpt", "")
        existing= post.get("tags", [])

        # Si ya tiene suficientes etiquetas buenas, no llamar a la IA
        if len(existing) >= 4:
            return existing

        # Incluir muestra del vocabulario dinámico actual como contexto
        vocab_sample = ", ".join(self._dynamic_vocab[:30]) if self._dynamic_vocab else ""
        vocab_hint   = f"\nEtiquetas ya usadas en otros artículos (reutiliza si aplican): {vocab_sample}" if vocab_sample else ""

        system = (
            "Eres un especialista en documentación y ciencias de la información. "
            "Analiza el título y resumen de un artículo académico y genera etiquetas temáticas "
            "en español. Responde SOLO con un JSON válido: {\"tags\": [\"tag1\", \"tag2\", ...]}. "
            "Máximo 6 etiquetas, concisas (1-3 palabras). Reutiliza etiquetas existentes cuando "
            "sea apropiado para mantener coherencia entre artículos. Si el contenido requiere "
            "etiquetas nuevas, inclúyelas. No incluyas texto adicional, solo el JSON."
            + vocab_hint
        )
        user = f"Título: {title}\nResumen: {excerpt}"

        raw = self._call(system, user)
        tags = existing.copy()

        if raw:
            try:
                # Limpiar posibles backticks de markdown
                clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                data  = json.loads(clean)
                new_tags = data.get("tags", [])
                # Combinar con etiquetas existentes, sin duplicados
                seen = set(t.lower() for t in tags)
                for t in new_tags:
                    if isinstance(t, str) and t.lower() not in seen:
                        tags.append(t)
                        seen.add(t.lower())
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("No se pudo parsear tags JSON: %s | raw: %s", e, raw[:100])

        self._save_cache(pid, "tags", {"tags": tags})
        return tags

    def summarize(self, post: dict) -> str:
        """Genera un resumen de 2-3 frases del post."""
        pid = post.get("id", post.get("title", ""))
        cached = self._load_cache(pid, "summary")
        if cached:
            return cached.get("summary", "")

        # Extraer texto plano del HTML limpio
        clean_html = post.get("clean_html", "")
        soup       = BeautifulSoup(clean_html, "html.parser")
        text       = soup.get_text(" ", strip=True)
        text       = " ".join(text.split())[:1500]  # Truncar a 1500 chars

        if len(text) < 100:
            return post.get("excerpt", "")

        system = (
            "Eres un especialista en documentación académica. "
            "Resume el siguiente texto en exactamente 2-3 frases en español. "
            "El resumen debe ser informativo, académico y fiel al contenido original. "
            "Responde SOLO con el texto del resumen, sin introducciones ni comentarios."
        )
        user = f"Título: {post.get('title', '')}\n\nTexto:\n{text}"

        summary = self._call(system, user)
        if not summary:
            summary = post.get("excerpt", "")

        self._save_cache(pid, "summary", {"summary": summary})
        return summary

    def classify(self, post: dict) -> list:
        """
        Clasifica el post según el vocabulario controlado.
        Devuelve lista de categorías asignadas (1-3 máximo).
        """
        pid = post.get("id", post.get("title", ""))
        cached = self._load_cache(pid, "classify")
        if cached:
            return cached.get("categories", [])

        title   = post.get("title", "")
        excerpt = post.get("excerpt", "")
        vocab   = "\n".join(f"- {v}" for v in self._dynamic_vocab)

        system = (
            "Eres un documentalista especializado. Clasifica el artículo según el "
            "vocabulario controlado proporcionado. Selecciona entre 1 y 3 categorías "
            "que mejor describan el contenido. "
            "Responde SOLO con JSON válido: {\"categories\": [\"Categoría 1\", \"Categoría 2\"]}. "
            "Usa exactamente los nombres del vocabulario. Sin texto adicional."
        )
        user = (
            f"Vocabulario controlado:\n{vocab}\n\n"
            f"Artículo:\nTítulo: {title}\nResumen: {excerpt}"
        )

        raw = self._call(system, user)
        categories = []

        if raw:
            try:
                clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                data  = json.loads(clean)
                raw_cats = data.get("categories", [])
                # Validar que pertenecen al vocabulario
                vocab_set = set(CONTROLLED_VOCABULARY)
                categories = [c for c in raw_cats if c in vocab_set]
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("No se pudo parsear classify JSON: %s | raw: %s", e, raw[:100])

        self._save_cache(pid, "classify", {"categories": categories})
        return categories

    def clean_html_ai(self, post: dict) -> str:
        """
        Repara HTML muy degradado. Solo se usa si la limpieza heurística
        produce un resultado con muy poco texto legible.
        """
        pid = post.get("id", post.get("title", ""))
        cached = self._load_cache(pid, "clean_html")
        if cached:
            return cached.get("html", post.get("clean_html", ""))

        clean_html = post.get("clean_html", "")
        soup       = BeautifulSoup(clean_html, "html.parser")
        text       = soup.get_text(" ", strip=True)

        # Solo activar si hay muy poco texto (señal de HTML muy degradado)
        if len(text.strip()) > 200:
            return clean_html

        raw_html = post.get("raw_html", "")[:3000]  # Limitar tamaño

        system = (
            "Eres un experto en procesamiento de HTML. Se te proporciona HTML de un blog "
            "con mucho ruido (estilos inline, fuentes hardcodeadas, divs anidados, etc.). "
            "Extrae el contenido legible y devuélvelo como HTML semántico limpio: "
            "usa solo p, h2, h3, ul, ol, li, blockquote, strong, em, a. "
            "Preserva todo el texto original sin modificarlo. "
            "Responde SOLO con el HTML limpio, sin explicaciones."
        )
        user = f"HTML a limpiar:\n{raw_html}"

        result = self._call(system, user)
        html   = result if result else clean_html

        self._save_cache(pid, "clean_html", {"html": html})
        return html

    def reformat_text(self, post: dict) -> str:
        """
        Reformatea texto muy degradado: añade párrafos, convierte bloques
        en mayúsculas a encabezados, une palabras partidas, normaliza
        espaciado. NO modifica el contenido, solo la estructura.
        """
        pid = post.get("id", post.get("title", ""))
        cached = self._load_cache(pid, "reformat")
        if cached:
            return cached.get("html", post.get("clean_html", ""))

        from bs4 import BeautifulSoup
        clean_html = post.get("clean_html", "")
        soup       = BeautifulSoup(clean_html, "html.parser")
        text       = soup.get_text(" ", strip=True)

        # Solo actuar si hay bloques de MAYÚSCULAS (señal de texto sin formatear)
        upper_ratio = sum(1 for c in text if c.isupper()) / max(len(text), 1)
        if upper_ratio < 0.25 and len(text) < 500:
            return clean_html

        system = (
            "Eres un editor académico especializado en documentación y ciencias de la información. "
            "Se te proporciona un fragmento de texto HTML extraído de un blog académico. "
            "El texto tiene problemas de formato: bloques en MAYÚSCULAS que deberían ser encabezados, "
            "párrafos sin separar, palabras unidas sin espacio, puntuación incorrecta. "
            "Tu tarea: mejorar la estructura y legibilidad del texto aplicando estas reglas:\n"
            "1. Convierte bloques en MAYÚSCULAS que parecen títulos de sección a <h3> con Title Case en español\n"
            "2. Separa bloques de texto denso en párrafos <p> lógicos\n"
            "3. Une palabras que estén separadas incorrectamente (ej: 'estu dios' -> 'estudios')\n"
            "4. Normaliza mayúsculas en titulares (Title Case español)\n"
            "5. Conserva TODO el contenido textual sin omitir ni añadir información\n"
            "6. Devuelve SOLO el HTML mejorado, sin explicaciones ni markdown."
        )
        user = f"HTML a reformatear:\n{clean_html[:4000]}"

        result = self._call(system, user)
        html   = result if result else clean_html

        self._save_cache(pid, "reformat", {"html": html})
        return html

    def update_vocabulary_from_tags(self, new_tags: list, min_count: int = 2) -> list:
        """
        Analiza las etiquetas generadas hasta ahora y añade al vocabulario
        las que aparecen con frecuencia suficiente.
        Devuelve el vocabulario actualizado.
        """
        from collections import Counter
        counts = Counter(t.lower() for t in new_tags if isinstance(t, str) and len(t) > 3)
        vocab_lower = {v.lower() for v in self._dynamic_vocab}
        added = []
        for tag, count in counts.most_common(20):
            # Capitalizar para añadir al vocabulario
            tag_cap = tag.title()
            if count >= min_count and tag.lower() not in vocab_lower:
                self._dynamic_vocab.append(tag_cap)
                vocab_lower.add(tag.lower())
                added.append(tag_cap)
        return added

    # ── ENRIQUECIMIENTO COMPLETO ──────────────────────────────────────────────

    def enrich_posts(self, posts: list, progress_cb: Optional[Callable] = None) -> list:
        """
        Enriquece una lista de posts con las tareas configuradas.
        Procesa en lotes para no saturar el modelo.
        """
        if not self.enabled:
            if progress_cb:
                progress_cb("  IA deshabilitada (ai.enabled: false en config.yaml)")
            return posts

        ok, ready, msg = self.is_available()
        if not ok:
            if progress_cb:
                progress_cb(f"  AVISO IA: {msg}")
                progress_cb(f"  Omitiendo enriquecimiento IA — el pipeline continua sin ella")
            return posts
        if not ready:
            if progress_cb:
                progress_cb(f"  AVISO IA: {msg}")
                progress_cb(f"  El modelo no esta listo todavia — omitiendo enriquecimiento IA")
                progress_cb(f"  Consejo: activa la IA mas tarde con force_extract=False (usa cache)")
            return posts

        tasks     = self.use_for
        total     = len(posts)
        enriched  = []

        if progress_cb:
            progress_cb(f"  🤖 Modelo: {self.model}")
            progress_cb(f"  📋 Tareas activas: {', '.join(tasks) if tasks else 'ninguna'}")
            progress_cb(f"  📦 Procesando {total} posts en lotes de {self.batch_size}…")

        for i, post in enumerate(posts, 1):
            title_short = (post.get("title", "") or "")[:50]

            if progress_cb and i % self.batch_size == 1:
                progress_cb(f"  IA — lote {(i-1)//self.batch_size + 1}: posts {i}–{min(i+self.batch_size-1, total)}")

            try:
                if "generate_tags" in tasks:
                    new_tags = self.generate_tags(post)
                    if new_tags:
                        post["tags"] = new_tags
                        self._accumulated_tags.extend(new_tags)
                        # Actualizar vocabulario dinámico cada 20 posts
                        if i % 20 == 0:
                            added = self.update_vocabulary_from_tags(self._accumulated_tags)
                            if added and progress_cb:
                                progress_cb(f"  Vocabulario actualizado +{len(added)}: {', '.join(added[:5])}")

                if "summarize" in tasks:
                    summary = self.summarize(post)
                    if summary:
                        post["excerpt"] = summary
                        post["ai_summary"] = summary

                if "classify" in tasks:
                    cats = self.classify(post)
                    if cats:
                        post["categories"] = cats
                        existing = set(post.get("tags", []))
                        for c in cats:
                            if c not in existing:
                                post.setdefault("tags", []).append(c)

                if "reformat" in tasks:
                    post["clean_html"] = self.reformat_text(post)

                if "clean_html" in tasks:
                    post["clean_html"] = self.clean_html_ai(post)

            except Exception as e:
                logger.warning("Error enriqueciendo post '%s': %s", title_short, e)
                if progress_cb:
                    progress_cb(f"  ⚠ Error en '{title_short[:30]}': {e}")

            enriched.append(post)

            # Pausa entre lotes para no saturar el modelo
            if i % self.batch_size == 0 and i < total:
                time.sleep(self.delay)

        if progress_cb:
            progress_cb(f"  ✓ Enriquecimiento IA completado ({total} posts)")

        return enriched


def test_connection(config: dict) -> dict:
    """
    Prueba la conexion con LM Studio con diagnostico detallado.
    Distingue entre: servidor caido, servidor activo sin modelo, modelo cargado.
    """
    ai_cfg   = config.get("ai", {})
    endpoint = ai_cfg.get("endpoint", "http://localhost:1234/v1").rstrip("/")
    model    = ai_cfg.get("model", "")

    # 1. Verificar que el servidor responde
    try:
        resp = requests.get(f"{endpoint}/models", timeout=5)
    except requests.exceptions.ConnectionError:
        return {
            "ok":      False,
            "ready":   False,
            "models":  [],
            "message": f"LM Studio no responde en {endpoint}. Verifica que el servidor este activo y que 'Permitir Conexiones de Red' este ON.",
        }
    except requests.exceptions.Timeout:
        return {
            "ok":      False,
            "ready":   False,
            "models":  [],
            "message": f"Timeout conectando con {endpoint} (5s). El servidor tarda demasiado.",
        }
    except Exception as e:
        return {"ok": False, "ready": False, "models": [], "message": str(e)}

    # 2. Servidor activo — revisar modelos cargados
    if resp.status_code != 200:
        return {
            "ok":      False,
            "ready":   False,
            "models":  [],
            "message": f"Servidor responde pero devuelve HTTP {resp.status_code}",
        }

    try:
        data   = resp.json()
        models = [m.get("id", "") for m in data.get("data", [])]
    except Exception:
        models = []

    # 3. Verificar si el modelo configurado esta cargado
    model_loaded = any(model in m or m in model for m in models) if model and models else False

    if not models:
        return {
            "ok":      True,   # servidor OK
            "ready":   False,  # pero sin modelo
            "models":  [],
            "message": (
                f"LM Studio activo en {endpoint} pero sin ningun modelo cargado. "
                f"Carga '{model}' en LM Studio antes de activar la IA."
            ),
        }

    if model and not model_loaded:
        return {
            "ok":      True,
            "ready":   False,
            "models":  models,
            "message": (
                f"LM Studio activo. Modelos cargados: {', '.join(models)}. "
                f"El modelo configurado '{model}' no coincide con ninguno. "
                f"Actualiza 'ai.model' en config.yaml con uno de los anteriores."
            ),
        }

    # 4. Todo bien — hacer un ping real con una llamada minima
    try:
        ping_resp = requests.post(
            f"{endpoint}/chat/completions",
            json={
                "model": models[0] if models else model,
                "max_tokens": 5,
                "messages": [{"role": "user", "content": "ping"}],
            },
            timeout=15,
        )
        if ping_resp.status_code == 200:
            return {
                "ok":      True,
                "ready":   True,
                "models":  models,
                "message": (
                    f"LM Studio listo. Modelo activo: {models[0] if models else model}. "
                    f"Inferencia verificada correctamente."
                ),
            }
        else:
            return {
                "ok":      True,
                "ready":   False,
                "models":  models,
                "message": (
                    f"LM Studio activo pero la inferencia devolvio HTTP {ping_resp.status_code}. "
                    f"El modelo puede estar todavia cargandose en memoria."
                ),
            }
    except requests.exceptions.Timeout:
        return {
            "ok":      True,
            "ready":   False,
            "models":  models,
            "message": (
                f"LM Studio activo pero la inferencia tarda mas de 15s. "
                f"El modelo Gemma 4 26B puede estar cargandose en VRAM/RAM. Espera unos minutos."
            ),
        }
    except Exception as e:
        return {
            "ok":      True,
            "ready":   False,
            "models":  models,
            "message": f"Servidor activo pero error en inferencia: {e}",
        }
