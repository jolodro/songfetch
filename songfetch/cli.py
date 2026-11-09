"""Linha de comando do songfetch."""
from __future__ import annotations

import argparse
import csv
import random
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from . import config as C
from .downloader import FORMATS
from .inputs import collect
from .library import Library
from .pipeline import Ctx, Settings, fix_covers, folders_for, organize, process
from .tagging import mutagen
from .youtube import make_base_opts

EPILOG = """exemplos:
  songfetch minha_playlist.csv                  # CSV do Exportify (uma playlist)
  songfetch exports/                            # pasta com vários CSVs
  songfetch lista.txt                           # um "Artista - Música" por linha
  songfetch "Skank - Vamos Fugir"               # uma música
  songfetch https://open.spotify.com/track/ID   # um link (Spotify ou YouTube)
  songfetch exports/ --dry-run --limit 20       # só procura e gera preview_links.csv
  songfetch --fix-covers                        # capa nos arquivos já baixados
"""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="songfetch", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Baixa músicas a partir de CSV do Exportify, planilhas, listas de texto e links.",
        epilog=EPILOG)
    ap.add_argument("inputs", nargs="*", metavar="ENTRADA",
                    help="arquivo (.csv .tsv .xlsx .json .txt), pasta, link do Spotify/YouTube "
                         "ou texto 'Artista - Música'")
    ap.add_argument("--out", type=Path, default=Path("downloads"), help="pasta de destino (padrão: downloads)")
    ap.add_argument("--state-dir", type=Path, default=Path("."),
                    help="onde ficam os logs (download_log.json etc.; padrão: pasta atual)")
    ap.add_argument("--format", choices=FORMATS, default="best", dest="fmt",
                    help="best = mantém o áudio original sem reencodar (padrão); mp3/m4a/opus convertem")
    ap.add_argument("--layout", choices=("album", "artist", "flat"), default="album",
                    help="organização dentro da pasta da playlist: Álbum/ (padrão), Artista/Álbum/ ou tudo junto")
    ap.add_argument("--no-playlist-folders", action="store_true",
                    help="não cria pasta por playlist (usa só o layout)")
    ap.add_argument("--dry-run", action="store_true", help="só busca; gera preview_links.csv e não baixa")
    ap.add_argument("--limit", type=int, default=0, help="processa só as N primeiras pendentes")
    ap.add_argument("--skip-failed", action="store_true", help="pula faixas que já falharam antes")
    ap.add_argument("--no-fallback", action="store_true", help="desativa o plano B (busca flexível)")
    ap.add_argument("--no-cover", action="store_true", help="não grava a capa do álbum")
    ap.add_argument("--fix-covers", action="store_true",
                    help="só grava a capa nos arquivos já baixados que não têm")
    ap.add_argument("--cookies-from-browser", metavar="NAVEGADOR",
                    help="ex.: firefox, chrome (útil contra bloqueios / com YouTube Premium)")
    ap.add_argument("--version", action="version", version=f"songfetch {__version__}")
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.inputs and not args.fix_covers:
        ap.print_help()
        return 1

    has_ffmpeg = shutil.which("ffmpeg") is not None
    if not has_ffmpeg:
        if args.fmt != "best":
            print(f"[ERRO] --format {args.fmt} precisa do ffmpeg instalado.")
            return 2
        print("[AVISO] ffmpeg não encontrado: o áudio será salvo no formato original (.webm/.m4a), sem capa.")
    if mutagen is None:
        print("[AVISO] mutagen não instalado: sem tags nem capa (pip install mutagen).")

    base_opts = make_base_opts(args.cookies_from_browser)
    lib = Library(args.state_dir)
    ctx = Ctx(Settings(out=args.out, layout=args.layout, fmt=args.fmt, cover=not args.no_cover,
                       dry_run=args.dry_run, fallback=not args.no_fallback,
                       playlist_folders=not args.no_playlist_folders),
              base_opts, lib, has_ffmpeg)

    tracks: list = []
    playlists: dict = {}
    if args.inputs:
        tracks, notes, playlists = collect(args.inputs, base_opts)
        for n in notes:
            print(f"[AVISO] {n}")

    if args.fix_covers:
        if mutagen is None:
            print("[ERRO] instale o mutagen: pip install mutagen")
            return 2
        novos, ja, sem = fix_covers(ctx, {t.id: t for t in tracks})
        print(f"\nCapas: {novos} gravadas | {ja} já tinham | {sem} sem capa")
        return 0

    if not tracks:
        print("Nenhuma faixa encontrada nas entradas.")
        return 1

    # pastas das playlists, na ordem em que foram dadas (a repetida vira 'Nome (1)', '(2)'...)
    if ctx.s.playlist_folders and playlists:
        counts = {k: sum(k in t.playlists for t in tracks) for k in playlists}
        print("Playlists:")
        for k, n in playlists.items():
            print(f"  {lib.playlist_folder(k, n)}/  ({counts[k]} faixas)"
                  + (f"   <- '{n}'" if lib.playlist_folder(k, n) != n else ""))

    skipped = {t.id for t in tracks if args.skip_failed and t.id in lib.failed}
    done = [t for t in tracks if lib.is_done(t, args.out, args.layout)]
    done_ids = {t.id for t in done}
    todo = [t for t in tracks if t.id not in done_ids and t.id not in skipped]
    if args.limit:
        todo = todo[: args.limit]
    print(f"Faixas únicas: {len(tracks)} | já baixadas: {len(done)} | pendentes: {len(todo)}"
          + (" | MODO DRY-RUN" if args.dry_run else ""))

    ok = bad = moved = 0
    try:
        if not args.dry_run:        # faixas já baixadas: garante que estejam nas pastas das playlists
            moved = sum(organize(t, ctx) for t in done)
            if moved:
                print(f"{moved} faixa(s) já baixada(s) organizada(s) nas pastas das playlists")
        for i, t in enumerate(todo, 1):
            print(f"\n[{i}/{len(todo)}] {', '.join(t.artists) or '?'} - {t.name}"
                  + (" (ao vivo)" if t.is_live else "")
                  + (f"  [{' | '.join(folders_for(t, ctx))}]" if folders_for(t, ctx) else ""))
            if process(t, ctx) == "ok":
                ok += 1
            else:
                bad += 1
            if not args.dry_run and i % 10 == 0:
                lib.save()
            time.sleep(random.uniform(*C.SLEEP_RANGE))
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário; salvando progresso...")
    finally:
        if args.dry_run:
            if ctx.preview:
                path = args.state_dir / C.PREVIEW_FILE
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=list(ctx.preview[0]))
                    w.writeheader()
                    w.writerows(ctx.preview)
                print(f"Preview salvo em {path}")
        else:
            lib.save()

    print(f"\nRESUMO: ok={ok} falhas={bad} | falhas acumuladas: {len(lib.failed)}")
    if not args.dry_run:
        print(f"Arquivos em {args.out} | logs em {lib.state_dir}")
    return 0 if bad == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
