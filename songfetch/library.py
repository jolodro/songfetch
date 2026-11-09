"""Estado: o que já foi baixado e o que falhou (JSON gravado de forma atômica)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import config as C
from .models import Track
from .textutil import sanitize, short


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        backup = path.with_suffix(path.suffix + ".corrompido")
        try:
            path.replace(backup)
        except OSError:
            pass
        print(f"[AVISO] {path.name} ilegível ({short(e)}); copiado para {backup.name}")
        return default


def save_json(path: Path, data) -> None:
    """Escrita atômica: nunca deixa o arquivo pela metade."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def target_dir(out: Path, track: Track, layout: str, folder: str | None = None) -> Path:
    """<out>/[pasta da playlist]/[layout interno]. layout: album | artist | flat."""
    base = out / folder if folder else out
    album = sanitize(track.album or "Sem álbum")
    if layout == "flat":
        return base
    if layout == "artist":
        return base / sanitize(track.artists[0] if track.artists else "Desconhecido") / album
    return base / album


class Library:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir.resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.state_dir / C.STATE_LOG
        self.failed_path = self.state_dir / C.STATE_FAILED
        self.playlists_path = self.state_dir / C.STATE_PLAYLISTS
        self.log = load_json(self.log_path, {})
        failed = load_json(self.failed_path, {})
        self.failed = failed if isinstance(failed, dict) else {}  # formato antigo era lista
        pls = load_json(self.playlists_path, {})
        self.playlists = pls if isinstance(pls, dict) else {}   # chave da playlist -> pasta
        self.known_urls = {v["url"]: v["file"] for v in self.log.values()
                           if isinstance(v, dict) and v.get("file") and v.get("url")}

    def playlist_folder(self, key: str, name: str) -> str:
        """Pasta da playlist. Mesma playlist = mesma pasta sempre; playlists diferentes com o
        mesmo nome viram 'Nome', 'Nome (1)', 'Nome (2)'..."""
        if key in self.playlists:
            return self.playlists[key]
        base = sanitize(name) or "Playlist"
        used = {v.casefold() for v in self.playlists.values()}
        cand, n = base, 0
        while cand.casefold() in used:
            n += 1
            cand = f"{base} ({n})"
        self.playlists[key] = cand
        return cand

    def path_of(self, file: str) -> Path:
        p = Path(file)
        return p if p.is_absolute() else self.state_dir / p

    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.state_dir).as_posix()
        except ValueError:
            return str(path.resolve())

    def is_done(self, track: Track, out: Path, layout: str) -> bool:
        entry = self.log.get(track.id)
        if isinstance(entry, dict):
            f = entry.get("file")
            return self.path_of(f).exists() if f else True   # apagou o arquivo -> baixa de novo
        if track.legacy_key in self.log:    # log da primeira versão: confia se a pasta tem arquivos
            d = target_dir(out, track, "album")
            return d.is_dir() and any(d.iterdir())
        return False

    def record_ok(self, track: Track, info: dict, file: str, reused: bool) -> None:
        self.log[track.id] = {
            "status": "success", "artist": "; ".join(track.artists), "track": track.name,
            "album": track.album, "uri": track.uri, "url": info["url"], "title": info["title"],
            "channel": info["channel"], "kind": info["kind"], "fallback": info["kind"] == "fallback",
            "verified": info["verified"], "file": file, "reused": reused,
        }
        self.failed.pop(track.id, None)
        self.known_urls[info["url"]] = file

    def record_fail(self, track: Track, reason: str, details=None) -> None:
        self.failed[track.id] = {
            "artist": "; ".join(track.artists), "track": track.name, "album": track.album,
            "fontes": sorted(track.sources), "reason": reason, "detalhes": (details or [])[:5],
        }

    def save(self) -> None:
        save_json(self.log_path, self.log)
        save_json(self.failed_path, self.failed)
        save_json(self.playlists_path, self.playlists)
