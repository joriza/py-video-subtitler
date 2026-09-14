# Propuesta — add-subtitler-cli

- **Cambio:** `add-subtitler-cli` (único, liviano)
- **Fase:** proposal · **Fecha:** 2026-09-13 · **Estado:** listo para `specs`
- **Almacén:** openspec (este archivo)
- **Fuente de producto:** `PLAN.md` — decisiones CERRADAS el 2026-09-13; esta propuesta las refleja, no las reabre.
- **Correcciones de gate heredadas de explore:** el intérprete de PATH es Python **3.11.15** (shim de uv) y coincide con PLAN.md; la lectura 3.11.6 en explore.md corresponde a la instalación del py-launcher, no al PATH. Conteos reales de la referencia espejo: `convert.py` = 1229 líneas, `test_smoke.py` = 442 líneas (los de explore.md eran aproximados).

## Resumen (intent)

CLI personal de Python, single-file (`subtitler.py`), que genera un `.srt` en español junto a cada video de `input/` (o de rutas pasadas como argumento): `video.mp4` → `video.srt`, listo para que VLC/MPC-HC lo carguen por defecto. Operación local: transcripción con faster-whisper (CPU) y traducción con Argos; la red solo interviene en la primera descarga de modelos.

## Problema

- Biblioteca personal de videos mayormente en inglés (con otros orígenes variados) sin subtítulos en español que los reproductores levanten por defecto.
- Conseguir subs a mano (buscar SRT externos, sincronizar, traducir) es lento y repetitivo.
- Las pistas embebidas, cuando existen, suelen estar en el idioma original: requieren extracción y traducción igualmente manual.

## Objetivo / resultado de producto

Ejecutar un comando y obtener, junto a cada video elegido, un `.srt` válido en español con el mismo nombre base. La corrida es robusta: un archivo problemático falla solo y nunca rompe la tanda. Si hay pista embebida de texto se extrae (exacto e instantáneo); si no, se transcribe localmente. Cierre con resumen `TOTAL: N ok, M failed, K skipped` y exit code `0`/`1`.

## Decisiones cerradas (heredadas de PLAN.md — no reabrir)

| Decisión | Valor |
| --- | --- |
| Motor | `faster-whisper` 1.2.1, CPU, `int8` (~4x vs Whisper original en CPU, sin PyTorch en el motor, offline) |
| Idioma origen | Autodetección por video (`--lang auto`) — detección de inglés prácticamente perfecta |
| Idioma destino | Español (`--target es`, registro extensible) |
| Traducción | `argostranslate` 1.11.0: par directo si existe, si no pivote vía inglés, si no → WARN + subs en idioma original (nunca rompe la corrida) |
| Modelo default | `small` (~460 MB; registro: tiny/base/small/medium/large-v3) |
| Subs embebidos | Extraer pista de texto si existe; `--no-extract` fuerza transcripción |
| Entorno | Windows; Python 3.11.15 (PATH); ffmpeg/ffprobe 8.1.2 (scoop) en PATH; GPU AMD sin CUDA → CPU only |

## Pipeline por archivo

1. **Sondeo** — `ffprobe` (JSON): streams de subtítulos, audio, duración. Sin audio → error por archivo, la corrida sigue.
2. **Extracción** (si hay pista de texto y no `--no-extract`):
   - Pista preferida: la marcada *default*; si no, la primera de texto.
   - `language=es` o sin metadata → extraer tal cual (`ffmpeg -c:s srt`).
   - `language≠es` → extraer + traducir con Argos.
   - Solo bitmap (PGS/DVB) → WARN + transcribir.
3. **Transcripción** — `faster-whisper` con VAD y autodetección:
   - Detecta `es` → SRT directo.
   - Otro idioma → Argos traduce los segmentos al español → SRT.
4. **Escritura SRT** — junto al video, mismo stem, numeración `1..n`, `HH:MM:SS,mmm --> HH:MM:SS,mmm`, corte de línea a ~42 caracteres (máx 2 líneas), **UTF-8 con BOM + CRLF**, escritura a temp + rename atómico.
5. **`.srt` existente** → SKIP con advertencia; `--force` regenera.

## Superficie CLI

`python subtitler.py [OPTIONS] [INPUT ...]` — sin `INPUT`, selector interactivo sobre `--input-dir` (sintaxis `1 3 5-7`, `a`, `q`; crea la carpeta con guía si falta).

| Opción | Default | Descripción |
| --- | --- | --- |
| `--input-dir DIR` | `input` | Carpeta del selector interactivo |
| `--model {tiny,base,small,medium,large-v3}` | `small` | Modelo Whisper (registro extensible) |
| `--lang {auto,es,en,...}` | `auto` | Idioma del audio |
| `--target {es}` | `es` | Idioma de los subtítulos (registro, futuro) |
| `--no-extract` | off | Ignorar subs embebidos y transcribir siempre |
| `--force` | off | Regenerar aunque el `.srt` exista |
| `--dry-run` | off | Plan por archivo (sondeo → ruta elegida → salida) sin procesar |

