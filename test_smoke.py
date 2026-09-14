#!/usr/bin/env python3
"""Pruebas de humo para py-video-subtitler (solo biblioteca estándar).

Ejecutar desde la raíz del proyecto:
    .venv/Scripts/python.exe test_smoke.py

Sección con modelos reales (descarga one-time, red): opt-in estricto vía
    SUBTITLER_SMOKE_REAL=1 .venv/Scripts/python.exe test_smoke.py

Genera muestras sintéticas pequeñas con ffmpeg lavfi dentro de tests_tmp/ (un
nombre de archivo contiene espacios a propósito, para demostrar el manejo de
argumentos seguro para Windows), ejecuta subtitler.py como subproceso y
verifica las salidas .srt a nivel de bytes. Sin SUBTITLER_SMOKE_REAL=1 la
suite no usa modelos ni red. tests_tmp/ se elimina al salir.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
SUBTITLER = ROOT / "subtitler.py"
TMP = ROOT / "tests_tmp"
# D8: semántica estricta — solo el valor exacto "1" activa la sección real.
# subtitler.py jamás lee esta variable.
REAL_MODE = os.environ.get("SUBTITLER_SMOKE_REAL") == "1"

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    """Registra e imprime una aserción PASS/FAIL."""
    global passed, failed
    if condition:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        suffix = f" -- {detail}" if detail else ""
        print(f"[FAIL] {name}{suffix}")


def force_utf8_stdio() -> None:
    """Fuerza stdio UTF-8 en la propia suite: nombres y detalles con unicode
    (p. ej. la flecha del plan) no deben romper la salida redirigida."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8", errors="replace")


# Aislamiento Argos de la suite default (enmienda 5.5): la descarga en demanda
# consulta un índice y paquetes; para que la suite default tenga CERO red y NO
# dependa del estado Argos de la máquina, los subprocesos apuntan a una URL
# file:// inexistente (URLError instantáneo, cero sockets) y a dirs de
# datos/config/cache/paquetes vacíos bajo tests_tmp (sin índice en caché no hay
# descargas posibles). Solo se omite en modo real (SUBTITLER_SMOKE_REAL=1).
_ARGOS_ISOLATION_DIR = TMP / "argos-aislado"
_ARGOS_FAKE_INDEX_URI = (_ARGOS_ISOLATION_DIR / "index-inexistente.json").as_uri()


def argos_isolation_env() -> dict[str, str]:
    """Env que deja a argostranslate del subproceso sin índice, sin paquetes
    instalados y sin proxy: la descarga en demanda resulta imposible sin red."""
    return {
        "ARGOS_PACKAGE_INDEX": _ARGOS_FAKE_INDEX_URI,
        "XDG_DATA_HOME": str(_ARGOS_ISOLATION_DIR / "xdg-data"),
        "XDG_CONFIG_HOME": str(_ARGOS_ISOLATION_DIR / "xdg-config"),
        "XDG_CACHE_HOME": str(_ARGOS_ISOLATION_DIR / "xdg-cache"),
        "ARGOS_PACKAGES_DIR": str(_ARGOS_ISOLATION_DIR / "packages"),
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": "",
        "NO_PROXY": "*",
        "no_proxy": "*",
    }


