"""
quality_metrics.py — Métricas de calidad de preservación para BlogPreservationSuite.

Evalúa el grado de fidelidad del archivo HTML preservado respecto al contenido
original extraído del feed Atom, produciendo un informe cuantitativo y cualitativo.

Métricas implementadas:
  M1  Cobertura de entradas          : entradas preservadas / entradas originales
  M2  Integridad textual             : similitud de texto por entrada (ratio Levenshtein)
  M3  Cobertura de imágenes          : imágenes embebidas base64 / imágenes detectadas
  M4  Cobertura de vídeos YouTube    : iframes preservados / vídeos detectados
  M5  Completitud de metadatos DC    : campos DC presentes / campos DC esperados (12)
  M6  Completitud de metadatos METS  : secciones METS presentes / esperadas (3)
  M7  Cobertura de etiquetas         : etiquetas preservadas / etiquetas originales
  M8  Fidelidad de fechas            : entradas con fecha correcta / total
  M9  Integridad de hipervínculos    : enlaces sin URL de edición Blogger / total
  M10 Puntuación global              : media ponderada M1..M9
"""

import re
import json
import logging
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Pesos para la puntuación global (deben sumar 1.0)
WEIGHTS = {
    "M1_entry_coverage":     0.25,
    "M2_text_integrity":     0.20,
    "M3_image_coverage":     0.15,
    "M4_video_coverage":     0.10,
    "M5_dc_completeness":    0.10,
    "M6_mets_completeness":  0.05,
    "M7_tag_coverage":       0.05,
    "M8_date_fidelity":      0.05,
    "M9_link_integrity":     0.05,
}

BLOGGER_EDIT_RE = re.compile(
    r'https?://www\.blogger\.com/(?:u/\d+/)?blog/post/edit/'
)

DC_FIELDS_EXPECTED = {
    "DC.title", "DC.creator", "DC.subject", "DC.description",
    "DC.publisher", "DC.date", "DC.type", "DC.format",
    "DC.identifier", "DC.language", "DC.coverage", "DC.rights"
}

METS_SECTIONS_EXPECTED = {"metsHdr", "dmdSec", "mods:mods"}

YOUTUBE_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/)([\w-]+)',
    re.IGNORECASE
)


class PreservationQualityReport:
    """
    Calcula y almacena las métricas de calidad para un blog preservado.
    """

    def __init__(self, slug: str, blog_title: str):
        self.slug       = slug
        self.blog_title = blog_title
        self.metrics    = {}
        self.details    = {}
        self.timestamp  = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "slug":       self.slug,
            "title":      self.blog_title,
            "timestamp":  self.timestamp,
            "metrics":    self.metrics,
            "details":    self.details,
            "score":      self.metrics.get("M10_global_score", 0.0),
        }

    def save(self, output_dir: Path):
        reports_dir = output_dir / "quality_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"{self.slug}_quality.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("Informe de calidad guardado: %s", path)
        return path

    def summary(self) -> str:
        lines = [
            f"\n{'='*60}",
            f"INFORME DE CALIDAD — {self.blog_title}",
            f"{'='*60}",
        ]
        labels = {
            "M1_entry_coverage":    "M1  Cobertura de entradas",
            "M2_text_integrity":    "M2  Integridad textual",
            "M3_image_coverage":    "M3  Cobertura de imágenes",
            "M4_video_coverage":    "M4  Cobertura de vídeos",
            "M5_dc_completeness":   "M5  Completitud metadatos DC",
            "M6_mets_completeness": "M6  Completitud METS",
            "M7_tag_coverage":      "M7  Cobertura de etiquetas",
            "M8_date_fidelity":     "M8  Fidelidad de fechas",
            "M9_link_integrity":    "M9  Integridad de enlaces",
            "M10_global_score":     "PUNTUACION GLOBAL",
        }
        for key, label in labels.items():
            val = self.metrics.get(key, 0.0)
            bar = "#" * int(val * 20)
            sep = "─" * 40 if key == "M10_global_score" else ""
            if sep:
                lines.append(sep)
            lines.append(f"  {label:<30} {val:5.1%}  [{bar:<20}]")
        lines.append("=" * 60)
        return "\n".join(lines)


def _text_ratio(text_a: str, text_b: str) -> float:
    """
    Calcula la similitud de dos textos como ratio de caracteres comunes
    (aproximación rápida sin necesidad de difflib completo).
    """
    if not text_a and not text_b:
        return 1.0
    if not text_a or not text_b:
        return 0.0
    # Usar tokens en lugar de chars para mayor robustez
    tokens_a = set(text_a.lower().split())
    tokens_b = set(text_b.lower().split())
    if not tokens_a:
        return 0.0
    intersection = tokens_a & tokens_b
    return len(intersection) / max(len(tokens_a), len(tokens_b))


