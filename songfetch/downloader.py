"""Download do áudio com retry em 403, tags e capa."""
from __future__ import annotations

import time
from pathlib import Path

import yt_dlp

from . import config as C
from .models import Track
from .tagging import add_cover, tag_file
from .textutil import sanitize, short

FORMATS = ("best", "mp3", "m4a", "opus")


def is_forbidden(e: Exception) -> bool:
    msg = str(e)
    return "HTTP Error 403" in msg or "403: Forbidden" in msg


def cleanup_partials(out_dir: Path, stem: str) -> None:
    """Remove restos de download interrompido (.part etc.) antes de tentar de novo."""
    for p in out_dir.iterdir():
        if p.name.startswith(stem) and p.suffix in (".part", ".ytdl", ".temp"):
            try:
                p.unlink()
            except OSError:
                pass


def postprocessors(fmt: str) -> list:
    if fmt == "best":   # mantém o codec original (opus/aac), sem reencodar
        return [{"key": "FFmpegExtractAudio", "preferredcodec": "best"}]
    q = {"preferredquality": "0"} if fmt == "mp3" else {}
    return [{"key": "FFmpegExtractAudio", "preferredcodec": fmt, **q}]


def download(info: dict, track: Track, out_dir: Path, base_opts: dict, *,
             fmt: str = "best", cover: bool = True, has_ffmpeg: bool = True):
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = sanitize(f"{', '.join(track.artists)} - {track.name}" if track.artists else track.name)
    opts = {
        **base_opts,
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / (stem.replace("%", "%%") + ".%(ext)s")),
        "retries": 5, "fragment_retries": 5,
    }
    if has_ffmpeg:
        opts["postprocessors"] = postprocessors(fmt)

    total = 1 + C.DL_403_RETRIES
    res = None
    for attempt in range(total):
        run_opts = dict(opts)
        clients = C.DL_CLIENT_ROTATION[attempt] if attempt < len(C.DL_CLIENT_ROTATION) else None
        if clients:
            run_opts["extractor_args"] = {"youtube": {"player_client": clients}}
        try:
            with yt_dlp.YoutubeDL(run_opts) as ydl:
                res = ydl.extract_info(info["url"], download=True)
            break
        except Exception as e:  # sem ignoreerrors: falha de verdade vira exceção
            cleanup_partials(out_dir, stem)
            if is_forbidden(e) and attempt < total - 1:
                wait = C.DL_403_WAIT[min(attempt, len(C.DL_403_WAIT) - 1)]
                nxt = C.DL_CLIENT_ROTATION[attempt + 1] if attempt + 1 < len(C.DL_CLIENT_ROTATION) else None
                print(f"   403 do servidor (tentativa {attempt + 1}/{total}); "
                      f"aguardando {wait}s e tentando de novo"
                      + (f" com cliente {'/'.join(nxt)}" if nxt else ""))
                time.sleep(wait)
                continue
            print(f"   erro no download: {short(e)}"
                  + (f" (403 persistente após {total} tentativas)" if is_forbidden(e) else ""))
            return None

    path = None
    for d in (res or {}).get("requested_downloads") or []:
        if d.get("filepath"):
            path = Path(d["filepath"])
    if not path or not path.exists():
        found = [p for p in out_dir.iterdir() if p.stem == stem and p.is_file()]
        path = found[0] if found else None
    if path:
        tag_file(path, track)
        if cover and not add_cover(path, track):
            print("   [aviso] sem capa (rode --fix-covers depois para tentar de novo)")
    return path
