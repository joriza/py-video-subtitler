# Exploración — add-subtitler-cli (py-video-subtitler)

Fecha: 2026-09-13 · Fase: explore · Almacén: openspec · Modo: notas, sin implementar.
Fuentes: PLAN.md (producto CERRADO), openspec/config.yaml, repo hermano
`D:/Desarrollo/py-video-converter` (SOLO LECTURA, no modificado), entorno local
verificado por filesystem (esta sesión no tiene shell; se indica qué se verificó y cómo).

---

## 1. convert.py — estructura espejable (~1.060 líneas, single-file)

### 1.1 Tope del módulo: registros y constantes

- Bloque de constantes delimitado por separadores de comentario de caja
  (`# ----- #`) con: nombres de ejecutables (`FFMPEG`, `FFPROBE`), timeouts
  (`FFPROBE_TIMEOUT_S = 30`, `ENCODER_PROBE_TIMEOUT_S = 15`), constantes de
  política y presentación (`PROGRESS_BAR_WIDTH = 24`,
  `PROGRESS_MIN_INTERVAL_S = 0.1`), y `VIDEO_EXTENSIONS` como `set` de
  extensiones sin punto.
- Patrón de registro: `@dataclass(frozen=True)` con campo `implemented: bool =
  False` + `dict[str, Spec]` al tope (`RES_POLICIES`, `SPEED_PROFILES`,
  `HEVC_ENCODER_ARGS`, `CODECS`). Las tablas comparten argumentos entre specs
  (p. ej. `HEVC_ENCODER_ARGS` alimenta `EncoderSpec.args_by_speed` vía helper
  `_hevc_encoder`). Una opción futura = entrada nueva del registro.
- `validate_registry_choices(parser, args)` rechaza valores registrados pero
  sin implementar con `parser.error(...)` y lista de disponibles → el `choices=`
  de argparse valida membresía y la validación posterior valida implementación.
  → Espejar tal cual con `MODELS` (tiny/base/small/medium/large-v3) y registros
  de idiomas (`--lang`, `--target es`).

### 1.2 Estilo de docstrings

- Docstring de módulo en español: título `py-video-converter: <qué hace>`,
  párrafo descriptivo, lista "Puntos de diseño:", cierre "Requiere solo …".
- Docstrings y comentarios de funciones/clases: español, concisos, explican el
  porqué. Secciones del archivo separadas por cajas de comentario:
  `Constantes y registros`, `Tipos de datos`, `Auxiliares de formateo`,
  `Sondeo de medios`, `Resolución de políticas`, `Detección de encoders`,
  `Renderizado de progreso`, `Pipeline por archivo`, `Resolución de entradas y
  selector interactivo`, `CLI`.
- **Dato observado (no decidido aquí):** los `help=` de argparse en convert.py
  están en INGLÉS (solo README/docstrings en español). El espejo debe decidir
  explícitamente el idioma del `--help` (diseño/tareas).

### 1.3 Tipos de datos

- `class MediaError(RuntimeError)` — error de sondeo por archivo.
- `@dataclass MediaInfo` — metadatos de ffprobe (path, dimensiones, codec,
  duration_s, fps, size_bytes, audio_streams).
- `@dataclass(frozen=True) ConvertOptions` — opciones CLI validadas compartidas
  por la corrida.
- `@dataclass FileResult` — resultado por archivo: `status: "ok"|"failed"|"skipped"`,
  detail, bytes, elapsed, encoder_used. → Espejo directo: `SubtituloResult`.

### 1.4 argparse y CLI

- `build_parser()`: `prog="convert.py"`, `description`, `formatter_class=
  argparse.ArgumentDefaultsHelpFormatter`; `inputs` `nargs="*"`;
  `--input-dir` default `"input"`; `choices=tuple(REGISTRO)`; flags booleanos
  `action="store_true"` (`--force`, `--dry-run`).
- `main(argv: Sequence[str] | None = None) -> int`: configura stdio UTF-8,
  parsea, valida registros, verifica herramientas (`shutil.which`), resuelve
  entradas, itera `convert_one` acumulando `FileResult`, `summarize`,
  `return 1 if any(failed) else 0`.
