"""Fluxo por faixa: buscar, baixar, colocar nas pastas das playlists e registrar."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .downloader import download
from .library import Library, target_dir
from .models import Track, make_track
from .tagging import add_cover, has_cover
from .youtube import candidates


@dataclass
class Settings:
    out: Path
    layout: str = "album"            # organização dentro da playlist: album | artist | flat
    fmt: str = "best"
    cover: bool = True
    dry_run: bool = False
    fallback: bool = True
    playlist_folders: bool = True
    max_attempts: int = 4


@dataclass
class Ctx:
    s: Settings
    base_opts: dict
    lib: Library
    has_ffmpeg: bool = True
    preview: list = field(default_factory=list)


# ------------------------------------------------------------------ pastas / arquivos
def folders_for(track: Track, ctx: Ctx) -> list:
    """Pastas de playlist da faixa (na ordem em que a faixa apareceu nas playlists)."""
    if not ctx.s.playlist_folders:
        return []
    return [ctx.lib.playlist_folder(k, n) for k, n in track.playlists.items()]


def link_or_copy(src: Path, dst: Path) -> None:
    """Hardlink (não ocupa espaço extra); se o disco não suportar, copia."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def prune_empty(d: Path, stop: Path) -> None:
    d, stop = d.resolve(), stop.resolve()
    while d != stop and stop in d.parents and d.is_dir() and not any(d.iterdir()):
        d.rmdir()
        d = d.parent


def organize(track: Track, ctx: Ctx, move: bool = True) -> bool:
    """Garante o arquivo da faixa na pasta da 1ª playlist e uma cópia (hardlink) em cada uma
    das outras. Arquivos antigos dentro de `out` são movidos; retorna True se algo mudou."""
    folders = folders_for(track, ctx)
    entry = ctx.lib.log.get(track.id)
    if not folders or not isinstance(entry, dict) or not entry.get("file"):
        return False
    src = ctx.lib.path_of(entry["file"])
    if not src.exists():
        return False
    out = ctx.s.out.resolve()
    changed = False
    dst = target_dir(out, track, ctx.s.layout, folders[0]) / src.name

    if src.resolve() != dst.resolve():
        shared = any(e is not entry and isinstance(e, dict) and e.get("file") == entry["file"]
                     for e in ctx.lib.log.values())
        if dst.exists():
            if os.path.samefile(src, dst) and out in src.resolve().parents and not shared:
                src.unlink()                  # era só outro nome do mesmo arquivo
                prune_empty(src.parent, out)
        elif move and not shared and out in src.resolve().parents:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            prune_empty(src.parent, out)
        else:
            link_or_copy(src, dst)
        entry["file"] = ctx.lib.rel(dst)
        if entry.get("url"):
            ctx.lib.known_urls[entry["url"]] = entry["file"]
        changed = True

    copies = []
    for f in folders[1:]:
        d = target_dir(out, track, ctx.s.layout, f) / dst.name
        if not d.exists():
            link_or_copy(dst, d)
            changed = True
        copies.append(ctx.lib.rel(d))
    names = list(track.playlists.values())
    if entry.get("copies") != copies or entry.get("playlists") != names:
        entry["copies"], entry["playlists"] = copies, names
        changed = True
    return changed


# ------------------------------------------------------------------------- processo
def fail(ctx: Ctx, track: Track, reason: str, details=None) -> str:
    ctx.lib.record_fail(track, reason, details)
    print(f"   [FALHA] {reason}")
    return "fail"


def process(track: Track, ctx: Ctx) -> str:
    folders = folders_for(track, ctx)
    out_dir = target_dir(ctx.s.out, track, ctx.s.layout, folders[0] if folders else None)
    notes: list = []
    tried = 0
    for info in candidates(track, ctx.base_opts, ctx.s.fallback, notes):
        fb = info["kind"] == "fallback"
        diff = f"{info['diff']:.0f}s" if info["diff"] is not None else "?"
        print(f"   -> {'[PLANO B] ' if fb else ''}{info['title']} | {info['channel']} | "
              f"{info['kind']} | Δdur {diff} | {info['url']}")

        if ctx.s.dry_run:
            ctx.preview.append({"playlist": folders[0] if folders else "",
                                "artista": "; ".join(track.artists), "faixa": track.name,
                                "url": info["url"], "titulo_yt": info["title"],
                                "canal": info["channel"], "tipo": info["kind"],
                                "dif_duracao_s": diff, "score": info["score"]})
            return "ok"

        known = ctx.lib.known_urls.get(info["url"])
        if known and ctx.lib.path_of(known).exists():     # mesmo vídeo já baixado antes
            file, reused = known, True
        else:
            path = download(info, track, out_dir, ctx.base_opts, fmt=ctx.s.fmt,
                            cover=ctx.s.cover, has_ffmpeg=ctx.has_ffmpeg)
            if not path:
                tried += 1
                notes.append(f"download falhou: {info['url']}")
                if tried >= ctx.s.max_attempts:
                    break
                print("   tentando o próximo candidato...")
                continue
            file, reused = ctx.lib.rel(path), False

        ctx.lib.record_ok(track, info, file, reused)
        organize(track, ctx, move=not reused)   # reaproveitado: só linka, não move o original
        print("   [OK]" + (" (vídeo já baixado antes)" if reused else "")
              + (" — veio do plano B, vale conferir" if fb else ""))
        return "ok"

    if tried:
        return fail(ctx, track, f"Download falhou em {tried} candidato(s)", notes)
    return fail(ctx, track, "Nenhuma versão encontrada (busca estrita e flexível)", notes)


# ---------------------------------------------------------------------------- capas
def fix_covers(ctx: Ctx, by_id: dict | None = None) -> tuple:
    """Grava a capa nos arquivos do log que ainda não têm (inclui as cópias nas playlists)."""
    by_id = by_id or {}
    novos = ja = sem = 0
    for tid, entry in ctx.lib.log.items():
        if not isinstance(entry, dict) or not entry.get("file"):
            continue
        t = by_id.get(tid) or make_track(entry.get("track", ""), entry.get("artist", ""),
                                         entry.get("album", ""), uri=entry.get("uri", ""))
        for f in [entry["file"], *entry.get("copies", [])]:
            path = ctx.lib.path_of(f)
            if not path.exists():
                continue
            if has_cover(path):
                ja += 1
            elif add_cover(path, t):
                novos += 1
                print(f"   capa gravada: {path.name}")
            else:
                sem += 1
    return novos, ja, sem
