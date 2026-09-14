# Archive Report — add-subtitler-cli

- **Cambio:** `add-subtitler-cli` · **Fase:** archive · **Fecha:** 2026-09-13 · **Almacén:** openspec
- **Estado: PASS — archivado exitoso.** Verificación limpia (PASS, 0 blockers, 0 críticos), tareas 30/30, sync canónico completo y delta puramente aditivo. Ningún gate de archivo bloqueante activo.

## Estado estructurado consumido

- `gentle-ai.sdd-status` v2 (autoridad nativa, proyección read-only): `changeName: add-subtitler-cli`, `artifactStore: openspec`, `dependencies.archive: ready`, `taskProgress 30/30 allComplete`, `applyState: all_done`, `nextRecommended: archive`, `blockedReasons: []`.
- `actionContext`: `mode: repo-local`, `workspaceRoot: D:\Desarrollo\py-video-subtitler`, `allowedEditRoots: [D:\Desarrollo\py-video-subtitler]` — reporte y movimiento de carpeta íntegramente dentro de la raíz autorizada; nada fuera de `openspec/`.
- Relaciones: `dependsOn`/`supersedes`/`amends`/`conflictsWith` vacíos; `sameDomainActiveChanges: []` — sin advertencias de cambio activo del mismo dominio (único cambio activo en `openspec/changes/`).

## Artefactos leídos (precondiciones de archivo)

| Artefacto | Resultado |
| --- | --- |
| `proposal.md` | OK — decisiones cerradas PLAN.md, criterios de éxito 1–8 |
| `specs/subtitle-generation/spec.md` | OK — full-format dominio nuevo, 12 requisitos / 37 escenarios |
| `design.md` | OK — D1–D14 (incl. §10 enmienda D13/D14) |
| `tasks.md` | OK — 30/30 `[x]`; grep `^\s*- \[ \]` → 0 coincidencias |
| `apply-progress.md` | OK — 25 tareas implementación + enmienda con evidencia TDD propia (RED `74 passed, 3 failed` → GREEN `87 passed, 0 failed`) |
| `verify-report.md` | OK — YAML `verdict: pass`, `blockers: 0`, `critical_findings: 0`, 12/12 requisitos, 37/37 escenarios, suite `RESULT: 87 passed, 0 failed` rc 0, `py_compile` ok. SUPERSEDE al reporte previo stale (31≠37) |
| `sync-report.md` | OK — estado `SYNCED`; copia canónica completada por el orquestador |
| `openspec/config.yaml` | OK — regla `archive: avisar antes de mezclar deltas destructivos` (no activada: mezcla aditiva pura) |

## Sincronización canónica (previa, vía sdd-sync + orquestador)

- **Dominios sincronizados:** `subtitle-generation` (1).
- **Acción:** copia íntegra full-format `openspec/changes/add-subtitler-cli/specs/subtitle-generation/spec.md` → `openspec/specs/subtitle-generation/spec.md` (dominio NUEVO; la copia íntegra ES la semántica correcta). Verificado en canónico: 12 `### Requirement:`, 37 `#### Scenario:`, 0 secciones delta.

## Requisitos ADDED / MODIFIED / REMOVED

- **ADDED (primera copia canónica del dominio — 12):** Sondeo de medios por archivo · Extracción de subtítulos embebidos · Transcripción local del audio · Ruteo de traducción Argos · Formato del archivo SRT · Escritura atómica y ubicación de salida · SKIP y --force sobre .srt existente · --dry-run · Códigos de salida y resumen · Resolución de entradas y selector interactivo · Superficie CLI · Verificación de herramientas.
- **MODIFIED: 0.** **REMOVED: 0.** Sin mezcla destructiva; sin aprobaciones requeridas.

## Gate de tareas (Final Task Completion Gate)

- Relectura de `tasks.md` inmediatamente previa a la escritura de este reporte y al movimiento: **0 líneas `- [ ]`** — no queda ninguna tarea de implementación sin marcar (30/30, incluidas las 2 filas `sdd-owner: parent` resueltas y las tareas de enmienda 5.5–5.7).
- No hubo reparación mecánica de checkboxes ni reconciliación stale (innecesaria).

## Estado final del cambio (hechos explícitos post-verify)

- **Enmienda post-verify implementada y cubierta por la re-verificación:** descarga Argos en demanda one-time (par directo → patas del pivote, WARN como fallback preservado, nunca aborta) + doble salida (`<stem>-<lang>.srt` original con guion + código 639-1, `-orig` si desconocido; `<stem>.srt` principal en español; salida única para orígenes españoles).
- **README.md documenta ambos comportamientos** (pasos 4–6 del pipeline, actualizado por el orquestador tras la enmienda) — resuelve el hallazgo 6 del verify-report.
- **Volumen:** la enmienda absorbió ~688 líneas authored adicionales sobre el forecast original (total ~3137; `subtitler.py` 1278, `test_smoke.py` 1714). No es scope creep: enmienda dirigida por el dueño de producto con spec/design/tareas/TDD propios.
- **Entrega:** push único a `main` por instrucción explícita del usuario — SUPERSEDE el plan previo de 3 PRs encadenados `stacked-to-main` anotado en tasks.md. Sin `size:exception` invocado.
- **Residuales declarados (aceptados por el mantenedor, no gaps):**
  1. Checks opt-in de modelos reales (`SUBTITLER_SMOKE_REAL=1`) nunca ejecutados — SKIP por diseño (D8); `subtitler.py` jamás lee la variable.
  2. Señal física Ctrl-C no simulada — cubierto por unit del handler (S27 → 130); flaky en Windows por diseño.

## Hallazgos de archivo

- Ningún bloqueador: verificación claramente PASS, artefactos completos, tareas íntegras, sync completo, delta aditivo.
- Advertencias de mismo-dominio activo: **ninguna** (`sameDomainActiveChanges: []`, confirmado en filesystem).
- Aprobaciones destructivas: **no requeridas** (MODIFIED 0 / REMOVED 0; regla `archive` de config.yaml no activada).
- Aprobación de archivo parcial: **no aplicada** (archivo completo, sin omisiones intencionales).
- Este reporte se escribió dentro de la carpeta del cambio ANTES del movimiento (auditoría preservada).

## Resultado del archivado

```text
openspec/changes/add-subtitler-cli/
  -> openspec/changes/archive/2026-09-13-add-subtitler-cli/
```

- Canónico vigente: `openspec/specs/subtitle-generation/spec.md` (12 requisitos / 37 escenarios).
- Sin commits ni push (fuera del alcance de archive); sin subagentes; sin ediciones fuera de `openspec/`.
