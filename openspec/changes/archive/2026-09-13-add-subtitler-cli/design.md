# Diseño — add-subtitler-cli

- **Cambio:** `add-subtitler-cli` · **Fase:** design · **Fecha:** 2026-09-13 · **Almacén:** openspec
- **Fuentes:** `proposal.md` (PRD confirmado), `specs/subtitle-generation/spec.md` (12 requisitos / 31 escenarios), `explore.md` (espejo convert.py, costuras §6, diferidos §7), `openspec/config.yaml` (`rules.design`).
- **Regla rectora:** decisiones con justificación breve, explícitamente **sin sobre-ingeniería**; single-file con registros al tope (estilo `convert.py`). Este diseño define el CÓMO; el QUÉ está cerrado en spec/PLAN.

---

## 1. Contexto y forma general

**D1 — Single-file `subtitler.py`, espejo estructural de `convert.py`.**
Justificación: la app es personal y el repo hermano ya validó el patrón (constantes en caja de comentarios, registros `@dataclass(frozen=True)`, pipeline por archivo que nunca aborta, selector interactivo, suite de humo stdlib). Espejar reduce riesgo y costo de revisión; inventar estructura nueva no aporta nada.

**D2 — Sin capa de abstracción sobre Whisper/Argos/ffmpeg.**
Justificación: cada motor se usa en un solo lugar (transcripción, traducción, extracción) tras una costura pura que decide *qué* hacer; envolverlos en interfaces sería sobre-ingeniería para una app de un usuario.

**D3 — Imports pesados perezosos (lazy).**
`faster_whisper` y `argostranslate` se importan **dentro** de las funciones que los usan, nunca a nivel de módulo.
Justificación: `subtitler.py` queda importable (unit tests del smoke, `--dry-run`, extracción embebida) sin cargar modelos ni depender de que los paquetes estén siquiera instalados; la suite default no toca red por construcción.

---

## 2. Estructura de `subtitler.py`

### 2.1 Mapa de secciones (orden del archivo, espejo del converter)

```text
Docstring de módulo (español: título, párrafo, "Puntos de diseño:", "Requiere solo…")
# ----- Constantes y registros -----
# ----- Tipos de datos -----
# ----- Auxiliares de formateo SRT (costuras puras) -----
# ----- Ruteo de traducción (costura pura + adaptador Argos) -----
# ----- Sondeo de medios (ffprobe) -----
# ----- Extracción de pista embebida (ffmpeg) -----
# ----- Transcripción (faster-whisper, lazy) -----
# ----- Renderizado de progreso -----
# ----- Pipeline por archivo -----
# ----- Resolución de entradas y selector interactivo -----
# ----- CLI -----
```

### 2.2 Registros y constantes al tope

**D4 — `MODELS: dict[str, ModelSpec]`** con `tiny`, `base`, `small`, `medium`, `large-v3`; `DEFAULT_MODEL = "small"`.

```python
@dataclass(frozen=True)
class ModelSpec:
    device: str = "cpu"        # GPU AMD sin CUDA → CPU only (PLAN cerrado)
    compute_type: str = "int8" # ~4x vs Whisper original en CPU (PLAN cerrado)
    implemented: bool = True   # los 5 están implementados hoy
```

Justificación: hoy los 5 comparten defaults de compute, pero el registro permite overrides por modelo futuro (p. ej. `large-v3` con otro `compute_type`) sin tocar la superficie CLI. `argparse` toma `choices=tuple(MODELS)`.

**D5 — Registros de idiomas.**

```python
@dataclass(frozen=True)
class LangSpec:
    implemented: bool = False

SOURCE_LANGS = {  # --lang: solo se pasan a Whisper / al ruteo; "auto" = autodetección
    "auto": LangSpec(True), "es": LangSpec(True), "en": LangSpec(True),
    "de": LangSpec(True), "fr": LangSpec(True), "it": LangSpec(True),
    "pt": LangSpec(True), "ru": LangSpec(True), "ja": LangSpec(True), "zh": LangSpec(True),
}
TARGET_LANGS = {"es": LangSpec(True)}  # --target: registro extensible, hoy solo "es"
DEFAULT_TARGET = "es"
```

