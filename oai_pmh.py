"""
oai_pmh.py — Proveedor OAI-PMH para BlogPreservationSuite.

Expone el corpus de posts preservados como un repositorio compatible con
Open Archives Initiative Protocol for Metadata Harvesting (OAI-PMH 2.0).
Permite que repositorios institucionales (DSpace, EPrints, Zenodo) cosechan
automáticamente los metadatos del archivo preservado.

Verbos implementados:
  - Identify
  - ListMetadataFormats
  - ListSets
  - ListIdentifiers
  - ListRecords
  - GetRecord

Formato de metadatos: oai_dc (Dublin Core simple)

Uso standalone:
  python oai_pmh.py --output ./output --slug cinedocnet-patrimonio

Integrado en Flask (app.py):
  GET /oai?verb=Identify
  GET /oai?verb=ListRecords&metadataPrefix=oai_dc
  GET /oai?verb=GetRecord&identifier=oai:...&metadataPrefix=oai_dc
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

logger = logging.getLogger(__name__)

# Namespaces OAI-PMH
NS_OAI     = "http://www.openarchives.org/OAI/2.0/"
NS_OAI_DC  = "http://www.openarchives.org/OAI/2.0/oai_dc/"
NS_DC      = "http://purl.org/dc/elements/1.1/"
NS_XSI     = "http://www.w3.org/2001/XMLSchema-instance"
NS_SCHEMA  = "http://www.openarchives.org/OAI/2.0/ http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd"


class OAIPMHProvider:
    """
    Proveedor OAI-PMH que transforma el corpus JSON de posts preservados
    en respuestas XML compatibles con OAI-PMH 2.0.
    """

    def __init__(self, config: dict, output_dir: Path):
        self.config     = config
        self.output_dir = output_dir
        self.oai_cfg    = config.get("oai_pmh", {})
        self.base_url   = self.oai_cfg.get("base_url", "http://localhost:5000/oai")
        self.repo_name  = self.oai_cfg.get(
            "repository_name",
            config.get("author", {}).get("name", "Blog Archive") + " — Archivo Digital"
        )
        self.admin_email = self.oai_cfg.get(
            "admin_email",
            config.get("author", {}).get("email", "admin@example.com")
        )

    # ── CARGA DE DATOS ────────────────────────────────────────────────────────

    def _load_posts(self, slug: str) -> list:
        """Carga posts limpios desde el JSON de caché."""
        raw_path = self.output_dir / "raw" / f"{slug}_raw.json"
        if raw_path.exists():
            with open(raw_path, encoding="utf-8") as f:
                return json.load(f)
        return []

    def _post_to_identifier(self, post: dict, slug: str) -> str:
        """Genera el identificador OAI para un post."""
        post_id = post.get("id", "").split("/")[-1] if post.get("id") else ""
        if not post_id:
            post_id = post.get("url", "").split("/")[-2] or "unknown"
        return f"oai:{slug}:{post_id}"

    def _datestamp(self, post: dict) -> str:
        """Devuelve la fecha en formato OAI (YYYY-MM-DD)."""
        updated = post.get("updated", "") or post.get("published", "")
        if updated:
            return updated[:10]
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── XML HELPERS ───────────────────────────────────────────────────────────

    def _make_root(self, verb: str) -> tuple:
        """Crea el elemento raíz OAI-PMH y el elemento de verbo."""
        root = Element("OAI-PMH")
        root.set("xmlns", NS_OAI)
        root.set("xmlns:xsi", NS_XSI)
        root.set("xsi:schemaLocation", NS_SCHEMA)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        SubElement(root, "responseDate").text = now
        request_el = SubElement(root, "request")
        request_el.set("verb", verb)
        request_el.text = self.base_url

        verb_el = SubElement(root, verb)
        return root, verb_el

    def _prettify(self, root: Element) -> str:
        """Convierte el árbol XML a string indentado."""
        raw = tostring(root, encoding="unicode")
        dom = minidom.parseString(raw)
        return dom.toprettyxml(indent="  ", encoding=None)

    def _make_oai_dc(self, parent: Element, post: dict):
        """Añade un elemento oai_dc:dc con los metadatos Dublin Core del post."""
        dc = SubElement(parent, "oai_dc:dc")
        dc.set("xmlns:oai_dc", NS_OAI_DC)
        dc.set("xmlns:dc", NS_DC)
        dc.set("xmlns:xsi", NS_XSI)
        dc.set(
            "xsi:schemaLocation",
            f"{NS_OAI_DC} http://www.openarchives.org/OAI/2.0/oai_dc.xsd"
        )

        title = post.get("title", "Sin título")
        SubElement(dc, "dc:title").text = title

        author = post.get("author", "")
        if author:
            SubElement(dc, "dc:creator").text = author

        for tag in post.get("tags", []):
            SubElement(dc, "dc:subject").text = tag

        excerpt = post.get("excerpt", "")
        if excerpt:
            SubElement(dc, "dc:description").text = excerpt

        pub_date = post.get("published", "")
        if pub_date:
            SubElement(dc, "dc:date").text = pub_date

        url = post.get("url", "")
        if url:
            SubElement(dc, "dc:identifier").text = url

        SubElement(dc, "dc:language").text = "es"
        SubElement(dc, "dc:type").text     = "Text"
        SubElement(dc, "dc:format").text   = "text/html"

    # ── VERBOS OAI-PMH ────────────────────────────────────────────────────────

    def identify(self, slug: str = "") -> str:
        root, verb_el = self._make_root("Identify")
        posts = self._load_posts(slug) if slug else []
        dates = sorted(p.get("published", "") for p in posts if p.get("published"))
        earliest = (dates[0][:10] + "T00:00:00Z") if dates else "2000-01-01T00:00:00Z"

        SubElement(verb_el, "repositoryName").text   = self.repo_name
        SubElement(verb_el, "baseURL").text          = self.base_url
        SubElement(verb_el, "protocolVersion").text  = "2.0"
        SubElement(verb_el, "adminEmail").text       = self.admin_email
        SubElement(verb_el, "earliestDatestamp").text= earliest
        SubElement(verb_el, "deletedRecord").text    = "no"
        SubElement(verb_el, "granularity").text      = "YYYY-MM-DD"
        return self._prettify(root)

    def list_metadata_formats(self) -> str:
        root, verb_el = self._make_root("ListMetadataFormats")
        fmt = SubElement(verb_el, "metadataFormat")
        SubElement(fmt, "metadataPrefix").text   = "oai_dc"
        SubElement(fmt, "schema").text           = "http://www.openarchives.org/OAI/2.0/oai_dc.xsd"
        SubElement(fmt, "metadataNamespace").text= NS_OAI_DC
        return self._prettify(root)

    def list_sets(self, slug: str) -> str:
        root, verb_el = self._make_root("ListSets")
        set_el = SubElement(verb_el, "set")
        SubElement(set_el, "setSpec").text = slug
        SubElement(set_el, "setName").text = self.repo_name
        return self._prettify(root)

    def list_identifiers(self, slug: str, from_date: str = "",
                         until_date: str = "") -> str:
        root, verb_el = self._make_root("ListIdentifiers")
        posts = self._load_posts(slug)

        for post in posts:
            ds = self._datestamp(post)
            if from_date  and ds < from_date:  continue
            if until_date and ds > until_date: continue

            header = SubElement(verb_el, "header")
            SubElement(header, "identifier").text = self._post_to_identifier(post, slug)
            SubElement(header, "datestamp").text  = ds
            SubElement(header, "setSpec").text    = slug

        if not verb_el:
            err = SubElement(root, "error")
            err.set("code", "noRecordsMatch")
            err.text = "No records match the query"
        return self._prettify(root)

    def list_records(self, slug: str, from_date: str = "",
                     until_date: str = "") -> str:
        root, verb_el = self._make_root("ListRecords")
        posts = self._load_posts(slug)
        count = 0

        for post in posts:
            ds = self._datestamp(post)
            if from_date  and ds < from_date:  continue
            if until_date and ds > until_date: continue

            record = SubElement(verb_el, "record")
            header = SubElement(record, "header")
            SubElement(header, "identifier").text = self._post_to_identifier(post, slug)
            SubElement(header, "datestamp").text  = ds
            SubElement(header, "setSpec").text    = slug

            metadata = SubElement(record, "metadata")
            self._make_oai_dc(metadata, post)
            count += 1

        if count == 0:
            err = SubElement(root, "error")
            err.set("code", "noRecordsMatch")
            err.text = "No records match the query"
        return self._prettify(root)

    def get_record(self, identifier: str, slug: str) -> str:
        root, verb_el = self._make_root("GetRecord")
        posts = self._load_posts(slug)

        target = None
        for post in posts:
            if self._post_to_identifier(post, slug) == identifier:
                target = post
                break

        if target is None:
            err = SubElement(root, "error")
            err.set("code", "idDoesNotExist")
            err.text = f"No record with identifier: {identifier}"
        else:
            record = SubElement(verb_el, "record")
            header = SubElement(record, "header")
            SubElement(header, "identifier").text = identifier
            SubElement(header, "datestamp").text  = self._datestamp(target)
            SubElement(header, "setSpec").text    = slug
            metadata = SubElement(record, "metadata")
            self._make_oai_dc(metadata, target)

        return self._prettify(root)

    # ── DISPATCHER ───────────────────────────────────────────────────────────

    def handle_request(self, params: dict, slug: str = "") -> str:
        """
        Punto de entrada principal. Recibe los parámetros GET de la petición
        OAI-PMH y devuelve la respuesta XML como string.
        """
        verb            = params.get("verb", "")
        metadata_prefix = params.get("metadataPrefix", "oai_dc")
        identifier      = params.get("identifier", "")
        from_date       = params.get("from", "")
        until_date      = params.get("until", "")

        if not slug:
            # Intentar extraer el slug del identificador
            if identifier and ":" in identifier:
                slug = identifier.split(":")[1]

        if verb == "Identify":
            return self.identify(slug)
        elif verb == "ListMetadataFormats":
            return self.list_metadata_formats()
        elif verb == "ListSets":
            return self.list_sets(slug)
        elif verb == "ListIdentifiers":
            return self.list_identifiers(slug, from_date, until_date)
        elif verb == "ListRecords":
            if metadata_prefix != "oai_dc":
                root = Element("OAI-PMH")
                err = SubElement(root, "error")
                err.set("code", "cannotDisseminateFormat")
                err.text = f"Format not supported: {metadata_prefix}"
                return self._prettify(root)
            return self.list_records(slug, from_date, until_date)
        elif verb == "GetRecord":
            return self.get_record(identifier, slug)
        else:
            root = Element("OAI-PMH")
            err  = SubElement(root, "error")
            err.set("code", "badVerb")
            err.text = f"Illegal OAI verb: {verb}"
            return self._prettify(root)


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse, sys
    from pipeline import load_config

    parser = argparse.ArgumentParser(description="BlogPreservationSuite — OAI-PMH provider")
    parser.add_argument("--config",  default="config.yaml")
    parser.add_argument("--output",  default="./output")
    parser.add_argument("--slug",    required=True, help="Slug del blog (ej: cinedocnet-patrimonio)")
    parser.add_argument("--verb",    default="Identify",
                        choices=["Identify","ListMetadataFormats","ListSets",
                                 "ListIdentifiers","ListRecords","GetRecord"])
    parser.add_argument("--from",    dest="from_date", default="")
    parser.add_argument("--until",   dest="until_date", default="")
    parser.add_argument("--id",      dest="identifier", default="")
    args = parser.parse_args()

    cfg      = load_config(args.config)
    provider = OAIPMHProvider(cfg, Path(args.output))
    params   = {"verb": args.verb, "metadataPrefix": "oai_dc",
                "identifier": args.identifier,
                "from": args.from_date, "until": args.until_date}
    print(provider.handle_request(params, args.slug))
