#!/usr/bin/env python3
"""py-video-subtitler: generación local de subtítulos .srt en español.

Genera, junto a cada video elegido, un archivo ``<stem>.srt`` en español
listo para VLC/MPC-HC: ``video.mp4 -> video.srt``. Cuando el idioma de origen
no es español, TAMBIÉN escribe el original como ``<stem>-<lang>.srt`` (o
``-orig`` si el idioma es desconocido) para conservar la fuente; si la
traducción no es posible, solo se escribe el original sufijado. La operación
es local (CPU); la red solo interviene en la primera descarga de modelos y en
la descarga one-time de pares Argos faltantes (en demanda). Un archivo
problemático falla solo y nunca interrumpe el resto de la tanda.

Puntos de diseño:

* Espejo estructural de convert.py (py-video-converter): registros y
  constantes al tope, pipeline por archivo que nunca aborta, selector
  interactivo y suite de humo con biblioteca estándar.
* Prioridad de fuente por archivo: pista de subtítulos embebida de texto
  (extracción con ffmpeg en segundos) y, solo como respaldo (sin pistas,
  solo bitmap o --no-extract), transcripción local con faster-whisper
  (CPU, int8, VAD) seguida de traducción Argos si el idioma no es español.
* Descarga en demanda (D13): sin ruta Argos, se intenta instalar el par
  directo (origen, destino) y, si el índice no lo ofrece, las dos patas del
  pivote vía inglés; one-time y con fallback amable (WARN + original).
* Imports pesados perezosos: faster_whisper y argostranslate se importan
  dentro de las funciones que los usan, nunca a nivel de módulo.
* Seguro para Windows: ffmpeg/ffprobe siempre se invocan como listas de
  argumentos, nunca a través de una shell.

Requiere ffmpeg/ffprobe del sistema y, para transcribir/traducir, los
paquetes de requirements.txt (faster-whisper, argostranslate).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
SRT_LINE_MAX_CHARS = 42  # política cerrada de spec/PLAN: líneas ~42 caracteres
SRT_MAX_LINES_PER_CUE = 2  # política cerrada de spec/PLAN: máx 2 líneas por cue
# Allowlist de codecs de subtítulos de texto; lo no listado cae a bitmap.
TEXT_SUBTITLE_CODECS = {"subrip", "srt", "mov_text", "ass", "ssa", "webvtt", "text"}
FFPROBE_TIMEOUT_S = 30  # espejo converter; sondeo es instantáneo
FFMPEG_EXTRACT_TIMEOUT_S = 300  # extracción de texto es rápida; margen grande
STDERR_TAIL_CHARS = 300  # detalle de error recortado, espejo converter
PROGRESS_BAR_WIDTH = 24  # espejo de la línea de progreso
PROGRESS_MIN_INTERVAL_S = 0.1  # evita parpadeo/redibujado en ráfaga
WHISPER_BEAM_SIZE = 5  # default razonable de faster-whisper


@dataclass(frozen=True)
class ModelSpec:
    """Especificación de un modelo Whisper del registro ``--model``."""

    device: str = "cpu"  # GPU AMD sin CUDA -> CPU only (PLAN cerrado)
    compute_type: str = "int8"  # ~4x vs Whisper original en CPU (PLAN cerrado)
    implemented: bool = True


@dataclass(frozen=True)
class LangSpec:
    """Entrada de un registro de idiomas con marca de implementación."""

    implemented: bool = False


MODELS: dict[str, ModelSpec] = {
    "tiny": ModelSpec(),
    "base": ModelSpec(),
    "small": ModelSpec(),
    "medium": ModelSpec(),
    "large-v3": ModelSpec(),
}
DEFAULT_MODEL = "small"

# --lang: solo se pasan a Whisper / al ruteo; "auto" = autodetección.
SOURCE_LANGS: dict[str, LangSpec] = {
    "auto": LangSpec(True),
    "es": LangSpec(True),
    "en": LangSpec(True),
    "de": LangSpec(True),
    "fr": LangSpec(True),
    "it": LangSpec(True),
    "pt": LangSpec(True),
    "ru": LangSpec(True),
    "ja": LangSpec(True),
    "zh": LangSpec(True),
}
# --target: registro extensible, hoy solo "es" implementado.
TARGET_LANGS: dict[str, LangSpec] = {"es": LangSpec(True)}
DEFAULT_TARGET = "es"

# Extensiones de video aceptadas (espejo del converter; sin punto).
VIDEO_EXTENSIONS = {
    "mp4",
    "mkv",
    "mov",
    "avi",
    "webm",
    "m4v",
    "mpg",
    "mpeg",
    "ts",
    "wmv",
    "flv",
}


def _safe_int(value: object, default: int = 0) -> int:
    """Convierte a int lo mejor posible; devuelve ``default`` si algo falla."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _to_float(value: object) -> float | None:
    """Convierte a float campos de ffprobe que llegan como cadena, si es posible."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class MediaError(RuntimeError):
    """Se lanza cuando un archivo de medios no puede sondearse."""


# --------------------------------------------------------------------------- #
# Tipos de datos
# --------------------------------------------------------------------------- #


@dataclass
class Cue:
    """Un segmento de subtítulo: intervalo en segundos y texto sin envolver."""

    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True)
class TranslationRoute:
    """Ruta de traducción elegida sobre los pares Argos instalados."""

    kind: str  # "direct" | "pivot" | "none"
    hops: tuple[tuple[str, str], ...]


@dataclass
class TranslationOutcome:
    """Resultado de un intento de traducción de cues (D13).

    ``original`` son los cues tal cual llegaron; ``original_lang`` es el código
    639-1 del idioma de origen (None si es desconocido); ``translated`` son los
    cues traducidos al destino, o None si la traducción no fue posible (sin
    ruta incluso tras la descarga en demanda, o idioma desconocido).
    """

    original: list[Cue]
    original_lang: str | None
    translated: list[Cue] | None


@dataclass
class SubtitleStream:
    """Una pista de subtítulos del sondeo ffprobe."""

    index: int
    codec_name: str
    is_text: bool
    language: str | None
    disposition_default: bool


@dataclass
class ProbeInfo:
    """Metadatos relevantes de un video sondeado con ffprobe."""

    path: Path
    duration_s: float
    has_audio: bool
    subtitle_streams: list[SubtitleStream]


@dataclass(frozen=True)
class ExtractionDecision:
    """Qué hacer con un archivo según sus pistas y las opciones (C8)."""

    kind: str  # "extract" | "extract_translate" | "transcribe_no_track" |
    # "transcribe_bitmap" | "transcribe_forced"
    stream_index: int | None
    language: str | None


@dataclass
class ProducedSubtitles:
    """Cues producidos para un archivo, antes de escribir salidas (D14).

    ``original`` son los cues en el idioma fuente; ``final`` son los cues de la
    salida principal (traducidos al destino) o None si la traducción falló;
    ``lang`` es el código 639-1 del idioma fuente (None si es desconocido);
    ``attempted`` indica si se intentó traducir (solo entonces procede la
    salida original sufijada de la doble salida).
    """

    original: list[Cue]
    final: list[Cue] | None
    lang: str | None
    attempted: bool


@dataclass(frozen=True)
class SubtitlerOptions:
    """Opciones de CLI validadas, compartidas por todos los archivos de la corrida."""

    model: str
    lang: str
    target: str
    no_extract: bool
    force: bool
    dry_run: bool
    input_dir: str


@dataclass
class FileResult:
    """Resultado de un intento de subtulación de un archivo."""

    src: Path
    out_path: Path | None = None
    status: str = "failed"  # "ok" | "failed" | "skipped"
    detail: str = ""
    elapsed_s: float = 0.0
    cues: int = 0
    route: str = ""


# --------------------------------------------------------------------------- #
# Auxiliares de formateo SRT (costuras puras)
# --------------------------------------------------------------------------- #


def format_srt_timestamp(seconds: float) -> str:
    """Formatea segundos como HH:MM:SS,mmm (coma decimal) para un cue SRT.

    Clampa negativos a 0 y redondea al milisegundo.
    """
    total_ms = round(max(0.0, seconds) * 1000)
    total_s, ms = divmod(total_ms, 1000)
    hours, remainder = divmod(total_s, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def wrap_text(text: str, max_chars: int = SRT_LINE_MAX_CHARS) -> list[str]:
    """Reparte ``text`` en líneas greedy por palabras de ``max_chars`` caracteres.

    Nunca corta una palabra: una palabra más larga que la línea queda sola en
    su línea.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def split_cue(cue: Cue) -> list[Cue]:
    """Aplica la política de líneas (42/máx 2) a un cue.

    Si el texto envuelto excede ``SRT_MAX_LINES_PER_CUE`` líneas, reparte en
    cues contiguos dividiendo el intervalo ``[start, end]`` proporcionalmente
    al conteo de caracteres de cada bloque, con gap mínimo de 1 ms. El texto
    jamás se pierde: solo se reparte.
    """
    lines = wrap_text(cue.text)
    if len(lines) <= SRT_MAX_LINES_PER_CUE:
        return [cue]
    blocks = [
        lines[i : i + SRT_MAX_LINES_PER_CUE]
        for i in range(0, len(lines), SRT_MAX_LINES_PER_CUE)
    ]
    weights = [len(" ".join(block)) for block in blocks]
    total_chars = sum(weights)
    duration = cue.end_s - cue.start_s
    out: list[Cue] = []
    cursor = cue.start_s
    covered = 0
    for i, block in enumerate(blocks):
        covered += weights[i]
        if i == len(blocks) - 1:
            end = cue.end_s
        else:
            end = cue.start_s + duration * (covered / total_chars)
        if end <= cursor:
            end = cursor + 0.001  # gap mínimo 1 ms
        out.append(Cue(cursor, end, " ".join(block)))
        cursor = end
    return out