Justificación: `--target` es registro-con-`implemented` porque el spec exige rechazar valores registrados-no-implementados con error que liste los implementados (escenario «opción registrada no implementada»); `--lang` usa el mismo mecanismo con una lista curada (códigos passthrough; lista corta evita basura por typo, se amplifica gratis en el futuro). `validate_registry_choices(parser, args)` (espejo verbatim del converter) hace `parser.error(...)` listando los implementados.

**D6 — Constantes de timeouts y política** (bloque en caja `# ----- #`, espejo):

| Constante | Valor | Porqué (breve) |
| --- | --- | --- |
| `FFPROBE_TIMEOUT_S` | `30` | espejo converter; sondeo es instantáneo |
| `FFMPEG_EXTRACT_TIMEOUT_S` | `300` | extracción de texto es rápida; margen para contenedores grandes |
| `SRT_LINE_MAX_CHARS` | `42` | política cerrada de spec/PLAN |
| `SRT_MAX_LINES_PER_CUE` | `2` | ídem |
| `SRT_ENCODING` | `"utf-8-sig"` | emite BOM UTF-8 al escribir |
| `PROGRESS_BAR_WIDTH` | `24` | espejo de la línea de progreso |
| `PROGRESS_MIN_INTERVAL_S` | `0.1` | evita parpadeo/redibujado en ráfaga |
| `STDERR_TAIL_CHARS` | `300` | detalle de error recortado, espejo |
| `WHISPER_BEAM_SIZE` | `5` | default razonable de faster-whisper |
| `TEXT_SUBTITLE_CODECS` | `{"subrip","srt","mov_text","ass","ssa","webvtt","text"}` | allowlist: codec desconocido cae a bitmap → transcribe (fallback robusto, nunca rompe) |
| `VIDEO_EXTENSIONS` | `{mp4, mkv, mov, avi, webm, m4v, mpg, mpeg, ts, wmv, flv}` | espejo del `set` sin punto |

### 2.3 Tipos de datos (espejo del converter)

- `class MediaError(RuntimeError)` — error de sondeo por archivo (nombre espejo).
- `@dataclass SubtitleStream` — `index, codec_name, is_text, language: str | None, disposition_default: bool`.
- `@dataclass ProbeInfo` — `path, duration_s: float, has_audio: bool, subtitle_streams: list[SubtitleStream]`.
- `@dataclass Cue` — `start_s: float, end_s: float, text: str` (texto sin envolver, una «frase»).
- `@dataclass(frozen=True) SubtitlerOptions` — opciones CLI validadas (`model, lang, target, no_extract, force, dry_run, input_dir`).
- `@dataclass FileResult` — `status: "ok"|"failed"|"skipped"`, `detail`, `out_path`, `elapsed_s`, `cues`, `route` (espejo directo de `FileResult`).
- `@dataclass(frozen=True) TranslationRoute` — `kind: "direct"|"pivot"|"none"`, `hops: tuple[tuple[str, str], ...]`.
- `@dataclass(frozen=True) ExtractionDecision` — `kind: "extract" | "extract_translate" | "transcribe_no_track" | "transcribe_bitmap" | "transcribe_forced"`, `stream_index: int | None`, `language: str | None`.

---

## 3. Costuras de funciones puras (testeables sin modelos ni red)

Todas viven en secciones puras del módulo, sin I/O; los adaptadores impuros (ffprobe/ffmpeg/Argos/Whisper) solo traducen mundo real ↔ estos tipos.

**C1 — `parse_selection(text: str, count: int) -> list[int] | None`** (espejo verbatim del converter): separa por `[,\s]+`, rangos `N-M` inclusivos (normaliza inversión), 1-based → 0-based, inválido/fuera de rango → `None`. `a`/`q` se manejan en el bucle interactivo, no aquí (igual que el espejo).

**C2 — `format_srt_timestamp(seconds: float) -> str`** → `HH:MM:SS,mmm` con **coma** decimal; clampa negativos a 0; redondeo a ms.

**C3 — `wrap_text(text: str, max_chars=SRT_LINE_MAX_CHARS) -> list[str]`** — greedy por palabras; nunca corta una palabra.