Códigos de salida `0`/`1` (`130` en Ctrl-C). Progreso en una línea (porcentaje + ETA) alimentado por los segmentos de Whisper.

## Alcance y áreas afectadas

Un solo cambio SDD liviano sobre `joriza/py-video-subtitler` (branch `main`):

- **Nuevos:** `subtitler.py` (single-file, registros al tope, docstrings en español, subprocess con listas de argumentos — seguro en Windows), `test_smoke.py` (suite de humo solo stdlib, estilo converter: muestras sintéticas lavfi en `tests_tmp/`, unit tests en subproceso, `RESULT N passed/M failed`; transcripción real opt-in vía variable de entorno para no descargar modelos en cada smoke), `README.md` (español: uso, opciones, pipeline, modelos y tiempos, limitaciones, hoja de ruta, historial), `requirements.txt` (`faster-whisper==1.2.1`, `argostranslate==1.11.0`), `.venv/` (local, gitignored, aún no creado).
- **Modificados:** `.gitignore` (añadir `.venv/`, `input/`, `__pycache__/`, `tests_tmp/`, `.ruff_cache/` al `.atl/` existente).
- **Solo lectura (nunca modificar):** `D:/Desarrollo/py-video-converter` como espejo de convenciones (`convert.py` 1229 líneas; `test_smoke.py` 442 líneas).
- **Runtime:** `input/` y `tests_tmp/` se crean al vuelo (gitignored).

## No-objetivos (fuera de este cambio)

- No reabrir motor, idiomas ni alcance: están cerrados en PLAN.md.
- Sin GUI ni empaquetado/distribución: se ejecuta con `python subtitler.py`, no es paquete instalable.
- Sin GPU/CUDA ni aceleración distinta de CPU int8.
- Sin quemar (burn-in) de subtítulos en el video ni edición/sincronización fina de SRT: solo sidecar.
- Sin idiomas destino adicionales implementados: `--target` queda como registro con `es`; otros valores son futuro.
- Sin pytest ni CI: la suite de humo con stdlib es suficiente para una app personal.
- Sin sobre-ingeniería deliberada: single-file y decisiones con justificación breve.

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
| --- | --- | --- |
| Traducción Argos correcta pero no perfecta (español neutro, no rioplatense) | Calidad de subs para orígenes no-españoles | Aceptado en PLAN; solo se traduce cuando el origen no es español |
| Índice de paquetes Argos lento en la primera descarga | Primera corrida lenta | One-time; después offline y cacheado |
| Deps de Argos pesadas (posible torch transitivo) → venv grande, install lento | Tiempo/espacio de setup | No reabre el plan ("sin PyTorch" aplica al motor Whisper); verificar al crear el venv |
| Primera corrida descarga modelos (~460 MB Whisper small + 100–300 MB por par Argos) | Ancho de banda/disco | One-time, cacheado por usuario |
| Sin camino de traducción Argos para un idioma poco común | Subs quedan en idioma original | WARN y continuar; la corrida nunca se rompe |
| Pista embebida solo bitmap (PGS/DVB) | Extracción imposible | WARN + transcripción como fallback |

Estimaciones de producto (CPU int8, `small`): 1 h de video en inglés + traducción ≈ 20–25 min; 1 h en español ≈ 15–20 min; extracción embebida: segundos.

## Plan de reversión (breve)

1. `git revert` del commit/PR del cambio: el delta es aditivo salvo `.gitignore`, que queda restaurado a su estado previo (solo `.atl/`).
2. Borrar residuos locales no versionados si se desea limpieza total: `.venv/`, `input/`, `tests_tmp/`, cachés (`__pycache__/`).
3. Estado externo: solo cachés de usuario (modelos Hugging Face, paquetes Argos) — opcionales de borrar.
4. Archivar `openspec/changes/add-subtitler-cli/` al cerrar el cambio, avisando antes de cualquier mezcla de deltas destructivos.

## Criterios de éxito

1. Un video con pista embebida de texto produce su `.srt` en segundos: exacto si es `es`, traducido con Argos si no lo es.
2. Un video sin pista embebida produce `.srt` en español vía faster-whisper (+ Argos si el origen no es español).
3. `.srt` existente → SKIP con advertencia; con `--force` se regenera.
4. `--dry-run` imprime el plan por archivo (sondeo → ruta elegida → salida) sin escribir salidas.
5. Formato SRT verificado: UTF-8 con BOM + CRLF, numeración `1..n`, timestamps con coma, líneas ~42 caracteres (máx 2), escritura temp + rename atómico.
6. Video sin audio → error solo de ese archivo; la corrida continúa; exit code `0` si todo ok/omitido, `1` si algún fallo.
7. `test_smoke.py` pasa sin red ni descargas de modelos (transcripción real solo opt-in vía env var) con `.venv/Scripts/python.exe test_smoke.py`.
8. README en español documenta uso, opciones, pipeline, modelos/tiempos y limitaciones.
