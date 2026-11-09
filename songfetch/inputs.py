"""Leitura de entradas: CSV (Exportify ou planilha simples), TSV, XLSX, JSON, TXT,
pastas, links e frases tipo "Artista - Música".

Cada arquivo de lista é tratado como uma playlist (o nome vem do arquivo, de uma coluna
"playlist" ou do próprio export do Spotify)."""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import Track, make_track
from .resolvers import classify, resolve_link, to_spotify_uri, youtube_watch_url
from .textutil import norm, parse_duration, pretty_name

DIR_EXTS = {".csv", ".tsv", ".xlsx", ".json"}
FILE_EXTS = DIR_EXTS | {".txt"}
SKIP_NAMES = {"download_log.json", "failed_downloads.json", "playlists.json"}

# nomes de coluna aceitos (já normalizados: minúsculas, sem acento/pontuação)
ALIASES = {
    "name": {"track name", "track", "title", "name", "song", "song name", "track title", "musica",
             "nome da musica", "faixa", "nome", "titulo"},
    "artist": {"artist name s", "artist name", "artist names", "artist", "artists", "artista",
               "artistas", "autor", "cantor", "banda", "interprete"},
    "album": {"album name", "album", "disco"},
    "duration": {"duration ms", "duration", "duracao", "tempo", "length", "duration s",
                 "duration sec", "duration seconds"},
    "isrc": {"isrc"},
    "uri": {"track uri", "spotify uri", "uri", "spotify id"},
    "url": {"url", "link", "youtube", "youtube url", "link youtube", "spotify url",
            "spotify link", "video", "video url"},
    "query": {"query", "busca", "pesquisa", "search"},
    "playlist": {"playlist", "playlist name", "nome da playlist", "lista"},
}


@dataclass
class Loaded:
    tracks: list = field(default_factory=list)
    links: list = field(default_factory=list)    # [(link, playlist|None)]


def is_link(s: str) -> bool:
    return bool(re.match(r"^(https?://|spotify:)", s.strip(), re.I))


def header_key(h) -> str:
    return norm(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(h or "")))   # trackName -> track name


def map_header(header: list) -> dict:
    fm: dict = {}
    for i, h in enumerate(header):
        k = header_key(h)
        for fld, names in ALIASES.items():
            if k in names and fld not in fm:
                fm[fld] = (i, k)
    return fm


def parse_query(text: str, playlist=None) -> Track:
    """'Artista - Música' (ou só 'Música')."""
    t = text.strip()
    for sep in (" - ", " – ", " — "):
        if sep in t:
            a, b = t.split(sep, 1)
            if a.strip() and b.strip():
                return make_track(b.strip(), [a.strip()], playlist=playlist)
    return make_track(t, [], playlist=playlist)


def rows_to_loaded(header: list, rows: list, key: str, pl_name: str):
    """Converte linhas em faixas/links. `key` identifica a playlist (único por arquivo).
    Retorna None se as colunas não forem reconhecidas."""
    fm = map_header(header)
    if not ({"name", "query", "url"} & set(fm)):
        return None
    ms_hint = fm.get("duration", (0, ""))[1] == "duration ms"
    out = Loaded()
    for row in rows:
        def cell(f):
            if f not in fm:
                return ""
            i = fm[f][0]
            return str(row[i]).strip() if i < len(row) and row[i] is not None else ""

        name, url, query, pl_cell = cell("name"), cell("url"), cell("query"), cell("playlist")
        playlist = (f"{key}::{pl_cell}", pl_cell) if pl_cell else (key, pl_name)
        uri = to_spotify_uri(cell("uri"))
        direct = ""
        c = classify(url) if url else None
        if c and c[0] == "youtube" and c[1] == "video":
            direct = youtube_watch_url(c[2])
        elif c and c[0] == "spotify" and c[1] == "track" and not uri:
            uri = f"spotify:track:{c[2]}"
        if not name:
            if query:
                out.tracks.append(parse_query(query, playlist))
            elif url:
                out.links.append((url, playlist))
            continue
        out.tracks.append(make_track(
            name, cell("artist"), cell("album"), parse_duration(cell("duration"), ms_hint),
            uri=uri, isrc=cell("isrc"), direct_url=direct, playlist=playlist))
    return out


# ------------------------------------------------------------------------ formatos
def _meta(path: Path):
    return str(path.resolve()), pretty_name(path.stem)


def _read_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="latin-1")


def load_csv(path: Path):
    text = _read_text(path)
    first = text.splitlines()[0] if text.strip() else ""
    delim = "\t" if path.suffix.lower() == ".tsv" else max((",", ";", "\t"), key=first.count)
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delim))
    return rows_to_loaded(rows[0], rows[1:], *_meta(path)) if rows else None


