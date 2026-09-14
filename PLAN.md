# PLAN: py-video-subtitler (aprobado — pendiente de ejecución SDD)

> Nota de arranque para la sesión SDD que ejecute este proyecto.
> Consumir en `sdd-init`/`sdd-proposal`; puede eliminarse o archivarse al cerrar el cambio SDD.

## Objetivo

CLI de Python que toma los videos de `input/` (o rutas pasadas como argumento) y genera
junto a cada uno un `.srt` con el mismo nombre (`video.mp4` → `video.srt`), para que los
reproductores (VLC, MPC-HC, etc.) lo levanten por defecto.

**Destino: español siempre. Origen: mayormente inglés, variado.**

## Decisiones cerradas (con el usuario, 2026-09-13)

| Decisión | Valor | Justificación |
| --- | --- | --- |
| Motor | `faster-whisper` 1.2.1, CPU, `int8` | ~4x más rápido que Whisper original en CPU, sin PyTorch, offline |
| Idioma origen | Autodetección por video (`--lang auto` configurable) | Biblioteca variada con mayoría en inglés; la detección de inglés es prácticamente perfecta |
| Idioma destino | Español (`--target es`, registro extensible) | Origen es → transcripción directa; otro idioma → traducción Argos |
| Traducción | `argostranslate` 1.11.0 (offline tras primera descarga) | Par `en→es` (el caso dominante) es el mejor par de Argos; par directo si existe, si no pivote vía inglés; si no hay camino → subtítulos en idioma original + WARN (nunca rompe la corrida) |
| Modelo default | `small` (~460 MB, `--model` configurable: tiny/base/small/medium/large-v3) | ~3-4x tiempo real en CPU int8 |
| Subs embebidos | Extraer pista de texto si existe; `--no-extract` fuerza transcripción | Extraer es exacto e instantáneo |
| Entorno | Python 3.11.15, ffmpeg/ffprobe en PATH (scoop), GPU AMD sin CUDA → CPU only | Verificado en la máquina |

## Pipeline por archivo

1. **Sondeo** — `ffprobe` (JSON): streams de subtítulos, audio, duración. Sin audio → error por archivo, la corrida sigue.
2. **Extracción** (si hay pista de texto y no `--no-extract`):
   - Pista preferida: la marcada *default*; si no, la primera de texto.
   - `language=es` o sin metadata → extraer tal cual (`ffmpeg -c:s srt`).
   - `language≠es` → extraer + traducir con Argos.
   - Solo bitmap (PGS/DVB) → WARN + transcribir.
3. **Transcripción** — `faster-whisper` con VAD, autodetección:
   - Detecta `es` → SRT directo.
   - Otro idioma → Argos traduce segmentos al español → SRT.
4. **Escritura SRT** — junto al video, mismo stem, numeración `1..n`,
   `HH:MM:SS,mmm --> HH:MM:SS,mmm`, corte de línea a ~42 caracteres (máx 2 líneas),
   **UTF-8 con BOM + CRLF**. Escritura a temp + rename atómico.
5. **`.srt` existente** → SKIP con advertencia; `--force` regenera.

## CLI (espejo de py-video-converter)

`python subtitler.py [OPTIONS] [INPUT ...]` — sin `INPUT`, selector interactivo sobre
`--input-dir` (`1 3 5-7`, `a`, `q`).

| Opción | Default | Descripción |
| --- | --- | --- |
| `--input-dir DIR` | `input` | Carpeta del selector interactivo |
| `--model {tiny,base,small,medium,large-v3}` | `small` | Modelo Whisper (registro extensible) |
| `--lang {auto,es,en,...}` | `auto` | Idioma del audio |
| `--target {es}` | `es` | Idioma de los subtítulos (registro, futuro) |
| `--no-extract` | off | Ignorar subs embebidos y transcribir siempre |
| `--force` | off | Regenerar aunque el `.srt` exista |
| `--dry-run` | off | Plan por archivo (sondeo → ruta elegida → salida) sin procesar |

Códigos de salida `0`/`1`. Progreso en una línea (porcentaje + ETA) vía callback de segmentos.

## Convenios del repositorio (copiar de D:/Desarrollo/py-video-converter)

```
py-video-subtitler/
├── .git/            ← ya inicializado (branch main, remote joriza/py-video-subtitler)
├── .gitignore       ← adaptar del converter (+ input/, tests_tmp/, .venv/, caches)
├── .venv/           ← python -m venv (Python 3.11)
├── input/           ← gitignored, se crea con guía si falta
├── README.md        ← español: uso, opciones, cómo funciona, modelos y tiempos, limitaciones, hoja de ruta, historial
├── requirements.txt ← faster-whisper, argostranslate
├── subtitler.py     ← single-file, registros al tope, docstrings en español, subprocess con listas (seguro Windows)
└── test_smoke.py    ← smoke suite estilo converter (muestras sintéticas lavfi, unit tests SRT, extracción embebida; transcripción real opt-in vía env var para no descargar modelos en cada smoke)
```

## Estimaciones (CPU int8, small)

- 1 h de video en inglés + traducción ≈ 20-25 min
- 1 h en español ≈ 15-20 min
- Extracción embebida: segundos
- Primera corrida: descarga única de modelos (~460 MB Whisper small + ~100-300 MB por par Argos)

## Riesgos aceptados

- Traducción Argos: correcta, no perfecta; español neutro (no rioplatense). Solo para orígenes no-españoles.
- Índice de paquetes Argos a veces lento la primera descarga; luego offline y cacheado.

## Configuración SDD de sesión (preflight ya confirmado por el usuario)

- execution: `auto`
- artifact store: `openspec`
- delivery strategy: `ask-on-risk` (remote: <https://github.com/joriza/py-video-subtitler>)
- review budget: `400`

El usuario quiere probar SDD **sin sobre-ingeniería**: app personal, single-file, fases livianas.
