# Sync Report — add-subtitler-cli

- **Cambio:** `add-subtitler-cli` · **Fase:** sync · **Fecha:** 2026-09-13 · **Almacén:** openspec
- **Estado: SYNCED** — verificación limpia, colisiones cero y delta no destructivo. La copia a canónico quedó fuera del alcance autorizado de la corrida inicial y fue completada por el orquestador el 2026-09-13: `openspec/specs/subtitle-generation/spec.md` creado desde el spec del cambio (12 requisitos / 37 escenarios). Sync completo; `sdd-archive` desbloqueado.

## Estado estructurado consumido

- `gentle-ai.sdd-status`: `artifactStore: openspec`, `dependencies.sync: blocked`, `blockedReasons: []`, `isNonAuthoritative: false`, `nextRecommended: sdd-verify`, `taskProgress 28/28`, `deferredParentActions 2/2`.
- El gate real de sync («sincronizar solo tras verificación limpia») está **satisfecho por el artefacto del backend**: `verify-report.md` → `verdict: pass`, `blockers: 0`, `critical_findings: 0`, tests rc 0. El snapshot del motor (`nextRecommended: sdd-verify`, `dependencies.verify: ready`) es anterior a la enmienda post-verify; el orquestador lo declara obsoleto («outrank stale snapshots») y este informe lo confirma leyendo el artefacto directamente.
- `actionContext`: `mode: repo-local`, `workspaceRoot: D:\Desarrollo\py-video-subtitler`; el motor autoriza la raíz completa, pero la instrucción explícita de esta corrida redujo el alcance a `openspec/changes/add-subtitler-cli/`. Restricción respetada: **este informe es el único archivo escrito**.
- Relaciones: `dependsOn`/`supersedes`/`amends`/`conflictsWith` vacíos; `sameDomainActiveChanges: []` — confirmado en filesystem: `openspec/changes/` solo contiene `add-subtitler-cli` (sin colisiones de dominio).

## Sincronización canónica

- **Dominios sincronizados en canónico: ninguno** (pendiente la copia única).
- **Archivos canónicos actualizados: ninguno** — `openspec/specs/` contiene solo `.gitkeep`; no existe `openspec/specs/subtitle-generation/spec.md`.
- **Tipo de delta:** full-format, dominio NUEVO. Sin secciones `## ADDED/MODIFIED/REMOVED/RENAMED Requirements` (verificado por grep). Regla nativa del helper para canónico inexistente: **copiar la spec del cambio como nueva spec canónica** — la copia íntegra ES la semántica correcta.
- **MODIFIED: 0 · REMOVED: 0 · RENAMED: 0.** Sincronización aditiva pura; sin aprobaciones destructivas requeridas (la regla `archive` de config.yaml «avisar antes de mezclar deltas destructivos» no se activa). `rules.sync` no existe en config.yaml.
- **Colisiones mismo-dominio: ninguna** (único cambio activo; canónico vacío para el dominio).

## Acción canónica pendiente (única)

```text
copiar  openspec/changes/add-subtitler-cli/specs/subtitle-generation/spec.md
hacia   openspec/specs/subtitle-generation/spec.md
```

- Dominio nuevo + full-format: sin conflictos, sin mezcla, reversible con `git rm`.
- Tras ejecutarla: actualizar este informe a `status: synced` y proceder a `sdd-archive`. **No archivar antes de que exista la spec canónica.**

## Estado final verificado a reflejar (post-enmienda)

- **Shipped:** `subtitler.py` (single-file), `test_smoke.py`, `README.md` (actualizado por el orquestador: pasos 4–6 del pipeline con descarga Argos en demanda y doble salida), `requirements.txt`, `.gitignore`.
- **Suite:** `RESULT: 87 passed, 0 failed`, rc 0 (default, offline, sin descargas); `py_compile` ok (ambos archivos).
- **Enmienda post-verify (dueño de producto):**
  - **(A) Descarga Argos en demanda, one-time:** sin ruta sobre pares instalados, intentar el par directo `(origen, destino)`; si el índice no lo ofrece, las patas del pivote `(origen, en)` + `(en, destino)`; tras instalar, re-resolver la ruta y traducir. Fallo (sin red, par desconocido, instalación rota) → WARN + salida en idioma original; jamás aborta la corrida ni cuenta el archivo como failed. Con ruta ya posible: cero consultas al índice.
  - **(B) Doble salida cuando origen ≠ destino:** `<stem>-<lang>.srt` (código corto 639-1; `-orig` si el idioma es desconocido) con el original + `<stem>.srt` con la traducción al español. Orden de escritura: primero el sufijado. Traducción fallida → SOLO el sufijado. Origen ya español → salida única. SKIP/`--force` llaveados al `.srt` principal; `--force` regenera ambas.
