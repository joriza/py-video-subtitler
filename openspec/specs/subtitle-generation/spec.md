# Especificación de generación de subtítulos (subtitle-generation)

- **Cambio:** `add-subtitler-cli` · **Fase:** specs · **Fecha:** 2026-09-13
- **Tipo:** dominio NUEVO — no existe `openspec/specs/subtitle-generation/spec.md`, por lo que este archivo es la especificación completa (formato full, no delta).
- **Fuente:** `proposal.md` (PRD confirmado), `openspec/config.yaml` (reglas `specs`), `PLAN.md` (decisiones cerradas). Define QUÉ debe cumplirse; el CÓMO (costuras de funciones puras, registros internos, env var del smoke) queda para la fase de diseño.

## Purpose

Generar, junto a cada video elegido por el usuario, un archivo `.srt` válido en español con el mismo nombre base (`video.mp4` → `video.srt`), listo para que reproductores como VLC o MPC-HC lo carguen por defecto. Cuando el idioma de origen no es español, el sistema conserva además el subtítulo original como `<stem>-<lang>.srt`. La operación es local (CPU); la red solo interviene en la primera descarga de modelos y en la descarga one-time de pares Argos faltantes (en demanda). La corrida es robusta: un archivo problemático falla solo y nunca interrumpe el resto de la tanda.

## Requirements

### Requirement: Sondeo de medios por archivo

Antes de procesar un video, el sistema MUST sondearlo con `ffprobe` (salida JSON) para determinar sus pistas de subtítulos (texto vs bitmap), sus streams de audio y su duración. Si el video no tiene streams de audio, el sistema MUST registrar un error únicamente para ese archivo y continuar procesando el resto de la corrida. Un fallo de sondeo (salida inválida, timeout, archivo ilegible) MUST tratarse igual: error de ese archivo, la corrida sigue.

#### Scenario: video sin audio

- GIVEN una corrida con dos archivos donde uno no tiene streams de audio
- WHEN se ejecuta `python subtitler.py <sin-audio.mp4> <con-audio.mp4>`
- THEN el archivo sin audio se reporta como ERROR (failed) con motivo "sin audio"
- AND el archivo con audio se procesa normalmente y la corrida termina con ambos resultados reportados

#### Scenario: sondeo falla para un archivo

- GIVEN un archivo corrupto o ilegible por ffprobe
- WHEN llega su turno en la corrida
- THEN solo ese archivo se reporta como failed con un detalle de error recortado y la corrida continúa

#### Scenario: rutas con espacios

- GIVEN un video cuyo nombre contiene espacios (p. ej. `sample test.mp4`)
- WHEN se sondea y procesa
- THEN el sondeo y la salida `.srt` manejan la ruta completa sin truncarse ni dividirse en argumentos

### Requirement: Extracción de subtítulos embebidos

Cuando el sondeo encuentra al menos una pista de subtítulos de texto y no se pasa `--no-extract`, el sistema MUST usar esa pista como fuente del SRT en lugar de transcribir. La pista preferida MUST ser la marcada como *default* en el contenedor; si ninguna lo está, la primera pista de texto. Si el idioma de la pista es `es` o no tiene metadata de idioma, el texto MUST extraerse tal cual; si el idioma es distinto de `es`, el texto extraído MUST traducirse al español mediante Argos. Si todas las pistas de subtítulos son de bitmap (PGS/DVB), el sistema MUST emitir un WARN y transcribir el audio como fallback.

#### Scenario: pista embebida en español

- GIVEN un video con una pista de subtítulos de texto `language=es`
- WHEN se procesa sin `--no-extract`
- THEN el `.srt` se genera extrayendo esa pista tal cual, en segundos, sin transcribir audio

#### Scenario: pista embebida en otro idioma

- GIVEN un video con una pista de texto `language=en`
- WHEN se procesa sin `--no-extract`
- THEN la pista se extrae y su texto se traduce al español con Argos según el ruteo de traducción
- AND no se ejecuta transcripción de audio

#### Scenario: solo pistas bitmap

- GIVEN un video cuya única pista de subtítulos es de bitmap (PGS/DVB)
- WHEN se procesa
- THEN se emite un WARN indicando que la extracción no es posible
- AND el audio se transcribe como fallback

#### Scenario: --no-extract fuerza transcripción

- GIVEN un video con pista de texto `language=en` y la opción `--no-extract`
- WHEN se procesa
- THEN la pista embebida se ignora y el audio se transcribe

#### Scenario: elección de pista preferida

