# Apply Progress — add-subtitler-cli

- **Cambio:** `add-subtitler-cli` · **Fase:** apply · **Fecha:** 2026-09-13 · **Almacén:** openspec
- **Estado:** IMPLEMENTACIÓN COMPLETA — 25/25 tareas de implementación `[x]` (las 2 filas restantes son acciones del orquestador, `sdd-owner: parent`).
- **Modo:** TDD estricto (config `tdd: true`); RED → GREEN → TRIANGULATE → REFACTOR por `.venv/Scripts/python.exe test_smoke.py`.
- **Intento acotado:** token `sha256:f9187c714dd34f35c9f409709210c6869dc73f86b7638a1b716c1c03c2583380` reutilizado (resume tras cancelación a mitad de install).

## Resultado final de verificación (6.2)

- `.venv/Scripts/python.exe test_smoke.py` → `RESULT: 74 passed, 0 failed`, **rc 0**, sin red ni modelos.
- `.venv/Scripts/python.exe -m py_compile subtitler.py` → ok.
- `git status --porcelain` → solo archivos del cambio (`.gitignore`, `.pi/`, `PLAN.md`, `README.md`, `openspec/`, `requirements.txt`, `subtitler.py`, `test_smoke.py`); residuos locales gitignoreados.
- Corrida opt-in `SUBTITLER_SMOKE_REAL=1`: **NO ejecutada** durante apply (consigna del orquestador: no setearla); la maquinaria del gate y los checks reales S11/S12/S6 están escritos y el contrato verificado con `SUBTITLER_SMOKE_REAL=0` (triángulo, idéntico a unset).

## Tareas completadas (checkbox persistido en tasks.md)

| Tarea | Resumen | Evidencia de test |
| --- | --- | --- |
| 1.1 | `requirements.txt` (existente, verificado) + venv Python 3.11.15 + `pip install -r requirements.txt` (150 s, venv 1.2 GB; transitivos torch/spacy/stanza = nota D10 aceptada) | `.venv/Scripts/python.exe -c "import faster_whisper, argostranslate"` ok |
| 1.2 | `.gitignore` + `.venv/ input/ __pycache__/ tests_tmp/ .ruff_cache/` (conserva `.atl/`) | `git check-ignore -v` rc 0; `git status --porcelain` sin residuos |
| 2.1 | Harness del smoke (check/run_subtitler/UNIT/run_unit/TMP try-finally) | `RESULT: 0 passed, 0 failed` rc 0 |
| 2.2 | C1 `parse_selection` | RED: `No module named 'subtitler'` → GREEN+TRI (`2-2`, `a`, `q`) |
| 2.3 | C2 `format_srt_timestamp` + C3 `wrap_text` | RED: AttributeError → GREEN; frontera 42 y palabra>línea |
| 2.4 | C4 `split_cue` + C5 `render_srt` | RED: ImportError `Cue` → GREEN; proporcional 65/86, gap 1 ms, sin pérdida 150 chars; 2 correcciones del propio unit (matemática esperada 97→86; texto por palabras, no corridas de 'a') |
| 2.5 | C6 `parse_srt` | RED: AttributeError → GREEN; BOM, \r\n/\n, tags, multi-línea, vacío |
| 2.6 | C7 `resolve_translation_route` (+`TranslationRoute`) | RED: ImportError → GREEN; directo/pivote/none, dst≠es, pairs vacío |
| 2.7 | C8 `decide_extraction` + `pick_subtitle_track` | RED: ImportError → GREEN; 5 decisiones; default no-primera; solo bitmap |
| 2.8 | C9 `parse_probe_json` (+`_to_float`, `MediaError`) | RED: AttributeError → GREEN; duración ausente, codec desconocido→bitmap, JSON inválido |
| 2.9 | Registros (`MODELS`/`SOURCE_LANGS`/`TARGET_LANGS`, `ModelSpec`/`LangSpec`), `validate_registry_choices`, `build_parser`, `resolve_inputs` dedup | RED: AttributeError → GREEN; S31 SystemExit 2 lista `es`; dedup por `resolve()` |
| 3.1 | Fábricas lavfi (`make_video` con espacios, `make_embedded` mov_text spa/eng, sin audio, garbage) | 6 checks de fábrica + limpieza `tests_tmp` verificada |
| 3.2 | `probe_media` + esqueleto `subtitlar_one` + `main`/`__main__` mínimos | RED: stdout vacío → GREEN: ERROR recortado, «sin audio», corrida sigue, espacios (S3) |
| 3.3 | `extract_track` + `write_srt_atomic` + rama extract | RED: «ruta extract aún no implementada» → GREEN: S17/S19 a nivel de bytes (BOM `EF BB BF`, solo CRLF, numeración 1..n, timestamps, texto, sin .tmp) |
| 3.4 | SKIP/--force (S20/S21/S22) | RED: sin SKIP y mtime cambió → GREEN; unit de `write_srt_atomic` |
| 3.5 | `--dry-run` (`plan_line` §4.3; S23/S24/S8/S32) | RED: sin línea de plan → GREEN; exacta, SKIP (.srt existe), `--no-extract`, `medium`, extraer pista spa/eng+traducir; bitmap por unit |
| 3.6 | Resumen + exit codes (S25/S26/S27/S31) | RED: TOTAL ausente, KI mató el subproceso (rc 3221225786) → GREEN: `TOTAL: 1 ok, 1 failed, 1 skipped` exacto, rc 0/1, unit KI→130, `--target en` rc 2 lista `es`, dry-run rc 0 |
| 4.1 | `list_videos`/`interactive_select` (español) + wiring de `resolve_inputs` | RED: 7 fallos → GREEN: rangos exactos 5 .srt, re-pregunta, `a`, `q`, invertido, carpeta creada+guía, carpeta vacía (S28/S29/S30) |
| 4.2 | `ensure_tools` (S33) | RED: procesó sin tools → GREEN: rc 1 + mensaje claro + nada procesado; triángulo solo-ffprobe |
| 5.1 | Gate opt-in `SUBTITLER_SMOKE_REAL` estricto `== "1"` (D8) + `run_real_check`/`make_tts_wav`/checks reales S11/S12/S6 registrados | Default: SKIP visible, rc 0; triángulo `SUBTITLER_SMOKE_REAL=0` idéntico a unset; fix de robustez: `force_utf8_stdio()` en la suite (crash cp1252 con `→` al redirigir) |
| 5.2 | `draw_progress` (matemática pura + render `\r`, ancho 24, intervalo 0.1 s) | RED: no existía → GREEN: `45.0%`/`1.50x`/`ETA 00:37`; pct 0/1 y elapsed 0 sin división por cero |
| 5.3 | `transcribe_cues` lazy (D3) + rama transcribir del pipeline | Unit: `import subtitler` no carga `faster_whisper`/`argostranslate`; checks reales opt-in S11/S12 registrados (gated) |
| 5.4 | Argos: `installed_argos_pairs`/`build_translator`/`apply_translation`/`_lang1` + `_cues_for` (§4.1) | RED: 2 fallos → GREEN: S16 en default (sin pares → WARN + ok + texto original); unit rutas none/direct/pivot |
| 6.1 | `README.md` (132 líneas) contrastado contra `subtitler.py --help` real y superficie implementada | Opciones/defaults/datos 1.1 (Python 3.11.15, 1.2 GB, 2.5 min), códigos 0/1/2/130, opt-in |
| 6.2 | Verificación final | 74/0/rc 0; py_compile ok; git status limpio |