def load_xlsx(path: Path):
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("para ler .xlsx instale: pip install openpyxl")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = [["" if c is None else c for c in r] for r in wb.worksheets[0].iter_rows(values_only=True)]
    return rows_to_loaded(rows[0], rows[1:], *_meta(path)) if rows else None


def load_txt(path: Path):
    key, name = _meta(path)
    pl = (key, name)
    out = Loaded()
    for line in _read_text(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if is_link(line):
            out.links.append((line, pl))
        else:
            out.tracks.append(parse_query(line, pl))
    return out


def _json_items(items: list, key: str, name: str):
    out = Loaded()
    pl = (key, name)
    dicts = [i for i in items if isinstance(i, dict)]
    for i in items:
        if isinstance(i, str):
            if is_link(i):
                out.links.append((i, pl))
            else:
                out.tracks.append(parse_query(i, pl))
    if dicts:
        keys = list(dict.fromkeys(k for d in dicts for k in d))
        got = rows_to_loaded(keys, [[d.get(k) for k in keys] for d in dicts], key, name)
        if got is None:
            return None
        out.tracks += got.tracks
        out.links += got.links
    return out


def load_json(path: Path):
    data = json.loads(_read_text(path))
    key, name = _meta(path)
    if isinstance(data, dict) and isinstance(data.get("playlists"), list):
        # export de dados do Spotify: {"playlists":[{"name":..., "items":[{"track":{...}}]}]}
        out = Loaded()
        for idx, pl in enumerate(data["playlists"]):
            items = [it.get("track") for it in pl.get("items", [])
                     if isinstance(it, dict) and it.get("track")]
            got = _json_items(items, f"{key}#{idx}", pl.get("name") or f"{name} {idx + 1}")
            if got:
                out.tracks += got.tracks
                out.links += got.links
        return out
    items = data.get("tracks") or data.get("items") or [] if isinstance(data, dict) else data
    return _json_items(items, key, name)


def load_file(path: Path) -> Loaded:
    loaders = {".csv": load_csv, ".tsv": load_csv, ".xlsx": load_xlsx, ".txt": load_txt,
               ".json": load_json}
    got = loaders[path.suffix.lower()](path)
    if got is None:
        raise ValueError("colunas não reconhecidas (use 'Track Name' e 'Artist Name(s)' do Exportify, "
                         "ou 'música' e 'artista')")
    return got


def collect(inputs: list, base_opts: dict, resolve=resolve_link):
    """Entradas (arquivo, pasta, link ou texto) -> (faixas sem duplicatas, avisos, playlists).
    `playlists` é {chave: nome} na ordem em que as playlists foram dadas."""
    tracks: dict = {}
    order: dict = {}
    notes: list = []
    links: dict = {}

    def add(t: Track):
        if t.id in tracks:
            tracks[t.id].sources |= t.sources
            for k, n in t.playlists.items():
                tracks[t.id].playlists.setdefault(k, n)
        else:
            tracks[t.id] = t
        for k, n in t.playlists.items():
            order.setdefault(k, n)

    def add_links(pairs):
        for link, pl in pairs:
            links.setdefault((link, pl[0] if pl else ""), (link, pl))

    for raw in inputs:
        s = raw.strip()
        if not s:
            continue
        p = Path(s).expanduser()
        if is_link(s):
            add_links([(s, None)])
        elif p.is_dir():
            files = [f for f in sorted(p.iterdir()) if f.suffix.lower() in DIR_EXTS
                     and f.name not in SKIP_NAMES and not f.name.startswith("preview_")]
            for f in files:
                try:
                    got = load_file(f)
                except Exception:
                    continue    # em pastas, arquivos que não são listas de músicas são ignorados
                for t in got.tracks:
                    add(t)
                add_links(got.links)
        elif p.is_file():
            if p.suffix.lower() not in FILE_EXTS:
                notes.append(f"{s}: tipo de arquivo não suportado ({p.suffix or 'sem extensão'})")
                continue
            try:
                got = load_file(p)
            except Exception as e:
                notes.append(f"{s}: {e}")
                continue
            for t in got.tracks:
                add(t)
            add_links(got.links)
        elif Path(s).suffix.lower() in FILE_EXTS and not re.search(r"\s-\s", s):
            notes.append(f"{s}: arquivo não encontrado")
        else:
            add(parse_query(s))

    for link, pl in links.values():
        found, err = resolve(link, base_opts)
        if err:
            notes.append(f"{link}: {err}")
        for t in found:
            if pl and not t.playlists:      # faixa/vídeo solto dentro de uma lista: herda a lista
                t.playlists[pl[0]] = pl[1]
                t.sources.add(pl[1])
            add(t)
    return list(tracks.values()), notes, order