- GIVEN un video con varias pistas de texto
- WHEN se elige la pista a extraer
- THEN se usa la marcada como *default* si existe; si ninguna lo está, la primera pista de texto

### Requirement: Transcripción local del audio

Cuando no hay pista de texto utilizable (sin pistas, solo bitmap, o `--no-extract`), el sistema MUST transcribir el audio con faster-whisper en CPU con cuantización int8, VAD activado y autodetección de idioma; con `--lang` distinto de `auto`, MUST usarse el idioma fijado en lugar de la detección. Si el idioma resultante es `es`, los segmentos van directo al SRT; si es otro idioma, el texto de los segmentos MUST traducirse al español con Argos. Durante la transcripción, el sistema MUST mostrar progreso en una sola línea (porcentaje y ETA) redibujada al completarse segmentos, alimentada por el extremo de cada segmento respecto de la duración del video.

#### Scenario: transcripción de video en español

- GIVEN un video sin pistas de subtítulos cuyo audio está en español
- WHEN se transcribe con `--lang auto`
- THEN se detecta `es` y los segmentos se escriben directo al SRT sin traducción

#### Scenario: transcripción de video en inglés

- GIVEN un video sin pistas de subtítulos cuyo audio está en inglés
- WHEN se transcribe
- THEN los segmentos se traducen al español con Argos antes de escribir el SRT

#### Scenario: progreso en una línea

- GIVEN una transcripción en curso
- WHEN se completan segmentos
- THEN la consola redibuja una única línea con porcentaje y ETA, sin acumular una línea por segmento

### Requirement: Ruteo de traducción Argos

Cuando hay que traducir texto al español, el sistema MUST elegir ruta sobre los pares de Argos instalados: par directo `origen→es` si existe; si no, pivote vía inglés (`origen→en` + `en→es`). Si no existe ningún camino, el sistema MUST intentar una descarga en demanda one-time de los pares faltantes: el par directo `(origen, destino)` primero y, si el índice no lo ofrece, las dos patas del pivote `(origen, en)` y `(en, destino)`; tras una instalación exitosa MUST re-resolver la ruta y traducir por la nueva ruta. Si la descarga no es posible (sin red, par desconocido para el índice, instalación rota), el sistema MUST emitir un WARN y producir la salida en el idioma original sin romper la corrida; ese archivo MUST NOT contarse como failed por culpa de la traducción. La descarga en demanda MUST ser one-time: si los pares ya alcanzan para armar una ruta, el sistema MUST NOT consultar el índice ni descargar nada. La traducción y la transcripción operan localmente una vez descargados los modelos; la red solo MAY usarse para la primera descarga/instalación de modelos y paquetes y para esta descarga en demanda de pares faltantes.

#### Scenario: par directo

- GIVEN pares instalados que incluyen `en→es`, y texto en inglés por traducir
- WHEN se traduce
- THEN se usa el par directo `en→es` y el SRT queda en español

#### Scenario: pivote vía inglés

- GIVEN pares instalados con `de→en` y `en→es` pero sin `de→es`
- WHEN se traduce texto en alemán
- THEN se traduce por pivote `de→en→es` y el SRT queda en español

#### Scenario: descarga en demanda del par directo

- GIVEN pares instalados que no alcanzan para traducir `origen→es`, y un índice que ofrece el par directo `origen→es`
- WHEN se procesa ese archivo
- THEN se descarga e instala SOLO el par directo, consultando el índice una única vez
- AND la ruta se re-resuelve como directa y el texto se traduce al español

#### Scenario: descarga en demanda de las patas del pivote

- GIVEN un índice que NO ofrece el par directo `origen→es` pero sí `origen→en` y `en→es`
- WHEN se procesa ese archivo
- THEN se descargan las dos patas del pivote y la ruta se re-resuelve como pivote `origen→en→es`

#### Scenario: descarga one-time no repite trabajo

- GIVEN pares ya instalados que alcanzan para armar una ruta de traducción
- WHEN se procesa otro archivo con el mismo idioma origen
- THEN no se consulta el índice ni se descarga ningún paquete

#### Scenario: sin camino incluso tras la descarga en demanda

- GIVEN un idioma origen sin par directo ni camino vía inglés, y un entorno sin red (o un índice que no ofrece los pares necesarios)
- WHEN se procesa ese archivo
- THEN se intenta la descarga en demanda una sola vez, se emite un WARN y la salida se produce en el idioma original (sufijada, según el Requirement de escritura y nombres)
- AND la corrida continúa y ese archivo no se cuenta como failed

### Requirement: Formato del archivo SRT

