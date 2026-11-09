"""Escolha do vídeo certo (puro: não acessa a rede)."""
from __future__ import annotations

from . import config as C
from .models import Track
from .textutil import (BAD_RE, LIVE_RE, LYRIC_RE, OFFICIAL_RE, coverage, has_phrase, norm)


def evaluate(track: Track, entry: dict):
    """Avalia um candidato. Retorna (info, None) se serve ou (None, motivo)."""
    vid = entry.get("id")
    if not vid:
        return None, "resultado sem id"
    title = entry.get("title") or ""
    channel = entry.get("channel") or entry.get("uploader") or ""
    tn, cn = norm(title), norm(channel)

    unwanted = set(BAD_RE.findall(tn)) - set(BAD_RE.findall(track.name_norm))
    if unwanted:
        return None, f"'{title}': versão não oficial ({', '.join(sorted(unwanted))})"
    if track.artist_norms and not any(has_phrase(tn, a) or has_phrase(cn, a)
                                      for a in track.artist_norms):
        return None, f"'{title}': artista não encontrado"
    if not (has_phrase(tn, track.title_norm) or coverage(track.title_norm, tn) >= 0.8):
        return None, f"'{title}': nome da faixa não encontrado"

    dur = entry.get("duration")
    tol = C.TOL_LIVE if track.is_live else C.TOL_STUDIO
    diff = abs(dur - track.duration_s) if dur and track.duration_s else None
    if diff is not None and diff > tol:
        return None, f"'{title}': duração {dur:.0f}s vs {track.duration_s:.0f}s"

    is_topic = cn.endswith(" topic") or cn == "topic"
    is_official = bool(OFFICIAL_RE.search(tn) or OFFICIAL_RE.search(cn))
    is_artist_channel = bool(track.artist_norms) and any(has_phrase(cn, a) for a in track.artist_norms)
    kind = ("topic" if is_topic else "official" if is_official
            else "artist_channel" if is_artist_channel else "other")

    score = {"topic": 40, "official": 25, "artist_channel": 15, "other": 0}[kind]
    score -= diff * 0.8 if diff is not None else 10
    vid_live = bool(LIVE_RE.search(tn))
    if track.is_live and not vid_live:
        score -= 15
    elif not track.is_live and vid_live:
        score -= 25
    if LYRIC_RE.search(tn):
        score -= 8

    return {
        "url": f"https://www.youtube.com/watch?v={vid}", "title": title,
        "channel": channel, "kind": kind, "duration": dur, "diff": diff,
        "score": round(score, 1), "verified": dur is not None,
    }, None


def rank_candidates(track: Track, entries: list):
    """Plano A (estrito): filtra e ordena por pontuação. Retorna (lista, motivos)."""
    ok, why = [], []
    for e in entries or []:
        if not e:
            continue
        info, reason = evaluate(track, e)
        if info:
            ok.append(info)
        else:
            why.append(reason)
    ok.sort(key=lambda i: i["score"], reverse=True)
    return ok, why


def loose_rows(track: Track, entries: list):
    """Plano B (flexível): sem exigir artista/título; só descarta covers/karaokê e ordena
    pela duração mais próxima. Retorna [(diff, entry, duration)] (diff=10**6 se desconhecida)."""
    rows = []
    for e in entries or []:
        if not e or not e.get("id"):
            continue
        title = e.get("title") or ""
        if set(BAD_RE.findall(norm(title))) - set(BAD_RE.findall(track.name_norm)):
            continue
        dur = e.get("duration")
        diff = abs(dur - track.duration_s) if dur and track.duration_s else None
        rows.append((diff if diff is not None else 10**6, e, dur))
    rows.sort(key=lambda r: r[0])  # estável: sem duração mantém a ordem da busca
    return rows