def render_srt(cues: list[Cue]) -> str:
    """Renderiza cues a un cuerpo SRT completo: numeración 1..n, timestamps
    ``HH:MM:SS,mmm --> HH:MM:SS,mmm``, \\r\\n como único salto y exactamente
    una línea en blanco entre cues (más el cierre final).
    """
    expanded: list[Cue] = []
    for cue in cues:
        expanded.extend(split_cue(cue))
    blocks: list[str] = []
    for number, cue in enumerate(expanded, 1):
        lines = wrap_text(cue.text)
        assert len(lines) <= SRT_MAX_LINES_PER_CUE, (
            "invariante interna: cue con más de 2 líneas"
        )
        block_lines = [
            f"{format_srt_timestamp(cue.start_s)} --> {format_srt_timestamp(cue.end_s)}",
            *lines,
        ]
        blocks.append(f"{number}\r\n" + "\r\n".join(block_lines))
    return "\r\n\r\n".join(blocks) + "\r\n\r\n"


def _parse_srt_timestamp(text: str) -> float | None:
    """Interpreta 'HH:MM:SS,mmm' (o con punto) como segundos; None si no puede."""
    parts = text.strip().replace(",", ".").split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (float(part) for part in parts)
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def parse_srt(payload: str) -> list[Cue]:
    """Parseo tolerante de un SRT extraído por ffmpeg (C6).

    Acepta BOM y saltos \\r\\n o \\n, ignora la numeración original, elimina
    tags tipo <i>...</i> y une las líneas multi-línea de cada cue con espacio.
    """
    text = payload.lstrip("\ufeff").replace("\r\n", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line for line in block.split("\n") if line.strip()]
        arrow_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if arrow_index is None:
            continue
        start_raw, _, end_raw = lines[arrow_index].partition("-->")
        start = _parse_srt_timestamp(start_raw)
        end = _parse_srt_timestamp(end_raw)
        if start is None or end is None:
            continue
        content = " ".join(
            re.sub(r"<[^>]+>", "", line).strip() for line in lines[arrow_index + 1 :]
        )
        cues.append(Cue(start, end, " ".join(content.split())))
    return cues