El `.srt` generado MUST ser un SRT válido: cues numerados consecutivamente `1..n`, timestamps con formato `HH:MM:SS,mmm --> HH:MM:SS,mmm` (coma decimal), una línea en blanco entre cues, codificación UTF-8 con BOM y saltos de línea CRLF. El texto de cada cue SHOULD ajustarse en líneas de aproximadamente 42 caracteres y MUST ocupar como máximo 2 líneas por cue; el texto que no quepa en ese presupuesto MUST repartirse en cues adicionales y nunca MUST perderse texto en el proceso.

#### Scenario: verificación de formato

- GIVEN un `.srt` generado por una corrida exitosa
- WHEN se inspecciona el archivo a nivel de bytes
- THEN comienza con BOM UTF-8 y usa CRLF como salto de línea
- AND los cues están numerados consecutivamente desde 1 con timestamps `HH:MM:SS,mmm --> HH:MM:SS,mmm`
- AND hay exactamente una línea en blanco entre cues

#### Scenario: ajuste de línea

- GIVEN un segmento de texto más largo que una línea de ~42 caracteres
- WHEN se formatea el SRT
- THEN el texto se reparte en líneas de ~42 caracteres, sin exceder 2 líneas por cue, repartiendo el excedente en cues adicionales y sin perder texto

### Requirement: Escritura atómica y ubicación de salida

El `.srt` principal MUST escribirse junto al video con el mismo nombre base (`video.mp4` → `video.srt`) para que los reproductores lo carguen por defecto. Cuando el idioma de origen difiere del destino (normalizado a código corto ISO 639-1) y se intentó traducir, el sistema MUST escribir TAMBIÉN el subtítulo en el idioma original como `<stem>-<lang>.srt` (guion + código corto; si el idioma es desconocido, `<stem>-orig.srt`). El orden de escritura MUST ser: primero el original sufijado y después el principal traducido. Si la traducción falla (sin ruta incluso tras la descarga en demanda, o idioma desconocido), el sistema MUST escribir SOLO el original sufijado. Cuando el origen ya es el destino (español), la salida MUST ser única (`video.srt`, sin duplicado sufijado). Toda escritura MUST ser atómica: contenido completo a un archivo temporal seguido de rename atómico, de modo que nunca quede visible un `.srt` parcial. Si el procesamiento de un archivo falla, MUST eliminarse cualquier salida parcial de ese archivo (principal y sufijada). La lógica de SKIP y `--force` MUST seguir llaveada al `.srt` principal; con `--force` el sistema MUST regenerar ambas salidas.

#### Scenario: salida principal junto al video

- GIVEN un video `input/video.mp4` con pista en español procesado con éxito
- WHEN termina su turno
- THEN existe `input/video.srt` con el contenido completo y NO existe un duplicado sufijado

#### Scenario: doble salida con origen distinto del destino

- GIVEN un video `video.mp4` con pista en inglés y la traducción disponible
- WHEN termina su turno
- THEN existen `video-en.srt` con el texto original y `video.srt` con la traducción al español

#### Scenario: idioma de origen desconocido

- GIVEN un archivo cuyo idioma de origen no puede normalizarse a 639-1 y se intentó traducir
- WHEN termina su turno
- THEN el original se conserva como `<stem>-orig.srt`

#### Scenario: fallo de traducción deja solo el original sufijado

- GIVEN un video con pista en inglés sin ruta de traducción posible (sin red y sin paquetes instalables)
- WHEN termina su turno con un WARN
- THEN existe SOLO `video-en.srt` con el texto original y NO existe `video.srt`

#### Scenario: fallo a mitad de generación

- GIVEN un archivo cuyo procesamiento falla después de iniciada la escritura
- WHEN la corrida reporta el fallo
- THEN no queda ningún `.srt` parcial (principal ni sufijado) ni `.tmp` en el directorio del video

### Requirement: SKIP y --force sobre .srt existente

Si ya existe un `.srt` junto al video y no se pasa `--force`, el sistema MUST omitir ese archivo (SKIP) con una advertencia, sin reprocesarlo. Con `--force`, el sistema MUST regenerar el `.srt` aunque exista.

#### Scenario: .srt existente sin --force

- GIVEN `video.mp4` y `video.srt` ya existentes
- WHEN se corre sin `--force`
- THEN el archivo se reporta como SKIP con advertencia y el `.srt` existente no se modifica

#### Scenario: --force regenera

- GIVEN `video.mp4` y `video.srt` ya existentes
- WHEN se corre con `--force`
- THEN el `.srt` se regenera por completo

