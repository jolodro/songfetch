"""Ajustes que você pode mexer. Tudo em um lugar só."""

SEARCH_RESULTS = 15           # candidatos por busca (plano A)
TOL_STUDIO = 20               # tolerância de duração (s), faixa de estúdio
TOL_LIVE = 60                 # idem, faixa ao vivo
TOL_LOOSE_STUDIO = 45         # plano B (flexível): tolerância, estúdio
TOL_LOOSE_LIVE = 90           # plano B: ao vivo
LOOSE_RESULTS = 5             # candidatos do plano B

MAX_RETRIES = 3               # tentativas da busca quando o YouTube falha
MAX_ATTEMPTS = 4              # downloads tentados por faixa antes de desistir
DL_403_RETRIES = 3            # tentativas extras quando o servidor devolve 403
DL_403_WAIT = (8, 20, 40)     # espera (s) antes de cada nova tentativa após 403
# Cliente do YouTube em cada tentativa (None = padrão do yt-dlp). Nomes não
# suportados pela sua versão do yt-dlp são ignorados por ele.
DL_CLIENT_ROTATION = [None, None, ["web_safari"], ["tv"]]

SLEEP_RANGE = (2.0, 4.0)      # pausa entre faixas (s), evita bloqueio

STATE_LOG = "download_log.json"
STATE_FAILED = "failed_downloads.json"
STATE_PLAYLISTS = "playlists.json"
PREVIEW_FILE = "preview_links.csv"