**C4 — `split_cue(cue: Cue) -> list[Cue]`** — aplica `wrap_text`; si excede `SRT_MAX_LINES_PER_CUE` líneas, divide en cues contiguos repartiendo el intervalo `[start, end]` **proporcionalmente al conteo de caracteres** de cada bloque; garantiza `end > start` (gap mínimo 1 ms).
Justificación del reparto proporcional: determinista, puro y verificable; sincronización fina está fuera de alcance (no-objetivo del PRD).

**C5 — `render_srt(cues: list[Cue]) -> str`** — numeración `1..n`, `format_srt_timestamp`, `\r\n` como único salto, exactamente una línea en blanco entre cues; aplica `split_cue` a cada cue y **afirma** ≤2 líneas/cue (invariante interna). El texto que no cabe NUNCA se pierde: `split_cue` solo reparte.

**C6 — `parse_srt(payload: str) -> list[Cue]`** — parseo tolerante de SRT extraído por ffmpeg: strip de BOM, acepta `\r\n` o `\n`, ignora numeración original, une líneas multi-cue con espacio, elimina tags tipo `<i>…</i>` (regex `<[^>]+>`).
Justificación: el SRT extraído se re-formatea con NUESTRA política (42/2), así toda salida es uniforme pase por transcripción o extracción.

**C7 — `resolve_translation_route(src: str, dst: str, pairs: frozenset[tuple[str, str]]) -> TranslationRoute`** — pura sobre un conjunto de pares instalados: `src == dst` → ruta vacía «directa» (no traducir); `(src, dst) ∈ pairs` → direct; si no `(src, "en")` y `("en", dst)` ∈ pairs → pivot con 2 saltos; si no → `none`. El adaptador Argos construye `pairs` desde `package.get_installed_packages()` (`from_code`/`to_code`).

**C8 — `decide_extraction(info: ProbeInfo, no_extract: bool) -> ExtractionDecision`** — pura sobre datos de sondeo:

1. `no_extract` → `transcribe_forced`.
2. Sin pistas → `transcribe_no_track`.
3. Con `pick_subtitle_track(info.subtitle_streams)` (preferida: *default* marcada; si no, primera de texto): `language in (None, "es", "spa", "und")` → `extract`; otro idioma → `extract_translate`.
4. Solo bitmap (PGS/DVB = codec_type subtitle fuera de la allowlist) → `transcribe_bitmap` (quien llama emite el WARN).

**C9 — `parse_probe_json(payload: str) -> ProbeInfo`** — pura sobre el JSON de ffprobe (streams, duración, has_audio, clasificación texto/bitmap por allowlist); JSON inválido → `MediaError`. Helpers tolerantes `_to_float`/`_safe_int` espejo.

**C10 — `parse_selection` + selector**: `list_videos`, `interactive_select`, `resolve_inputs` (dedup por `expanduser().resolve()` con dict ordenado) — espejo casi verbatim del converter; cambia solo el filtro de extensiones (no hay «sufijo de salida» que excluir; `.srt` no es extensión de video).

---

## 4. Pipeline por archivo

### 4.1 `subtitlar_one(src: Path, options: SubtitlerOptions) -> FileResult` — nunca lanza

Orden interno (espejo de `convert_one`, con las diferencias del subtitler):

1. `say(f"--- {src.name}")`; `probe_media(src)` → `MediaError` (timeout, JSON inválido, rc≠0, sin ffmpeg) ⇒ `FileResult("failed")` con detalle recortado (`STDERR_TAIL_CHARS`). **La corrida sigue.**
2. `has_audio == False` ⇒ `failed` con motivo `"sin audio"` (espejo del escenario del spec).
3. Salida: `src.with_suffix(".srt")` junto al video; si existe y no `--force` ⇒ `FileResult("skipped")` con WARN «.srt ya existe (usa --force)».
4. `--dry-run`: imprime el plan y retorna `ok` (ver §4.3). **No se importa nada pesado ni se escribe nada.**
5. `decide_extraction(...)`:
   - `extract` / `extract_translate`: `ffmpeg -hide_banner -nostats -loglevel error -y -i <video> -map 0:<index> -c:s srt -f srt pipe:1` (lista de argumentos, captura de stdout) → `parse_srt` → cues. Si `extract_translate`: ruta Argos (§4.4).
   - `transcribe_*` (con WARN en el caso bitmap): transcripción §4.2 → cues (+ Argos si el idioma detectado ≠ `es`).