### Requirement: --dry-run

Con `--dry-run`, el sistema MUST imprimir por archivo el plan (sondeo → ruta elegida → salida esperada) sin procesar ni escribir ninguna salida. En el plan, los `.srt` existentes sin `--force` se reportan como SKIP.

#### Scenario: plan sin procesar

- GIVEN un video transcribible y la opción `--dry-run`
- WHEN se ejecuta la corrida
- THEN se imprime el plan por archivo con sondeo, ruta elegida y salida esperada
- AND no se crea ningún `.srt` ni se descargan modelos

#### Scenario: dry-run con .srt existente

- GIVEN un video con `.srt` existente, `--dry-run` y sin `--force`
- WHEN se imprime el plan
- THEN ese archivo se reporta como SKIP

### Requirement: Códigos de salida y resumen

Al final de la corrida el sistema MUST imprimir un resumen con la forma `TOTAL: N ok, M failed, K skipped` y terminar con exit code `0` cuando no hubo fallos (incluye corridas solo ok/skipped y dry-run) y `1` cuando hubo al menos un fallo. La interrupción con Ctrl-C MUST terminar con exit code `130`.

#### Scenario: corrida con mezcla de resultados

- GIVEN una corrida donde un archivo termina ok, uno falla (sin audio) y uno se omite (`.srt` existente)
- WHEN termina la corrida
- THEN se imprime `TOTAL: 1 ok, 1 failed, 1 skipped` y el exit code es `1`

#### Scenario: corrida sin fallos

- GIVEN una corrida donde todos los archivos terminan ok o skipped
- WHEN termina la corrida
- THEN el exit code es `0`

#### Scenario: interrupción con Ctrl-C

- GIVEN una corrida en curso
- WHEN el usuario presiona Ctrl-C
- THEN el proceso termina con exit code `130`

### Requirement: Resolución de entradas y selector interactivo

Sin `INPUT` posicional, el sistema MUST ofrecer un selector interactivo sobre `--input-dir` (default `input`): lista numerada de videos, selección con sintaxis `1 3 5-7` (rangos inclusivos), `a` para todos y `q` para salir; una entrada inválida o fuera de rango vuelve a preguntar. Si la carpeta no existe, MUST crearse acompañada de una guía para el usuario. Las rutas pasadas como argumentos MUST deduplicarse (misma ruta resuelta se procesa una sola vez).

#### Scenario: selección por rangos

- GIVEN un `input/` con 7 videos listados por el selector
- WHEN el usuario responde `1 3 5-7`
- THEN se procesan los videos 1, 3, 5, 6 y 7

#### Scenario: todos y salir

- GIVEN el selector en pantalla
- WHEN el usuario responde `a` o `q`
- THEN `a` selecciona todos los videos listados y `q` abandona sin procesar

#### Scenario: carpeta inexistente

- GIVEN `--input-dir` apuntando a una carpeta que no existe
- WHEN se lanza el selector
- THEN la carpeta se crea y se muestra una guía para colocar videos ahí

### Requirement: Superficie CLI

El comando MUST aceptar `python subtitler.py [OPTIONS] [INPUT ...]` con las opciones `--input-dir` (default `input`), `--model` (registro tiny/base/small/medium/large-v3, default `small`), `--lang` (default `auto`), `--target` (registro; hoy solo `es` implementado), `--no-extract`, `--force` y `--dry-run`. Un valor registrado pero no implementado MUST rechazarse con un error claro que liste los valores implementados disponibles. El registro de modelos e idiomas MAY ampliarse en el futuro sin cambiar esta superficie.

#### Scenario: opción registrada no implementada

- GIVEN el registro de `--target` con `es` como único valor implementado
- WHEN se pasa `--target en`
- THEN el comando falla con un error que lista los valores implementados

#### Scenario: modelo no default elegido

- GIVEN la opción `--model medium` (valor registrado e implementado)
- WHEN se parsea la línea de comandos
- THEN la corrida usa el modelo `medium` en lugar del default `small`

### Requirement: Verificación de herramientas

Antes de procesar archivos, la corrida MUST verificar que `ffmpeg` y `ffprobe` están disponibles en PATH; si falta alguna, MUST terminar con exit code `1` y un mensaje claro, sin procesar archivos.

#### Scenario: ffprobe ausente

- GIVEN un entorno donde `ffprobe` no está en PATH
- WHEN se ejecuta `python subtitler.py video.mp4`
- THEN la corrida termina con exit code `1` y un mensaje claro, sin procesar el video
