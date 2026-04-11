# blogPreserv

<div align="center">

![BlogPreservationSuite Logo](https://img.shields.io/badge/BlogPreservationSuite-v1.0.0-003e7e?style=for-the-badge&logo=archive&logoColor=white)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![OAI-PMH](https://img.shields.io/badge/OAI--PMH-2.0-8B0000?style=for-the-badge)](https://www.openarchives.org/OAI/openarchivesprotocol.html)
[![Dublin Core](https://img.shields.io/badge/Dublin_Core-ISO_15836-5B4A8A?style=for-the-badge)](https://www.dublincore.org)
[![METS](https://img.shields.io/badge/METS-Standard-B8860B?style=for-the-badge)](https://www.loc.gov/standards/mets/)

**Suite de preservación digital de blogs académicos alojados en Blogger mediante sindicación Atom, limpieza semántica, metadatos normalizados e integración con repositorios institucionales**

</div>

---

## 📋 Tabla de contenidos

- [Descripción general](#-descripción-general)
- [Características principales](#-características-principales)
- [Requisitos del sistema](#-requisitos-del-sistema)
- [Instalación](#-instalación)
- [Configuración](#-configuración)
- [Uso del programa](#-uso-del-programa)
- [Estructura del proyecto](#-estructura-del-proyecto)
- [Arquitectura técnica](#️-arquitectura-técnica)
- [Métricas de calidad](#-métricas-de-calidad)
- [Metadatos para la preservación](#-metadatos-para-la-preservación)
- [Exportación OAI-PMH](#-exportación-oai-pmh)
- [Limitaciones conocidas](#-limitaciones-conocidas)
- [Líneas de desarrollo futuro](#-líneas-de-desarrollo-futuro)
- [Autoría y créditos](#-autoría-y-créditos)
- [Licencia](#-licencia)
- [Citas y referencias](#-citas-y-referencias)

---

## 🔍 Descripción general

**BlogPreservationSuite** es una suite de preservación digital desarrollada en Python que automatiza la captura, limpieza, reestructuración y archivado del contenido de blogs académicos alojados en la plataforma Blogger. Diseñada con una perspectiva de **Ciencias de la Documentación y Archivística Digital**, permite a investigadores, bibliotecarios y archivistas generar versiones autocontenidas, semánticamente enriquecidas e interoperables de blogs cuya continuidad depende de decisiones corporativas ajenas al control del autor.

El sistema fue desarrollado en el marco del proyecto de preservación digital del corpus de publicaciones del Prof. Alfonso López Yepes, catedrático de Documentación Audiovisual de la Universidad Complutense de Madrid, cuyos cuatro blogs en Blogger suman 1.135 entradas publicadas a lo largo de aproximadamente dos décadas. El resultado de la preservación es un único archivo HTML5 autocontenido por blog, con todas las imágenes embebidas en base64, buscador de texto completo integrado, índice cronológico interactivo y cuatro capas de metadatos normalizados (Dublin Core, Open Graph, Schema.org y METS).

---

## ✨ Características principales

- **Extracción completa mediante sindicación Atom**: acceso programático al feed nativo de Blogger, con paginación automática y caché en disco para evitar re-descargas.
- **Pipeline de limpieza semántica**: doce transformaciones secuenciales que eliminan el ruido presentacional de Blogger (estilos inline, residuos de Word, entidades mal codificadas, URLs de edición administrativa) preservando íntegramente el contenido.
- **Incrustación base64 de imágenes**: todas las imágenes se descargan desde el CDN de Google, se redimensionan si superan el umbral configurado y se codifican como Data URIs embebidas en el HTML, eliminando cualquier dependencia de red.
- **Preservación de vídeos YouTube**: mediante iframes responsivos que garantizan la visualización en cualquier dispositivo.
- **Metadatos normalizados**: Dublin Core (ISO 15836), Open Graph, Schema.org JSON-LD y METS generados automáticamente para cada blog preservado.
- **Enriquecimiento mediante IA generativa local**: módulo opcional que utiliza un modelo de lenguaje local (LM Studio / Gemma, LLaMA, Mistral…) para generar etiquetas temáticas, resúmenes académicos y clasificaciones según vocabulario controlado, sin enviar datos a servicios externos.
- **Buscador de texto completo integrado**: índice JSON embebido en el HTML con búsqueda instantánea sin servidor sobre título, texto, fecha, categorías y etiquetas.
- **Índice cronológico interactivo**: navegación por año y mes completamente localizada en español.
- **Módulo de métricas de calidad**: diez indicadores cuantitativos (M1-M10) que miden la fidelidad de la preservación y se exportan en JSON para su análisis y comparación.
- **Proveedor OAI-PMH 2.0**: exposición del corpus como repositorio cosechable por sistemas institucionales (DSpace, EPrints, Zenodo).
- **Interfaz web de control**: panel Flask para operar el pipeline completo desde el navegador sin línea de comandos.

---

## 📋 Requisitos del sistema

| Componente | Versión mínima | Notas |
|------------|----------------|-------|
| Python | 3.8 o superior | Probado hasta 3.12 |
| pip | 21.0+ | Para la instalación de dependencias |
| Sistema operativo | Windows, macOS o Linux | Incluyendo ARM (Snapdragon, Apple Silicon) |
| Conexión a internet | Requerida en F1 | Solo para la extracción inicial; el resto del pipeline funciona offline |
| LM Studio | 0.3.x+ | Opcional; solo para el módulo de enriquecimiento IA |
| Espacio en disco | Variable | Los archivos HTML con imágenes base64 pueden superar los 50 MB por blog |

### Dependencias Python principales

```
requests
beautifulsoup4
lxml
Pillow
flask
PyYAML
```

La lista completa se encuentra en `requirements.txt`.

---

## 🚀 Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/manublaz/blogPreserv.git
cd blogPreserv
```

### 2. Crear entorno virtual (recomendado)

```bash
python -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Verificar la instalación

```bash
python pipeline.py --help
```

No se requiere base de datos ni infraestructura de servidor. El programa está listo para usarse.

---

## ⚙️ Configuración

Toda la configuración se gestiona a través del archivo `config.yaml`. Un ejemplo comentado:

```yaml
blogs:
  - slug: cinedocnet-patrimonio
    title: "CineDocNet - Patrimonio"
    feed_url: "https://cinedocnet-patrimonio.blogspot.com/feeds/posts/default"

extraction:
  delay: 1.5          # Segundos entre peticiones al feed Atom
  timeout: 90         # Timeout HTTP en segundos
  max_image_size: 500 # Umbral de redimensionado de imágenes (KB)

ai:
  enabled: false      # true para activar el módulo de enriquecimiento
  endpoint: "http://127.0.0.1:1234/v1"
  model: "gemma-3-4b"

quality_metrics:
  enabled: true
  sample_size: 50     # Entradas a muestrear para M2 (integridad textual)

oai_pmh:
  enabled: false
  repository_name: "Corpus ALY - UCM"
  admin_email: "manublaz@ucm.es"
```

---

## 💻 Uso del programa

### Ejecución por línea de comandos

```bash
# Procesar todos los blogs definidos en config.yaml
python pipeline.py

# Procesar un blog específico
python pipeline.py --blog cinedocnet-patrimonio

# Forzar re-descarga ignorando la caché
python pipeline.py --blog cinedocnet-patrimonio --force-extract
```

### Interfaz web (Flask)

```bash
python app.py
```

Accede desde el navegador a `http://127.0.0.1:5000`. La interfaz permite seleccionar blogs, lanzar el pipeline, monitorizar el progreso en tiempo real y descargar los archivos generados.

### Fases del pipeline

| Fase | Módulo | Descripción |
|------|--------|-------------|
| F1 | `extractor.py` | Extracción del corpus vía feed Atom y descarga de imágenes |
| F2 | `cleaner.py` | Limpieza semántica del HTML (12 transformaciones) |
| F3 | `ai_enricher.py` | Enriquecimiento con IA local (opcional) |
| F4 | `generator.py` | Generación del HTML autocontenido con metadatos |
| F5 | `quality_metrics.py` | Cálculo y exportación de las 10 métricas de calidad |
| F6 | `oai_pmh.py` | Exportación del repositorio OAI-PMH (opcional) |

### Archivos generados

```
output/
  cinedocnet-patrimonio.html        ← Archivo HTML autocontenido
  cinedocnet-patrimonio_quality.json ← Informe de métricas de calidad
  redauvi.html
  redauvi_quality.json
  ...
```

---

## 📁 Estructura del proyecto

```
blogPreserv/
│
├── pipeline.py           # Orquestador principal del pipeline
├── app.py                # Interfaz web de control (Flask)
├── extractor.py          # Módulo de extracción vía feed Atom
├── cleaner.py            # Módulo de limpieza semántica del HTML
├── ai_enricher.py        # Módulo de enriquecimiento con IA local
├── generator.py          # Módulo de generación del HTML autocontenido
├── quality_metrics.py    # Módulo de métricas de calidad
├── oai_pmh.py            # Módulo de exportación OAI-PMH 2.0
│
├── config.yaml           # Configuración principal del sistema
├── requirements.txt      # Dependencias Python
├── README.md             # Este documento
│
├── cache/                # Caché de datos crudos del feed Atom
└── output/               # Archivos HTML y JSON generados
```

---

## 🏗️ Arquitectura técnica

### Flujo de ejecución

```
config.yaml
     ↓
pipeline.py (orquestador)
     ↓
F1: extractor.py ──→ Feed Atom de Blogger (paginación automática)
     │                Descarga de imágenes + codificación base64
     │                Caché en disco
     ↓
F2: cleaner.py ───→ 12 transformaciones semánticas
     │                Eliminación de ruido presentacional
     │                Normalización de títulos y entidades
     ↓
F3: ai_enricher.py → Inferencia local vía LM Studio (opcional)
     │                Etiquetas, resúmenes, clasificación
     ↓
F4: generator.py ──→ HTML5 autocontenido
     │                Dublin Core + Open Graph + Schema.org + METS
     │                Buscador full-text + índice cronológico
     ↓
F5: quality_metrics.py → Informe JSON con M1-M10
     ↓
F6: oai_pmh.py ────→ Repositorio OAI-PMH 2.0 cosechable (opcional)
```

### Estrategia de resolución de imágenes

El sistema intenta obtener la versión de mayor resolución disponible en el CDN de Blogger, siguiendo una escalera de sufijos:

```
s1600 → s1280 → s800 → s640 → s400
```

Si la imagen supera el umbral configurado (500 KB por defecto), se redimensiona en memoria con Pillow antes de codificarla como Data URI.

---

## 📊 Métricas de calidad

El módulo `quality_metrics.py` calcula diez indicadores cuantitativos que permiten evaluar la fidelidad de la preservación de forma objetiva y reproducible:

| Métrica | Descripción |
|---------|-------------|
| M1 | Cobertura de entradas (entradas preservadas / entradas originales) |
| M2 | Integridad textual (solapamiento de tokens sobre muestra de 50 entradas) |
| M3 | Cobertura de imágenes (imágenes embebidas en b64 / imágenes detectadas) |
| M4 | Cobertura de vídeos YouTube (iframes preservados / vídeos detectados) |
| M5 | Completitud de metadatos Dublin Core (campos presentes / 12 esperados) |
| M6 | Completitud de metadatos METS (secciones presentes / 3 esperadas) |
| M7 | Cobertura de etiquetas (etiquetas preservadas / etiquetas originales) |
| M8 | Fidelidad de fechas (entradas con fecha ISO válida / total) |
| M9 | Integridad de enlaces (enlaces de edición Blogger eliminados / detectados) |
| M10 | Puntuación global (media ponderada de M1-M9) |

Resultados obtenidos sobre el corpus del Prof. Alfonso López Yepes (abril 2026):

| Blog | Entradas | M3 Imágenes | M4 Vídeos | M10 Global |
|------|----------|-------------|-----------|------------|
| CineDocNet - Patrimonio | 388 | 98,7% | 69,3% | 96,2% |
| RedAuvi | 271 | 98,7% | 88,0% | 97,9% |
| MEIT Doc | 17 | 100,0% | 50,0% | 94,1% |
| Archivoz Magazine | 459 | 98,9% | 87,6% | 98,1% |
| **Total / Media** | **1.135** | **98,8%** | **80,3%** | **96,6%** |

---

## 🗂️ Metadatos para la preservación

Cada archivo HTML generado incorpora cuatro capas de metadatos normalizados embebidos en el `<head>` del documento:

- **Dublin Core** (ISO 15836:2017): 12 campos descriptivos como meta-etiquetas, compatibles con OAI-PMH.
- **Open Graph**: interoperabilidad con motores de indexación y redes académicas.
- **Schema.org Blog** (JSON-LD): datos estructurados legibles por máquina para motores de búsqueda.
- **METS** (*Metadata Encoding and Transmission Standard*, Biblioteca del Congreso): envoltorio archivístico con secciones `metsHdr`, `dmdSec` y `mods:mods`.

---

## 🔄 Exportación OAI-PMH

El módulo `oai_pmh.py` expone el corpus como un repositorio OAI-PMH 2.0 cosechable, compatible con sistemas institucionales como DSpace, EPrints o Zenodo. Soporta los verbos estándar `Identify`, `ListMetadataFormats`, `ListRecords` y `GetRecord`, con metadatos en formato `oai_dc`.

---

## ⚠️ Limitaciones conocidas

- **Dependencia del feed Atom de Blogger**: si Google modifica o elimina el endpoint `/feeds/posts/default`, la fase de extracción dejará de funcionar y será necesario adaptar el módulo `extractor.py`.
- **Bloqueos del CDN de Google**: el CDN de imágenes de Blogger puede bloquear peticiones automatizadas, provocando pérdidas de imagen (< 2% en las pruebas realizadas). Se recomienda respetar el delay configurado entre peticiones.
- **Vídeos de YouTube privados o eliminados**: los vídeos privados o eliminados no pueden preservarse mediante iframe y se contabilizan como pérdida en la métrica M4. La solución requeriría descarga local con herramientas externas.
- **Solo compatible con Blogger**: el sistema está optimizado para la estructura del feed Atom de Blogger. La extensión a WordPress (formato WXR) se propone como línea de trabajo futuro.
- **Enriquecimiento IA dependiente de LM Studio**: el módulo `ai_enricher.py` requiere que LM Studio esté activo localmente con un modelo cargado. Su desactivación no afecta al resto del pipeline.

---

## 🔮 Líneas de desarrollo futuro

- [ ] Soporte para blogs WordPress mediante el formato de exportación WXR
- [ ] Descarga local de vídeos YouTube mediante integración con yt-dlp
- [ ] Interfaz de revisión asistida para corrección manual de resultados del módulo IA
- [ ] Extensión del vocabulario controlado para clasificación temática
- [ ] Soporte para múltiples idiomas en el índice cronológico (actualmente solo español)
- [ ] Módulo de detección de duplicados entre blogs del mismo autor
- [ ] Panel de comparación de métricas entre ejecuciones del pipeline

---

## 👥 Autoría y créditos

### Desarrollador principal

**Prof. Manuel Blázquez Ochando**
Profesor Titular de Universidad
Departamento de Biblioteconomía y Documentación
Facultad de Ciencias de la Documentación
Universidad Complutense de Madrid

📧 [manublaz@ucm.es](mailto:manublaz@ucm.es)
🔗 [ORCID: 0000-0002-4108-7531](https://orcid.org/0000-0002-4108-7531)

### Corpus de prueba

Los blogs del **Prof. Alfonso López Yepes**, catedrático emérito de Documentación Audiovisual de la Universidad Complutense de Madrid, constituyen el corpus sobre el que se desarrolló y validó el sistema. Su producción intelectual distribuida en cuatro blogs de Blogger (1.135 entradas, 2012-2026) motivó y dio forma a todos los requisitos funcionales de la suite.

### Tecnología de asistencia al desarrollo

Desarrollado con Claude Sonnet de Anthropic como herramienta de asistencia al desarrollo.

---

## 📄 Licencia

Este proyecto se distribuye bajo licencia MIT. Consulta el archivo LICENSE para más detalles.

---

## 📚 Citas y referencias

Si utilizas **blogPreserv** en tu investigación o docencia, por favor cítalo de la siguiente forma:

> Blázquez Ochando, M. (2026). *blogPreserv: Suite de preservación digital de blogs académicos mediante sindicación Atom, limpieza semántica y metadatos normalizados* (v1.0.0) [Software]. GitHub. https://github.com/manublaz/blogPreserv

En formato BibTeX:
```bibtex
@software{blazquez2026blogpreserv,
  author       = {Blázquez Ochando, Manuel},
  title        = {{BlogPreservationSuite}: Suite de preservación digital
                  de blogs académicos mediante sindicación {Atom},
                  limpieza semántica y metadatos normalizados},
  year         = {2026},
  version      = {1.0.0},
  publisher    = {GitHub},
  url          = {https://github.com/manublaz/blogPreserv},
  note         = {Desarrollado en el marco del proyecto de preservación
                  del corpus digital del Prof. Alfonso López Yepes,
                  Facultad de Ciencias de la Documentación,
                  Universidad Complutense de Madrid}
}
```

---

<div align="center">

BlogPreservationSuite es una herramienta de investigación y preservación del patrimonio digital desarrollada en la
Facultad de Ciencias de la Documentación de la Universidad Complutense de Madrid,
en el marco de los estudios de Información y Documentación.

</div>
