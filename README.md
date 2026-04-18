# BlogPreservationSuite

Herramienta de preservación digital para blogs de Blogger.
Desarrollada para preservar los blogs del Prof. Alfonso López Yepes (UCM).

## Instalación

```bash
# 1. Crear entorno virtual (recomendado)
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

# 2. Instalar dependencias
pip install -r requirements.txt
```

## Uso — Interfaz gráfica (Flask)

```bash
python app.py
# Abrir http://localhost:5000 en el navegador
```

La interfaz permite:
- Editar `config.yaml` directamente en el navegador
- Lanzar el proceso para todos los blogs o solo uno
- Ver el progreso en tiempo real (log en vivo)
- Descargar los archivos HTML generados

## Uso — Línea de comandos

```bash
# Procesar todos los blogs habilitados
python pipeline.py

# Procesar solo un blog (por URL o título)
python pipeline.py --blog cinedocnet

# Forzar re-descarga aunque existan datos en caché
python pipeline.py --force

# Config alternativa
python pipeline.py --config mi_config.yaml
```

## Estructura del proyecto

```
blogger_suite/
├── app.py           — Interfaz Flask
├── pipeline.py      — Orquestador principal
├── extractor.py     — Descarga posts via Atom Feed
├── cleaner.py       — Limpieza de HTML
├── generator.py     — Generación del HTML final
├── config.yaml      — Configuración
├── requirements.txt
└── output/          — Archivos HTML generados (se crea automáticamente)
    └── raw/         — Datos crudos en JSON (caché)
```

## config.yaml — Opciones principales

```yaml
blogs:
  - url: "https://mi-blog.blogspot.com/"
    type: "blogspot"
    title: "Mi Blog"
    enabled: true

author:
  name: "Nombre Apellido"
  role: "Cargo"
  institution: "Institución"

design:
  accent_color: "#1d4ed8"    # Color de énfasis (hex)
  font_size_base: "17px"     # Tamaño de fuente del contenido
  font_family: "Georgia, serif"

output:
  dir: "./output"
  embed_images: true         # Convertir imágenes a base64
  max_image_size_kb: 500     # Límite de tamaño por imagen

scraping:
  delay_between_requests: 1.5  # Segundos entre peticiones
  max_posts_per_blog: 0        # 0 = sin límite
```

## Blogs preservados

- **CineDocNet - Patrimonio**: https://cinedocnet-patrimonio.blogspot.com/
- **RedAuvi**: http://www.redauvi.com/
- **MEIT Doc**: https://meitdoc.blogspot.com/
- **Archivoz Magazine**: https://archivozmagazine.blogspot.com/

## Metadatos incluidos en el HTML generado

- **Dublin Core** (DC.title, DC.creator, DC.date, DC.format…)
- **Open Graph** (og:title, og:description…)
- **Schema.org** BlogPosting (JSON-LD)
- **METS** (Metadata Encoding and Transmission Standard) como comentario estructurado