def run_subtitler(
    args: list[str],
    timeout: float = 600.0,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Ejecuta subtitler.py como subproceso con argumentos en lista (sin shell).

    Salvo en modo real, inyecta el aislamiento Argos de la suite default
    (cero red, cero paquetes reales); ``env`` explícito tiene la última palabra.
    """
    merged_env: dict[str, str] | None = env
    if not REAL_MODE:
        merged_env = {**os.environ, **argos_isolation_env(), **(env or {})}
    return subprocess.run(
        [PYTHON, str(SUBTITLER), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        input=input_text,
        env=merged_env,
    )


FAKE_ARGOS_SCRIPT_PREFIX = '''\
"""Bootstrap del subproceso: argostranslate falso inyectado en sys.modules."""
import sys
import types


installed_fake = []


class FakeArgosPackage:
    def __init__(self, from_code, to_code):
        self.from_code = from_code
        self.to_code = to_code

    def download(self):
        return self  # install_from_path recibe el objeto directamente


fake_argos = types.ModuleType("argostranslate")
fake_package = types.ModuleType("argostranslate.package")
fake_package.get_installed_packages = lambda: list(installed_fake)
fake_package.get_available_packages = lambda: [
    FakeArgosPackage(a, b) for a, b in AVAILABLE
]
fake_package.update_package_index = lambda: None
fake_package.install_from_path = lambda package: installed_fake.append(package)
fake_argos.package = fake_package
fake_translate = types.ModuleType("argostranslate.translate")
fake_translate.translate = lambda text, src, dst: f"[{dst}] {text}"
fake_argos.translate = fake_translate
sys.modules["argostranslate"] = fake_argos
sys.modules["argostranslate.package"] = fake_package
sys.modules["argostranslate.translate"] = fake_translate
'''


def run_with_fake_argos(
    args: list[str], available_pairs: list[tuple[str, str]]
) -> subprocess.CompletedProcess:
    """Corre subtitler.py (runpy) con un argostranslate falso inyectado (5.5).

    e2e de la enmienda sin red ni paquetes reales: ``available_pairs`` es lo
    que ofrece el índice falso; instalar agrega el par a los "instalados" y la
    traducción antepone ``[dst] `` al texto. Los .srt reales se escriben en
    tests_tmp como en cualquier corrida.
    """
    script = FAKE_ARGOS_SCRIPT_PREFIX + (
        f"AVAILABLE = {available_pairs!r}\n"
        f"import runpy\nrunpy.run_path({str(SUBTITLER)!r}, run_name='__main__')\n"
    )
    return subprocess.run(
        [sys.executable, "-c", script, *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300.0,
    )


def fail_detail(proc: subprocess.CompletedProcess) -> str:
    """Construye una cadena compacta de depuración de una corrida del subtitler."""
    return (
        f"rc={proc.returncode}\n"
        f"stdout tail:\n{proc.stdout[-1200:]}\n"
        f"stderr tail:\n{proc.stderr[-600:]}"
    )


def ffprobe_json(path: Path) -> dict:
    """Devuelve los metadatos JSON de ffprobe para ``path``."""
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {proc.stderr[:400]}")
    return json.loads(proc.stdout)


def audio_count(data: dict) -> int:
    """Cuenta los streams de audio de un payload JSON de ffprobe."""
    return sum(1 for s in data.get("streams", []) if s.get("codec_type") == "audio")


def _run_ffmpeg(args: list[str], what: str) -> None:
    """Ejecuta ffmpeg con argumentos en lista y falla fuerte si no genera."""
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{what} failed: {proc.stderr[:400]}")


def make_video(path: Path, seconds: float = 1.0, with_audio: bool = True) -> None:
    """Genera una muestra sintética H.264 (+ AAC opcional) vía lavfi."""
    args = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=128x96:rate=15:duration={seconds}",
    ]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", "libx264", "-crf", "28", "-preset", "veryfast"]
    if with_audio:
        args += ["-c:a", "aac", "-b:a", "64k", "-shortest"]
    args.append(str(path))
    _run_ffmpeg(args, f"make_video({path.name})")


def make_srt(path: Path, cues: list[tuple[str, str, str]]) -> None:
    """Escribe un .srt fuente simple (inicio, fin, texto) para muxear."""
    blocks = [
        f"{i}\n{start} --> {end}\n{text}\n"
        for i, (start, end, text) in enumerate(cues, 1)
    ]
    path.write_text("\n".join(blocks), encoding="utf-8")


def make_embedded(
    path: Path,
    cues_text: str = "hola",
    lang: str = "spa",
    default: bool = False,
    seconds: float = 1.0,
) -> None:
    """Genera un video con pista de subtítulos mov_text embebida (S5/S9).

    El .srt fuente se muxea desde un nombre distinto al stem del video y se
    borra tras el mux, para no pre-crear la salida que el subtitler escribiría.
    """
    srt = path.with_name(path.stem + " mux src.srt")
    make_srt(srt, [("00:00:00,000", f"00:00:0{int(seconds)},000", cues_text)])
    args = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=128x96:rate=15:duration={seconds}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={seconds}",
        "-i",
        str(srt),
        "-c:v",
        "libx264",
        "-crf",
        "28",
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-shortest",
        "-c:s",
        "mov_text",
        "-metadata:s:s:0",
        f"language={lang}",
    ]
    if default:
        args += ["-disposition:s:0", "default"]
    args.append(str(path))
    _run_ffmpeg(args, f"make_embedded({path.name})")
    srt.unlink(missing_ok=True)


def make_garbage(path: Path) -> None:
    """Escribe un archivo de bytes basura con extensión .mp4 (S2)."""
    path.write_bytes(b"esto no es un video " * 100)


def run_unit(src: str, timeout: float = 120.0) -> subprocess.CompletedProcess:
    """Corre un script unitario (UNIT_*) en subproceso contra el subtitler real."""
    return subprocess.run(
        [sys.executable, "-c", src],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def check_unit(name: str, proc: subprocess.CompletedProcess) -> None:
    """Una verificación de suite por script unitario; el detalle incrusta la salida."""
    check(
        name,
        proc.returncode == 0,
        (
            f"rc={proc.returncode}\n"
            f"stdout:\n{proc.stdout[-1200:]}\n"
            f"stderr:\n{proc.stderr[-1200:]}"
        ),
    )


def run_real_check(name: str, fn) -> None:
    """Ejecuta un check real opt-in; sin SUBTITLER_SMOKE_REAL=1 lo reporta
    como SKIP visible y NO cuenta como fallo (D8)."""
    if not REAL_MODE:
        print(f"[SKIP] {name} (opt-in: SUBTITLER_SMOKE_REAL=1)")
        return
    fn()


def make_tts_wav(path: Path, text: str) -> bool:
    """Sintetiza voz con SAPI de Windows (System.Speech); False si no hay voz."""
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{text}'); $s.Dispose()"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    return proc.returncode == 0 and path.exists() and path.stat().st_size > 44


def real_transcribe_en() -> None:
    """Check real S11: voz TTS en inglés -> --model tiny -> SRT no vacío.
    Incluye S12 real: progreso con ETA y sin una línea por segmento."""
    wav = TMP / "tts en.wav"
    if not make_tts_wav(wav, "hello world, this is a test"):
        print("[SKIP] real S11: no hay voz TTS disponible en este equipo")
        return
    mp4 = TMP / "tts en.mp4"
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=128x96:rate=15:duration=3",
            "-i",
            str(wav),
            "-c:v",
            "libx264",
            "-crf",
            "28",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-shortest",
            str(mp4),
        ],
        "mux tts",
    )
    proc = run_subtitler(["--model", "tiny", "--no-extract", str(mp4)], timeout=900.0)
    srt = mp4.with_suffix(".srt")
    check(
        "real S11: transcribe tiny produces valid srt",
        proc.returncode == 0 and srt.exists(),
        fail_detail(proc),
    )
    if srt.exists():
        text = srt.read_text(encoding="utf-8-sig")
        cue_lines = [
            line.strip()
            for line in text.replace("\r\n", "\n").split("\n")
            if line.strip() and "-->" not in line and not line.strip().isdigit()
        ]
        check(
            "real S11: srt has at least one non-empty cue",
            bool(cue_lines),
            text[:300],
        )
    check("real S12: progress shows ETA", "ETA" in proc.stdout, proc.stdout[-300:])
    cr_count = proc.stdout.count("\r")
    check(
        "real S12: \\r redraws, not one line per segment",
        cr_count <= 30,
        f"cr_count={cr_count}",
    )


def real_argos_en_to_es() -> None:
    """Check real S6: pista eng -> extracción + Argos en→es -> SRT español."""
    mp4 = TMP / "argos en.mp4"
    make_embedded(
        mp4, cues_text="hello world, this is a simple test", lang="eng", default=True
    )
    proc = run_subtitler([str(mp4)], timeout=900.0)
    srt = mp4.with_suffix(".srt")
    check(
        "real S6: Argos en→es produces valid non-empty srt",
        proc.returncode == 0 and srt.exists(),
        fail_detail(proc),
    )
    if srt.exists():
        text = srt.read_text(encoding="utf-8-sig")
        check(
            "real S6: srt has cue timestamps and text",
            "-->" in text and len(text.replace("\r\n", "").strip()) > 20,
            text[:300],
        )


UNIT_C1_SRC = '''\
"""Unit C1: parse_selection (S28) contra el subtitler real."""

import subtitler


# Rangos inclusivos y lista con separadores mixtos [,\\s]+, 1-based -> 0-based.
assert subtitler.parse_selection("1 3 5-7", 7) == [0, 2, 4, 5, 6]
assert subtitler.parse_selection("1,3,5-7", 7) == [0, 2, 4, 5, 6]
assert subtitler.parse_selection("1\\t3", 7) == [0, 2]
# Inversión de rango normalizada.
assert subtitler.parse_selection("7-5", 7) == [4, 5, 6]
# Fuera de rango / inválido -> None.
assert subtitler.parse_selection("0", 7) is None
assert subtitler.parse_selection("8", 7) is None
assert subtitler.parse_selection("1-8", 7) is None
assert subtitler.parse_selection("x", 7) is None
assert subtitler.parse_selection("", 7) is None
# Triángulo: rango de un solo elemento, 'a'/'q' quedan fuera (los maneja el selector).
assert subtitler.parse_selection("2-2", 7) == [1]
assert subtitler.parse_selection("a", 7) is None
assert subtitler.parse_selection("q", 7) is None

print("unit C1 ok")
'''

UNIT_C2_C3_SRC = '''\
"""Unit C2/C3: format_srt_timestamp y wrap_text (S17/S18) contra el subtitler real."""

import subtitler


# C2: HH:MM:SS,mmm con coma decimal.
assert subtitler.format_srt_timestamp(0.0) == "00:00:00,000"
assert subtitler.format_srt_timestamp(7.5) == "00:00:07,500"
assert subtitler.format_srt_timestamp(3661.5) == "01:01:01,500"
assert subtitler.format_srt_timestamp(7227.8234) == "02:00:27,823"
# Clamp de negativos a 0 y redondeo a milisegundos.
assert subtitler.format_srt_timestamp(-0.2) == "00:00:00,000"
assert subtitler.format_srt_timestamp(1.9999) == "00:00:02,000"
assert subtitler.format_srt_timestamp(0.0006) == "00:00:00,001"

# C3: greedy por palabras <= 42 sin cortar nunca una palabra.
assert subtitler.wrap_text("hola mundo") == ["hola mundo"]
largo = "palabra1 palabra2 palabra3 palabra4 palabra5"
lineas = subtitler.wrap_text(largo)
assert lineas == ["palabra1 palabra2 palabra3 palabra4", "palabra5"], lineas
assert all(len(linea) <= subtitler.SRT_LINE_MAX_CHARS for linea in lineas)
assert " ".join(lineas) == largo  # sin pérdida de palabras
# Frontera exacta 42 y palabra más larga que la línea (nunca se corta).
assert subtitler.wrap_text("a" * 42) == ["a" * 42]
assert subtitler.wrap_text("a" * 43) == ["a" * 43]

print("unit C2/C3 ok")
'''

UNIT_C4_C5_SRC = '''\
"""Unit C4/C5: split_cue y render_srt (S17/S18) contra el subtitler real."""

import subtitler
from subtitler import Cue


# Cue que ya cabe: sale igual (un solo cue).
corto = Cue(0.0, 1.0, "un cue corto")
assert subtitler.split_cue(corto) == [corto]

# Reparto proporcional al conteo de caracteres: 8 palabras de 10 -> 3 líneas
# de 32/32/21; bloque1 = líneas 1-2 (65 chars), bloque2 = línea 3 (21 chars).
texto8 = " ".join(["a" * 10] * 8)
out8 = subtitler.split_cue(Cue(10.0, 110.0, texto8))
assert len(out8) == 2, out8
esperado = 10.0 + 100.0 * 65 / 86
assert abs(out8[0].end_s - esperado) < 1e-9, out8[0].end_s
assert out8[0].text == " ".join(["a" * 10] * 6)  # líneas 1-2 = 6 palabras (65)
assert out8[1].start_s == out8[0].end_s
assert out8[1].end_s == 110.0
assert out8[1].text == " ".join(["a" * 10] * 2)  # línea 3 = 2 palabras (21)

# Duración nula: gap mínimo 1 ms garantizado, jamás end <= start.
cero = subtitler.split_cue(Cue(5.0, 5.0, texto8))
assert len(cero) == 2
assert all(c.end_s > c.start_s for c in cero)
assert cero[1].start_s >= cero[0].end_s

# Texto de ~150 chars: varios cues, <= 2 líneas por cue, sin pérdida palabra
# a palabra.
texto150 = (
    "la transcripción local genera segmentos que pueden ser bastante largos "
    "y el formato srt exige líneas cortas de cuarenta y dos caracteres como "
    "maximo con dos lineas por cue sin perder nunca texto"
)
assert len(texto150) >= 140
out150 = subtitler.split_cue(Cue(10.0, 70.0, texto150))
assert len(out150) >= 3, len(out150)
assert " ".join(c.text for c in out150) == texto150
assert all(len(subtitler.wrap_text(c.text)) <= subtitler.SRT_MAX_LINES_PER_CUE for c in out150)
assert all(c.end_s > c.start_s for c in out150)

# C5: numeración 1..n, \\r\\n único salto, una línea en blanco entre cues.
srt1 = subtitler.render_srt([Cue(0.0, 2.0, "hola mundo")])
assert srt1 == "1\\r\\n00:00:00,000 --> 00:00:02,000\\r\\nhola mundo\\r\\n\\r\\n", repr(srt1)
srt2 = subtitler.render_srt([Cue(0.0, 1.0, "uno"), Cue(2.0, 3.0, "dos")])
assert (
    srt2
    == "1\\r\\n00:00:00,000 --> 00:00:01,000\\r\\nuno\\r\\n\\r\\n"
       "2\\r\\n00:00:02,000 --> 00:00:03,000\\r\\ndos\\r\\n\\r\\n"
), repr(srt2)
srt150 = subtitler.render_srt([Cue(10.0, 70.0, texto150)])
n = len(out150)
assert srt150.count("\\r\\n\\r\\n") == n  # n-1 separadores + cierre final
assert "\\r\\n\\r\\n\\r\\n" not in srt150  # jamás dos líneas en blanco seguidas
assert srt150.startswith("1\\r\\n")  # numeración consecutiva 1..n
for i in range(2, n + 1):
    assert f"\\r\\n{i}\\r\\n" in srt150

print("unit C4/C5 ok")
'''

UNIT_C6_SRC = '''\
"""Unit C6: parse_srt (S5/S6/S17) contra el subtitler real."""

import subtitler
from subtitler import Cue


# BOM, \\r\\n, numeración original ignorada, tags eliminados, multi-línea unida.
srt_in = (
    "\\ufeff99\\r\\n"
    "00:00:01,000 --> 00:00:02,500\\r\\n"
    "Hola <i>mundo</i>\\r\\n"
    "\\r\\n"
    "7\\r\\n"
    "00:00:03,000 --> 00:00:04,000\\r\\n"
    "linea uno\\r\\n"
    "linea dos\\r\\n"
)
assert subtitler.parse_srt(srt_in) == [
    Cue(1.0, 2.5, "Hola mundo"),
    Cue(3.0, 4.0, "linea uno linea dos"),
]

# El mismo payload con \\n produce el mismo resultado.
assert subtitler.parse_srt(srt_in.replace("\\r\\n", "\\n")) == [
    Cue(1.0, 2.5, "Hola mundo"),
    Cue(3.0, 4.0, "linea uno linea dos"),
]

# Payload vacío o sin cues -> lista vacía.
assert subtitler.parse_srt("") == []
assert subtitler.parse_srt("\\ufeff\\r\\n") == []

print("unit C6 ok")
'''

UNIT_C7_SRC = '''\
"""Unit C7: resolve_translation_route (S14/S15/S16) contra el subtitler real."""

import subtitler
from subtitler import TranslationRoute


pairs = frozenset({("en", "es"), ("de", "en")})

# src == dst: ruta directa sin saltos (no se traduce).
assert subtitler.resolve_translation_route("es", "es", pairs) == TranslationRoute("direct", ())
# Par directo instalado.
assert subtitler.resolve_translation_route("en", "es", pairs) == TranslationRoute(
    "direct", (("en", "es"),)
)
# Pivote vía inglés con 2 saltos.
assert subtitler.resolve_translation_route("de", "es", pairs) == TranslationRoute(
    "pivot", (("de", "en"), ("en", "es"))
)
# Sin camino.
assert subtitler.resolve_translation_route("fr", "es", pairs) == TranslationRoute("none", ())

# Triángulo: pairs vacío y dst distinto de es.
assert subtitler.resolve_translation_route("en", "es", frozenset()) == TranslationRoute("none", ())
assert subtitler.resolve_translation_route("de", "fr", frozenset({("de", "en"), ("en", "fr")})) == (
    TranslationRoute("pivot", (("de", "en"), ("en", "fr")))
)
assert subtitler.resolve_translation_route("de", "de", frozenset()) == TranslationRoute("direct", ())

print("unit C7 ok")
'''

UNIT_C8_SRC = '''\
"""Unit C8: decide_extraction y pick_subtitle_track (S5-S9) contra el subtitler real."""

from pathlib import Path

import subtitler
from subtitler import ExtractionDecision, ProbeInfo, SubtitleStream


def stream(index, codec="subrip", lang="spa", default=False):
    """SubtitleStream de prueba; is_text según la allowlist real."""
    return SubtitleStream(
        index=index,
        codec_name=codec,
        is_text=codec in subtitler.TEXT_SUBTITLE_CODECS,
        language=lang,
        disposition_default=default,
    )


def info(streams, has_audio=True):
    return ProbeInfo(
        path=Path("video.mp4"),
        duration_s=60.0,
        has_audio=has_audio,
        subtitle_streams=streams,
    )


# --no-extract fuerza transcripción.
assert subtitler.decide_extraction(info([stream(0)]), True) == ExtractionDecision(
    "transcribe_forced", None, None
)
# Sin pistas.
assert subtitler.decide_extraction(info([]), False) == ExtractionDecision(
    "transcribe_no_track", None, None
)
# Idiomas None/es/spa/und -> extract tal cual.
assert subtitler.decide_extraction(info([stream(2, lang="spa")]), False) == ExtractionDecision(
    "extract", 2, "spa"
)
assert subtitler.decide_extraction(info([stream(0, lang=None)]), False) == ExtractionDecision(
    "extract", 0, None
)
assert subtitler.decide_extraction(info([stream(1, lang="und")]), False) == ExtractionDecision(
    "extract", 1, "und"
)
assert subtitler.decide_extraction(info([stream(3, lang="es")]), False) == ExtractionDecision(
    "extract", 3, "es"
)
# Otro idioma -> extraer y traducir.
assert subtitler.decide_extraction(info([stream(0, lang="eng")]), False) == ExtractionDecision(
    "extract_translate", 0, "eng"
)
# Solo bitmap (PGS) -> transcribir.
assert subtitler.decide_extraction(
    info([stream(0, codec="hdmv_pgs_subtitle")]), False
) == ExtractionDecision("transcribe_bitmap", None, None)

# Triángulo: varias pistas; la default marcada gana aunque no sea la primera.
mix = [stream(0, codec="hdmv_pgs_subtitle"), stream(1, lang="eng"), stream(2, lang="spa", default=True)]
assert subtitler.pick_subtitle_track(mix).index == 2
# Sin default: primera de texto (ignorando bitmap).
assert subtitler.pick_subtitle_track([stream(0, lang="eng"), stream(1, lang="spa")]).index == 0
assert subtitler.pick_subtitle_track([]) is None

print("unit C8 ok")
'''

UNIT_C9_SRC = '''\
"""Unit C9: parse_probe_json (S1/S2) contra el subtitler real."""

import json
from pathlib import Path

import subtitler


payload = json.dumps(
    {
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264"},
            {"index": 1, "codec_type": "audio", "codec_name": "aac"},
            {
                "index": 2,
                "codec_type": "subtitle",
                "codec_name": "mov_text",
                "tags": {"language": "spa"},
                "disposition": {"default": 1},
            },
            {"index": 3, "codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle"},
            {"index": 4, "codec_type": "subtitle", "codec_name": "weird_unknown"},
        ],
        "format": {"duration": "61.5"},
    }
)
info = subtitler.parse_probe_json(payload, Path("v.mp4"))
assert info.path == Path("v.mp4")
assert info.has_audio is True
assert abs(info.duration_s - 61.5) < 1e-9
assert [s.index for s in info.subtitle_streams] == [2, 3, 4]
# is_text por allowlist; el codec desconocido cae a bitmap.
assert [s.is_text for s in info.subtitle_streams] == [True, False, False]
assert info.subtitle_streams[0].disposition_default is True
assert info.subtitle_streams[0].language == "spa"
assert info.subtitle_streams[1].language is None

# Triángulo: duración ausente -> 0.0; sin audio.
info2 = subtitler.parse_probe_json(
    json.dumps({"streams": [{"index": 0, "codec_type": "video"}]}), Path("v.mp4")
)
assert info2.duration_s == 0.0
assert info2.has_audio is False

# JSON inválido -> MediaError.
try:
    subtitler.parse_probe_json("{not json", Path("v.mp4"))
    raise SystemExit("expected MediaError")
except subtitler.MediaError:
    pass

# Helpers tolerantes.
assert subtitler._to_float("12.5") == 12.5
assert subtitler._to_float("N/A") is None
assert subtitler._to_float(None) is None
assert subtitler._safe_int("7") == 7
assert subtitler._safe_int("x", 3) == 3

print("unit C9 ok")
'''

UNIT_C10_REG_SRC = '''\
"""Unit 2.9: registros, validación y dedup (S31/S32) contra el subtitler real."""

import io
from contextlib import redirect_stderr
from pathlib import Path

import subtitler


# --model medium es un valor registrado e implementado (S32).
parser = subtitler.build_parser()
args = parser.parse_args(["--model", "medium", "--target", "es"])
assert args.model == "medium"
assert subtitler.MODELS["medium"].implemented
assert subtitler.DEFAULT_MODEL == "small"
assert subtitler.DEFAULT_TARGET == "es"
# Valores válidos: la validación no lanza nada.
subtitler.validate_registry_choices(parser, args)

# Valor registrado pero no implementado: SystemExit 2 listando 'es' (S31).
subtitler.TARGET_LANGS["en"] = subtitler.LangSpec(implemented=False)
args_bad = parser.parse_args(["--target", "es"])
args_bad.target = "en"
err = io.StringIO()
try:
    with redirect_stderr(err):
        subtitler.validate_registry_choices(parser, args_bad)
    raise SystemExit("expected SystemExit")
except SystemExit as exc:
    assert exc.code == 2, exc.code
mensaje = err.getvalue()
assert "--target" in mensaje and "es" in mensaje, mensaje
del subtitler.TARGET_LANGS["en"]

# Dedup de entradas por expanduser().resolve(), en orden de primera aparición.
raws = ["v.mp4", "./v.mp4", "otro.mp4", "v.mp4"]
res = subtitler.resolve_inputs(Path("input"), raws)
assert res == [Path("v.mp4").expanduser().resolve(), Path("otro.mp4").expanduser().resolve()], res

print("unit 2.9 ok")
'''

UNIT_34_SRC = '''\
"""Unit 3.4: write_srt_atomic contra el subtitler real."""

from pathlib import Path

import subtitler


out = Path("tests_tmp") / "atomic check.srt"
out.parent.mkdir(exist_ok=True)
body = "1\\r\\n00:00:00,000 --> 00:00:01,000\\r\\nhola\\r\\n\\r\\n"
subtitler.write_srt_atomic(out, body)
raw = out.read_bytes()
assert raw == b"\\xef\\xbb\\xbf" + body.encode("ascii"), raw[:20]  # BOM + CRLF literales
assert not out.with_name(out.name + ".tmp").exists()  # el .tmp fue renombrado
out.unlink()

print("unit 3.4 atomic ok")
'''

UNIT_35_SRC = '''\
"""Unit 3.5: texto de plan para rutas sin muestra real (bitmap) contra el subtitler real."""

from pathlib import Path

import subtitler


# transcribir (bitmap: extracción imposible) vía decisión fabricada (S7).
d = subtitler.ExtractionDecision("transcribe_bitmap", None, None)
linea = subtitler.plan_line(Path("v.mp4"), d, skip=False, model="small")
assert linea.startswith("  [plan] v.mp4 → "), linea
assert "transcribir (bitmap: extracción imposible)" in linea, linea
assert "v.srt" in linea, linea

print("unit 3.5 plan ok")
'''

UNIT_S27_SRC = '''\
"""Unit S27: main retorna 130 ante KeyboardInterrupt (handler por unit)."""

import subtitler


def _raise_ki(src, options):
    raise KeyboardInterrupt()


subtitler.subtitlar_one = _raise_ki
assert subtitler.main(["cualquier.mp4"]) == 130

print("unit S27 ok")
'''

UNIT_52_SRC = '''\
"""Unit 5.2: matemática y render de progreso en una línea (S12)."""

import io
from contextlib import redirect_stdout

import subtitler


assert subtitler.PROGRESS_BAR_WIDTH == 24
assert subtitler.PROGRESS_MIN_INTERVAL_S == 0.1


def progress_line(done, duration, elapsed):
    buf = io.StringIO()
    with redirect_stdout(buf):
        subtitler.draw_progress(done, duration, elapsed)
    return buf.getvalue()


# 45% con speed 1.50x: ETA = 30 * 0.55 / 0.45 = 36.7 s -> 00:37.
linea = progress_line(45.0, 100.0, 30.0)
assert linea.startswith("\\r"), repr(linea)
assert "[" + "#" * 10 + "-" * 14 + "]" in linea, repr(linea)  # 24 chars de barra
assert "45.0%" in linea, repr(linea)
assert "speed 1.50x" in linea, repr(linea)
assert "ETA 00:37" in linea, repr(linea)

# pct 0 y elapsed 0: sin división por cero, ETA n/a.
linea0 = progress_line(0.0, 100.0, 0.0)
assert "n/a" in linea0 and "--:--" in linea0, repr(linea0)

# pct 1: ETA 00:00.
linea1 = progress_line(100.0, 100.0, 50.0)
assert "100.0%" in linea1 and "ETA 00:00" in linea1, repr(linea1)

print("unit 5.2 ok")
'''

UNIT_53_LAZY_SRC = '''\
"""Unit 5.3: imports perezosos — importar subtitler NO carga los motores (D3)."""

import sys

import subtitler


assert "faster_whisper" not in sys.modules, "faster_whisper se cargó al importar subtitler"
assert "argostranslate" not in sys.modules, "argostranslate se cargó al importar subtitler"

print("unit 5.3 lazy ok")
'''

UNIT_54_SRC = '''\
"""Unit 5.4: build_translator ruta none -> identidad sin importar Argos (S16)."""

import sys

import subtitler
from subtitler import TranslationRoute


translator = subtitler.build_translator(TranslationRoute("none", ()))
assert translator("hello world") == "hello world"
assert "argostranslate" not in sys.modules, "la identidad no debe importar Argos"

# Ruta directa de un salto: el traductor encadena exactamente ese par.
translator_direct = subtitler.build_translator(TranslationRoute("direct", (("en", "es"),)))
assert callable(translator_direct)

# Ruta pivote: dos saltos encadenados.
translator_pivot = subtitler.build_translator(
    TranslationRoute("pivot", (("de", "en"), ("en", "es")))
)
assert callable(translator_pivot)

print("unit 5.4 ok")
'''


UNIT_A1_SRC = '''\
"""Unit A1 (enmienda): ruta none + descarga exitosa -> re-resuelve y traduce."""

import io
from contextlib import redirect_stdout

import subtitler
from subtitler import Cue


estado = {"instalados": frozenset()}
llamadas_ensure = []
subtitler.installed_argos_pairs = lambda: estado["instalados"]


def fake_ensure(pairs):
    llamadas_ensure.append(tuple(pairs))
    estado["instalados"] = frozenset({("de", "es")})
    return True


subtitler.ensure_pairs_installed = fake_ensure
subtitler.build_translator = lambda route: (lambda text: "HOLA " + text)

cues = [Cue(0.0, 1.0, "Hallo Welt"), Cue(1.0, 2.0, "Zweite Zeile")]
buf = io.StringIO()
with redirect_stdout(buf):
    prod = subtitler.apply_translation(cues, "deu", "es")
assert prod.original == cues, prod.original
assert prod.original_lang == "de", prod.original_lang
assert prod.translated is not None, prod
assert prod.translated[0].text == "HOLA Hallo Welt", prod.translated
assert prod.translated[1].text == "HOLA Zweite Zeile", prod.translated
# Candidatos exactos: par directo primero, patas del pivote después (D13).
assert llamadas_ensure == [
    (("de", "es"), ("de", "en"), ("en", "es"))
], llamadas_ensure
# La ruta re-resuelta es directa y el mensaje de traducción aparece.
assert "traduciendo 2 segmentos (direct)" in buf.getvalue(), buf.getvalue()
# Costura pura de candidatos.
assert subtitler.download_candidates("fr", "es") == (
    ("fr", "es"),
    ("fr", "en"),
    ("en", "es"),
)

# Triángulo: origen ya inglés -> solo el par directo; ni (en, en) ni duplicado.
assert subtitler.download_candidates("en", "es") == (("en", "es"),)

print("unit A1 ok")
'''


UNIT_A2_SRC = '''\
"""Unit A2 (enmienda): fallo de descarga / idioma desconocido -> sin traducción."""

import io
from contextlib import redirect_stdout

import subtitler
from subtitler import Cue


subtitler.installed_argos_pairs = lambda: frozenset()
subtitler.ensure_pairs_installed = lambda pairs: False

cues = [Cue(0.0, 1.0, "hello world")]
buf = io.StringIO()
with redirect_stdout(buf):
    prod = subtitler.apply_translation(cues, "eng", "es")
assert prod.original == cues, prod.original
assert prod.original_lang == "en", prod.original_lang
assert prod.translated is None, prod.translated
salida = buf.getvalue()
assert "WARN" in salida and "en→es" in salida, salida

# Triángulo: idioma desconocido (None y 'und') -> original_lang None.
buf2 = io.StringIO()
with redirect_stdout(buf2):
    prod2 = subtitler.apply_translation(cues, None, "es")
assert prod2.original_lang is None and prod2.translated is None, prod2
assert "desconocido" in buf2.getvalue(), buf2.getvalue()
buf3 = io.StringIO()
with redirect_stdout(buf3):
    prod3 = subtitler.apply_translation(cues, "und", "es")
assert prod3.original_lang is None and prod3.translated is None, prod3

# Origen ya destino: cues tal cual, sin sufijo ni WARN.
prod4 = subtitler.apply_translation(cues, "spa", "es")
assert prod4.original_lang == "es" and prod4.translated == cues, prod4

print("unit A2 ok")
'''


UNIT_A3_SRC = '''\
"""Unit A3 (enmienda): ensure_pairs_installed — directo preferido, one-time."""

import io
import sys
import types
from contextlib import redirect_stdout

# La llamada directa a ensure_pairs_installed imprime INFO con flechas (→);
# igual que configure_utf8_stdio en producción, se fuerza UTF-8 para que el
# subproceso -c no muera con cp1252 al encontrar unicode.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        _reconfigure(encoding="utf-8", errors="replace")

import subtitler


instalados = []
indice_actualizaciones = []
descargas = []
disponibles = {}


class PaqueteFalso:
    def __init__(self, frm, to):
        self.from_code = frm
        self.to_code = to

    def download(self):
        return self  # install_from_path recibe el objeto directamente


def fabricar():
    return [
        PaqueteFalso("de", "es"),
        PaqueteFalso("de", "en"),
        PaqueteFalso("en", "es"),
    ]


def instalar(pkg):
    instalados.append(pkg)
    descargas.append((pkg.from_code, pkg.to_code))


fake_argos = types.ModuleType("argostranslate")
fake_package = types.ModuleType("argostranslate.package")
fake_package.get_installed_packages = lambda: list(instalados)
fake_package.get_available_packages = lambda: list(disponibles.values())
fake_package.update_package_index = lambda: indice_actualizaciones.append(1)
fake_package.install_from_path = instalar
fake_argos.package = fake_package
sys.modules["argostranslate"] = fake_argos
sys.modules["argostranslate.package"] = fake_package

candidatos = (("de", "es"), ("de", "en"), ("en", "es"))

# Directo disponible en el índice: SOLO se descarga el directo, índice 1 vez.
disponibles.update({(p.from_code, p.to_code): p for p in fabricar()})
buf = io.StringIO()
with redirect_stdout(buf):
    assert subtitler.ensure_pairs_installed(candidatos) is True
assert descargas == [("de", "es")], descargas
assert indice_actualizaciones == [1], indice_actualizaciones
assert "INFO descargando paquete Argos de→es" in buf.getvalue(), buf.getvalue()

# One-time: con el directo instalado, ni índice ni descargas nuevas.
assert subtitler.ensure_pairs_installed(candidatos) is True
assert indice_actualizaciones == [1] and descargas == [("de", "es")]

# Directo ausente del índice -> las DOS patas del pivote faltantes.
instalados.clear()
descargas.clear()
indice_actualizaciones.clear()
del disponibles[("de", "es")]
assert subtitler.ensure_pairs_installed(candidatos) is True
assert descargas == [("de", "en"), ("en", "es")], descargas

# Pivote ya completo (sin directo en el índice): True sin tocar red.
assert subtitler.ensure_pairs_installed(candidatos) is True
assert indice_actualizaciones == [1] and len(descargas) == 2

# Nada disponible -> False sin lanzar.
instalados.clear()
descargas.clear()
indice_actualizaciones.clear()
disponibles.clear()
assert subtitler.ensure_pairs_installed(candidatos) is False

# Excepción en download -> False, jamás propaga.
disponibles[("de", "es")] = PaqueteFalso("de", "es")


def instalar_roto(pkg):
    raise RuntimeError("disco lleno")


fake_package.install_from_path = instalar_roto
assert subtitler.ensure_pairs_installed(candidatos) is False

print("unit A3 ok")
'''


def main() -> int:
    """Ejecuta todas las pruebas de humo y limpia tests_tmp/ al final."""
    force_utf8_stdio()
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True, exist_ok=True)
    try:
        # --- Fase 2: costuras puras (unit en subproceso) ---
        check_unit("unit C1: parse_selection", run_unit(UNIT_C1_SRC))  # 2.2
        check_unit("unit C2/C3: srt timestamp + wrap", run_unit(UNIT_C2_C3_SRC))  # 2.3
        check_unit(
            "unit C4/C5: split_cue + render_srt", run_unit(UNIT_C4_C5_SRC)
        )  # 2.4
        check_unit("unit C6: parse_srt", run_unit(UNIT_C6_SRC))  # 2.5
        check_unit("unit C7: translation route", run_unit(UNIT_C7_SRC))  # 2.6
        check_unit("unit C8: extraction decision", run_unit(UNIT_C8_SRC))  # 2.7
        check_unit("unit C9: parse_probe_json", run_unit(UNIT_C9_SRC))  # 2.8
        check_unit(
            "unit 2.9: registries/validate/dedup", run_unit(UNIT_C10_REG_SRC)
        )  # 2.9
        check_unit("unit 3.4: write_srt_atomic", run_unit(UNIT_34_SRC))  # 3.4
        check_unit("unit 3.5: plan bitmap route", run_unit(UNIT_35_SRC))  # 3.5
        check_unit("unit S27: KeyboardInterrupt -> 130", run_unit(UNIT_S27_SRC))  # 3.6
        check_unit("unit 5.2: progress math + render", run_unit(UNIT_52_SRC))  # 5.2
        check_unit("unit 5.3: lazy heavy imports", run_unit(UNIT_53_LAZY_SRC))  # 5.3
        check_unit("unit 5.4: build_translator routes", run_unit(UNIT_54_SRC))  # 5.4
        check_unit(
            "unit A1: on-demand download success translates", run_unit(UNIT_A1_SRC)
        )  # 5.5 enmienda
        check_unit(
            "unit A2: download failure / unknown lang -> no translation",
            run_unit(UNIT_A2_SRC),
        )  # 5.5 enmienda
        check_unit(
            "unit A3: ensure_pairs_installed direct-first one-time",
            run_unit(UNIT_A3_SRC),
        )  # 5.5 enmienda

        # --- 3.1: fábricas lavfi ---
        sample = TMP / "sample test.mp4"  # espacios a propósito (S3)
        make_video(sample)
        check(
            "factories: make_video with spaces",
            sample.exists() and sample.stat().st_size > 0,
            str(sample),
        )
        data = ffprobe_json(sample)
        kinds = {s.get("codec_type") for s in data.get("streams", [])}
        check(
            "factories: make_video has video+audio",
            {"video", "audio"} <= kinds,
            str(kinds),
        )

        noaudio = TMP / "sin audio.mp4"
        make_video(noaudio, with_audio=False)
        check(
            "factories: video without audio",
            noaudio.exists() and audio_count(ffprobe_json(noaudio)) == 0,
            str(noaudio),
        )

        embedded_spa = TMP / "embedded spa.mp4"
        make_embedded(embedded_spa, cues_text="hola mundo", lang="spa", default=True)
        subs = [
            s
            for s in ffprobe_json(embedded_spa).get("streams", [])
            if s.get("codec_type") == "subtitle"
        ]
        check(
            "factories: embedded spa default",
            bool(subs)
            and subs[0].get("tags", {}).get("language") == "spa"
            and subs[0].get("disposition", {}).get("default") == 1,
            json.dumps(subs)[:300],
        )

        embedded_eng = TMP / "embedded eng.mp4"
        make_embedded(embedded_eng, cues_text="hello world", lang="eng", default=False)
        subs_eng = [
            s
            for s in ffprobe_json(embedded_eng).get("streams", [])
            if s.get("codec_type") == "subtitle"
        ]
        # El muxer MP4/mov_text siempre marca default=1 la primera pista de
        # subtítulos (incluso con -disposition:s:0 0); la distinción
        # default/primera-de-texto queda cubierta por unit en C8 (S9).
        check(
            "factories: embedded eng stream",
            bool(subs_eng) and subs_eng[0].get("tags", {}).get("language") == "eng",
            json.dumps(subs_eng)[:300],
        )

        garbage = TMP / "garbage.mp4"
        make_garbage(garbage)
        check(
            "factories: garbage mp4",
            garbage.exists() and garbage.stat().st_size > 0,
            str(garbage),
        )

        # --- 3.2: sondeo + fallo aislado por archivo ---
        proc = run_subtitler([str(garbage), str(noaudio), str(sample)])
        check(
            "3.2: run accepts files (no crash)",
            proc.returncode in (0, 1),
            fail_detail(proc),
        )
        check(
            "3.2: probe failure reported as ERROR",
            "ERROR" in proc.stdout,
            fail_detail(proc),
        )
        check(
            "3.2: garbage file named in header",
            "--- garbage.mp4" in proc.stdout,
            proc.stdout[-400:],
        )
        check(
            "3.2: no-audio reason",
            "sin audio" in proc.stdout,
            proc.stdout[-400:],
        )
        check(
            "3.2: run continues after failure",
            proc.stdout.find("--- garbage.mp4") != -1
            and proc.stdout.find("--- sin audio.mp4")
            > proc.stdout.find("--- garbage.mp4")
            and proc.stdout.find("--- sample test.mp4")
            > proc.stdout.find("--- sin audio.mp4"),
            proc.stdout[-600:],
        )
        check(
            "3.2: spaces path fully probed (S3)",
            "--- sample test.mp4" in proc.stdout,
            proc.stdout[-400:],
        )

        # --- 3.3: extracción embebida + formato a nivel de bytes ---
        out_srt = embedded_spa.with_suffix(".srt")
        proc = run_subtitler([str(embedded_spa)])
        check(
            "3.3: extraction run exits 0 (S5)", proc.returncode == 0, fail_detail(proc)
        )
        check(
            "3.3: .srt next to video with same stem (S19)",
            out_srt.exists(),
            str(out_srt),
        )
        if out_srt.exists():
            raw = out_srt.read_bytes()
            check(
                "3.3: starts with BOM EF BB BF (S17)",
                raw.startswith(b"\xef\xbb\xbf"),
                raw[:8].hex(" "),
            )
            body = raw.decode("utf-8-sig")
            sin_crlf = body.replace("\r\n", "")
            check(
                "3.3: only CRLF line endings (S17)",
                "\n" not in sin_crlf and "\r" not in sin_crlf,
                repr(sin_crlf[-60:]),
            )
            blocks = [b for b in body.split("\r\n\r\n") if b.strip()]
            check(
                "3.3: numbering 1..n consecutive (S17)",
                bool(blocks)
                and all(b.startswith(f"{i + 1}\r\n") for i, b in enumerate(blocks)),
                body[:200],
            )
            check(
                "3.3: timestamps HH:MM:SS,mmm --> HH:MM:SS,mmm (S17)",
                bool(blocks) and "00:00:00,000 -->" in blocks[0],
                body[:120],
            )
            check(
                "3.3: cue text present, not transcribed (S5)",
                "hola mundo" in body,
                body[:200],
            )
            check(
                "3.3: no partial .tmp left",
                not out_srt.with_name(out_srt.name + ".tmp").exists(),
            )

        # --- 3.4: SKIP/--force sobre .srt existente (S20/S21/S22) ---
        skip_srt = embedded_spa.with_suffix(".srt")
        if skip_srt.exists():  # de la corrida 3.3
            mtime_before = skip_srt.stat().st_mtime_ns
            proc = run_subtitler([str(embedded_spa)])
            check(
                "3.4: skip run exits 0 (S26 preview)",
                proc.returncode == 0,
                fail_detail(proc),
            )
            check("3.4: reported SKIP (S21)", "SKIP" in proc.stdout, proc.stdout[-400:])
            check(
                "3.4: existing .srt untouched (S21)",
                skip_srt.stat().st_mtime_ns == mtime_before,
            )
            proc = run_subtitler(["--force", str(embedded_spa)])
            check("3.4: --force exits 0 (S22)", proc.returncode == 0, fail_detail(proc))
            check(
                "3.4: --force regenerates, mtime changed (S22)",
                skip_srt.stat().st_mtime_ns != mtime_before,
            )
        else:
            check("3.4: prerequisite .srt from 3.3", False, str(skip_srt))
        # S20: tras la corrida con fallos de 3.2, jamás quedó .srt ni .tmp
        # para los archivos fallidos (garbage/sin audio/sample).
        failed_srt = TMP / "sin audio.srt"
        failed_tmp = TMP / "garbage.mp4.srt.tmp"
        check(
            "3.4: no .srt left for failed files (S20)",
            not failed_srt.exists() and not failed_tmp.exists(),
        )

        # --- 3.5: --dry-run (S23/S24/S8/S32) ---
        dry_video = TMP / "dry run video.mp4"
        make_video(dry_video)
        proc = run_subtitler(["--dry-run", str(dry_video)])
        check("3.5: dry-run exits 0 (S23)", proc.returncode == 0, fail_detail(proc))
        check(
            "3.5: exact plan line (S23)",
            "  [plan] dry run video.mp4 → transcribir (sin pistas) → dry run video.srt"
            in proc.stdout,
            proc.stdout[-500:],
        )
        check("3.5: no .srt created (S23)", not dry_video.with_suffix(".srt").exists())

        proc = run_subtitler(["--dry-run", "--model", "medium", str(dry_video)])
        check(
            "3.5: plan mentions medium (S32)",
            "medium" in proc.stdout,
            proc.stdout[-400:],
        )

        proc = run_subtitler(["--dry-run", str(embedded_spa)])
        check(
            "3.5: dry-run with existing .srt reports SKIP (S24)",
            "SKIP (.srt existe)" in proc.stdout,
            proc.stdout[-400:],
        )

        proc = run_subtitler(["--dry-run", "--no-extract", str(embedded_eng)])
        check(
            "3.5: --no-extract forces transcribe plan (S8)",
            "transcribir (--no-extract)" in proc.stdout,
            proc.stdout[-400:],
        )

        # Triángulo: rutas extraer pista (spa) y extraer pista (eng) + traducir.
        plan_spa = TMP / "plan spa.mp4"
        make_embedded(plan_spa, cues_text="hola", lang="spa", default=True)
        proc = run_subtitler(["--dry-run", str(plan_spa)])
        check(
            "3.5: plan extract spa track",
            "extraer pista #" in proc.stdout and "(spa)" in proc.stdout,
            proc.stdout[-400:],
        )
        plan_eng = TMP / "plan eng.mp4"
        make_embedded(plan_eng, cues_text="hello", lang="eng", default=True)
        proc = run_subtitler(["--dry-run", str(plan_eng)])
        check(
            "3.5: plan extract eng + traducir",
            "extraer pista #" in proc.stdout and "+ traducir" in proc.stdout,
            proc.stdout[-400:],
        )
        check(
            "3.5: dry-run triangle creates no .srt",
            not plan_spa.with_suffix(".srt").exists()
            and not plan_eng.with_suffix(".srt").exists(),
        )

        # --- 3.6: CLI + resumen + exit codes (S25/S26/S27/S31) ---
        # S25/S1: mezcla exacta 1 ok + 1 failed + 1 skipped, rc 1.
        proc = run_subtitler([str(plan_spa), str(garbage), str(embedded_spa)])
        check("3.6: mixed run rc 1 (S25)", proc.returncode == 1, fail_detail(proc))
        check(
            "3.6: exact TOTAL line (S25/S1)",
            "TOTAL: 1 ok, 1 failed, 1 skipped" in proc.stdout,
            proc.stdout[-600:],
        )
        check(
            "3.6: elapsed total line",
            "Tiempo total:" in proc.stdout,
            proc.stdout[-300:],
        )

        # S26: solo ok/skipped -> rc 0.
        s26 = TMP / "s26 fresh.mp4"
        make_embedded(s26, cues_text="hola", lang="spa", default=True)
        proc = run_subtitler([str(s26), str(embedded_spa)])
        check("3.6: ok+skipped run rc 0 (S26)", proc.returncode == 0, fail_detail(proc))
        check(
            "3.6: TOTAL 1 ok 1 skipped (S26)",
            "TOTAL: 1 ok, 0 failed, 1 skipped" in proc.stdout,
            proc.stdout[-400:],
        )

        # S31: --target en -> rc 2 con stderr listando 'es'.
        proc = run_subtitler(["--target", "en", str(s26)])
        check(
            "3.6: --target en rc 2 (S31)", proc.returncode == 2, f"rc={proc.returncode}"
        )
        check(
            "3.6: stderr lists implemented 'es' (S31)",
            "es" in proc.stderr and "--target" in proc.stderr,
            proc.stderr[-300:],
        )

        # Triángulo: dry-run puro -> rc 0.
        proc = run_subtitler(["--dry-run", str(plan_spa)])
        check("3.6: dry-run triangle rc 0", proc.returncode == 0, fail_detail(proc))

        # --- 4.1: selector interactivo (S28/S29/S30) ---
        sel_dir = TMP / "selector"
        sel_dir.mkdir(parents=True, exist_ok=True)
        sel_videos = []
        for i in range(1, 8):
            vid = sel_dir / f"vid {i}.mp4"
            make_embedded(vid, cues_text=f"cuevo {i}", lang="spa", default=True)
            sel_videos.append(vid)

        def clear_srts(directory: Path) -> None:
            for srt_path in directory.glob("*.srt"):
                srt_path.unlink()

        # S28: selección por rangos 1 3 5-7 -> exactamente 5 .srt.
        proc = run_subtitler(["--input-dir", str(sel_dir)], input_text="1 3 5-7\n")
        srts = sorted(p.name for p in sel_dir.glob("*.srt"))
        check(
            "4.1: range selection rc 0 (S28)", proc.returncode == 0, fail_detail(proc)
        )
        check(
            "4.1: exactly 5 srts with expected names (S28)",
            srts == ["vid 1.srt", "vid 3.srt", "vid 5.srt", "vid 6.srt", "vid 7.srt"],
            str(srts),
        )

        # S28b: entrada inválida re-pregunta y no procesa.
        clear_srts(sel_dir)
        proc = run_subtitler(["--input-dir", str(sel_dir)], input_text="99 x\nq\n")
        check(
            "4.1: invalid input re-asks, rc 0 (S28)",
            proc.returncode == 0,
            fail_detail(proc),
        )
        check(
            "4.1: invalid input processed nothing (S28)",
            not any(sel_dir.glob("*.srt"))
            and proc.stdout.count("Selecciona archivos") >= 2,
            proc.stdout[-500:],
        )

        # S29: 'a' procesa todos.
        proc = run_subtitler(["--input-dir", str(sel_dir)], input_text="a\n")
        check(
            "4.1: 'a' processes all 7 (S29)",
            proc.returncode == 0 and len(list(sel_dir.glob("*.srt"))) == 7,
            f"rc={proc.returncode} srts={len(list(sel_dir.glob('*.srt')))}",
        )

        # S29b: 'q' abandona sin procesar.
        clear_srts(sel_dir)
        proc = run_subtitler(["--input-dir", str(sel_dir)], input_text="q\n")
        check(
            "4.1: 'q' quits with zero outputs, rc 0 (S29)",
            proc.returncode == 0 and not any(sel_dir.glob("*.srt")),
            fail_detail(proc),
        )

        # Triángulo: rango invertido en el selector.
        proc = run_subtitler(["--input-dir", str(sel_dir)], input_text="7-5\n")
        srts = sorted(p.name for p in sel_dir.glob("*.srt"))
        check(
            "4.1: inverted range selects 5,6,7",
            srts == ["vid 5.srt", "vid 6.srt", "vid 7.srt"],
            str(srts),
        )

        # S30: --input-dir inexistente -> carpeta creada + guía, rc 0.
        nueva = TMP / "carpeta nueva"
        proc = run_subtitler(["--input-dir", str(nueva)], input_text="q\n")
        check("4.1: missing dir created (S30)", nueva.is_dir(), str(nueva))
        check(
            "4.1: guide printed (S30)",
            "Coloca videos" in proc.stdout and proc.returncode == 0,
            proc.stdout[-400:],
        )

        # Triángulo: selector con carpeta vacía existente.
        vacia = TMP / "carpeta vacia"
        vacia.mkdir(parents=True, exist_ok=True)
        proc = run_subtitler(["--input-dir", str(vacia)], input_text="q\n")
        check(
            "4.1: empty folder shows guide, rc 0",
            proc.returncode == 0 and "Coloca videos" in proc.stdout,
            proc.stdout[-400:],
        )

        # --- 4.2: ensure_tools (S33) ---
        base_env = {
            k: v
            for k, v in os.environ.items()
            if k in ("SYSTEMROOT", "TEMP", "TMP", "COMSPEC", "PATHEXT")
        }

        empty_bin = TMP / "empty bin"
        empty_bin.mkdir(parents=True, exist_ok=True)
        env_no_tools = {**base_env, "PATH": str(empty_bin)}
        proc = run_subtitler([str(sample)], env=env_no_tools)
        check(
            "4.2: missing tools rc 1 (S33)",
            proc.returncode == 1,
            f"rc={proc.returncode}",
        )
        check(
            "4.2: clear message names missing tools (S33)",
            "ffmpeg" in proc.stdout
            and "ffprobe" in proc.stdout
            and "PATH" in proc.stdout,
            proc.stdout[-400:],
        )
        check(
            "4.2: nothing processed without tools (S33)",
            "--- sample test.mp4" not in proc.stdout,
            proc.stdout[-300:],
        )

        # Triángulo: solo falta ffmpeg (ffprobe copiado al dir vacío).
        ffprobe_exe = shutil.which("ffprobe")
        if ffprobe_exe:
            shutil.copy(ffprobe_exe, empty_bin / "ffprobe.exe")
            proc = run_subtitler([str(sample)], env=env_no_tools)
            check(
                "4.2: ffprobe-only env still rc 1 naming ffmpeg",
                proc.returncode == 1
                and "ffmpeg" in proc.stdout
                and "--- " not in proc.stdout,
                proc.stdout[-400:],
            )
        else:
            check(
                "4.2: ffprobe found for triangle",
                False,
                "shutil.which(ffprobe) is None",
            )
        # --- 5.1: sección real opt-in (los checks llegan con 5.3/5.4) ---
        if not REAL_MODE:
            print(
                "[SKIP] sección real: transcripción y traducción con modelos (opt-in: SUBTITLER_SMOKE_REAL=1)"
            )
        run_real_check("real S11/S12: transcribe tiny + progreso", real_transcribe_en)
        run_real_check("real S6: Argos en→es", real_argos_en_to_es)
        # --- 5.4: contrato S16 en default (sin pares Argos instalados) ---
        s16 = TMP / "s16 eng.mp4"
        make_embedded(s16, cues_text="hello world", lang="eng", default=True)
        proc = run_subtitler([str(s16)])
        check(
            "5.4: no-route run rc 0, not failed (S16)",
            proc.returncode == 0,
            fail_detail(proc),
        )
        check(
            "5.4: WARN for missing route (S16)",
            "WARN" in proc.stdout,
            proc.stdout[-400:],
        )
        # Enmienda 5.5: con la ruta imposible (aislamiento Argos sin red) el
        # fallback escribe SOLO el original sufijado; el principal no existe.
        s16_orig = s16.with_name(f"{s16.stem}-en.srt")
        check(
            "5.4/5.5: failure keeps only suffixed original (S16)",
            s16_orig.exists()
            and "hello world" in s16_orig.read_text(encoding="utf-8-sig")
            and not s16.with_suffix(".srt").exists(),
            f"orig={s16_orig} main={s16.with_suffix('.srt')}",
        )

        # --- 5.5 (enmienda): descarga Argos en demanda + doble salida (D13/D14)
        # e2e con argostranslate falso (cero red, cero índice real): disponible
        # [("en","es")] -> descarga el directo, re-resuelve y traduce.
        en_ok = TMP / "en ok.mp4"
        make_embedded(en_ok, cues_text="hello world", lang="eng", default=True)
        proc = run_with_fake_argos([str(en_ok)], [("en", "es")])
        check(
            "5.5: download success rc 0",
            proc.returncode == 0,
            fail_detail(proc),
        )
        ok_main = en_ok.with_suffix(".srt")
        ok_orig = en_ok.with_name("en ok-en.srt")
        check(
            "5.5: translated main video.srt (en source)",
            ok_main.exists()
            and "[es] hello world" in ok_main.read_text(encoding="utf-8-sig"),
            fail_detail(proc),
        )
        check(
            "5.5: original side video-en.srt kept",
            ok_orig.exists()
            and "hello world" in ok_orig.read_text(encoding="utf-8-sig"),
            str(ok_orig),
        )
        check(
            "5.5: INFO download line for direct pair",
            "INFO descargando paquete Argos en→es" in proc.stdout,
            proc.stdout[-400:],
        )
        check(
            "5.5: no partial .tmp for either output",
            not ok_main.with_name(ok_main.name + ".tmp").exists()
            and not ok_orig.with_name(ok_orig.name + ".tmp").exists(),
        )

        # Índice vacío: descarga imposible -> WARN + SOLO el original sufijado.
        en_fail = TMP / "en fail.mp4"
        make_embedded(en_fail, cues_text="hello world", lang="eng", default=True)
        proc = run_with_fake_argos([str(en_fail)], [])
        check(
            "5.5: download failure rc 0 (never aborts)",
            proc.returncode == 0,
            fail_detail(proc),
        )
        check(
            "5.5: WARN names missing route",
            "WARN" in proc.stdout and "en→es" in proc.stdout,
            proc.stdout[-400:],
        )
        fail_orig = en_fail.with_name("en fail-en.srt")
        check(
            "5.5: failure writes only suffixed original",
            fail_orig.exists()
            and "hello world" in fail_orig.read_text(encoding="utf-8-sig")
            and not en_fail.with_suffix(".srt").exists(),
            f"orig={fail_orig} main={en_fail.with_suffix('.srt')}",
        )

        # Origen español: salida única video.srt, sin sufijo ni duplicado.
        es_single = TMP / "es single.mp4"
        make_embedded(es_single, cues_text="hola mundo", lang="spa", default=True)
        proc = run_with_fake_argos([str(es_single)], [("en", "es")])
        check(
            "5.5: es source rc 0",
            proc.returncode == 0,
            fail_detail(proc),
        )
        check(
            "5.5: es source single video.srt, no suffixed duplicate",
            es_single.with_suffix(".srt").exists()
            and "hola mundo"
            in es_single.with_suffix(".srt").read_text(encoding="utf-8-sig")
            and not es_single.with_name("es single-es.srt").exists(),
            proc.stdout[-400:],
        )
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

    print(f"\nRESULT: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
