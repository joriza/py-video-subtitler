```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:40712a8df88281204ea23ebf37453f0ae6b99f95f3b2f50249177b2d939c0e48
verdict: pass
blockers: 0
critical_findings: 0
requirements: 12/12
scenarios: 37/37
test_command: .venv/Scripts/python.exe test_smoke.py
test_exit_code: 0
test_output_hash: sha256:40712a8df88281204ea23ebf37453f0ae6b99f95f3b2f50249177b2d939c0e48
build_command: .venv/Scripts/python.exe -m py_compile subtitler.py
build_exit_code: 0
build_output_hash: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

# Verify Report — add-subtitler-cli (enmienda post-verify)

- **Cambio:** `add-subtitler-cli` · **Fase:** verify · **Fecha:** 2026-09-13 · **Almacén:** openspec
- **Veredicto: PASS** — implementación conforme a proposal, specs (ENMIENDADAS: 12 requisitos / 37 escenarios), design (con §10 D13/D14) y tareas 30/30. Cero blockers, cero hallazgos críticos.
- **SUPERSEDE el reporte previo** (que cubría 31 escenarios pre-enmienda y quedó stale: total 31 ≠ 37 reales). Este reporte verifica la especificación enmendada (R4 descarga Argos en demanda + doble salida con nombres `<stem>-<lang>.srt`/`-orig`) y su total ahora coincide con los specs actuales, desbloqueando archive.

## Estado estructurado consumido

- `gentle-ai.sdd-status` v2: `changeName: add-subtitler-cli`, `dependencies.verify: ready`, `applyState: all_done`, `taskProgress 30/30 allComplete`, `archive: blocked` (motivo declarado: reporte stale 31≠37 — este informe lo resuelve).
- `actionContext.mode: repo-local`, `workspaceRoot: D:\Desarrollo\py-video-subtitler`, `allowedEditRoots: [D:\Desarrollo\py-video-subtitler]` — propiedad de implementación probada: `subtitler.py` (1278 líneas), `test_smoke.py` (1714), `README.md`, `requirements.txt`, `.gitignore`, `openspec/` viven dentro de la raíz autorizada; `git status --porcelain` solo lista archivos del cambio.
- `sdd-attempt acquire` con el token activo `sha256:7267cea285538d07eb4ad0aa16d268a72b4ac237b4521eaff99b81d82654fce9` → estado **proceed**; settle con outcome `passed` al cierre de esta fase.

## Comandos de verificación ejecutados (esta sesión, sobre los bytes actuales)

| Comando | Resultado | Evidencia |
| --- | --- | --- |
| `.venv/Scripts/python.exe test_smoke.py` (sin `SUBTITLER_SMOKE_REAL`) | `RESULT: 87 passed, 0 failed`, **rc 0**, sin red ni descargas (74 base + 3 units de enmienda A1–A3 + 10 checks e2e de enmienda) | hash de salida `sha256:40712a8df88281204ea23ebf37453f0ae6b99f95f3b2f50249177b2d939c0e48` |
| `.venv/Scripts/python.exe -m py_compile subtitler.py` | ok, **rc 0**, sin salida | hash `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (salida vacía) |
| `gentle-ai sdd-attempt acquire --token sha256:7267cea…4fce9` | estado `proceed` | token retenido para settle |

- `evidence_revision` = sha256 de los bytes de salida del test concatenados con los del build (el build no produce salida, por eso coincide con el hash del test).
- La sección real opt-in (`SUBTITLER_SMOKE_REAL=1`) **NO se ejecutó** por consigna; sus 3 checks aparecen `[SKIP] (opt-in: …)` y no cuentan como fallo (D8, semántica estricta `"1"`). Verificado por grep que `subtitler.py` **no** lee la variable (0 coincidencias): el gate vive solo en el smoke.
- Conteo del spec ENMIENDADO verificado con grep sobre los bytes actuales: `^### Requirement:` → **12**, `^#### Scenario:` → **37**.

## Cobertura de especificación — 12 requisitos / 37 escenarios

