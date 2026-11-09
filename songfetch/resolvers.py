"""Transforma links (YouTube e Spotify) em faixas.

Atenção: a parte do Spotify lê as páginas públicas de "embed", que não são uma API
oficial e podem mudar. Para playlists grandes, o caminho mais confiável continua sendo
exportar o CSV pelo Exportify.
"""
from __future__ import annotations

import json
import re
import urllib.request
from urllib.parse import parse_qs, urlparse

import yt_dlp

from .models import Track, make_track
from .textutil import parse_duration, short

YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
_UA = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.8"}

# ------------------------------------------------------------------ classificação
def classify(link: str):
    """('youtube', 'video'|'playlist', id) | ('spotify', 'track'|'album'|'playlist', id) | None"""
    link = (link or "").strip()
    m = re.match(r"^spotify:(track|album|playlist):([A-Za-z0-9]+)$", link)
    if m:
        return "spotify", m.group(1), m.group(2)
    u = urlparse(link)
    host = (u.hostname or "").lower()
    if host == "open.spotify.com":
        parts = [p for p in u.path.split("/") if p]
        if parts and parts[0].startswith("intl-"):
            parts = parts[1:]
        if len(parts) >= 2 and parts[0] in ("track", "album", "playlist"):
            return "spotify", parts[0], parts[1]
        return None
    if host in YT_HOSTS:
        q = parse_qs(u.query)
        if host == "youtu.be":
            vid = u.path.strip("/").split("/")[0]
            return ("youtube", "video", vid) if vid else None
        segs = [p for p in u.path.split("/") if p]
        if segs and segs[0] in ("shorts", "embed", "live") and len(segs) > 1:
            return "youtube", "video", segs[1]
        if "v" in q:            # watch?v=X&list=Y conta como vídeo único
            return "youtube", "video", q["v"][0]
        if "list" in q:
            return "youtube", "playlist", q["list"][0]
    return None


def to_spotify_uri(value: str) -> str:
    """URL/URI de faixa do Spotify -> 'spotify:track:ID' (ou '')."""
    m = re.search(r"spotify[:/.]+(?:com/)?(?:intl-\w+/)?track[:/]([A-Za-z0-9]+)", value or "")
    return f"spotify:track:{m.group(1)}" if m else ""


def youtube_watch_url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


# --------------------------------------------------------------------------- YouTube
_NOISE = re.compile(
    r"\s*[\(\[]\s*(?:official|oficial|lyric|lyrics|letra|clipe|video|vídeo|audio|áudio|"
    r"hd|4k|legendado|visualizer)[^\)\]]*[\)\]]", re.I)


def parse_video_title(title: str, channel: str = ""):
    """'Artista - Música (Official Video)' -> ('Artista', 'Música'); senão usa o canal."""
    t = " ".join(_NOISE.sub("", title or "").split())
    for sep in (" - ", " – ", " — "):
        if sep in t:
            a, b = t.split(sep, 1)
            if a.strip() and b.strip():
                return a.strip(), b.strip()
    ch = re.sub(r"\s*-\s*topic$|vevo$|\s+official$", "", channel or "", flags=re.I).strip()
    return ch, t


def track_from_video_info(info: dict, source: str = "", playlist=None) -> Track:
    vid = info.get("id", "")
    artist = info.get("artist") or ""            # yt-dlp preenche em faixas do YouTube Music/Topic
    name = info.get("track") or ""
    if not (artist and name):
        artist2, name2 = parse_video_title(info.get("title", ""), info.get("channel")
                                           or info.get("uploader") or "")
        artist, name = artist or artist2, name or name2
    artists = [a.strip() for a in re.split(r",\s*", artist) if a.strip()] if artist else []
    return make_track(name or info.get("title", ""), artists, info.get("album") or "",
                      info.get("duration") or 0, tid=f"yt:{vid}",
                      direct_url=youtube_watch_url(vid), source=source, playlist=playlist)