## Archivos del cambio

- `subtitler.py` (nuevo, 1082 líneas)
- `test_smoke.py` (nuevo, 1222 líneas)
- `README.md` (nuevo, 132 líneas)
- `requirements.txt` (nuevo, 5 líneas — de la sesión cancelada, verificado)
- `.gitignore` (modificado, 8 líneas)
- `.venv/` (entorno, no versionado) · `openspec/changes/add-subtitler-cli/tasks.md` y `apply-progress.md`

**Total authored: ~2449 líneas** (forecast de tasks: 1500–1900 + README/test crecidos por cobertura de escenarios; dentro de lo razonable para el mismo alcance).

## Desviaciones del diseño (documentadas)

1. **Fábrica `make_embedded`:** el muxer MP4/mov_text marca `default=1` la primera pista de subtítulos incluso con `-disposition:s:0 0`; el check de fábrica no afirma `default=0` y la distinción default/primera-de-texto queda por unit en C8 (S9, tal como dicta la tabla de diseño). El `.srt` fuente del mux usa nombre distinto al stem y se borra, para no pre-crear la salida.
2. **Suite: `force_utf8_stdio()`:** al redirigir stdout (cp1252) el carácter `→` del plan crasheaba la propia suite; se fuerza UTF-8+replace al estilo `configure_utf8_stdio` del espejo.
3. **`except Exception` residual (§4.1):** con cuerpo sin `or` (regla `no-boolean-in-except` del linter); la captura amplia se mantiene porque el diseño exige «jamás propaga».
4. **Orden interno:** `main`/`summarize` viven tras el pipeline; el arranque `__main__` se añadió en 3.2 (infra mínima para los checks de subproceso) con contrato completo 0/1/130 en 3.6.
5. **`resolve_inputs` sin argumentos** delega en el selector desde 4.1 (en 2.9 era dedup-only, según el ciclo TDD de cada tarea).

## Residuales / riesgos

- Corrida opt-in real (modelos tiny + Argos `en→es` + voz SAPI) pendiente de aceptación explícita de descargas — la ejecuta el mantenedor cuando quiera; fallos de esa sección cuentan en RESULT por diseño.
- S10 e2e (voz TTS española) queda condicional a que haya voz instalada (residual §6.3 declarado).
- PGS sintético real no se añadió al default (residual aceptado: unit de `decide_extraction` cubre la decisión).
- 2 filas `sdd-owner: parent` sin marcar (decisión de entrega y bounded review) — no son tareas de implementación.