Leyenda: **SUITE** = verificado por la suite default (87 checks verdes esta sesión); **RESIDUAL** = costura verificada en default + extremo a extremo real diferido al opt-in declarado (design §6.3, tasks 5.3/5.4, apply-progress §residuales; política vigente: sin `SUBTITLER_SMOKE_REAL`). **GAP = 0.**

| # | Requisito | Escenario | Cobertura | Evidencia en la suite (checks PASS de esta corrida) |
| --- | --- | --- | --- | --- |
| 1 | R1 Sondeo de medios | video sin audio | SUITE | `3.2: no-audio reason` + `3.2: run continues after failure` + `3.6: exact TOTAL line (S25/S1)` — `TOTAL: 1 ok, 1 failed, 1 skipped` exacto, rc 1 |
| 2 | R1 | sondeo falla para un archivo | SUITE | `3.2: probe failure reported as ERROR` + `3.2: garbage file named in header` (detalle recortado) + la corrida sigue |
| 3 | R1 | rutas con espacios | SUITE | `3.2: spaces path fully probed (S3)`; fábrica `make_video with spaces`; subprocess con listas |
| 4 | R2 Extracción embebida | pista embebida en español | SUITE | `3.3: extraction run exits 0 (S5)` + `3.3: cue text present, not transcribed (S5)` — extracción en segundos |
| 5 | R2 | pista embebida en otro idioma | SUITE+RESIDUAL | unit C8 `extract_translate`; `3.5: plan extract eng + traducir`; **5.5 e2e fake-argos**: descarga + traducción + doble salida; Argos real = opt-in residual (real S6) |
| 6 | R2 | solo pistas bitmap | SUITE+RESIDUAL | unit C8 `transcribe_bitmap` (PGS); `unit 3.5: plan bitmap route`; WARN en `_cues_for`; transcripción real = opt-in residual (declarado) |
| 7 | R2 | --no-extract fuerza transcripción | SUITE+RESIDUAL | unit C8 `transcribe_forced`; `3.5: --no-extract forces transcribe plan (S8)`; real = opt-in residual |
| 8 | R2 | elección de pista preferida | SUITE | unit C8 `pick_subtitle_track`: default marcada no-primera gana; sin default → primera de texto (limitación de fábrica mov_text documentada) |
| 9 | R3 Transcripción | transcripción de video en español | SUITE+RESIDUAL | unit 5.3 (contrato `transcribe_cues`: un `Cue` por segmento, `language=None` si auto, VAD); e2e condicional a voz TTS española = opt-in residual (S10, declarado) |
| 10 | R3 | transcripción de video en inglés | RESIDUAL | check real opt-in S11 registrado (tiny + TTS); `transcribe_cues` implementado lazy y compilado; traducción de segmentos cubierta por units A1/A2 + 5.5 e2e fake-argos |
| 11 | R3 | progreso en una línea | SUITE+RESIDUAL | unit 5.2: matemática pura pct/speed/ETA, `\r`, ancho 24, intervalo 0.1 s, pct 0/1 y elapsed 0; real (`ETA` en stdout) = opt-in residual (S12) |
| 12 | R4 Ruteo Argos | par directo | SUITE | unit C7: `(en,es) ∈ pairs` → direct; unit A3: `descargas == [("de","es")]` (directo primero) |
| 13 | R4 | pivote vía inglés | SUITE | unit C7: `de→en→es` 2 saltos; unit 5.4 `build_translator` pivote; unit A3: patas `[("de","en"),("en","es")]` |
| 14 | R4 | **(enmienda)** descarga en demanda del par directo | SUITE | unit A1: candidatos exactos `(("de","es"),("de","en"),("en","es"))` — directo primero, re-resuelve direct y traduce; unit A3: SOLO el directo descargado, índice consultado 1 vez (`indice_actualizaciones == [1]`); 5.5 e2e: `INFO descargando paquete Argos en→es` + ruta re-resuelta + `video.srt` traducido |
| 15 | R4 | **(enmienda)** descarga en demanda de las patas del pivote | SUITE | unit A3: directo ausente del índice → se descargan las DOS patas `("de","en")` + `("en","es")` |
| 16 | R4 | **(enmienda)** descarga one-time no repite trabajo | SUITE | unit A3: segunda llamada con pares suficientes → ni índice ni descargas nuevas; pivote ya completo → True sin tocar red |
| 17 | R4 | **(enmienda)** sin camino incluso tras la descarga | SUITE | unit A3: nada disponible → `False` sin lanzar; excepción de instalación → `False`; unit A2: WARN nombra `en→es`, `translated is None`; 5.5 e2e: rc 0 (jamás aborta) + solo original sufijado — el archivo NO cuenta como failed |
| 18 | R5 Formato SRT | verificación de formato | SUITE | bytes 3.3: BOM `EF BB BF`, solo `\r\n`, numeración `1..n` consecutiva, `HH:MM:SS,mmm --> HH:MM:SS,mmm`, exactamente una línea en blanco entre cues |
| 19 | R5 | ajuste de línea | SUITE | units C2/C3/C4/C5: ≤42 chars/línea, ≤2 líneas/cue, reparto proporcional con gap 1 ms, reconstrucción palabra a palabra sin pérdida (~150 chars) |
| 20 | R6 Escritura/doble salida | salida principal junto al video | SUITE | `3.3: .srt next to video with same stem (S19)` |
| 21 | R6 | **(enmienda)** doble salida con origen ≠ destino | SUITE | 5.5 e2e fake-argos: `5.5: translated main video.srt (en source)` (`[es] hello world`) + `5.5: original side video-en.srt kept` (texto original, stem completo) |
| 22 | R6 | **(enmienda)** idioma de origen desconocido | SUITE (contrato) | unit A2: `None` y `und` → `original_lang is None`; mapeo en producto `code = produced.lang if produced.lang else "orig"` (subtitler.py:1131) — ver hallazgo 2 |
| 23 | R6 | **(enmienda)** fallo de traducción deja solo el original sufijado | SUITE | `5.4/5.5: failure keeps only suffixed original (S16)` + `5.5: failure writes only suffixed original` — existe SOLO `sufijo-en.srt` con el original, NO existe el principal |
| 24 | R6 | fallo a mitad de generación | SUITE | unit 3.4 `write_srt_atomic` (todo a `.tmp`, `os.replace`, sin residuo) + `3.4: no .srt left for failed files (S20)` + `5.5: no partial .tmp for either output` (ambas salidas) |
| 25 | R7 SKIP/--force | existente sin --force | SUITE | `3.4: reported SKIP (S21)` + `3.4: existing .srt untouched` (`st_mtime_ns` intacto) |
| 26 | R7 | --force regenera | SUITE | `3.4: --force exits 0 (S22)` + mtime cambia |
| 27 | R8 --dry-run | plan sin procesar | SUITE | `3.5: exact plan line (S23)` + `3.5: no .srt created` + `dry-run exits 0` + triángulo sin `.srt` |
| 28 | R8 | dry-run con .srt existente | SUITE | `3.5: dry-run with existing .srt reports SKIP (S24)` |
| 29 | R9 Exit codes | corrida con mezcla de resultados | SUITE | `3.6: mixed run rc 1 (S25)` + `TOTAL: 1 ok, 1 failed, 1 skipped` exacto + rc 1 |
| 30 | R9 | corrida sin fallos | SUITE | `3.6: ok+skipped run rc 0 (S26)` + `TOTAL 1 ok 1 skipped` + triángulo dry-run rc 0 |
| 31 | R9 | interrupción con Ctrl-C | SUITE (unit) | unit S27: `KeyboardInterrupt` parcheada → `main([...]) == 130`; señal física no simulada (residual de diseño: flaky en Windows, §6.2/6.3) |
| 32 | R10 Selector | selección por rangos | SUITE | `4.1: range selection rc 0 (S28)` + `exactly 5 srts with expected names` + entrada inválida re-pregunta sin procesar |
| 33 | R10 | todos y salir | SUITE | `4.1: 'a' processes all 7 (S29)` + `'q' quits with zero outputs, rc 0` + triángulo rango invertido |
| 34 | R10 | carpeta inexistente | SUITE | `4.1: missing dir created (S30)` + `guide printed` + triángulo carpeta vacía |
| 35 | R11 Superficie CLI | opción registrada no implementada | SUITE | `3.6: --target en rc 2 (S31)` + `stderr lists implemented 'es'` + unit 2.9 (registro ampliado) |
| 36 | R11 | modelo no default elegido | SUITE | `3.5: plan mentions medium (S32)` + unit 2.9 acepta del registro |
| 37 | R12 Herramientas | ffprobe ausente | SUITE | `4.2: missing tools rc 1 (S33)` + mensaje claro nombra ffmpeg/ffprobe/PATH + nada procesado + triángulo solo-ffprobe |