- Arranque: `sys.exit(main())` con `KeyboardInterrupt → 130`.
- Códigos de salida: `0` ok/omitidos/dry-run; `1` cualquier fallo (incluye
  ffmpeg/ffprobe ausentes); `130` interrupción.

### 1.5 Selector interactivo (reutilizable casi verbatim)

- `list_videos(dir, suffix)`: filtra por extensión (lowercase, sin punto),
  excluye salidas que ya terminan en el sufijo, ordena por nombre
  case-insensitive; carpeta inexistente → lista vacía.
- `parse_selection(text, count) -> list[int] | None`: separa por
  `[,\s]+`; rangos `N-M` inclusivos (normaliza inversión), 1-based → 0-based,
  inválido/fuera de rango → `None`.
- `interactive_select(dir, suffix)`: crea la carpeta si falta (con guía),
  lista índice + nombre + MB, bucle `input()` con `a`/`all`, `q`/`quit`,
  `EOFError → []`, re-pregunta ante inválida.
- `resolve_inputs(input_dir, raw_inputs, suffix)`: deduplica rutas
  (`expanduser().resolve()`, dict ordenado) o cae al selector.

### 1.6 Pipeline por archivo (`convert_one`) — forma a espejar

1. `say(f"--- {src.name}")` y try/except del sondeo → `MediaError` ⇒
   `FileResult(status="failed")` SIN lanzar (la corrida sigue).
2. Salida junto a la fuente (mismo stem); si salida == fuente → falla; si
   existe y no `--force` → `SKIP` con detalle.
3. Bloque `--dry-run`: imprime plan legible por archivo y retorna ok.
4. Ejecución real con progreso; en fallo limpia salida parcial
   (`_remove_quietly`) y reporta cola de stderr.
5. `OK`/`ERROR` final con métricas; `summarize(results, options)` imprime
   `TOTAL: N ok, M failed, K skipped | ...` (variante dry-run incluida).

- Subtitler difiere en: sondeo busca streams de subtítulos + audio + duración;
  la "ejecución real" es extraer (ffmpeg) y/o transcribir (faster-whisper) +
  traducir (Argos); escritura SRT a temp + rename atómico (convert escribe
  directo pero borra parciales al fallar — el plan del subtitler exige
  temp+`os.replace`, más estricto).

### 1.7 Sondeo y subprocess (patrones Windows-safe)

- ffprobe SIEMPRE con lista de argumentos:
  `["ffprobe","-v","error","-print_format","json","-show_format","-show_streams", path]`,
  `capture_output=True, text=True, encoding="utf-8", errors="replace",
  timeout=FFPROBE_TIMEOUT_S`. `FileNotFoundError` → "ffprobe not found in
  PATH"; `TimeoutExpired` → error por archivo; returncode≠0 → detalle de
  stderr recortado (300 chars); JSON inválido → error claro.
- Helpers tolerantes `_to_float`, `_safe_int`, `_parse_rate_fraction`
  (fracciones `"30000/1001"`).
- ffmpeg con `-hide_banner -nostats -loglevel error -progress pipe:1 -y`.
- `configure_utf8_stdio()`: `reconfigure(encoding="utf-8", errors="replace")`
  sobre stdout/stderr (nombres unicode seguros en consola Windows).
- Progreso: `Popen` + hilo daemon que drena stderr (cola de 60 líneas) +
  lectura de `key=value` de `-progress pipe:1` (`out_time_us`/`out_time_ms`,
  `speed`), redibujo de una línea con `\r` (`[####----]  45.0%  speed 1.53x
  ETA 03:21`), intervalo mínimo 0.1 s, `say()` final para el salto de línea.
  → El subtitler reutiliza la MISMA línea de progreso pero alimentada por
  segmentos de Whisper: `pct = segment.end / info.duration`, ETA por
  tiempo transcurrido/avance.

## 2. test_smoke.py — forma de la suite (~380 líneas, stdlib only)

- Cabecera: docstring español con el comando de ejecución
  (`.venv/Scripts/python.exe test_smoke.py`) desde la raíz del proyecto.
