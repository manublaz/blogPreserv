"""
pipeline.py — Orquestador principal.
Ejecuta el flujo completo: extracción → limpieza → generación.
Pensado para ser invocado tanto desde CLI como desde la interfaz Flask.
"""

import logging
import json
import re
from pathlib import Path
from slugify import slugify
import yaml

from extractor       import fetch_all_posts, save_raw, load_raw
from cleaner         import clean_all_posts
from generator       import generate_site
from ai_enricher     import AIEnricher
from quality_metrics import compute_metrics
from oai_pmh         import OAIPMHProvider

logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.yaml") -> dict:
    """Carga y valida el archivo de configuración."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró config.yaml en {path.absolute()}")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg


def run_blog(blog_cfg: dict, config: dict, progress_cb=None, force_extract: bool = False):
    """
    Procesa un único blog completo.
    
    Args:
        blog_cfg:      Configuración específica del blog (url, title, type)
        config:        Configuración global
        progress_cb:   Callable(message: str) para reportar progreso
        force_extract: Si True, re-descarga aunque existan datos crudos guardados
    
    Returns:
        dict con 'success', 'output_path', 'post_count', 'errors'
    """
    url       = blog_cfg.get("url", "")
    title     = blog_cfg.get("title", "Blog")
    slug      = slugify(title)
    output_dir = Path(config.get("output", {}).get("dir", "./output"))

    result = {
        "success":      False,
        "output_path":  None,
        "post_count":   0,
        "errors":       [],
        "quality":      None,
        "oai_path":     None,
    }

    def log(msg):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    try:
        # ── FASE 1: EXTRACCIÓN ──────────────────────────────────────
        log(f"▶ FASE 1/6 — Extracción: {title}")

        raw_path   = output_dir / "raw" / f"{slug}_raw.json"
        raw_exists = raw_path.exists()

        # Caché válida = archivo existe Y tiene al menos un post
        # Una caché vacía (resultado de un intento fallido anterior) debe ignorarse
        cache_valid = False
        if raw_exists and not force_extract:
            cached = load_raw(output_dir, slug)
            if cached:
                cache_valid = True
                posts = cached
                explicit_feed = blog_cfg.get("feed_url", "").strip()
                if explicit_feed:
                    log(f"  ↺ Usando datos crudos en caché — feed configurado: {explicit_feed}")
                else:
                    log(f"  ↺ Usando datos crudos en caché (usa force_extract=True para re-descargar)")
            else:
                log(f"  ⚠ Caché vacía detectada (intento anterior fallido) — re-extrayendo...")

        if not cache_valid:
            explicit_feed = blog_cfg.get("feed_url", "").strip()
            if explicit_feed:
                log(f"  ℹ feed_url explícita configurada: {explicit_feed}")
            posts = fetch_all_posts(url, config, progress_cb=log, blog_cfg=blog_cfg)
            save_raw(posts, output_dir, slug)

        if not posts:
            msg = f"No se obtuvieron posts de {url}"
            log(f"  ✗ {msg}")
            result["errors"].append(msg)
            return result

        log(f"  ✓ {len(posts)} posts extraídos")

        # ── FASE 2: LIMPIEZA ────────────────────────────────────────
        log(f"▶ FASE 2/4 — Limpieza y procesamiento")
        posts_original = list(posts)  # copia para métricas de calidad
        posts = clean_all_posts(posts, config, progress_cb=log)
        log(f"  ✓ Limpieza completada")

        # ── FASE 3: ENRIQUECIMIENTO IA (opcional) ───────────────────
        ai_enabled = config.get("ai", {}).get("enabled", False)
        log(f"▶ FASE 3/6 — Enriquecimiento IA {'(activo)' if ai_enabled else '(deshabilitado)'}")
        enricher = AIEnricher(config, output_dir)
        posts = enricher.enrich_posts(posts, progress_cb=log)
        if ai_enabled:
            log(f"  ✓ Enriquecimiento completado")

        # ── FASE 4: GENERACIÓN ──────────────────────────────────────
        log(f"▶ FASE 4/6 — Generando HTML")
        out_path = generate_site(posts, blog_cfg, config, output_dir)
        is_dir = out_path.is_dir()   # True en modo multi-fichero (single_file: false)
        if is_dir:
            log(f"  ✓ Sitio generado (multi-fichero): {out_path}  [{len(posts)} páginas]")
        else:
            log(f"  ✓ Archivo generado: {out_path}")

        # ── FASE 5: MÉTRICAS DE CALIDAD ─────────────────────────────
        quality_enabled = config.get("quality_metrics", {}).get("enabled", True)
        log(f"▶ FASE 5/6 — Métricas de calidad {'(activo)' if quality_enabled else '(deshabilitado)'}")
        if quality_enabled:
            # Modo multi-fichero: analizar el index.html; modo único: el propio archivo
            html_file = (out_path / "index.html") if is_dir else out_path
            if html_file.exists():
                html_output = html_file.read_text(encoding="utf-8")
                q_report = compute_metrics(
                    posts_original=posts_original,
                    posts_cleaned=posts,
                    html_output=html_output,
                    blog_title=title,
                    slug=slug,
                    progress_cb=log,
                )
                q_report.save(output_dir)
                result["quality"] = q_report.to_dict()
                log(f"  ✓ Puntuación global: {q_report.metrics.get('M10_global_score', 0):.1%}")
            else:
                log(f"  ⚠ No se encontró el HTML de salida para calcular métricas")

        # ── FASE 6: EXPORTACIÓN OAI-PMH ──────────────────────────────────
        oai_enabled = config.get("oai_pmh", {}).get("enabled", False)
        log(f"▶ FASE 6/6 — Exportación OAI-PMH {'(activo)' if oai_enabled else '(deshabilitado)'}")
        if oai_enabled:
            provider  = OAIPMHProvider(config, output_dir)
            oai_dir   = output_dir / "oai"
            oai_dir.mkdir(parents=True, exist_ok=True)
            # Generar los verbos principales como archivos estáticos
            for verb, params in [
                ("identify",          {"verb": "Identify"}),
                ("list_records",      {"verb": "ListRecords", "metadataPrefix": "oai_dc"}),
                ("list_identifiers",  {"verb": "ListIdentifiers", "metadataPrefix": "oai_dc"}),
            ]:
                xml_out = provider.handle_request(params, slug)
                oai_path = oai_dir / f"{slug}_{verb}.xml"
                oai_path.write_text(xml_out, encoding="utf-8")
            log(f"  ✓ Archivos OAI-PMH exportados en {oai_dir}")
            result["oai_path"] = str(oai_dir / f"{slug}_list_records.xml")

        result["success"]     = True
        result["output_path"] = str(out_path)
        result["post_count"]  = len(posts)

    except Exception as e:
        msg = f"Error procesando {title}: {e}"
        logger.exception(msg)
        result["errors"].append(msg)
        if progress_cb:
            progress_cb(f"✗ ERROR: {e}")

    return result


def run_all(config: dict, progress_cb=None, enabled_only: bool = True,
            force_extract: bool = False) -> list:
    """
    Procesa todos los blogs configurados.
    
    Returns:
        Lista de resultados por blog.
    """
    blogs = config.get("blogs", [])
    results = []

    for i, blog_cfg in enumerate(blogs, 1):
        if enabled_only and not blog_cfg.get("enabled", True):
            continue

        title = blog_cfg.get("title", blog_cfg.get("url", f"Blog {i}"))
        if progress_cb:
            progress_cb(f"\n{'='*60}")
            progress_cb(f"Blog {i}/{len(blogs)}: {title}")
            progress_cb(f"{'='*60}")

        res = run_blog(blog_cfg, config, progress_cb=progress_cb,
                       force_extract=force_extract)
        res["blog_title"] = title
        res["blog_url"]   = blog_cfg.get("url", "")
        results.append(res)

    return results


# ── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    parser = argparse.ArgumentParser(description="BlogPreservationSuite CLI")
    parser.add_argument("--config", default="config.yaml", help="Ruta al config.yaml")
    parser.add_argument("--blog",   default=None, help="Procesar solo este blog (por URL o slug)")
    parser.add_argument("--force",  action="store_true", help="Re-descargar aunque existan datos")
    args = parser.parse_args()

    cfg = load_config(args.config)

    def print_progress(msg):
        print(f"  {msg}")

    if args.blog:
        # Buscar el blog por URL o slug
        blogs = cfg.get("blogs", [])
        match = next((b for b in blogs
                      if args.blog in b.get("url", "") or
                         args.blog in slugify(b.get("title", ""))), None)
        if not match:
            print(f"Blog no encontrado: {args.blog}")
        else:
            run_blog(match, cfg, progress_cb=print_progress, force_extract=args.force)
    else:
        results = run_all(cfg, progress_cb=print_progress, force_extract=args.force)
        print("\n─── RESUMEN ───────────────────────────────")
        for r in results:
            status = "✓" if r["success"] else "✗"
            print(f"{status} {r['blog_title']}: {r.get('post_count', 0)} posts → {r.get('output_path', 'ERROR')}")
        print("───────────────────────────────────────────")
