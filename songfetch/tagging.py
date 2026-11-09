"""Tags (título/artista/álbum) e capa embutidas com mutagen."""
from __future__ import annotations

import base64
from pathlib import Path

from .covers import fetch_cover
from .models import Track
from .textutil import short

try:
    import mutagen
except ImportError:
    mutagen = None


def tag_file(path: Path, track: Track) -> None:
    if mutagen is None or not track.name:
        return
    try:
        audio = mutagen.File(path, easy=True)
        if audio is None:
            return
        if audio.tags is None:
            audio.add_tags()
        audio["title"] = track.name
        if track.artists:
            audio["artist"] = track.artists
        if track.album:
            audio["album"] = track.album
        audio.save()
    except Exception as e:
        print(f"   [aviso] não consegui gravar tags: {short(e, 80)}")


def has_cover(path: Path) -> bool:
    if mutagen is None:
        return False
    try:
        audio = mutagen.File(path)
        if audio is None or audio.tags is None:
            return False
        ext = path.suffix.lower()
        if ext in (".m4a", ".mp4"):
            return bool(audio.tags.get("covr"))
        if ext in (".opus", ".ogg"):
            return bool(audio.tags.get("metadata_block_picture"))
        if ext == ".mp3":
            return any(k.startswith("APIC") for k in audio.tags.keys())
    except Exception:
        pass
    return False


def embed_cover(path: Path, data: bytes, mime: str) -> bool:
    ext = path.suffix.lower()
    try:
        if ext in (".opus", ".ogg"):
            from mutagen.flac import Picture
            from mutagen.oggopus import OggOpus
            pic = Picture()
            pic.type, pic.mime, pic.desc, pic.data = 3, mime, "Capa", data
            audio = OggOpus(path)
            audio["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
            audio.save()
        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4, MP4Cover
            fmt = MP4Cover.FORMAT_JPEG if mime == "image/jpeg" else MP4Cover.FORMAT_PNG
            audio = MP4(path)
            audio["covr"] = [MP4Cover(data, imageformat=fmt)]
            audio.save()
        elif ext == ".mp3":
            from mutagen.id3 import APIC, ID3, ID3NoHeaderError
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Capa", data=data))
            tags.save(path)
        else:
            print(f"   [aviso] formato {ext or '?'} não suporta capa (instale o ffmpeg)")
            return False
        return True
    except Exception as e:
        print(f"   [aviso] não consegui gravar a capa: {short(e, 80)}")
        return False


def add_cover(path: Path, track: Track) -> bool:
    if mutagen is None:
        return False
    got = fetch_cover(track)
    return bool(got) and embed_cover(path, *got)