6. `render_srt(cues)` → escritura atómica §4.5.
7. `OK` con métricas (ruta usada, nº de cues, segundos). Cualquier excepción residual del paso 5–6 ⇒ limpiar temporales, `failed` con detalle recortado. **Jamás propaga.**

### 4.2 Transcripción (lazy)

`transcribe_cues(path, spec: ModelSpec, lang: str) -> tuple[list[Cue], str]`:

- Importa `faster_whisper` aquí (D3); `WhisperModel(options.model, device=spec.device, compute_type=spec.compute_type)`. Primera corrida descarga de Hugging Face a caché de usuario (esperado; offline después).
- `model.transcribe(str(path), language=None if lang=="auto" else lang, vad_filter=True, beam_size=WHISPER_BEAM_SIZE)`.
- Itera el generador perezoso: `text.strip()` por convención de espacio inicial; un `Cue(start, end, text)` por segmento; **callback de progreso** por segmento (§4.6). `info.language` determina la ruta de traducción (devuelto al caller).
- La decodificación de audio la hace PyAV interno; ffmpeg CLI sigue siendo requisito para sondeo/extracción (`ensure_tools`).

### 4.3 `--dry-run` (plan por archivo)

Formato exacto de línea de plan (el smoke lo aserte):

```text
  [plan] <nombre> → <ruta elegida> → <salida esperada>
```

con `<ruta elegida>` ∈ `extraer pista #N (spa)` · `extraer pista #N (eng) + traducir` · `transcribir (sin pistas)` · `transcribir (bitmap: extracción imposible)` · `transcribir (--no-extract)`, y salida `SKIP (.srt existe)` cuando corresponde. Sin escrituras, sin descargas, sin imports pesados.

### 4.4 Traducción (adaptador Argos + ruta)

- `installed_argos_pairs() -> frozenset[...]` — lazy import; lee `package.get_installed_packages()`.
- `build_translator(route: TranslationRoute) -> Callable[[str], str]` — directo: `translate.get_translation_from(src, dst)`; pivote: encadena los dos saltos; `none`: identidad (el caller ya emitió WARN y ese archivo **no** cuenta como failed — spec).
- Traducción por cue (strings cortos); barra simple «traduciendo N segmentos…» sin render por unidad (Argos es rápido; sin sobre-ingeniería).

### 4.5 Escritura atómica SRT

`write_srt_atomic(out: Path, body: str)`: escribe TODO el cuerpo a `<out>.tmp` con `encoding="utf-8-sig", newline=""` (BOM + `\r\n` literales sin traducción de la plataforma) y luego `os.replace(tmp, out)`.
Justificación: `os.replace` es atómico en NTFS; un fallo previo al rename deja a lo sumo un `.tmp` que `_remove_quietly` borra — nunca un `.srt` parcial visible.

### 4.6 Progreso en una línea

Reutiliza el renderizador del converter: `\r[####----]  45.0%  speed 1.53x  ETA 03:21`, ancho 24, intervalo mínimo 0.1 s, `say()` final para el salto de línea.
Alimentación: en transcripción, `pct = segment.end / info.duration` al completarse cada segmento; `speed = segment.end / elapsed`; `ETA = elapsed * (1 - pct) / pct`. Extracción y traducción muestran un mensaje estático de una línea (duran segundos).

### 4.7 CLI, arranque y códigos de salida