# --------------------------------------------------------------------------- #
# Ruteo de traducción (costura pura + adaptador Argos)
# --------------------------------------------------------------------------- #


def resolve_translation_route(
    src: str, dst: str, pairs: frozenset[tuple[str, str]]
) -> TranslationRoute:
    """Elige la ruta de traducción (C7) sobre el conjunto de pares instalados.

    ``src == dst`` -> direct sin saltos (no se traduce); ``(src, dst)`` en
    pairs -> direct; si no, pivote vía inglés con 2 saltos; si no, ``none``
    (el caller emite WARN y produce el SRT en el idioma original).
    """
    if src == dst:
        return TranslationRoute("direct", ())
    if (src, dst) in pairs:
        return TranslationRoute("direct", ((src, dst),))
    if (src, "en") in pairs and ("en", dst) in pairs:
        return TranslationRoute("pivot", ((src, "en"), ("en", dst)))
    return TranslationRoute("none", ())


def download_candidates(src: str, dst: str) -> tuple[tuple[str, str], ...]:
    """Candidatos de descarga en demanda (D13), en orden de preferencia.

    Par directo ``(src, dst)`` primero; luego las dos patas del pivote vía
    inglés. Sin duplicados ni pares triviales ``(x, x)``: para ``en → es`` el
    resultado es solo el par directo (el origen ya es el pivote).
    """
    candidates: list[tuple[str, str]] = []
    for pair in ((src, dst), (src, "en"), ("en", dst)):
        if pair[0] != pair[1] and pair not in candidates:
            candidates.append(pair)
    return tuple(candidates)


# Códigos ISO 639-2/b de las etiquetas ffprobe -> 639-1 (Argos).
_LANG3_TO_LANG1 = {
    "spa": "es",
    "eng": "en",
    "deu": "de",
    "fra": "fr",
    "ita": "it",
    "por": "pt",
    "rus": "ru",
    "jpn": "ja",
    "zho": "zh",
    "ara": "ar",
    "hin": "hi",
    "kor": "ko",
    "tur": "tr",
    "vie": "vi",
    "tha": "th",
    "ind": "id",
    "msa": "ms",
    "tan": "ta",
    "tel": "te",
    "mar": "mr",
    "ben": "bn",
    "urd": "ur",
    "pan": "pa",
    "guj": "gu",
    "kan": "kn",
    "mal": "ml",
    "ori": "or",
    "asm": "as",
    "nep": "ne",
    "sin": "si",
    "khm": "km",
    "lao": "lo",
    "bur": "my",
    "kin": "rw",
    "som": "so",
    "swa": "sw",
    "zho": "zh",
    "yue": "zh",
    "ces": "cs",
    "pol": "pl",
    "slk": "sk",
    "hun": "hu",
    "ron": "ro",
    "bul": "bg",
    "srp": "sr",
    "hrv": "hr",
    "slv": "sl",
    "lit": "lt",
    "lav": "lv",
    "est": "et",
    "fin": "fi",
    "swe": "sv",
    "dan": "da",
    "nor": "no",
    "isl": "is",
    "ell": "el",
    "heb": "he",
    "yid": "yi",
    "afr": "af",
    "kat": "ka",
    "aze": "az",
    "kaz": "kk",
    "uzb": "uz",
    "tuk": "tk",
    "mon": "mn",
    "tgl": "tl",
    "may": "ms",
    "cym": "cy",
    "alb": "sq",
    "mkd": "mk",
    "sqi": "sq",
    "snd": "ku",
    "div": "dv",
    "fry": "fy",
    "lat": "la",
}


def _lang1(code: str | None) -> str | None:
    """Normaliza el código de idioma de ffprobe al formato de Argos (639-1)."""
    if not code:
        return None
    code = code.lower()
    if len(code) == 2:
        return code
    return _LANG3_TO_LANG1.get(code)


def installed_argos_pairs() -> frozenset[tuple[str, str]]:
    """Pares de traducción instalados en Argos (lazy import, D3)."""
    import argostranslate.package  # perezoso (D3): solo al traducir

    return frozenset(
        (package.from_code, package.to_code)
        for package in argostranslate.package.get_installed_packages()
    )