- La spec del cambio ya incorpora la enmienda: R4 ampliado (3→6 escenarios) y R6 reescrito (2→5 escenarios).

## Cobertura final de especificación

- **12/12 requisitos · 37/37 escenarios** (31 pre-enmienda → 37 post-enmienda; verificado por conteo de encabezados en la spec).
- `verify-report.md` documenta 31/31 con evidencia SUITE/RESIDUAL (25 SUITE plena, 6 con residual declarado, GAP 0). Los 6 escenarios nuevos de la enmienda quedan cubiertos por la evidencia TDD de la enmienda en `apply-progress.md`: units A1–A3 (`download_candidates`, `ensure_pairs_installed`, `TranslationOutcome`) + 10 checks e2e (fake-Argos éxito → dual + INFO; fallo → solo sufijado; 5.4/5.5 offline real → WARN + solo `s16 eng-en.srt`; origen spa → salida única; sin `.tmp` residual en ninguna salida).

### Inventario de requisitos (todos ADDED-en-primera-copia, con escenarios)

| # | Requisito | Escenarios |
| --- | --- | --- |
| R1 | Sondeo de medios por archivo | 3 |
| R2 | Extracción de subtítulos embebidos | 5 |
| R3 | Transcripción local del audio | 3 |
| R4 | Ruteo de traducción Argos (incluye descarga en demanda) | 6 |
| R5 | Formato del archivo SRT | 2 |
| R6 | Escritura atómica y ubicación de salida (incluye doble salida) | 5 |
| R7 | SKIP y --force sobre .srt existente | 2 |
| R8 | --dry-run | 2 |
| R9 | Códigos de salida y resumen | 3 |
| R10 | Resolución de entradas y selector interactivo | 3 |
| R11 | Superficie CLI | 2 |
| R12 | Verificación de herramientas | 1 |

## Residuales (declarados, sin cambios de código)

1. **`SUBTITLER_SMOKE_REAL=1` opt-in NO ejecutado** — 3 checks reales aparecen como SKIP por diseño (D8, semántica estricta `"1"`; `subtitler.py` jamás lee la variable). Queda pendiente de aceptación explícita del mantenedor (descargas de modelos + voz TTS).
2. **Modelos Zen free-tier inutilizables fuera de OpenCode** — n/a al código (contexto del orquestador; sin acción de sync).
3. **PGS sintético real no añadido al default** — residual aceptado en verify; la decisión está cubierta por unit C8 `decide_extraction`.

## Chequeos realizados en esta fase

- `verify-report.md`: `verdict: pass`, blockers 0, hallazgos críticos 0 → gate de sync limpio.
- Grep sobre la spec del cambio: 12 `### Requirement:`, 37 `#### Scenario:`, 0 secciones delta (`ADDED/MODIFIED/REMOVED/RENAMED` ausentes → full-format).
- `tasks.md`: 30 filas de checkbox, **0 sin marcar** (motor: `taskProgress 28/28` + `deferredParentActions 2/2`).
- Filesystem: `openspec/specs/` solo `.gitkeep`; `openspec/changes/` solo `add-subtitler-cli` (sin colisiones); `config.yaml` sin `rules.sync`.
- Escritura limitada a `openspec/changes/add-subtitler-cli/sync-report.md` (restricción del orquestador respetada; sin commits, sin subagentes).

## Próxima fase recomendada

1. Completar la copia canónica (re-despachar `sdd-sync` con `openspec/specs/` en alcance, o que el orquestador ejecute la copia única) y marcar este informe `synced`.
2. Después: `sdd-archive` (target `openspec/changes/archive/2026-09-13-add-subtitler-cli`). **No archivar con `openspec/specs/` vacío.**