- `build_parser()`: `prog="subtitler.py"`, `description` española, `ArgumentDefaultsHelpFormatter`; `inputs` `nargs="*"`; `--input-dir` default `input`; `--model` `choices=tuple(MODELS)` default `small`; `--lang` `choices=tuple(SOURCE_LANGS)` default `auto`; `--target` `choices=tuple(TARGET_LANGS)` default `es`; `--no-extract`, `--force`, `--dry-run` como `store_true`.
- `main(argv) -> int`: `configure_utf8_stdio()` (espejo), parse → `validate_registry_choices` → `ensure_tools` (`shutil.which` de ffmpeg Y ffprobe; si falta: mensaje claro y **1** sin procesar) → `resolve_inputs` → bucle `subtitlar_one` → `summarize` → `0` si ningún failed, `1` si alguno.
- Resumen exacto (asertable): `TOTAL: N ok, M failed, K skipped` y, en línea separada, `Tiempo total: HH:MM:SS`.
- Arranque: `sys.exit(main())` con `except KeyboardInterrupt` → mensaje + **130**.
- **Errores de uso** (parseo/validación de registros) salen por `parser.error` ⇒ exit code **2** (convención argparse, espejo del converter). El contrato 0/1/130 del spec aplica a corridas aceptadas; documentado en README.

---

## 5. Decisiones diferidas de explore §7 (resueltas)

**D7 — Idioma del `--help`: ESPAÑOL** (docstrings y comentarios ya eran español por estilo del repo).
Justificación contra el espejo: convert.py usa `help=` en inglés como accidente histórico, no como convención de carga; el PRD/spec fijan español como idioma del proyecto (README, docstrings, selector, mensajes) y el usuario único es hispanohablante — un `--help` bilingüe suma fricción sin beneficio. Coste: cero (mismas cadenas, otro idioma).

**D8 — Env var opt-in del smoke: `SUBTITLER_SMOKE_REAL`, semántica estricta "1".**
Solo la lee `test_smoke.py`; `subtitler.py` jamás la consulta.

- **Sin la var (o valor ≠ "1")**: suite default — sin modelos, sin red, sin descargas. Los checks con modelos se reportan como `SKIP (opt-in: SUBTITLER_SMOKE_REAL=1)` y NO cuentan como fallo.
- **Con `SUBTITLER_SMOKE_REAL=1`**: tras la suite default, corre la sección "real": (a) e2e habla→transcribe→traduce→SRT y (b) extracción de pista `en` + traducción Argos (§6). Usa `--model tiny` (descarga ~75 MB vs ~460 MB; el plumbing de modelos es idéntico entre tamaños). Primer opt-in puede descargar el paquete Argos `en→es` (red one-time, luego caché).
- Fallos de la sección real SÍ cuentan en el `RESULT` final (rc 1).
Justificación del nombre: prefijo `SUBTITLER_` ancla al proyecto y evita colisiones; sufijo `_REAL` dice qué gatea; valor "1" es el booleano más simple posible.

---

## 6. Estrategia de pruebas

### 6.1 Forma de `test_smoke.py` (espejo del converter, stdlib only)

- Docstring español con el comando: `.venv/Scripts/python.exe test_smoke.py` (y la forma opt-in).
- Contadores `passed`/`failed`; `check(name, condition, detail="")` → `[PASS]`/`[FAIL] nombre -- detalle`; cierre `RESULT: N passed, M failed`, rc 0/1.
- `TMP = ROOT / "tests_tmp"`; `main()` con `rmtree(ignore_errors=True)` + `mkdir` y `try/finally: rmtree` idempotente.
- `run_subtitler(args, timeout, input_text=None, env=None)`: `[sys.executable, str(SUBTITLER), *args]` en lista, `capture_output=True, text=True, encoding="utf-8", errors="replace"`, `cwd=ROOT`; stdin parcheado para el selector; env parcheable para el test de ffprobe ausente.
- Fábricas lavfi (ffmpeg CLI, sin modelos):
  - `make_video(path, seconds=1, with_audio=True)`: `testsrc2=size=128x96:rate=15:duration=…` + `sine=frequency=440`, `libx264` + `aac`. Un nombre lleva espacios («sample test.mp4») para la ruta Windows-safe.
  - `make_embedded(path, cues_text, lang)`: genera un `.srt` fuente y lo muxea con `-c:s mov_text -metadata:s:s:0 language=<spa|eng>` (y `-disposition:s:0 default` para el caso pista preferida).