def _route_satisfiable(
    pairs_needed: Sequence[tuple[str, str]], installed: set[tuple[str, str]]
) -> bool:
    """True si los candidatos bastan para armar una ruta (D13).

    El par directo instalado alcanza; si no, las DOS patas del pivote completas.
    """
    if not pairs_needed:
        return False
    if pairs_needed[0] in installed:
        return True
    legs = pairs_needed[1:]
    return bool(legs) and all(leg in installed for leg in legs)


def ensure_pairs_installed(pairs_needed: Sequence[tuple[str, str]]) -> bool:
    """Descarga en demanda de pares Argos faltantes (D13, enmienda 5.5).

    One-time: si los candidatos ya alcanzan para armar una ruta, no toca red ni
    índice. Si no, actualiza el índice UNA vez y descarga en orden los pares
    faltantes que ofrezca el índice (directo primero, patas del pivote después),
    cortando en cuanto la ruta queda armada. Cualquier excepción (sin red,
    índice inaccesible, descarga o instalación rota, par desconocido) → False;
    jamás propaga: el caller conserva el fallback WARN + idioma original.
    """
    try:
        import argostranslate.package  # perezoso (D3): solo en la descarga

        installed = {
            (package.from_code, package.to_code)
            for package in argostranslate.package.get_installed_packages()
        }
        if _route_satisfiable(pairs_needed, installed):
            return True
        say("INFO actualizando índice de paquetes Argos…")
        argostranslate.package.update_package_index()
        available = {
            (package.from_code, package.to_code): package
            for package in argostranslate.package.get_available_packages()
        }
        for pair in pairs_needed:
            if pair in installed:
                continue
            package = available.get(pair)
            if package is None:
                continue  # el índice no ofrece este par; se prueban las patas
            say(f"INFO descargando paquete Argos {pair[0]}→{pair[1]}…")
            argostranslate.package.install_from_path(package.download())
            installed.add(pair)
            if _route_satisfiable(pairs_needed, installed):
                break
        return _route_satisfiable(pairs_needed, installed)
    except Exception:  # noqa: BLE001 — jamás propaga (contrato D13: fallback)
        return False


def build_translator(route: TranslationRoute):
    """Construye el traductor para la ruta elegida (§4.4).

    ``none`` -> identidad (el caller ya emitió WARN); directo -> un salto;
    pivote -> dos saltos encadenados.
    """
    if route.kind == "none":
        return lambda text: text
    import argostranslate.translate  # perezoso (D3): solo al traducir

    hops = [
        (
            lambda text, src=src, dst=dst: argostranslate.translate.translate(
                text, src, dst
            )
        )
        for src, dst in route.hops
    ]

    def translate_chain(text: str) -> str:
        for hop in hops:
            text = hop(text)
        return text

    return translate_chain


def apply_translation(
    cues: list[Cue], src_lang: str | None, target: str
) -> TranslationOutcome:
    """Traduce los cues al destino según la ruta Argos (S14-S16, D13).

    Devuelve un TranslationOutcome. ``translated`` es None cuando no hay camino
    (o el idioma es desconocido) incluso tras la descarga en demanda de pares;
    en ese caso aquí se emite el WARN y el caller conserva el idioma original.
    El archivo NUNCA cuenta como failed por culpa de la traducción.
    """
    src = _lang1(src_lang)
    if src is None:
        say("WARN idioma de origen desconocido; se conserva el idioma original")
        return TranslationOutcome(cues, None, None)
    if src == target:
        return TranslationOutcome(cues, src, cues)
    installed = installed_argos_pairs()
    route = resolve_translation_route(src, target, installed)
    if route.kind == "none":
        candidates = download_candidates(src, target)
        if ensure_pairs_installed(candidates):
            installed = installed_argos_pairs()
            route = resolve_translation_route(src, target, installed)
    if route.kind == "none":
        say(
            f"WARN sin ruta de traducción {src}→{target} en los pares instalados; "
            "se conserva el idioma original"
        )
        return TranslationOutcome(cues, src, None)
    if route.kind == "direct" and not route.hops:
        return TranslationOutcome(cues, src, cues)
    translator = build_translator(route)
    say(f"traduciendo {len(cues)} segmentos ({route.kind})…")
    return TranslationOutcome(
        cues,
        src,
        [Cue(cue.start_s, cue.end_s, translator(cue.text)) for cue in cues],
    )


# --------------------------------------------------------------------------- #
# Sondeo de medios (ffprobe)
# --------------------------------------------------------------------------- #


def pick_subtitle_track(streams: list[SubtitleStream]) -> SubtitleStream | None:
    """Elige la pista de subtítulos preferida: la marcada como *default*; si
    no la hay, la primera de texto. Devuelve None si solo hay bitmap.
    """
    text_streams = [s for s in streams if s.is_text]
    for candidate in text_streams:
        if candidate.disposition_default:
            return candidate
    return text_streams[0] if text_streams else None