- **Resultado: 12/12 requisitos completos, 37/37 escenarios cubiertos (31 SUITE plena —incluido el contrato de 22—, 5 con residual declarado + 1 RESIDUAL (10), 0 GAP).**
- Los residuales (5/6/7/9/10/11) comparten una sola causa raíz declarada desde design/tasks: la transcripción y traducción reales requieren modelos (red one-time) y son opt-in del mantenedor. La política de esta sesión confirma que permanecen declarados-residuales; no son gaps.
- Cruce de la desviación documentada (apply-progress desviación 1): el muxer mov_text fuerza `default=1` en la primera pista; la LÓGICA de preferencia R2 está implementada en `pick_subtitle_track` y probada por unit C8. Interpretación aceptable, no violación.
- Los 6 escenarios nuevos de la enmienda (14–17 de R4 y 21–23 de R6) están todos verificados en la suite default con units mockeados (A1–A3) y e2e con argostranslate falso inyectado vía runpy — sin red ni descargas reales.

## Estado de tareas — 30/30 completas

- `grep "^\s*- \[ \]" tasks.md` → **0 coincidencias**. No queda ninguna tarea de implementación sin marcar; no hay bloqueador de archivo.
- Las 2 filas `sdd-owner: parent` están `[x]` con resolución anotada (encadenado PR 1→2→3 `stacked-to-main`; review nativo off por política del usuario/RDD off).
- Las tareas de enmienda 5.5/5.6/5.7 están `[x]` con evidencia TDD propia en apply-progress (sección «Enmienda»).

