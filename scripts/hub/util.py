"""Shared helpers: paths, JSON files, names, dates, HTTP."""
import datetime as dt
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

ROOT = os.environ.get("UBE_ROOT") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA = os.path.join(ROOT, "data")
CONFIG = os.path.join(ROOT, "config")
PAGE_DATASETS = ["standings", "schedule", "rosters", "players", "nba_games", "managers", "trades", "injuries", "news", "log"]

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 ube-league-hub"

NBA_CODES = {"SA": "SAS", "GS": "GSW", "NY": "NYK", "NO": "NOP", "PHO": "PHX", "BRK": "BKN", "CHO": "CHA",
             "UTAH": "UTA", "WSH": "WAS", "NOR": "NOP", "SAN": "SAS", "GSO": "GSW"}
NBA_TEAMS = {"ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW", "HOU", "IND", "LAC", "LAL", "MEM",
             "MIA", "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"}
CATS = ["FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]
STAT_KEYS = ["fgm", "fga", "ftm", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "tov"]


def nba_code(code):
    c = (code or "").strip().upper()
    return NBA_CODES.get(c, c)


def norm(name):
    """Name key: ignores accents, punctuation and Jr./Sr./II/III/IV."""
    s = unicodedata.normalize("NFKD", name or "")
    s = s.replace("ø", "o").replace("Ø", "O").replace("đ", "d").replace("Đ", "D").replace("ł", "l").replace("Ł", "L")
    s = s.encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def role_of(pos):
    """Guards / Wings / Bigs, same rule as the hub."""
    parts = [p.strip() for p in (pos or "").split(",") if p.strip()]
    if "C" in parts:
        return "Bigs"
    if "PG" in parts or parts == ["SG"]:
        return "Guards"
    return "Wings"


def slug(team):
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", team.lower()))


def load_config():
    with open(os.path.join(CONFIG, "league.json"), encoding="utf-8") as f:
        return json.load(f)


def today(cfg):
    forced = os.environ.get("UBE_TODAY")
    if forced:
        return dt.date.fromisoformat(forced)
    return dt.datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Manila"))).date()


def week_of(date, cfg, weeks=None):
    """UBE week number for a date. Uses Yahoo's week dates when known, else Mon-Sun weeks from week2_start."""
    iso = date.isoformat()
    for w in weeks or []:
        if w["start"] <= iso <= w["end"]:
            return int(w["week"])
    w2 = dt.date.fromisoformat(cfg["week2_start"])
    if date < w2:
        return 1
    return (date - w2).days // 7 + 2


def short_date(date):
    return date.strftime("%b ") + str(date.day)


def path(name):
    return os.path.join(DATA, name + ".json")


def read(name, default=None):
    try:
        with open(path(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def dump(value):
    if isinstance(value, list) and value and all(isinstance(r, dict) for r in value):
        return "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in value) + "\n]\n"
    return json.dumps(value, ensure_ascii=False, indent=1) + "\n"


def write(name, value):
    """Write only when the content changed. Returns True if it did."""
    if read(name, default=object()) == value:
        return False
    os.makedirs(DATA, exist_ok=True)
    with open(path(name), "w", encoding="utf-8") as f:
        f.write(dump(value))
    return True


def fetch(url, headers=None, data=None, timeout=40):
    """HTTP GET/POST returning text. Raises on any failure."""
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            charset = r.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = e.read().decode("utf-8", "replace")
            m = re.search(r"<description>(.*?)</description>", body, re.S) or re.search(r'"(?:error_description|description)"\s*:\s*"([^"]+)"', body)
            text = m.group(1) if m else re.sub(r"<[^>]+>", " ", body)
            text = re.sub(r"\s+", " ", text).strip()[:200]
            detail = (" (" + text + ")") if text else ""
        except Exception:
            pass
        raise RuntimeError("HTTP %s for %s%s" % (e.code, url.split("?")[0], detail)) from None
    except urllib.error.URLError as e:
        raise RuntimeError("Could not reach %s (%s)" % (url.split("?")[0], e.reason)) from None


def num(text, default=0.0):
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return default


def ordinal(n):
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, "%dth" % n)