- Sin pytest: contadores globales `passed`/`failed`; `check(name, condition,
  detail="")` imprime `[PASS]`/`[FAIL] name -- detail`.
- `TMP = ROOT / "tests_tmp"`; `main()` hace `rmtree(ignore_errors=True)` +
  `mkdir`, `try/finally: rmtree` (limpieza idempotente aunque haya fallos).
- `run_converter(args, timeout=600)`: `subprocess.run([sys.executable,
  str(CONVERTER), *args], cwd=str(ROOT), capture_output=True, text=True,
  encoding="utf-8", errors="replace")`. Argumentos en lista siempre.
- `make_sample(path, size, seconds, audio_kbps, audio_codec="aac")`:
  muestra sintética vía lavfi — video `testsrc2=size=…:rate=30:duration=…` +
  audio `sine=frequency=440:duration=…`, `-c:v libx264 -crf 18 -preset
  veryfast -c:a <codec> -b:a Nk -shortest`. Un nombre de archivo lleva
  espacios a propósito ("sample test.mp4") para demostrar el manejo
  Windows-safe de argumentos.
- `ffprobe_json(path)` verifica las salidas reales; `video_stream`,
  `audio_count` como helpers de aserción; `fail_detail(proc)` arma un bloque
  compacto `rc + stdout[-1200:] + stderr[-600:]` para los mensajes.
- Cobertura típica: conversión feliz con espacios, no-upscale, vertical,
  rama de audio no copiable (regresión), `--dry-run` (plan impreso y SIN
  archivo de salida, menciona encoder default y valores), skip/--force
  (compara `st_mtime_ns` para probar "no re-trabajo"), y unit tests.
- Unit tests en subproceso: constante `UNIT_SRC` con un script que
  `import convert` (el módulo REAL) y corre `assert`s puros (matemática de
  políticas, armado del comando, orden de argumentos); se ejecuta con
  `sys.executable -c UNIT_SRC` y cuenta como UNA verificación de suite cuyo
  `detail` incrusta stdout/stderr del subproceso. Un assert fallido corta con
  traceback y rc≠0.
- Cierre: `print(f"\nRESULT: {passed} passed, {failed} failed")`;
  `return 0 if failed == 0 else 1`. (Converter: 33 verificaciones.)
- **Diferencia para subtitler:** el converter no necesita gates (todo local y
  rápido). El subtitler SÍ necesita gate para transcripción real (descarga de
  modelos): plan prevé opt-in por variable de entorno. El nombre/gate exacto
  lo define el diseño (p. ej. solo import de módulos pesados y tests unitarios
  de SRT/selector/ruteo en la corrida default; transcripción real + Argos real
  solo con la env var). Mantener la regla: la suite default NO descarga modelos.

## 3. Archivos de soporte del converter (a adaptar)

- **README.md** (~210 líneas, español). Secciones en orden: título + link de
  repo + párrafo de una línea → `## Requisitos` (Python, ffmpeg/ffprobe en
  PATH, nota Windows-safe) → `## Uso` (bloque `text` de sintaxis + ejemplos
  `bash` comentados) → `### Opciones` (tabla `Opción | Predeterminado |
  Descripción`, marcando registradas-no-soportadas) → sección de A/B
  (opcional) → `### Selector interactivo` (sintaxis `1 3 5-7`, `a`, `q`;
  crea carpeta si falta) → `## Cómo funciona` (pipeline numerado + `###
  Códigos de salida`) → `## Pruebas` (comando + qué cubre, nº de
  verificaciones) → `## Historial de cambios` (fecha + bullets) →
  `## Limitaciones conocidas` → `## Hoja de ruta` (registrado vs soportado).
  PLAN pide además "modelos y tiempos" → insertar entre Cómo funciona y
  Limitaciones.