def youtube_to_tracks(kind: str, ident: str, link: str, base_opts: dict):
    """Vídeo único ou playlist do YouTube -> faixas com link direto."""
    try:
        if kind == "playlist":
            opts = {**base_opts, "extract_flat": "in_playlist", "noplaylist": False,
                    "skip_download": True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                res = ydl.extract_info(link, download=False) or {}
            src = res.get("title") or f"playlist {ident}"
            entries = [e for e in res.get("entries") or [] if e and e.get("id")]
            pl = (f"youtube:playlist:{ident}", src)
            return [track_from_video_info(e, src, pl) for e in entries], \
                   (None if entries else "playlist vazia ou privada")
        with yt_dlp.YoutubeDL({**base_opts, "extract_flat": False, "skip_download": True}) as ydl:
            info = ydl.extract_info(link, download=False) or {}
        if not info.get("id"):
            return [], "vídeo indisponível"
        return [track_from_video_info(info, "link")], None
    except Exception as e:
        return [], short(e)


# --------------------------------------------------------------------------- Spotify
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def http_get(url: str, timeout: int = 20) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _find(obj, key):
    """Primeiro valor da chave `key` em qualquer nível de dicts/listas."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            got = _find(v, key)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _find(v, key)
            if got is not None:
                return got
    return None


def _names(entity: dict) -> list:
    arts = entity.get("artists")
    if isinstance(arts, list):
        names = [a.get("name", "") if isinstance(a, dict) else str(a) for a in arts]
        return [n.strip() for n in names if n and n.strip()]
    sub = (entity.get("subtitle") or entity.get("artist") or "").replace("\xa0", " ")
    return [n.strip() for n in sub.split(",") if n.strip()]


def tracks_from_embed(data: dict, kind: str, sid: str):
    """Extrai faixas do JSON embutido (__NEXT_DATA__) da página de embed do Spotify."""
    entity = _find(data, "entity") or {}
    title = entity.get("name") or entity.get("title") or ""
    if kind == "track":
        names = _names(entity)
        if not title:
            return [], "faixa não encontrada na página"
        return [make_track(title, names, "", parse_duration(entity.get("duration"), True),
                           uri=f"spotify:track:{sid}", source="link")], None
    items = entity.get("trackList") or _find(data, "trackList") or []
    out = []
    for it in items:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        uri = to_spotify_uri(it.get("uri", ""))
        out.append(make_track(it["title"], _names(it), title if kind == "album" else "",
                              parse_duration(it.get("duration"), True), uri=uri,
                              source=title or kind,
                              playlist=(f"spotify:playlist:{sid}", title or f"playlist {sid}")
                              if kind == "playlist" else None))
    if not out:
        return [], "lista vazia ou privada (playlists privadas exigem o CSV do Exportify)"
    return out, None


def track_from_meta(html: str, sid: str):
    """Plano B para faixa única: meta tags og:* da página pública."""
    def meta(prop):
        m = re.search(r'<meta[^>]+(?:property|name)="%s"[^>]+content="([^"]*)"' % re.escape(prop), html)
        return m.group(1) if m else ""
    name = meta("og:title")
    parts = [p.strip() for p in meta("og:description").split("·")]
    if not name or not parts or not parts[0]:
        return None
    return make_track(name, [a.strip() for a in parts[0].split(",") if a.strip()], "",
                      parse_duration(meta("music:duration")), uri=f"spotify:track:{sid}",
                      source="link")


def spotify_to_tracks(kind: str, sid: str):
    try:
        html = http_get(f"https://open.spotify.com/embed/{kind}/{sid}")
        m = _NEXT.search(html)
        if m:
            tracks, err = tracks_from_embed(json.loads(m.group(1)), kind, sid)
            if tracks:
                if len(tracks) >= 100:
                    print("   [aviso] o embed do Spotify limita a ~100 faixas; "
                          "para listas maiores use o CSV do Exportify")
                return tracks, None
        else:
            err = "página sem dados"
    except Exception as e:
        err = short(e)
    if kind == "track":     # reserva: meta tags da página normal
        try:
            t = track_from_meta(http_get(f"https://open.spotify.com/track/{sid}"), sid)
            if t:
                return [t], None
        except Exception as e:
            err = short(e)
    return [], err or "não consegui ler o link"


# ----------------------------------------------------------------------------- API
def resolve_link(link: str, base_opts: dict):
    """link -> (faixas, erro|None)."""
    c = classify(link)
    if not c:
        return [], "link não reconhecido (aceito: YouTube e Spotify)"
    site, kind, ident = c
    if site == "youtube":
        return youtube_to_tracks(kind, ident, link, base_opts)
    return spotify_to_tracks(kind, ident)
