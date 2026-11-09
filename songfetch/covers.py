"""Busca de capa do álbum (rede): Spotify (oEmbed público) e, se preciso, iTunes."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from .models import Track
from .textutil import coverage, has_phrase, norm, short

_UA = {"User-Agent": "Mozilla/5.0"}
_CACHE: dict = {}


def _get(url: str, timeout: int = 15) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:
        return r.read()


def _image(url: str):
    if url in _CACHE:
        return _CACHE[url]
    try:
        data = _get(url, 20)
    except Exception:
        return None
    if data[:2] == b"\xff\xd8":
        _CACHE[url] = (data, "image/jpeg")
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        _CACHE[url] = (data, "image/png")
    else:
        return None
    return _CACHE[url]


def _spotify_cover(uri: str):
    m = re.search(r"track[:/]([A-Za-z0-9]+)", uri or "")
    if not m:
        return None
    try:
        data = json.loads(_get(
            f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{m.group(1)}"))
    except Exception as e:
        print(f"   [aviso] capa do Spotify indisponível: {short(e, 80)}")
        return None
    thumb = data.get("thumbnail_url")
    if not thumb:
        return None
    for url in (thumb.replace("00001e02", "0000b273"), thumb):  # tenta 640px, depois 300px
        got = _image(url)
        if got:
            return got
    return None


def _itunes_cover(track: Track):
    if not track.title_norm:
        return None
    term = urllib.parse.quote(f"{' '.join(track.artists[:1])} {track.clean}".strip())
    try:
        data = json.loads(_get(f"https://itunes.apple.com/search?term={term}&media=music&entity=song&limit=5"))
    except Exception:
        return None
    for r in data.get("results", []):
        tn, an = norm(r.get("trackName", "")), norm(r.get("artistName", ""))
        if not (has_phrase(tn, track.title_norm) or coverage(track.title_norm, tn) >= 0.8):
            continue
        if track.artist_norms and not any(has_phrase(an, a) or has_phrase(a, an) for a in track.artist_norms):
            continue
        art = r.get("artworkUrl100", "")
        if art:
            got = _image(art.replace("100x100bb", "600x600bb")) or _image(art)
            if got:
                return got
    return None


def fetch_cover(track: Track):
    """(bytes, mime) ou None. Spotify primeiro (capa exata do álbum), iTunes como reserva."""
    return (_spotify_cover(track.uri) if track.uri else None) or _itunes_cover(track)
