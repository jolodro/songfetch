"""Funções de texto puras (sem rede, sem yt-dlp)."""
from __future__ import annotations

import re
import unicodedata

LIVE_RE = re.compile(r"\b(ao vivo|live)\b")
OFFICIAL_RE = re.compile(r"\b(official|oficial|vevo)\b")
LYRIC_RE = re.compile(r"\b(lyric|lyrics|letra|legendado)\b")
# versões indesejadas (só rejeita se a palavra NÃO estiver no nome da faixa original)
BAD_RE = re.compile(
    r"\b(cover|covers|karaoke|tribute|tributo|homenagem|reaction|tutorial|playback|"
    r"instrumental|nightcore|slowed|sped up|8d|remix)\b"
)


def norm(s: str) -> str:
    """minúsculas, sem acentos, só letras/números separados por espaço único."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[\W_]+", " ", s).split())


def has_phrase(hay: str, needle: str) -> bool:
    """needle aparece em hay como palavra(s) inteira(s) (ambos já normalizados)."""
    return bool(needle) and f" {needle} " in f" {hay} "


def coverage(needle: str, hay: str) -> float:
    toks = needle.split()
    if not toks:
        return 0.0
    hs = set(hay.split())
    return sum(t in hs for t in toks) / len(toks)


def sanitize(name: str, maxlen: int = 150) -> str:
    name = re.sub(r"[/\\:|]", "-", name)
    name = re.sub(r'[*?"<>\x00-\x1f]', "", name)
    name = " ".join(name.split())[:maxlen].strip(" .")
    return name or "sem-nome"


def clean_title(name: str) -> str:
    """Tira (parênteses), [colchetes] e tudo depois do primeiro ' - ' ou ' / '."""
    t = re.sub(r"\s*[\(\[].*?[\)\]]\s*", " ", name)
    t = re.split(r"\s+-\s+", t)[0]
    t = re.split(r"\s+/\s+", t)[0]  # "Amor I Love You / Citação: ..." -> "Amor I Love You"
    return " ".join(t.split()) or name


def pretty_name(stem: str) -> str:
    """'Rock_pra_Brócolas____' (nome de arquivo do Exportify) -> 'Rock pra Brócolas'."""
    return " ".join(stem.replace("_", " ").split()) or stem


def short(e, n: int = 160) -> str:
    return " ".join(str(e).split())[:n]


def parse_duration(value, ms_hint: bool = False) -> float:
    """'283813' (ms), '3:45', '1:02:03' ou '225.5' (s) -> segundos."""
    v = str(value if value is not None else "").strip()
    if not v:
        return 0.0
    if ":" in v:
        try:
            parts = [float(p) for p in v.split(":")]
        except ValueError:
            return 0.0
        secs = 0.0
        for p in parts:
            secs = secs * 60 + p
        return secs
    try:
        x = float(v.replace(",", "."))
    except ValueError:
        return 0.0
    return x / 1000 if ms_hint or x >= 10000 else x