- **requirements.txt**: en el converter es SOLO un comentario español ("Sin
  dependencias externas…"). Para subtitler: mantener el estilo de comentario
  cabecera en español y añadir pines exactos de PLAN: `faster-whisper==1.2.1`
  y `argostranslate==1.11.0` (comentario breve de para qué es cada uno).
- **.gitignore** del converter: cabecera `# Local Pi runtime state` +
  `.atl/ .venv/ input/ __pycache__/ tests_tmp/ .ruff_cache/`. El repo
  subtitler YA tiene `.gitignore` con solo `.atl/` → adaptar = añadir el
  resto (`.venv/`, `input/`, `__pycache__/`, `tests_tmp/`, `.ruff_cache/`).

## 4. Entorno (verificado en esta sesión, con método)

| Hecho | Estado | Método / evidencia |
| --- | --- | --- |
| ffmpeg/ffprobe vía scoop | ✅ en disco | `C:/Users/USER/scoop/apps/ffmpeg/8.1.2/bin/{ffmpeg,ffprobe,ffplay}.exe` + shims `C:/Users/USER/scoop/shims/{ffmpeg,ffprobe}.exe`. ffmpeg **8.1.2**. El converter funciona con esta instalación (README: "ffmpeg 8.x"). |
| ffmpeg/ffprobe en PATH | ✅ alta confianza | Los shims de scoop son el mecanismo PATH de scoop; verificación de resolución real no ejecutable en esta sesión (sin shell). `shutil.which` en runtime lo confirmará. |
| Python 3.11 disponible | ✅ **3.11.6** | `C:/Users/USER/AppData/Local/Programs/Python/Python311/python.exe`; `include/patchlevel.h` → `PY_VERSION "3.11.6"`. NO viene de scoop (sin python en scoop/apps ni shims). |
| ⚠ PLAN.md dice "Python 3.11.15" | discrepancia | El intérprete en disco es **3.11.6**. No reabrir el plan (la decisión cerrada es "Python 3.11"); el diseño/tareas deben registrar la versión real y crear el venv con este intérprete (`python -m venv .venv`). Para esta app es funcionalmente equivalente. |
| `.venv` ausente en el repo | ✅ | Listado raíz: solo `.git/`, `.gitignore`, `.pi/`, `PLAN.md`, `openspec/`. Tampoco existen `input/`, `subtitler.py`, `test_smoke.py` ni `README.md`. El `test_command` de config.yaml es la forma declarada "para cuando exista". |
| Git | ✅ | Remote `origin` verificado en `.git/config`: `https://github.com/joriza/py-video-subtitler.git` (branch `main` según PLAN). |
| SDD preflight | ✅ | `.pi/gentle-ai/sdd-preflight.json`: auto / openspec / ask-on-risk / 400 líneas / engram disponible. |
| lavfi disponible para muestras | ✅ heredado | ffmpeg 8.1.2 full build scoop incluye `lavfi` (testsrc2, sine ya usados por el converter). Encoder PGS (`hdmv_pgs_subtitle`) para tests de bitmap: probable en 8.x, verificar en apply con `ffmpeg -encoders`. |

## 5. Hechos de integración (API, de conocimiento de paquete — sin instalar nada)

### faster-whisper 1.2.1

- Entrada: `from faster_whisper import WhisperModel`;
  `WhisperModel("small", device="cpu", compute_type="int8")` (PLAN). Tamaños
  por nombre admitidos: tiny, base, small, medium, large-v3 (coincide con el
  registro previsto). Primera corrida descarga de Hugging Face a
  `~/.cache/huggingface` y cachea (offline después).
- `segments, info = model.transcribe(ruta_o_array, language=None|código,
  vad_filter=True, beam_size=5, vad_parameters={...})`.
  - `language=None` → autodetección; `info.language` e
    `info.language_probability` disponibles (usar para rutear es vs no-es).
  - `vad_filter=True` usa Silero VAD incluido (onnxruntime); recorta silencios.
  - `segments` es generador PEREZOSO de `Segment(start, end, text, …)`;
    `text` trae espacio inicial por convención → `strip()` antes de escribir.
  - `info.duration` (segundos float) sirve para el progreso:
    `pct = segment.end / info.duration`.
- Decodifica audio internamente con PyAV (FFmpeg embebido) → la transcripción
  no depende del ffmpeg CLI; ffprobe/ffmpeg CLI siguen siendo nuestros para
  sondeo y extracción de pistas.
- Deps: ctranslate2 (inferencia int8), tokenizers, huggingface-hub,
  onnxruntime, av. Confianza: alta (API estable documentada); verificación
  final de firmas en apply es barata (una vez creado el venv).

### argostranslate 1.11.0

- `from argostranslate import package, translate`.
- `package.get_installed_packages()` → lista de `Package` con `.from_code` /
  `.to_code` → construir el conjunto de pares instalados para el ruteo
  (directo → pivote vía inglés → WARN).
- `translate.get_translation_from(from_code, to_code)` → `Translation`
  (lanza `PackageNotFoundError` si no hay camino; las traducciones con pivote
  vienen encadenadas). `translation.translate(texto) -> str`; existe también
  la conveniencia `translate.translate(texto, de, a)`. El nombre exacto del
  getter (`get_translation_from` vs `get_translation` histórico) confirmarlo
  en apply con `dir(translate)` — el ruteo no depende del nombre.
- Offline SOLO tras instalar paquetes; la instalación puntual requiere red:
  `package.update_package_index()` → `get_available_packages()` →
  `pkg.download()` → `package.install_from_path(...)`. Coincide con "primera
  corrida descarga" de PLAN.
- ⚠ Peso de deps: argostranslate arrastra sentencepiece/sacremoses/stanza
  (históricamente stanza → PyTorch CPU). El "sin PyTorch" de PLAN aplica al
  motor Whisper; el tamaño del venv/tiempo de primer `pip install` estará
  dominado por Argos. Verificar en la creación del venv; NO reabre el plan.
- Directorio de paquetes instalados: por usuario, estilo appdirs
  (`~/.local/cache/argos-translate/…` en Windows según su módulo settings);
  la ruta exacta se consulta en apply vía `argostranslate.settings`.

### Formato SRT (spec estable)

- Bloque: `N\nHH:MM:SS,mmm --> HH:MM:SS,mmm\ntexto\n\n` — separador decimal
  COMA (no punto), numeración 1..n, línea en blanco entre bloques.
- Convenciones de PLAN a respetar: UTF-8 con BOM + CRLF, ajuste de línea a
  ~42 caracteres (máx 2 líneas), escritura a temp + rename atómico
  (`os.replace`) junto al video con el mismo stem.

## 6. Implicaciones para las fases siguientes (síntesis)

- El esqueleto a espejar es directo: registros con `implemented` + validación
  posterior (`MODELS`, `--target`), `SubtituloOptions`/`SubtituloResult`
  frozen/dataclass, `convert_one` → `subtitular_one` sin lanzar, selector y
  dedup casi verbatim, línea de progreso reutilizable, `summarize`, códigos
  0/1 (+130 Ctrl-C), `ensure_tools` (ffmpeg+ffprobe).
- Costuras puras para unit tests (como la "matemática de políticas" del
  converter): `parse_selection`, formateo de timestamps SRT, wrap ~42,
  ruteo de traducción (directo/pivote/none) sobre un conjunto de pares falso,
  decisión de extracción (es / no-es / bitmap) sobre datos de sondeo falsos.
- Suite default sin red y sin descargas: lavfi para audio+video, `mov_text`/
  `srt` para pistas embebidas de texto; rama bitmap vía datos falsos (o PGS
  real si `hdmv_pgs_subtitle` existe en 8.1.2); transcripción real tras env
  var opt-in.

## 7. Riesgos / puntos abiertos

1. **Versión de Python**: 3.11.6 real vs 3.11.15 en PLAN — registrar la real
   en diseño/README; no bloquea.
2. **Peso de argostranslate** (posible torch transitivo): afecta tiempo de
   instalación y tamaño, no el diseño; verificar al crear el venv.
3. **Gating de smoke**: el nombre de la env var opt-in y qué tests corren sin
   ella lo fija el diseño (PLAN: "transcripción real opt-in").
4. **PGS sintético en tests**: verificar `ffmpeg -encoders | findstr pgs` en
   apply; si no existe, cubrir bitmap con datos de sondeo falsos.
5. **PATH de herramientas**: verificado por filesystem; la primera ejecución
   de `shutil.which` (ya prevista en el código espejo) es la confirmación
   runtime.
6. **Idioma del `--help`**: convert.py usa help en inglés; el espejo debe
   decidir (sugerencia de coherencia: español).