- Unit tests en subproceso (`UNIT_SRC`): script que `import subtitler` REAL y corre asserts puros (C1–C9); se ejecuta como UNA verificación cuyo `detail` incrusta stdout/stderr. Patrón espejo verbatim.
- Envío de Ctrl-C real por consola es flaky en Windows (señales a hijos) → **no** se simula por señal; se prueba el handler por unit (§6.2 S28).

### 6.2 Mapa escenarios del spec → checks del smoke

**Suite default (sin modelos, sin red):**

| # | Escenario del spec | Check |
| --- | --- | --- |
| S1 | video sin audio | mezcla: video sin audio + video con pista `spa` + video con `.srt` existente → `TOTAL: 1 ok, 1 failed, 1 skipped` exacto + rc 1 + el ok procesado |
| S2 | sondeo falla | archivo de bytes basura `.mp4` → failed con detalle recortado, la corrida sigue |
| S3 | rutas con espacios | «sample test.mp4» en todos los checks con muestras |
| S5 | pista embebida `es` | mux `mov_text` + `language=spa` → `.srt` extraído en segundos, sin transcribir |
| S7 | solo bitmap | unit: `decide_extraction` sobre `ProbeInfo` falso con PGS → `transcribe_bitmap`; PGS real queda condicional a apply (§6.3) |
| S8 | `--no-extract` fuerza transcripción | muestra con pista `eng` + `--no-extract` + `--dry-run` → plan dice «transcribir (--no-extract)»; e2e con modelos en la sección real |
| S9 | pista preferida | unit: `pick_subtitle_track` con default marcada vs primera de texto (probe JSON falso) |
| S14 | par directo | unit: `resolve_translation_route("en","es", {(en,es),(de,en)})` → direct |
| S15 | pivote vía inglés | unit: pares `{(de,en),(en,es)}`, src `de` → pivot 2 saltos |
| S16 | sin camino | unit: src sin par → `none`; + diseño: ruta none = identidad + WARN, archivo ok |
| S17 | verificación de formato | bytes del `.srt` extraído: BOM `EF BB BF`, solo `\r\n`, numeración 1..n, `HH:MM:SS,mmm --> HH:MM:SS,mmm`, exactamente una línea en blanco entre cues |
| S18 | ajuste de línea | unit: texto de ~150 chars → `split_cue`/`render_srt`: líneas ≤42, ≤2 por cue, varios cues, reconstrucción palabra a palabra sin pérdida |
| S19 | salida junto al video | S5 aserte `video.srt` junto al fuente con stem igual |
| S20 | fallo a mitad | tras corrida con failed (S2/S1): no queda `.srt` ni `.srt.tmp` de los fallados |
| S21 | `.srt` existente sin `--force` | crear `.srt` manual → SKIP + WARN + `st_mtime_ns` intacto |
| S22 | `--force` regenera | ídem + `--force` → contenido/mtime cambian |
| S23 | plan sin procesar | `--dry-run` sobre transcribible → plan impreso, cero `.srt` creados, cero descargas |
| S24 | dry-run con existente | `.srt` existente + `--dry-run` → plan reporta `SKIP (.srt existe)` |
| S25 | corrida con mezcla | = S1 (aserción exacta del TOTAL + rc 1) |
| S26 | corrida sin fallos | solo extracciones ok/skips → rc 0 |
| S27 | Ctrl-C → 130 | unit en subproceso: parchear `subtitler.subtitlar_one` para lanzar `KeyboardInterrupt` → `main([...])` retorna 130 |
| S28 | selección por rangos | selector con 7 muestras `spa` embebidas, stdin `1 3 5-7\n` → exactamente 5 `.srt`; entrada inválida (`99 x`) re-pregunta (stdin `99 x\nq\n` → no procesa, rc 0) |
| S29 | todos y salir | stdin `a\n` → todos; stdin `q\n` → cero salidas, rc 0 |
| S30 | carpeta inexistente | `--input-dir <nueva>` + `q` → carpeta creada + guía impresa, rc 0 |
| S31 | opción registrada no implementada | `--target en` → rc 2 con stderr listando `es` |
| S32 | modelo no default | `--model medium --dry-run` → plan menciona `medium` |
| S33 | ffprobe ausente | env con PATH mínimo (solo dir vacío) → rc 1 + mensaje claro + sin procesar |