def decide_extraction(info: ProbeInfo, no_extract: bool) -> ExtractionDecision:
    """Decide la ruta por archivo (C8) a partir del sondeo y --no-extract."""
    if no_extract:
        return ExtractionDecision("transcribe_forced", None, None)
    if not info.subtitle_streams:
        return ExtractionDecision("transcribe_no_track", None, None)
    track = pick_subtitle_track(info.subtitle_streams)
    if track is None:
        return ExtractionDecision("transcribe_bitmap", None, None)
    if track.language in (None, "es", "spa", "und"):
        return ExtractionDecision("extract", track.index, track.language)
    return ExtractionDecision("extract_translate", track.index, track.language)


def parse_probe_json(payload: str, path: Path) -> ProbeInfo:
    """Parsea el JSON de ffprobe (C9) en un ProbeInfo; tolerante a campos
    ausentes. Lanza MediaError si el JSON es inválido.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MediaError(f"could not parse ffprobe output for '{path.name}'") from exc
    streams = data.get("streams", [])
    subtitle_streams: list[SubtitleStream] = []
    for stream in streams:
        if stream.get("codec_type") != "subtitle":
            continue
        codec = str(stream.get("codec_name") or "")
        tags = stream.get("tags") or {}
        disposition = stream.get("disposition") or {}
        language = str(tags.get("language") or "").strip() or None
        subtitle_streams.append(
            SubtitleStream(
                index=_safe_int(stream.get("index")),
                codec_name=codec,
                is_text=codec in TEXT_SUBTITLE_CODECS,
                language=language,
                disposition_default=bool(_safe_int(disposition.get("default"))),
            )
        )
    duration = _to_float((data.get("format") or {}).get("duration"))
    if duration is None:
        for stream in streams:
            duration = _to_float(stream.get("duration"))
            if duration is not None:
                break
    return ProbeInfo(
        path=path,
        duration_s=duration if duration is not None else 0.0,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        subtitle_streams=subtitle_streams,
    )


def say(message: str = "") -> None:
    """Imprime con flush inmediato para mantener el orden de logs y progreso."""
    print(message, flush=True)


def _remove_quietly(path: Path) -> None:
    """Borra un archivo de salida parcial, ignorando errores de borrado."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def format_clock(seconds: float | None) -> str:
    """Formatea segundos como MM:SS (o H:MM:SS por encima de una hora)."""
    total = round(max(0.0, seconds or 0.0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


# --------------------------------------------------------------------------- #
# Renderizado de progreso
# --------------------------------------------------------------------------- #


def draw_progress(done_s: float, duration_s: float, elapsed_s: float) -> None:
    """Redibuja el indicador de progreso de una sola línea con \\r (S12).

    Matemática pura alimentada por el extremo de cada segmento:
    ``pct = done/duration``, ``speed = done/elapsed`` y
    ``ETA = elapsed * (1 - pct) / pct``. Tolerante a duration/elapsed nulos.
    """
    pct = done_s / duration_s if duration_s > 0 else 0.0
    pct = max(0.0, min(1.0, pct))
    speed = done_s / elapsed_s if elapsed_s > 0 else None
    speed_txt = f"{speed:.2f}x" if speed else "n/a"
    eta_s = elapsed_s * (1 - pct) / pct if speed and pct > 0 else None
    eta_txt = f"ETA {format_clock(eta_s)}" if eta_s is not None else "ETA --:--"
    filled = _safe_int(pct * PROGRESS_BAR_WIDTH)
    bar = "#" * filled + "-" * (PROGRESS_BAR_WIDTH - filled)
    line = f"\r  [{bar}] {pct * 100:5.1f}%  speed {speed_txt}  {eta_txt}   "
    sys.stdout.write(line)
    sys.stdout.flush()


def configure_utf8_stdio() -> None:
    """Fuerza stdio UTF-8 para que los nombres de archivo unicode se impriman
    de forma segura en Windows.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8", errors="replace")


def probe_media(path: Path) -> ProbeInfo:
    """Sondea ``path`` con ffprobe (JSON) y devuelve el ProbeInfo analizado.

    Lanza:
        MediaError: Si la ruta no existe, no es un archivo, ffprobe falta,
            falla, excede el timeout o emite un JSON inválido.
    """
    if not path.exists():
        raise MediaError(f"file not found: {path}")
    if not path.is_file():
        raise MediaError(f"not a regular file: {path}")
    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=FFPROBE_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise MediaError("ffprobe not found in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffprobe timed out on: {path.name}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:STDERR_TAIL_CHARS] or "unknown error"
        raise MediaError(f"ffprobe failed on '{path.name}': {detail}")
    return parse_probe_json(proc.stdout, path)


# --------------------------------------------------------------------------- #
# Extracción de pista embebida (ffmpeg)
# --------------------------------------------------------------------------- #


def extract_track(src: Path, stream_index: int) -> list[Cue]:
    """Extrae la pista embebida ``stream_index`` como SRT por pipe (S5).

    Devuelve los cues parseados con ``parse_srt`` (tags eliminados, política
    propia de formato). Lanza MediaError ante cualquier fallo de ffmpeg.
    """
    cmd = [
        FFMPEG,
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-map",
        f"0:{stream_index}",
        "-c:s",
        "srt",
        "-f",
        "srt",
        "pipe:1",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=FFMPEG_EXTRACT_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise MediaError("ffmpeg not found in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffmpeg timed out extracting: {src.name}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:STDERR_TAIL_CHARS] or "unknown error"
        raise MediaError(f"ffmpeg failed extracting '{src.name}': {detail}")
    return parse_srt(proc.stdout)


def write_srt_atomic(out: Path, body: str) -> None:
    """Escritura atómica del SRT (S20): todo el cuerpo a ``<out>.tmp`` con
    BOM UTF-8 y \\r\\n literales, y luego rename atómico con ``os.replace``.
    """
    tmp = out.with_name(out.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(body)
        os.replace(tmp, out)
    except OSError:
        _remove_quietly(tmp)
        raise


# --------------------------------------------------------------------------- #
# Transcripción (faster-whisper, lazy)
# --------------------------------------------------------------------------- #


def transcribe_cues(
    path: Path, model_name: str, spec: ModelSpec, lang: str, duration_s: float
) -> tuple[list[Cue], str]:
    """Transcribe el audio con faster-whisper (import perezoso, D3).

    ``lang == "auto"`` delega la detección; VAD activado y beam configurable.
    Devuelve ``(cues, idioma_detectado)`` con un Cue por segmento y ``strip()``
    por convención de espacio inicial. Progreso en una línea (S12) alimentada
    por el extremo de cada segmento respecto de la duración del video.
    """
    import faster_whisper  # perezoso (D3): solo se importa al transcribir

    model = faster_whisper.WhisperModel(
        model_name, device=spec.device, compute_type=spec.compute_type
    )
    segments, info = model.transcribe(
        str(path),
        language=None if lang == "auto" else lang,
        vad_filter=True,
        beam_size=WHISPER_BEAM_SIZE,
    )
    started = time.monotonic()
    last_draw = 0.0
    cues: list[Cue] = []
    for segment in segments:
        text = (segment.text or "").strip()
        start = _to_float(segment.start)
        if start is None:
            continue
        end = _to_float(segment.end)
        if end is None or end <= start:
            end = start
        cues.append(Cue(start, end, text))
        if duration_s > 0:
            now = time.monotonic()
            if now - last_draw >= PROGRESS_MIN_INTERVAL_S:
                last_draw = now
                draw_progress(end, duration_s, now - started)
    if duration_s > 0 and cues:
        say()  # salto de línea final tras el último \\r
    detected = str(getattr(info, "language", None) or "auto")
    return cues, detected


# --------------------------------------------------------------------------- #
# Resolución de entradas y selector interactivo
# --------------------------------------------------------------------------- #


def parse_selection(text: str, count: int) -> list[int] | None:
    """Interpreta una selección del selector como '1 3 5-7' en índices base 0.

    Devuelve None cuando la selección está vacía o es inválida. 'a' y 'q' se
    manejan en el bucle interactivo, no aquí.
    """
    indices: set[int] = set()
    for token in re.split(r"[,\s]+", text.strip()):
        if not token:
            continue
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
        if match:
            low, high = _safe_int(match.group(1)), _safe_int(match.group(2))
            if low > high:
                low, high = high, low
            if low < 1 or high > count:
                return None
            indices.update(range(low - 1, high))
            continue
        if token.isdigit():
            number = _safe_int(token)
            if number < 1 or number > count:
                return None
            indices.add(number - 1)
            continue
        return None
    return sorted(indices) if indices else None


def resolve_inputs(input_dir: Path, raw_inputs: Sequence[str]) -> list[Path]:
    """Devuelve la lista deduplicada de archivos a procesar (C10).

    Deduplica por ``expanduser().resolve()`` conservando el orden de primera
    aparición; sin argumentos delega en el selector interactivo. Valida que
    cada ruta exista y sea un archivo regular; emite WARN por archivos
    problemáticos y los omite sin abortar la corrida.
    """
    if raw_inputs:
        seen: dict[Path, None] = {}
        for raw in raw_inputs:
            resolved = Path(raw).expanduser().resolve()
            if not resolved.exists():
                say(f"WARN archivo no encontrado, se omite: {raw}")
                continue
            if not resolved.is_file():
                say(f"WARN no es un archivo regular, se omite: {raw}")
                continue
            seen.setdefault(resolved, None)
        return list(seen)
    return interactive_select(input_dir)


def list_videos(directory: Path) -> list[Path]:
    """Lista los videos procesables de ``directory``, ordenados por nombre."""
    if not directory.is_dir():
        return []
    files = [
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower().lstrip(".") in VIDEO_EXTENSIONS
    ]
    return sorted(files, key=lambda p: p.name.lower())


def interactive_select(directory: Path) -> list[Path]:
    """Selecciona videos de ``directory`` en forma interactiva vía input()."""
    if not directory.is_dir():
        directory.mkdir(parents=True, exist_ok=True)
    videos = list_videos(directory)
    if not videos:
        say(
            f"La carpeta '{directory}' está vacía o no tiene videos (creada si no existía)."
        )
        say("Coloca videos ahí, o pasa rutas completas como argumentos, p. ej.:")
        say('  python subtitler.py "C:\\ruta\\mi video.mp4"')
        return []
    say(f"Videos en {directory}:")
    for index, path in enumerate(videos, 1):
        say(f"  {index:>2}. {path.name}")
    while True:
        try:
            raw = input(
                "Selecciona archivos (ej. '1 3 5-7', 'a'=todos, 'q'=salir): "
            ).strip()
        except EOFError:
            return []
        lowered = raw.lower()
        if lowered in ("q", "quit", "salir"):
            return []
        if lowered in ("a", "all", "todos"):
            return videos
        indices = parse_selection(raw, len(videos))
        if not indices:
            say(
                "Selección inválida. Usa números/rangos como '1 3 5-7', "
                "'a' para todos, 'q' para salir."
            )
            continue
        return [videos[i] for i in indices]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de CLI con argparse a partir de los registros."""
    parser = argparse.ArgumentParser(
        prog="subtitler.py",
        description=(
            "Genera un .srt en español junto a cada video (video.mp4 -> "
            "video.srt), listo para VLC/MPC-HC."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        metavar="INPUT",
        help=(
            "videos a procesar; omitir para elegir de forma interactiva "
            "desde --input-dir"
        ),
    )
    parser.add_argument(
        "--input-dir",
        default="input",
        metavar="DIR",
        help="carpeta que escanea el selector interactivo",
    )
    parser.add_argument(
        "--model",
        choices=tuple(MODELS),
        default=DEFAULT_MODEL,
        help="modelo Whisper para transcribir",
    )
    parser.add_argument(
        "--lang",
        choices=tuple(SOURCE_LANGS),
        default="auto",
        help="idioma del audio (auto = autodetección)",
    )
    parser.add_argument(
        "--target",
        choices=tuple(TARGET_LANGS),
        default=DEFAULT_TARGET,
        help="idioma destino de los subtítulos",
    )
    parser.add_argument(
        "--no-extract",
        action="store_true",
        help="ignora las pistas embebidas y siempre transcribe",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="regenera el .srt aunque ya exista",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="imprime el plan por archivo sin procesar ni escribir nada",
    )
    return parser


def validate_registry_choices(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """Rechaza valores registrados pero sin implementar, con errores claros."""
    checks = (
        ("--model", MODELS, args.model),
        ("--lang", SOURCE_LANGS, args.lang),
        ("--target", TARGET_LANGS, args.target),
    )
    for flag, table, value in checks:
        entry = table[value]
        if not entry.implemented:
            available = [name for name, spec in table.items() if spec.implemented]
            parser.error(
                f"{flag} {value!r} está registrado pero aún no está implementado "
                f"en esta versión (disponibles: {', '.join(available)})"
            )


# --------------------------------------------------------------------------- #
# Pipeline por archivo
# --------------------------------------------------------------------------- #


def plan_line(src: Path, decision: ExtractionDecision, skip: bool, model: str) -> str:
    """Construye la línea de plan exacta de --dry-run (§4.3).

    Forma: ``  [plan] <nombre> → <ruta elegida> → <salida esperada>`` con la
    mención del modelo al final; la salida es ``SKIP (.srt existe)`` cuando
    corresponde omitir.
    """
    if decision.kind == "extract":
        ruta = f"extraer pista #{decision.stream_index} ({decision.language})"
    elif decision.kind == "extract_translate":
        ruta = (
            f"extraer pista #{decision.stream_index} ({decision.language}) + traducir"
        )
    elif decision.kind == "transcribe_no_track":
        ruta = "transcribir (sin pistas)"
    elif decision.kind == "transcribe_bitmap":
        ruta = "transcribir (bitmap: extracción imposible)"
    else:
        ruta = "transcribir (--no-extract)"
    salida = "SKIP (.srt existe)" if skip else src.with_suffix(".srt").name
    return f"  [plan] {src.name} → {ruta} → {salida} · modelo {model}"


def subtitlar_one(src: Path, options: SubtitlerOptions) -> FileResult:
    """Genera el .srt de un único archivo según ``options``. Nunca lanza."""
    say(f"--- {src.name}")
    started = time.monotonic()
    try:
        info = probe_media(src)
    except MediaError as exc:
        detail = str(exc)[:STDERR_TAIL_CHARS]
        say(f"ERROR {detail}")
        return FileResult(
            src=src,
            status="failed",
            detail=detail,
            elapsed_s=time.monotonic() - started,
        )
    if not info.has_audio:
        detail = "sin audio"
        say(f"ERROR {detail}")
        return FileResult(
            src=src,
            status="failed",
            detail=detail,
            elapsed_s=time.monotonic() - started,
        )
    out_path = src.with_suffix(".srt")
    skip_existing = out_path.exists() and not options.force
    if options.dry_run:
        decision = decide_extraction(info, options.no_extract)
        say(plan_line(src, decision, skip_existing, options.model))
        return FileResult(
            src=src,
            out_path=out_path,
            status="ok",
            detail="dry-run",
            elapsed_s=time.monotonic() - started,
            route=decision.kind,
        )
    if skip_existing:
        detail = f".srt ya existe (usa --force): {out_path.name}"
        say(f"WARN SKIP {detail}")
        return FileResult(
            src=src,
            out_path=out_path,
            status="skipped",
            detail=detail,
            elapsed_s=time.monotonic() - started,
        )
    decision = decide_extraction(info, options.no_extract)
    try:
        produced = _cues_for(src, info, decision, options)
    except Exception as exc:  # residual del paso 5: jamás propaga (§4.1)
        _remove_quietly(out_path)
        detail = str(exc)[:STDERR_TAIL_CHARS]
        if not detail:
            detail = type(exc).__name__
        say(f"ERROR {detail}")
        return FileResult(
            src=src,
            out_path=out_path,
            status="failed",
            detail=detail,
            elapsed_s=time.monotonic() - started,
        )
    # Doble salida (D14): si se intentó traducir, el original se conserva
    # como <stem>-<lang>.srt (-orig si el idioma es desconocido) y la salida
    # principal <stem>.srt lleva la traducción; si la traducción falló, solo
    # se escribe la sufijada. SKIP/--force siguen keyed al principal.
    orig_path: Path | None = None
    if produced.attempted:
        code = produced.lang if produced.lang else "orig"
        orig_path = src.with_name(f"{src.stem}-{code}.srt")
    try:
        if orig_path is not None:
            write_srt_atomic(orig_path, render_srt(produced.original))
        if produced.final is not None:
            write_srt_atomic(out_path, render_srt(produced.final))
    except OSError as exc:
        _remove_quietly(out_path)
        if orig_path is not None:
            _remove_quietly(orig_path)
        detail = f"no se pudo escribir {out_path.name}: {exc}"[:STDERR_TAIL_CHARS]
        say(f"ERROR {detail}")
        return FileResult(
            src=src,
            out_path=out_path,
            status="failed",
            detail=detail,
            elapsed_s=time.monotonic() - started,
        )
    elapsed = time.monotonic() - started
    main_cues = produced.final if produced.final is not None else produced.original
    if produced.final is None:
        salida = orig_path.name if orig_path is not None else out_path.name
        resumen = f"salida {salida} (sin traducción)"
    elif orig_path is not None:
        resumen = f"salidas {out_path.name} + {orig_path.name}"
    else:
        resumen = f"salida {out_path.name}"
    say(f"OK {decision.kind} | {len(main_cues)} cues | {resumen} | {elapsed:.1f}s")
    return FileResult(
        src=src,
        out_path=out_path,
        status="ok",
        detail=decision.kind,
        elapsed_s=elapsed,
        cues=len(main_cues),
        route=decision.kind,
    )


def _cues_for(
    src: Path, info: ProbeInfo, decision: ExtractionDecision, options: SubtitlerOptions
) -> ProducedSubtitles:
    """Paso 5 del pipeline (§4.1): obtiene los cues según la ruta decidida.

    Extracción embebida tal cual o + traducción Argos (con descarga en
    demanda, D13); transcripción con faster-whisper como respaldo (sin
    pistas, bitmap o --no-extract) seguida de traducción si el idioma
    detectado no es el destino. Devuelve los cues originales, los finales,
    el idioma fuente 639-1 y si se intentó traducir (D14). Puede lanzar: el
    caller convierte cualquier excepción en FileResult failed.
    """
    if decision.kind in ("extract", "extract_translate"):
        stream_index = decision.stream_index
        assert stream_index is not None, (
            "decide_extraction garantiza índice para extract"
        )
        cues = extract_track(src, stream_index)
        if decision.kind == "extract_translate":
            outcome = apply_translation(cues, decision.language, options.target)
            return ProducedSubtitles(
                cues, outcome.translated, _lang1(decision.language), True
            )
        return ProducedSubtitles(cues, cues, _lang1(decision.language), False)
    if decision.kind == "transcribe_bitmap":
        say(
            "WARN solo hay pistas de subtítulos bitmap (PGS/DVB); se transcribe el audio como respaldo."
        )
    spec = MODELS[options.model]
    cues, detected = transcribe_cues(
        src, options.model, spec, options.lang, info.duration_s
    )
    say(f"idioma detectado: {detected}")
    if detected != options.target:
        outcome = apply_translation(cues, detected, options.target)
        return ProducedSubtitles(cues, outcome.translated, _lang1(detected), True)
    return ProducedSubtitles(cues, cues, _lang1(detected), False)


# --------------------------------------------------------------------------- #
# CLI (main llega completo con la tarea 3.6)
# --------------------------------------------------------------------------- #


def summarize(results: Sequence[FileResult], total_elapsed_s: float) -> None:
    """Imprime el resumen TOTAL final de la corrida (S25) y el tiempo total."""
    ok = sum(1 for r in results if r.status == "ok")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")
    say("-" * 60)
    say(f"TOTAL: {ok} ok, {failed} failed, {skipped} skipped")
    say(f"Tiempo total: {format_clock(total_elapsed_s)}")


def ensure_tools() -> bool:
    """Verifica que ffmpeg Y ffprobe estén disponibles en PATH (S33)."""
    missing = [
        label
        for label, exe in (("ffmpeg", FFMPEG), ("ffprobe", FFPROBE))
        if shutil.which(exe) is None
    ]
    if missing:
        say(
            f"ERROR herramientas requeridas no encontradas en PATH: {', '.join(missing)}."
        )
        say("Instala ffmpeg (incluye ffprobe) y asegúrate de que estén en PATH.")
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de la CLI. Devuelve el código de salida del proceso
    (0 ok, 1 cualquier fallo, 130 interrumpido; 2 uso inválido).
    """
    configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_registry_choices(parser, args)
    if not ensure_tools():
        return 1
    options = SubtitlerOptions(
        model=args.model,
        lang=args.lang,
        target=args.target,
        no_extract=args.no_extract,
        force=args.force,
        dry_run=args.dry_run,
        input_dir=args.input_dir,
    )
    inputs = resolve_inputs(Path(args.input_dir).expanduser(), args.inputs)
    if not inputs:
        return 0
    started = time.monotonic()
    results: list[FileResult] = []
    try:
        for src in inputs:
            results.append(subtitlar_one(src, options))
    except KeyboardInterrupt:
        say()
        say("Interrumpido.")
        return 130
    summarize(results, time.monotonic() - started)
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