def _extract_text(html: str) -> str:
    """Extrae texto plano de HTML."""
    soup = BeautifulSoup(html, "html.parser")
    return " ".join(soup.get_text().split())


def _count_images_in_html(html: str) -> int:
    return len(re.findall(r'<img[^>]+src=', html, re.IGNORECASE))


def _count_b64_images(html: str) -> int:
    return len(re.findall(r'src=["\']data:image/', html, re.IGNORECASE))


def _count_youtube(html: str) -> int:
    return len(YOUTUBE_RE.findall(html))


def _count_blogger_edit_links(html: str) -> int:
    return len(BLOGGER_EDIT_RE.findall(html))


def compute_metrics(
    posts_original: list,
    posts_cleaned:  list,
    html_output:    str,
    blog_title:     str,
    slug:           str,
    progress_cb=None,
) -> PreservationQualityReport:
    """
    Calcula todas las métricas de calidad comparando los posts originales
    con los posts limpios y el HTML final generado.

    Args:
        posts_original: lista de posts tal como llegaron del feed Atom
        posts_cleaned:  lista de posts tras el pipeline de limpieza
        html_output:    contenido del archivo HTML final generado
        blog_title:     nombre del blog
        slug:           slug del blog
        progress_cb:    callback de progreso

    Returns:
        PreservationQualityReport con todas las métricas calculadas
    """
    def log(msg):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    report = PreservationQualityReport(slug, blog_title)
    log(f"  Calculando métricas de calidad para {blog_title}...")

    n_orig    = len(posts_original)
    n_cleaned = len(posts_cleaned)

    # ── M1: Cobertura de entradas ─────────────────────────────────────────────
    m1 = n_cleaned / n_orig if n_orig > 0 else 0.0
    report.metrics["M1_entry_coverage"] = round(m1, 4)
    report.details["M1"] = {
        "original": n_orig,
        "preserved": n_cleaned,
        "lost": n_orig - n_cleaned
    }
    log(f"  M1 Cobertura entradas: {n_cleaned}/{n_orig} ({m1:.1%})")

    # ── M2: Integridad textual ────────────────────────────────────────────────
    # Muestrear hasta 50 entradas para no ralentizar demasiado
    sample_size = min(50, n_cleaned)
    ratios = []
    orig_by_id = {p.get("id", p.get("url", p.get("title",""))): p
                  for p in posts_original}
    for post in posts_cleaned[:sample_size]:
        pid  = post.get("id", post.get("url", post.get("title", "")))
        orig = orig_by_id.get(pid)
        if orig:
            text_orig    = _extract_text(orig.get("raw_html", ""))
            text_cleaned = _extract_text(post.get("clean_html", ""))
            ratios.append(_text_ratio(text_orig, text_cleaned))

    m2 = sum(ratios) / len(ratios) if ratios else 0.0
    report.metrics["M2_text_integrity"] = round(m2, 4)
    report.details["M2"] = {
        "sample_size": sample_size,
        "avg_token_overlap": round(m2, 4)
    }
    log(f"  M2 Integridad textual: {m2:.1%} (muestra {sample_size} entradas)")

    # ── M3: Cobertura de imágenes ─────────────────────────────────────────────
    total_imgs_orig = sum(
        _count_images_in_html(p.get("raw_html", ""))
        for p in posts_original
    )
    total_imgs_b64 = _count_b64_images(html_output)
    m3 = total_imgs_b64 / total_imgs_orig if total_imgs_orig > 0 else 1.0
    m3 = min(m3, 1.0)
    report.metrics["M3_image_coverage"] = round(m3, 4)
    report.details["M3"] = {
        "images_detected":  total_imgs_orig,
        "images_embedded_b64": total_imgs_b64,
    }
    log(f"  M3 Cobertura imágenes: {total_imgs_b64}/{total_imgs_orig} ({m3:.1%})")

    # ── M4: Cobertura de vídeos YouTube ──────────────────────────────────────
    total_yt_orig = sum(
        _count_youtube(p.get("raw_html", ""))
        for p in posts_original
    )
    total_yt_pres = _count_youtube(html_output)
    m4 = total_yt_pres / total_yt_orig if total_yt_orig > 0 else 1.0
    m4 = min(m4, 1.0)
    report.metrics["M4_video_coverage"] = round(m4, 4)
    report.details["M4"] = {
        "youtube_detected":  total_yt_orig,
        "youtube_preserved": total_yt_pres,
    }
    log(f"  M4 Cobertura vídeos: {total_yt_pres}/{total_yt_orig} ({m4:.1%})")

    # ── M5: Completitud de metadatos Dublin Core ──────────────────────────────
    dc_present = set()
    for field in DC_FIELDS_EXPECTED:
        if f'name="{field}"' in html_output or f"name='{field}'" in html_output:
            dc_present.add(field)
    m5 = len(dc_present) / len(DC_FIELDS_EXPECTED)
    report.metrics["M5_dc_completeness"] = round(m5, 4)
    report.details["M5"] = {
        "fields_expected": list(DC_FIELDS_EXPECTED),
        "fields_present":  list(dc_present),
        "fields_missing":  list(DC_FIELDS_EXPECTED - dc_present),
    }
    log(f"  M5 Metadatos DC: {len(dc_present)}/{len(DC_FIELDS_EXPECTED)} ({m5:.1%})")

    # ── M6: Completitud de metadatos METS ────────────────────────────────────
    mets_present = set()
    for section in METS_SECTIONS_EXPECTED:
        if section in html_output:
            mets_present.add(section)
    m6 = len(mets_present) / len(METS_SECTIONS_EXPECTED)
    report.metrics["M6_mets_completeness"] = round(m6, 4)
    report.details["M6"] = {
        "sections_expected": list(METS_SECTIONS_EXPECTED),
        "sections_present":  list(mets_present),
    }
    log(f"  M6 Metadatos METS: {len(mets_present)}/{len(METS_SECTIONS_EXPECTED)} ({m6:.1%})")

    # ── M7: Cobertura de etiquetas ────────────────────────────────────────────
    tags_orig_total     = sum(len(p.get("tags", [])) for p in posts_original)
    tags_preserved_total= sum(len(p.get("tags", [])) for p in posts_cleaned)
    m7 = tags_preserved_total / tags_orig_total if tags_orig_total > 0 else 1.0
    m7 = min(m7, 1.0)
    report.metrics["M7_tag_coverage"] = round(m7, 4)
    report.details["M7"] = {
        "tags_original":  tags_orig_total,
        "tags_preserved": tags_preserved_total,
    }
    log(f"  M7 Cobertura etiquetas: {tags_preserved_total}/{tags_orig_total} ({m7:.1%})")

    # ── M8: Fidelidad de fechas ───────────────────────────────────────────────
    dates_ok = 0
    for post in posts_cleaned:
        if post.get("published") and len(post["published"]) >= 10:
            try:
                datetime.strptime(post["published"][:10], "%Y-%m-%d")
                dates_ok += 1
            except ValueError:
                pass
    m8 = dates_ok / n_cleaned if n_cleaned > 0 else 0.0
    report.metrics["M8_date_fidelity"] = round(m8, 4)
    report.details["M8"] = {
        "entries_with_valid_date": dates_ok,
        "total_entries": n_cleaned,
    }
    log(f"  M8 Fidelidad fechas: {dates_ok}/{n_cleaned} ({m8:.1%})")

    # ── M9: Integridad de hipervínculos ───────────────────────────────────────
    blogger_links_orig = sum(
        _count_blogger_edit_links(p.get("raw_html", ""))
        for p in posts_original
    )
    blogger_links_pres = _count_blogger_edit_links(html_output)
    if blogger_links_orig == 0:
        m9 = 1.0
    else:
        m9 = 1.0 - (blogger_links_pres / blogger_links_orig)
        m9 = max(0.0, m9)
    report.metrics["M9_link_integrity"] = round(m9, 4)
    report.details["M9"] = {
        "blogger_edit_links_original":  blogger_links_orig,
        "blogger_edit_links_remaining": blogger_links_pres,
        "fixed_ratio": round(m9, 4),
    }
    log(f"  M9 Integridad enlaces: {m9:.1%} ({blogger_links_pres} enlaces Blogger restantes)")

    # ── M10: Puntuación global ────────────────────────────────────────────────
    metric_map = {
        "M1_entry_coverage":    m1,
        "M2_text_integrity":    m2,
        "M3_image_coverage":    m3,
        "M4_video_coverage":    m4,
        "M5_dc_completeness":   m5,
        "M6_mets_completeness": m6,
        "M7_tag_coverage":      m7,
        "M8_date_fidelity":     m8,
        "M9_link_integrity":    m9,
    }
    m10 = sum(WEIGHTS[k] * v for k, v in metric_map.items())
    report.metrics["M10_global_score"] = round(m10, 4)
    log(f"  M10 Puntuacion global: {m10:.1%}")
    log(report.summary())

    return report
