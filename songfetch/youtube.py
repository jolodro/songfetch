"""Busca no YouTube via yt-dlp (plano A estrito e plano B flexível)."""
from __future__ import annotations

import time

import yt_dlp

from . import config as C
from .matcher import loose_rows, rank_candidates
from .models import Track
from .textutil import short


class QuietLogger:
    """Evita o 'ERROR:' duplicado do yt-dlp; o programa imprime os erros por conta própria."""
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def make_base_opts(cookies_browser: str | None = None) -> dict:
    opts = {"quiet": True, "no_warnings": True, "cachedir": False, "noplaylist": True,
            "logger": QuietLogger()}
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    return opts


def search(query: str, base_opts: dict, n: int = C.SEARCH_RESULTS):
    opts = {**base_opts, "extract_flat": True}
    for attempt in range(1, C.MAX_RETRIES + 1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                res = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
            return (res or {}).get("entries") or []
        except Exception as e:
            if attempt == C.MAX_RETRIES:
                print(f"   erro na busca: {short(e)}")
                return None
            wait = 15 * attempt
            print(f"   busca falhou ({short(e, 80)}); aguardando {wait}s ({attempt}/{C.MAX_RETRIES})")
            time.sleep(wait)


def fetch_duration(url: str, base_opts: dict):
    try:
        with yt_dlp.YoutubeDL({**base_opts, "extract_flat": False}) as ydl:
            return (ydl.extract_info(url, download=False) or {}).get("duration")
    except Exception:
        return None


def resolve_duration(info: dict, track: Track, base_opts: dict, tol: float) -> bool:
    """Se a busca não trouxe a duração, consulta o vídeo; False se estiver fora da tolerância."""
    if info["duration"] is not None or not track.duration_s:
        return True
    dur = fetch_duration(info["url"], base_opts)
    if dur:
        diff = abs(dur - track.duration_s)
        if diff > tol:
            return False
        info.update(duration=dur, diff=diff, verified=True)
    return True


def loose_candidates(track: Track, base_opts: dict):
    entries = search(f"{' '.join(track.artists)} {track.clean}".strip(), base_opts, C.LOOSE_RESULTS)
    if not entries:
        return
    tol = C.TOL_LOOSE_LIVE if track.is_live else C.TOL_LOOSE_STUDIO
    for diff, e, dur in loose_rows(track, entries):
        url = f"https://www.youtube.com/watch?v={e['id']}"
        if track.duration_s and dur is None:
            dur = fetch_duration(url, base_opts)
            diff = abs(dur - track.duration_s) if dur else None
        if track.duration_s and diff is not None and diff > tol:
            continue
        yield {"url": url, "title": e.get("title") or "",
               "channel": e.get("channel") or e.get("uploader") or "", "kind": "fallback",
               "duration": dur, "diff": diff if diff is not None and diff < 10**6 else None,
               "score": 0, "verified": dur is not None}


def candidates(track: Track, base_opts: dict, use_fallback: bool, notes: list):
    """Gera candidatos em ordem. Link direto: só ele. Senão plano A (até 3) e, se todos
    falharem, plano B."""
    if track.direct_url:
        yield {"url": track.direct_url, "title": track.name, "channel": "", "kind": "direct",
               "duration": None, "diff": None, "score": 100, "verified": True}
        return
    artist = track.artists[0] if track.artists else ""
    tol = C.TOL_LIVE if track.is_live else C.TOL_STUDIO
    seen: set = set()
    queries = [f"{artist} {track.clean}".strip() + (" ao vivo" if track.is_live else ""),
               f"{artist} {track.clean} topic".strip()]
    for q in queries:
        entries = search(q, base_opts)
        if entries is None:
            notes.append("erro na busca")
            continue
        ranked, why = rank_candidates(track, entries)
        notes.extend(why[:3])
        yielded = False
        for info in ranked[:3]:
            if info["url"] in seen or not resolve_duration(info, track, base_opts, tol):
                continue
            seen.add(info["url"])
            yielded = True
            yield info
        if yielded:
            break
    if use_fallback:
        for info in loose_candidates(track, base_opts):
            if info["url"] not in seen:
                seen.add(info["url"])
                yield info
