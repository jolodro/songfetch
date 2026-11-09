# songfetch

Baixa músicas a partir de **CSV do Exportify**, planilhas simples, listas de texto ou **links** (Spotify/YouTube).
Escolhe o vídeo certo no YouTube (pela duração, artista, versão ao vivo/estúdio), baixa o áudio **sem reencodar**,
grava tags e **capa do álbum**, e organiza tudo em **pastas por playlist**.

## Instalação

```bash
sudo apt install ffmpeg                 # Debian/Ubuntu (Windows: winget install ffmpeg; macOS: brew install ffmpeg)
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                        # instala o comando `songfetch`
pip install openpyxl                    # opcional: para ler planilhas .xlsx
```

Sem instalar, também funciona: `pip install -r requirements.txt` e `python -m songfetch ...`.

## Uso rápido

```bash
songfetch minha_playlist.csv                    # CSV do Exportify (uma playlist)
songfetch exports/                              # pasta com vários CSVs: cada um vira uma playlist
songfetch lista.txt                             # um pedido por linha
songfetch "Skank - Vamos Fugir"                 # uma música
songfetch https://open.spotify.com/track/ID     # um link de música
songfetch https://www.youtube.com/watch?v=ID    # um vídeo específico do YouTube
songfetch exports/ --dry-run --limit 20         # só procura e gera preview_links.csv (confira antes!)
```

Pode misturar entradas no mesmo comando. Pode interromper com `Ctrl+C` e rodar de novo: continua de onde parou.

## O que ele aceita como entrada

| Entrada | Detalhes |
|---|---|
| **CSV do Exportify** | Reconhecido direto (`Track Name`, `Artist Name(s)`, `Album Name`, `Duration (ms)`, `ISRC`, `Track URI`). Artistas separados por `;` são tratados como vários artistas. |
| **Planilha simples** (`.csv`, `.tsv`, `.xlsx`) | Colunas em português ou inglês: `música`/`title`, `artista`/`artist`, `álbum`, `duração` (`3:45`, segundos ou ms), `link`/`url`, `playlist`. Só **música** é obrigatória; separador `,` `;` ou tab é detectado sozinho. |
| **Lista de texto** (`.txt`) | Uma por linha: `Artista - Música`, só o título, ou um link. Linhas com `#` são comentário. |
| **JSON** | Lista de textos/objetos, ou o export de dados do Spotify (`Playlist1.json`, com os nomes das playlists). |
| **Pasta** | Lê todos os `.csv/.tsv/.xlsx/.json` dentro (ignora os que não são listas de músicas). |
| **Link do YouTube** | Vídeo (baixa exatamente aquele), ou playlist (cada vídeo vira uma faixa). |
| **Link do Spotify** | Faixa, álbum ou playlist. Veja a ressalva abaixo. |

Se a planilha tiver a coluna `link` com um link do YouTube em uma linha, esse vídeo é usado direto, sem busca.

## Pastas por playlist

Cada **arquivo de lista** é uma playlist, e o nome da pasta vem do nome do arquivo
(`Rock_pra_Brócolas____.csv` → `Rock pra Brócolas`). Também vale: coluna `playlist` dentro da planilha,
playlists do export JSON do Spotify e links de playlist (Spotify/YouTube, pelo título).
Músicas/links soltos digitados na linha de comando não têm playlist e vão direto em `Álbum/`.

```
downloads/
  Rock pra Brócolas/
    Cosmotron/
      Skank - Vamos Fugir.opus
  Rock pra Brócolas (1)/        <- outra playlist com o MESMO nome
    ...
```

- **Nomes repetidos:** a primeira playlist fica com o nome, as seguintes viram `Nome (1)`, `Nome (2)`... na ordem em que você
  as passou. A pasta de cada playlist fica gravada em `playlists.json`, então rodar de novo usa **a mesma pasta**
  (não cria `(2)` à toa). Para isso, mantenha o CSV no mesmo caminho: arquivo em outro lugar conta como outra playlist.
- **Música em várias playlists:** é baixada **uma vez** e aparece em cada pasta (hardlink: não ocupa espaço extra;
  se o disco não suportar, copia).
- **Biblioteca antiga:** arquivos já baixados que estavam em `downloads/<Álbum>/` são **movidos** para a pasta da playlist
  quando você roda de novo com o CSV dela (as pastas de álbum que ficarem vazias são removidas).
- `--layout album|artist|flat` muda a organização *dentro* da playlist (`Álbum/` é o padrão, `Artista/Álbum/`, ou tudo junto).
- `--no-playlist-folders` desliga as pastas de playlist.

## Qualidade e formatos

`--format best` (padrão) guarda o áudio original do YouTube (Opus/AAC) sem reencodar, que é a maior qualidade disponível.
`--format mp3|m4a|opus` converte (perde qualidade em relação ao original; só para compatibilidade).
Com **YouTube Premium** e `--cookies-from-browser firefox`, o YouTube pode servir o áudio de 256 kbps.

## Como a busca funciona

1. **Plano A (estrito):** exige artista e título no vídeo, rejeita cover/karaokê/playback/remix (se a faixa não for isso),
   confere a duração e pontua: canal "Tópico" > oficial > canal do artista, e ao vivo × estúdio.
   Se o download do melhor falhar, tenta o 2º e o 3º.
2. **Plano B (flexível):** se o A falhar, busca de forma mais solta e escolhe pela **duração mais próxima**.
   O terminal mostra `[PLANO B]` e o log marca `"fallback": true`: vale conferir essas.
3. **Erro 403:** tenta o mesmo link de novo até 4 vezes, com espera crescente e trocando o cliente do YouTube, antes de pular.

Opções em `songfetch/config.py` (tolerâncias de duração, esperas, número de tentativas...).

## Capas

Capa do álbum via Spotify (pelo `Track URI`) e, quando não houver, via iTunes. Para quem já baixou sem capa:
`songfetch --fix-covers` (inclui as cópias nas pastas das playlists). `--no-cover` desliga.

## Outras opções

```
--out PASTA            destino (padrão: downloads)
--state-dir PASTA      onde ficam download_log.json, failed_downloads.json, playlists.json (padrão: pasta atual)
--skip-failed          não tenta de novo o que já falhou
--no-fallback          desliga o plano B
--limit N              processa só as N primeiras pendentes
--cookies-from-browser firefox|chrome
```

`failed_downloads.json` traz o motivo de cada falha (e até 5 rejeições, ex.: `duração 400s vs 262s`). Rodar de novo tenta essas faixas outra vez.

## Ressalvas

- **Links do Spotify:** não há API oficial sem login. O programa lê as páginas públicas de "embed", que o Spotify pode mudar a qualquer momento,
  e playlists ficam limitadas a ~100 faixas. Para playlists (principalmente grandes ou privadas) o caminho confiável é o **CSV do Exportify**.
- Faixas sem `Duration` (listas de texto) são identificadas só por artista/título e canal, então há mais chance de pegar a versão errada: use `--dry-run` primeiro.
- Baixar do YouTube vai contra os termos de serviço deles e o conteúdo tem direitos autorais: use só para audição pessoal.

## Testes

```bash
python -m unittest discover -s tests -t .
```
Os testes não acessam a rede (YouTube/Spotify são simulados).