## Cumplimiento TDD estricto

- `openspec/config.yaml`: `tdd: true`, `test_command: .venv/Scripts/python.exe test_smoke.py`. Sin guía externa `strict-tdd-verify` (no existe `.pi/gentle-ai/support/strict-tdd-verify.md` ni global); se ejecutaron los chequeos embebidos.
- Evidencia de ciclo TDD en `apply-progress.md`: tabla por tarea (RED→GREEN→TRIANGULATE con fallos RED nombrados) + sección de ENMIENDA con su propia evidencia RED (`74 passed, 3 failed` + 8 fallos intencionales) → GREEN (`87 passed, 0 failed`) → TRIANGULATE → REFACTOR, con 3 correcciones documentadas del propio ciclo. Nota menor: el encabezado literal no es `TDD Cycle Evidence`, pero la sustancia está completa — no bloqueante.
- Referencia cruzada archivos↔código: los units A1/A2/A3 existen en `test_smoke.py` (líneas ~933–1150) y los checks e2e 5.5 (~1630–1701); los seams de enmienda existen en `subtitler.py` (`download_candidates`:405, `_route_satisfiable`:453, `ensure_pairs_installed`:468, `TranslationOutcome`:164, `ProducedSubtitles`:210). Suite re-corrida por esta fase sobre los bytes actuales: GREEN (`RESULT: 87 passed, 0 failed`, rc 0).
- Suite sin `SUBTITLER_SMOKE_REAL`: los 3 checks reales reportan `[SKIP]` y no cuentan; `subtitler.py` no lee la variable (grep 0 coincidencias).

