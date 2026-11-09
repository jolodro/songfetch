"""Modelo de faixa usado em todo o projeto."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textutil import LIVE_RE, clean_title, norm

_ARTIST_PART = re.compile(r"\s*(?:,|&|\+|\bfeat\.?|\bft\.?|\bfeaturing\b|\bx\b)\s*", re.I)


def split_artists(raw) -> list:
    """'A;B' (formato do Exportify) ou lista -> ['A', 'B']."""
    items = raw if isinstance(raw, (list, tuple)) else str(raw or "").split(";")
    return [str(a).strip() for a in items if str(a).strip()]


def artist_variants(artists: list) -> list:
    """Nomes normalizados aceitos na verificação (inclui partes de 'A & B', 'A feat. B')."""
    out: list = []
    for a in artists:
        n = norm(a)
        if n and n not in out:
            out.append(n)
        for part in _ARTIST_PART.split(a):
            pn = norm(part)
            if len(pn) >= 3 and pn not in out:
                out.append(pn)
    return out


@dataclass
class Track:
    id: str
    name: str
    album: str
    artists: list
    duration_s: float
    is_live: bool
    legacy_key: str
    clean: str = ""
    title_norm: str = ""
    name_norm: str = ""
    artist_norms: list = field(default_factory=list)
    sources: set = field(default_factory=set)
    uri: str = ""            # spotify:track:ID (quando houver; usado para a capa)
    isrc: str = ""
    direct_url: str = ""     # link do YouTube dado pelo usuário (pula a busca)
    playlists: dict = field(default_factory=dict)   # chave -> nome, na ordem em que apareceu


def make_track(name, artists="", album="", duration_s=0.0, *, tid="", uri="", isrc="",
               direct_url="", source="", playlist=None) -> Track:
    """playlist: (chave_única, nome) quando a faixa vem de uma playlist/lista."""
    name = (name or "").strip()
    album = (album or "").strip()
    arts = split_artists(artists)
    if not tid:
        tid = (f"isrc:{isrc.upper()}" if isrc else f"uri:{uri}" if uri
               else f"yt:{direct_url}" if direct_url
               else f"txt:{norm(';'.join(arts))}|{norm(name)}|{norm(album)}")
    clean = clean_title(name)
    return Track(
        id=tid, name=name, album=album, artists=arts, duration_s=float(duration_s or 0),
        is_live=bool(LIVE_RE.search(norm(f"{name} {album}"))),
        legacy_key=f"{';'.join(arts)} - {name} - {album}",
        clean=clean, title_norm=norm(clean), name_norm=norm(name),
        artist_norms=artist_variants(arts), sources={playlist[1]} if playlist else {source} if source else set(),
        uri=uri, isrc=isrc.upper(), direct_url=direct_url,
        playlists={playlist[0]: playlist[1]} if playlist else {},
    )