**Sección real opt-in (`SUBTITLER_SMOKE_REAL=1`; con modelos descargables y red one-time):**

| Escenario | Check |
| --- | --- |
| S6 pista embebida `en` | mux `eng` + correr → extracción + Argos `en→es` → SRT válido no vacío en español |
| S11 transcripción de inglés | voz sintética en inglés (SAPI de Windows: `System.Speech` → WAV «hello world, this is a test») muxeada a mp4 → `subtitler --model tiny` → SRT válido con ≥1 cue y texto no vacío |
| S10 transcripción de español | cubierto a nivel unit (ruteo es→directo por `info.language`); e2e condicional a voz TTS española instalada (§6.3) |
| S12 progreso en una línea | dentro del check S11: stdout contiene `ETA` y el render con `\r` no genera una línea por segmento (recuento de líneas acotado) |

### 6.3 Cobertura y residuales declarados

- **Cubierto por diseño + default suite:** 29 de 31 escenarios (los de arriba), incluida toda la superficie CLI, formato, skip/force/dry-run, exit codes, selector, sondeo y costuras puras de ruteo/extracción/wrap.
- **Cubierto solo en opt-in:** e2e con modelos reales (transcripción, Argos, progreso real).
- **Residuales aceptados (app personal, sin sobre-ingeniería):**
  - PGS sintético real: verificar `ffmpeg -encoders | findstr pgs` en apply; si existe y es barato, añadir muestra bitmap al default; si no, el unit de `decide_extraction` basta.
  - TTS española para S10 e2e: solo si hay voz instalada; el ruteo `es` está cubierto por unit.
  - «Sin camino» e2e (S16) requiere un entorno Argos sin pares: cubierto por unit + contrato identidad+WARN.
  - Ctrl-C por consola física: cubierto vía unit del handler (S27); no se simula señal real.
  - Calidad de la traducción Argos: fuera de alcance (riesgo aceptado en proposal).

---

## 7. Dependencias y entorno

**D9 — `requirements.txt`** (nuevo), estilo del converter con cabecera de comentario en español:

```text
# Dependencias de py-video-subtitler (pines exactos; decisiones cerradas en PLAN.md).
# Motor de transcripción local (CPU, int8; decodifica audio con PyAV interno).
faster-whisper==1.2.1
# Traducción local offline (par directo o pivote vía inglés).
argostranslate==1.11.0
```

**D10 — venv:** `python -m venv .venv` con el Python de PATH (3.11.x; corrección de gate de la propuesta: 3.11.15 shim de uv) → `.venv/Scripts/python.exe -m pip install -r requirements.txt`. La versión real usada se registra en README al crearlo.
Nota aceptada (PLAN): argostranslate puede arrastrar deps pesadas (sentencepiece/stanza → torch transitivo); el «sin PyTorch» de PLAN aplica al motor Whisper. Verificar tamaño/tiempo al instalar; no reabre el plan.

**D11 — `.gitignore`** (modificado; conserva `.atl/`):

```text
# Local Pi runtime state
.atl/
# Entorno virtual y residuos locales
.venv/
input/
__pycache__/
tests_tmp/
.ruff_cache/
```

**D12 — Runtime local:** `input/` y `tests_tmp/` se crean al vuelo (selector/suite) y están gitignorados. Cachés externas one-time: modelos Whisper en `~/.cache/huggingface`, paquetes Argos en el dir de usuario de argostranslate.

---

## 8. Riesgos de diseño aceptados

| Riesgo | Mitigación en el diseño |
| --- | --- |
| `mov_text`/`subrip` puede emitir tags (`<i>`) al convertir a srt | `parse_srt` los elimina (C6) y re-envuelve con política propia |
| Segmentos Whisper con espacio inicial o `end <= start` | `strip()` en transcripción; gap mínimo 1 ms en `split_cue` |
| Texto largo que desborda 2×42 | `split_cue` reparte en cues contiguos; invariante «sin pérdida» afirmada en `render_srt` y testeada en unit |
| Ruta Argos inexistente para idioma raro | `resolve_translation_route` → `none` → WARN + identidad; archivo ok (spec) |
| Env var mal seteada ejecuta modelos sin querer | semántica estricta "1"; skips visibles con hint del opt-in |
| Exit code 2 en errores de uso confunde el contrato 0/1 | documentado en diseño (§4.7) y README; el spec aplica 0/1/130 a corridas aceptadas |