## Calidad de aserciones (auditoría de los tests de la enmienda + carried-over)

- Sin tautologías: comparaciones exactas de tuplas (`download_candidates("en","es") == (("en","es"),)`, candidatos `(("de","es"),("de","en"),("en","es"))`), contenido de archivo byte-level (`[es] hello world` en `video.srt`, texto original en `video-en.srt`), contadores exactos de llamadas al índice (`indice_actualizaciones == [1]`), ausencia de archivos (`not ... .with_suffix('.srt').exists()`, sin `.tmp` de ninguna salida).
- Sin ghost loops ni aserciones solo-de-tipo: cada check verifica comportamiento observable (rc, stdout con marcadores exactos como `INFO descargando paquete Argos en→es`, efectos en filesystem).
- El harness e2e fake-argos ejecuta el `subtitler.py` REAL vía `runpy` con `argostranslate` falso inyectado: aísla la red sin debilitar la cobertura del pipeline (escrituras `.srt` reales en `tests_tmp`, verificadas por lectura).
- Carried-over: `render_srt` usa `assert` para el invariante ≤2 líneas (eliminado con `-O`; la corrección no depende de él y la suite no corre con `-O`).

## Review Workload / frontera de PR

- Forecast consumido: riesgo High confirmado; `Chained PRs recommended: Yes` → decisión ask-on-risk resuelta y anotada en tasks.md: encadenar 3 slices `stacked-to-main`. La `Chain strategy` retornada coincide con la resuelta. No se usó `size:exception`.
- La enmienda (tareas 5.5–5.7) añadió ~688 líneas authored (`subtitler.py` 1082→1278; `test_smoke.py` 1222→1714): total ~3137 vs forecast 1500–1900. No es scope creep — es una enmienda dirigida por el dueño de producto con spec/design/tareas/TDD propios — pero el encadenado debe absorberla: al seleccionar el chaining, confirmar si la enmienda va dentro del slice 3 o forma un slice propio (queda para el orquestador; presupuesto 400 líneas/slice se gestiona en la apertura de PRs).
- Solo se implementó el slice asignado más la enmienda con tareas explícitas; ningún comportamiento fuera del spec enmendado (los 37 escenarios mapean 1:1 con la tabla anterior).

## Hallazgos

1. **INFO** — 0 gaps de cobertura en 12/37; los 6 escenarios de la enmienda están cubiertos en SUITE (units mockeados + e2e fake-argos). Residuales opt-in (5/6/7/9/10/11) pre-declarados y vigentes por política.
2. **INFO** — El escenario «idioma de origen desconocido» (`<stem>-orig.srt`) está cubierto por contrato (unit A2 prueba `lang=None` para `None`/`und`; el mapeo a `-orig` en subtitler.py:1131 es la costura trivial que lo consume). El literal `-orig.srt` en disco no se ejercita e2e porque requeriría transcripción real con detección desconocida (familia opt-in residual). Riesgo bajo: la costura es una expresión condicional de una línea.
3. **NOTE** — Encabezado de evidencia TDD en apply-progress difiere del literal `TDD Cycle Evidence`; sustancia completa (incluida la evidencia de la enmienda).
4. **INFO** — La enmienda añadió ~688 líneas authored sobre el forecast original; decisión de encadenado ya resuelta (3 slices stacked-to-main) y la absorbe — confirmar fronteras de slice al abrir PRs.
5. **NOTE** — Carried-over: `assert` de invariante en `render_srt` se eliminaría con `-O`; no afecta corrección ni la suite.
6. **INFO** — README aún no documenta la doble salida/-orig de la enmienda (apply-progress de la enmienda lo deja explícitamente para el orquestador); no afecta el spec ni el código.

## Blockers exactos

**Ninguno.** Verificación PASS contra la especificación ENMIENDADA (12/12 requisitos, 37/37 escenarios); tareas 30/30; este reporte reemplaza al previo (stale 31≠37) y desbloquea archive.