## Workload / frontera de PR (delivery: auto-chain, stacked-to-main)

- Presupuesto de revisión: 400 líneas → riesgo High confirmado por tasks; el padre ya resolvió **auto-chain** con 3 slices.
- Slice 1 = grupos 1–2 (soporte + costuras puras C1–C10 con units) · Slice 2 = grupos 3–4 (sondeo/extracción/atómica/pipeline/CLI + selector/herramientas) · Slice 3 = grupos 5–6 (transcripción/traducción/progreso opt-in + README + verificación final).
- Cada slice cierra con la suite default en verde (verificada al final de cada fase). No se commitea ni se abren PRs desde apply (lo maneja el orquestador tras verify).

## Estado estructurado consumido

- `gentle-ai.sdd-status` v2 consumido al inicio: `applyState: ready`, `actionContext.mode: repo-local`, `allowedEditRoots = [D:\Desarrollo\py-video-subtitler]` — todas las ediciones dentro de raíces autorizadas.
- `sdd-attempt acquire` con el token activo del resume → estado `proceed`; settle con outcome `passed` al cierre.

---

## Enmienda (2026-09-13): descarga Argos en demanda + doble salida (D13/D14, tareas 5.5–5.7)

Decisión del dueño de producto implementada: **(A)** sin ruta Argos, intentar descarga one-time (par directo `(origen, destino)` primero; si el índice no lo ofrece, patas del pivote `(origen, en)` + `(en, dst)`), re-resolver y traducir; fallo → WARN + original, jamás aborta. **(B)** doble salida cuando el origen ≠ destino: `<stem>-<lang>.srt` (guion + código corto 639-1; `-orig` si desconocido) con el original + `<stem>.srt` con la traducción; si la traducción falla, SOLO la sufijada; SKIP/--force llaveados al principal; origen español → salida única.

### Evidencia TDD (runner: `.venv/Scripts/python.exe test_smoke.py`)

- **RED** (estado de partida: el reformateo automático de pi-lens había dejado units A1–A3 sin implementación): `RESULT: 74 passed, 3 failed` — `unit A1`/`A2` con `AttributeError: 'list' object has no attribute 'original'` (contrato `TranslationOutcome` inexistente) y `unit A3` con `IndentationError` (indentación rota por el reformateo en `PaqueteFalso`/`fabricar`; reparada, luego `AttributeError: ensure_pairs_installed`). RED completado con tests nuevos/actualizados: 8 fallos intencionales (sin traducción vía descarga, sin salida sufijada, sin INFO de descarga, principal escrito donde debía existir solo el sufijado).
- **GREEN**: implementación en `subtitler.py` (`download_candidates`, `_route_satisfiable`, `ensure_pairs_installed` lazy D3, `TranslationOutcome`, `ProducedSubtitles`; rework de `apply_translation`/`_cues_for`/`subtitlar_one`) → `RESULT: 87 passed, 0 failed`, **rc 0** (74 base + 3 units + 10 checks e2e), sin red en la suite default (aislamiento Argos + argostranslate falso + units mockeados).
- **TRIANGULATE**: `download_candidates("en","es")` = solo el directo (sin `(en,en)` ni duplicados); one-time sin re-consulta de índice; patas del pivote cuando el directo falta del índice; nada disponible → `False`; excepción de instalación → `False`; 5.4 e2e offline real → WARN + solo `s16 eng-en.srt`; e2e fake-argos éxito (dual + INFO) y fallo (solo sufijado); origen spa → salida única; sin `.tmp` residual de ninguna salida.
- **REFACTOR**: costuras pequeñas y tipadas; `py_compile` ok; sanity de seams en proceso verde.

### Correcciones del propio ciclo (documentadas)

1. `unit A3` llegó con indentación rota del reformateo automático (cuerpo de clase/función a columna 0 dentro del script) — reparada antes del GREEN.
2. El INFO de descarga contiene `→`: el unit A3 llama `ensure_pairs_installed` directo en un subproceso `-c` con stdio cp1252 → `UnicodeEncodeError` que el `except` del contrato convertía en `False`; el unit ahora fuerza stdio UTF-8 (en producción `configure_utf8_stdio` ya lo cubre).
3. Check 5.4/5.5: el sufijo correcto usa el stem completo (`s16 eng-en.srt`, no `s16-en.srt`) — corregido el nombre esperado del test; el comportamiento del producto era correcto (verificado con repro aislado previo).

### Verificación final de la enmienda

- `.venv/Scripts/python.exe test_smoke.py` → `RESULT: 87 passed, 0 failed`, rc 0, sin red ni descargas.
- `.venv/Scripts/python.exe -m py_compile subtitler.py test_smoke.py` → ok.
- Opt-in real (`SUBTITLER_SMOKE_REAL=1`): NO ejecutado (consigna vigente del orquestador).
- README: fuera de las superficies de edición autorizadas de esta enmienda (pendiente para el orquestador si se quiere documentar la doble salida).