---

## 9. Handoff a `tasks`

El plan de tareas debe producir, en fases TDD (config: `tdd: true`, RED-GREEN-REFACTOR vía `test_smoke.py`):

1. Soporte: `requirements.txt`, `.gitignore`, venv + verificación de imports.
2. `subtitler.py` por costuras puras primero (C1–C10) con sus unit tests.
3. Sondeo + extracción + escritura atómica + pipeline/skip/force/dry-run + CLI/exit codes (checks default).
4. Selector interactivo + verificación de herramientas (checks default).
5. Transcripción + traducción + progreso (sección real opt-in) + README en español.
6. Verificación final: `.venv/Scripts/python.exe test_smoke.py` verde sin red; opt-in documentado.

---

## 10. Enmienda (post-apply, decisión del dueño de producto 2026-09-13): descarga Argos en demanda + doble salida

**D13 — Descarga en demanda de pares Argos: one-time, directo primero, fallback amable.**
Costura pura `download_candidates(src, dst) -> (directo, (src, en), (en, dst))` sin duplicados ni pares `(x, x)` (para `en→es` queda solo el directo: el origen ya es el pivote). `ensure_pairs_installed(pairs_needed)` (lazy import, D3): si los candidatos ya arman una ruta (directo instalado o las DOS patas), retorna True sin tocar índice ni red (one-time); si no, `update_package_index()` UNA vez, descarga en orden los pares que el índice ofrezca (`install_from_path(p.download())`, INFO por descarga) cortando en cuanto la ruta queda armada, y re-verifica; cualquier excepción (sin red, índice roto, instalación fallida, par desconocido) → `False` sin propagar. `apply_translation` retorna ahora `TranslationOutcome(original, original_lang, translated)` (`translated=None` si no hubo camino incluso tras la descarga) y re-resuelve la ruta tras instalar.
Justificación: el dueño pidió traducir aunque los pares no estén instalados, sin comprometer la robustez por archivo (jamás aborta, WARN + original) ni la suite sin red (mock total vía argostranslate falso / aislamiento). Detalle aceptado de argostranslate 1.11: `update_package_index` traga errores y `get_available_packages` recursiona sin índice local → `RecursionError`; el `except` del contrato lo captura (fallback WARN) y el spam de logs de argos queda en stderr del subproceso.

**D14 — Doble salida: `<stem>-<lang>.srt` + `<stem>.srt` (guion + código corto 639-1).**
Cuando se intentó traducir (origen ≠ destino), el original se conserva como `<stem>-<lang>.srt` (`-orig` si el idioma es desconocido) con la MISMA escritura atómica (BOM + CRLF, `write_srt_atomic`), y el principal `<stem>.srt` lleva la traducción para que el reproductor lo cargue por defecto. Si la traducción falla, SOLO se escribe la sufijada (orden: sufijada primero). Cuando el origen es español, salida única. SKIP/--force siguen llaveados al principal; con `--force` se regeneran ambas. Costura del pipeline: `_cues_for` retorna `ProducedSubtitles(original, final, lang, attempted)` y `subtitlar_one` escribe ambas con limpieza de cualquier salida parcial ante fallo.
Justificación: preserva la extracción/transcripción cuando Argos no llega (no re-procesar para recuperar el original) y mantiene el contrato `video.srt`-por-defecto del PRD; guion (no punto) para no confundir el sufijo de idioma con una extensión.

Cobertura de la enmienda: units A1–A3 (mock total, sin red) + e2e con argostranslate falso (`run_with_fake_argos`) + 5.4 e2e offline real con aislamiento; escenario spec 31 → 37 (mismos 12 requisitos, enmendados R4 y Escritura).
