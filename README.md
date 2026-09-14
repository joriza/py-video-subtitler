# py-video-subtitler

CLI personal de Python que genera, junto a cada video, un archivo `.srt` en
español con el mismo nombre base (`video.mp4` → `video.srt`), listo para que
VLC o MPC-HC lo carguen por defecto. Todo el procesamiento es local (CPU); la
red solo interviene en la primera descarga de modelos.

```text
python subtitler.py                    # selector interactivo sobre input/
python subtitler.py "mi video.mp4"     # rutas directas (seguras con espacios)
python subtitler.py --dry-run a.mp4    # plan sin procesar
```

## Cómo procesa cada archivo (pipeline)

1. **Sondeo** con `ffprobe` (JSON): pistas de subtítulos, audio y duración.
2. **Pista embebida de texto** (si existe y no hay `--no-extract`): se prefiere
   la marcada como *default*; si no, la primera de texto.
   - Idioma `es` (o desconocido/`und`): extracción directa con ffmpeg, en segundos.
   - Otro idioma (p. ej. `eng`): extracción + traducción con Argos.
3. **Respaldo: transcripción** local con faster-whisper (CPU, int8, VAD,
   autodetección de idioma) cuando no hay pista utilizable, solo hay pistas
   bitmap (PGS/DVB, con WARN) o se pasa `--no-extract`.
4. **Traducción Argos** si el idioma origen no es `es`: par directo `x→es` o
   pivote vía inglés `x→en→es`. Si falta un par, se **descarga solo** (primero
   el directo, luego las patas del pivote); una sola vez por par, después
   queda offline. Sin red o sin par disponible: WARN y se conserva el idioma
   original (el archivo **no** cuenta como fallo).
5. **Salida doble** cuando el origen no es `es`: el SRT original se conserva
   como `video-<idioma>.srt` (ej. `video-en.srt`; `video-orig.srt` si el
   idioma es desconocido) y el traducido se escribe como `video.srt`, el que
   los reproductores cargan por defecto. Con origen `es`: un solo `video.srt`.
6. **Escritura atómica** de ambos SRT junto al video (UTF-8 con BOM, saltos
   CRLF, líneas de ~42 caracteres, máximo 2 por cue, temp + rename atómico).

Un archivo problemático falla solo y la corrida continúa con el resto.

## Opciones

| Opción | Default | Descripción |
| --- | --- | --- |
| `INPUT ...` | — | Videos a procesar; si se omiten, selector interactivo. |
| `--input-dir DIR` | `input` | Carpeta que escanea el selector interactivo. |
| `--model {tiny,base,small,medium,large-v3}` | `small` | Modelo Whisper para transcribir. |
| `--lang {auto,es,en,de,fr,it,pt,ru,ja,zh}` | `auto` | Idioma del audio (`auto` = autodetección). |
| `--target {es}` | `es` | Idioma destino (registro extensible). |
| `--no-extract` | falso | Ignora pistas embebidas y siempre transcribe. |
| `--force` | falso | Regenera el `.srt` aunque ya exista. |
| `--dry-run` | falso | Imprime el plan por archivo sin procesar ni escribir. |

## Selector interactivo

Sin `INPUT`, se listan los videos de `--input-dir` y se pide una selección:

```text
Selecciona archivos (ej. '1 3 5-7', 'a'=todos, 'q'=salir): 1 3 5-7
```

- Rangos inclusivos (`5-7`), invertidos (`7-5`) y separados por espacios o comas.
- `a` procesa todos; `q` abandona; entrada inválida vuelve a preguntar.
- Si la carpeta no existe, se crea con una guía para colocar videos.

## Modelos y tiempos estimados (CPU, int8)

| Modelo | Descarga one-time | Velocidad relativa | Uso típico |
| --- | --- | --- | --- |
| `tiny` | ~75 MB | muy rápido | pruebas, audio claro |
| `base` | ~140 MB | rápido | |
| `small` | ~460 MB | moderado | **default**: buen equilibrio |
| `medium` | ~1.5 GB | lento | mejor precisión |
| `large-v3` | ~3 GB | muy lento | máxima calidad |

La primera transcripción descarga el modelo a la caché de Hugging Face
(`~/.cache/huggingface`); después funciona offline. La primera traducción de
un par (p. ej. `en→es`) descarga el paquete Argos una única vez.

## Instalación

Requiere Python 3.11 y ffmpeg/ffprobe en PATH (en Windows, scoop):

```text
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Datos de la instalación original: Python **3.11.15**, venv ~**1.2 GB**
(Argos arrastra torch/spacy/stanza como dependencias transitivas), instalación
~**2.5 minutos**. El motor de transcripción (faster-whisper/CTranslate2) no usa
PyTorch; el GPU AMD sin CUDA no se aprovecha: todo va por CPU.

## Códigos de salida

| Código | Significado |
| --- | --- |
| `0` | Sin fallos (solo ok/skipped, incluidos dry-run y corrida vacía). |
| `1` | Al menos un archivo falló; o falta ffmpeg/ffprobe. |
| `2` | Uso inválido (opción desconocida o registrada no implementada). |
| `130` | Interrumpido con Ctrl-C. |

## Limitaciones conocidas

- Argos no ofrece variantes rioplatenses: la traducción al español es neutra.
- Pistas bitmap (PGS/DVB) no se pueden extraer: se emite WARN y se transcribe.
- Calidad de traducción: fuera de alcance (riesgo aceptado); Argos funciona
  offline con modelos pequeños.
- GPU AMD sin CUDA: transcripción solo por CPU (decisión cerrada de PLAN.md).
- Ctrl-C físico no se simula en la suite; el handler se verifica por unit.

## Pruebas

Suite de humo con biblioteca estándar (sin modelos ni red):

```text
.venv/Scripts/python.exe test_smoke.py
```

Sección real **opt-in** (usa `--model tiny`, descarga one-time ~75 MB y puede
descargar el paquete Argos `en→es`; síntesis de voz SAPI para el audio):

```text
SUBTITLER_SMOKE_REAL=1 .venv/Scripts/python.exe test_smoke.py
```

Sin la variable (o con cualquier valor distinto de `1`) los checks reales se
reportan como `SKIP` y no cuentan como fallo. `subtitler.py` jamás lee esa
variable. `tests_tmp/` se elimina al salir.

## Hoja de ruta

- [x] Extracción de pistas embebidas (texto) con formato uniforme.
- [x] Transcripción local CPU + traducción Argos (directo o pivote).
- [x] Selector interactivo, dry-run, códigos de salida y suite de humo.

## Historial

- 2026-09-13: primera versión completa (cambio SDD `add-subtitler-cli`):
  pipeline por archivo, formato SRT con BOM+CRLF y política 42/2, escritura
  atómica, SKIP/`--force`/`--dry-run`, selector, ruteo Argos y pruebas.
