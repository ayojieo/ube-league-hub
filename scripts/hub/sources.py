"""Public sources: ESPN injuries, ESPN headlines, Hashtagbasketball stats, NBA schedule."""
import datetime as dt
import email.utils
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from . import util

ESPN_INJURIES = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
ESPN_INJURIES_PAGE = "https://www.espn.com/nba/injuries"
ESPN_RSS = "https://www.espn.com/espn/rss/nba/news"
ESPN_NEWS_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news"
HTB_URL = "https://hashtagbasketball.com/fantasy-basketball-rankings"
NBA_SCHEDULE = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
BREF_MONTH = "https://www.basketball-reference.com/leagues/NBA_%d_games-%s.html"
MONTHS = ["october", "november", "december", "january", "february", "march", "april"]


class Tables(HTMLParser):
    """Collects every HTML table as rows of cells: {'text': ..., 'links': [...], 'hrefs': [...], 'attrs': {...}}."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.stack, self.cell, self.link = [], [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.stack.append({"attrs": a, "rows": []})
        elif tag == "tr" and self.stack:
            self.stack[-1]["rows"].append([])
        elif tag in ("td", "th") and self.stack and self.stack[-1]["rows"]:
            self.cell = {"text": "", "links": [], "hrefs": [], "attrs": a, "head": tag == "th"}
            self.stack[-1]["rows"][-1].append(self.cell)
        elif tag == "a" and self.cell is not None:
            self.link = ""
            self.cell["hrefs"].append(a.get("href", ""))
        elif tag == "br" and self.cell is not None:
            self.cell["text"] += " "

    def handle_endtag(self, tag):
        if tag == "table" and self.stack:
            self.tables.append(self.stack.pop())
            self.cell = None
        elif tag in ("td", "th"):
            if self.cell is not None:
                self.cell["text"] = re.sub(r"\s+", " ", self.cell["text"]).strip()
            self.cell = None
        elif tag == "a" and self.cell is not None and self.link is not None:
            self.cell["links"].append(re.sub(r"\s+", " ", self.link).strip())
            self.link = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data
            if self.link is not None:
                self.link += data


def tables(html):
    p = Tables()
    p.feed(html)
    return p.tables


# ---------------- injuries ----------------
def _injury_row(name, status_text, fantasy, kind, detail, side, return_date):
    s = (status_text or "").strip().lower()
    f = (fantasy or "").strip().upper()
    if "out" in s or f in ("OUT", "OFS", "IR"):
        status = "Out"
    elif f == "GTD" or "question" in s or "doubt" in s:
        status = "Questionable"
    else:
        status = "Day-to-day"
    words = [w for w in (side, kind, detail) if w and w.lower() not in ("not specified", "n/a")]
    text = " ".join(words).strip()
    return {"player": name, "status": status, "return": return_date or None, "detail": (text[:1].upper() + text[1:].lower()) if text else ""}


def injuries():
    """All NBA injuries, keyed by normalized player name."""
    try:
        data = json.loads(util.fetch(ESPN_INJURIES))
        out = {}
        for team in data.get("injuries", []):
            for it in team.get("injuries", []):
                name = (it.get("athlete") or {}).get("displayName")
                if not name:
                    continue
                d = it.get("details") or {}
                status = it.get("status") if isinstance(it.get("status"), str) else (it.get("type") or {}).get("description", "")
                ret = (d.get("returnDate") or "")[:10]
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ret):
                    ret = None
                out[util.norm(name)] = _injury_row(name, status, (d.get("fantasyStatus") or {}).get("abbreviation"), d.get("type"), d.get("detail"), d.get("side"), ret)
        if len(out) < 5:
            raise RuntimeError("ESPN injury list looked empty")
        return out
    except Exception as first:  # fall back to the public page
        try:
            return _injuries_from_page(util.fetch(ESPN_INJURIES_PAGE))
        except Exception:
            raise RuntimeError("ESPN injuries failed (%s)" % first) from None


def _injuries_from_page(html):
    out = {}
    year = dt.date.today().year
    for t in tables(html):
        rows = t["rows"]
        if not rows:
            continue
        head = [c["text"].upper() for c in rows[0]]
        if "NAME" not in head or "STATUS" not in head:
            continue
        col = {h: i for i, h in enumerate(head)}
        for r in rows[1:]:
            if len(r) < len(head):
                continue
            name = (r[col["NAME"]]["links"] or [r[col["NAME"]]["text"]])[0]
            ret = None
            when = r[col.get("EST. RETURN DATE", col.get("DATE", 0))]["text"] if ("EST. RETURN DATE" in col or "DATE" in col) else ""
            m = re.match(r"([A-Za-z]{3})\w* (\d{1,2})", when)
            if m:
                try:
                    d = dt.datetime.strptime("%s %s %d" % (m.group(1), m.group(2), year), "%b %d %Y").date()
                    if (dt.date.today() - d).days > 150:
                        d = d.replace(year=year + 1)
                    ret = d.isoformat()
                except ValueError:
                    ret = None
            out[util.norm(name)] = _injury_row(name, r[col["STATUS"]]["text"], "", "", "", "", ret)
    if len(out) < 5:
        raise RuntimeError("ESPN injury page had no table")
    return out


# ---------------- news ----------------
def news(limit=10):
    """Latest NBA headlines, oldest first (the page shows the last row on top)."""
    items = []
    try:
        root = ET.fromstring(util.fetch(ESPN_RSS).encode("utf-8"))
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            try:
                when = email.utils.parsedate_to_datetime((it.findtext("pubDate") or "").strip())
            except (TypeError, ValueError):
                when = None
            if title and link.startswith("http") and when:
                items.append((when, title, link))
    except Exception as first:
        try:
            data = json.loads(util.fetch(ESPN_NEWS_API))
            for a in data.get("articles", []):
                link = ((a.get("links") or {}).get("web") or {}).get("href", "")
                when = dt.datetime.fromisoformat(a["published"].replace("Z", "+00:00")) if a.get("published") else None
                if a.get("headline") and link.startswith("http") and when:
                    items.append((when, a["headline"].strip(), link))
        except Exception:
            raise RuntimeError("Headlines failed (%s)" % first) from None
    if not items:
        raise RuntimeError("No headlines found")
    seen, rows = set(), []
    for when, title, link in sorted(items, key=lambda x: x[0], reverse=True):
        if title in seen:
            continue
        seen.add(title)
        rows.append({"date": util.short_date(when), "headline": title, "angle": "", "url": link})
        if len(rows) >= limit:
            break
    return rows[::-1]


# ---------------- Hashtagbasketball ----------------
def hashtag(html=None):
    """Top-200 table as {normalized name: stat line}. Raises if the page layout is not what we expect."""
    if html is None:
        try:
            html = util.fetch(HTB_URL)
        except RuntimeError as e:
            raise RuntimeError("Hashtagbasketball: %s" % e) from None
    best = None
    for t in tables(html):
        for i, row in enumerate(t["rows"]):
            head = [c["text"].upper() for c in row]
            if "PLAYER" in head and "TOTAL" in head and "FG%" in head:
                if best is None or len(t["rows"]) > len(best[0]["rows"]):
                    best = (t, head)
                break
    if not best:
        raise RuntimeError("Hashtagbasketball: rankings table not found (page layout changed?)")
    t, head = best
    col = {h: i for i, h in enumerate(head)}
    need = ["R#", "PLAYER", "GP", "FG%", "FT%", "3PM", "PTS", "TREB", "AST", "STL", "BLK", "TO", "TOTAL"]
    missing = [h for h in need if h not in col]
    if missing:
        raise RuntimeError("Hashtagbasketball: missing columns %s" % ", ".join(missing))
    pct = re.compile(r"\(\s*([\d.]+)\s*/\s*([\d.]+)\s*\)")
    out = {}
    for row in t["rows"]:
        if len(row) < len(head) or not re.fullmatch(r"\d+", row[col["R#"]]["text"]):
            continue
        cell = row[col["PLAYER"]]
        links = [x for x in cell["links"] if x]
        name = (max(links, key=len) if links else cell["text"]).strip()
        fg, ft = pct.search(row[col["FG%"]]["text"]), pct.search(row[col["FT%"]]["text"])
        if not name or not fg or not ft:
            continue
        g = lambda h: util.num(row[col[h]]["text"], None)
        line = {"player": name, "htb_rank": int(row[col["R#"]]["text"]), "gp": int(util.num(row[col["GP"]]["text"])),
                "fgm": float(fg.group(1)), "fga": float(fg.group(2)), "ftm": float(ft.group(1)), "fta": float(ft.group(2)),
                "tpm": g("3PM"), "pts": g("PTS"), "reb": g("TREB"), "ast": g("AST"), "stl": g("STL"), "blk": g("BLK"), "tov": g("TO"), "value": g("TOTAL")}
        if any(line[k] is None for k in ("tpm", "pts", "reb", "ast", "stl", "blk", "tov", "value")):
            continue
        out.setdefault(util.norm(name), line)
    if len(out) < 150:
        raise RuntimeError("Hashtagbasketball: only %d player rows read (expected about 200)" % len(out))
    return out


# ---------------- NBA schedule ----------------
def nba_games(cfg, weeks=None):
    """Every regular-season game as two rows (one per team): date, week, nba_team, opp, home."""
    try:
        games = _games_cdn()
    except Exception as first:
        try:
            games = _games_bref(int(cfg["season"]) + 1)
        except Exception:
            raise RuntimeError("NBA schedule failed (%s)" % first) from None
    last_week = max(cfg.get("playoff_weeks") or [cfg["regular_season_last_week"]])
    rows, seen = [], set()
    for date, away, home in games:
        if away not in util.NBA_TEAMS or home not in util.NBA_TEAMS or (date, away, home) in seen:
            continue
        seen.add((date, away, home))
        week = util.week_of(dt.date.fromisoformat(date), cfg, weeks)
        if week < 1 or week > last_week or date < cfg["week1_start"]:
            continue
        rows.append({"date": date, "week": week, "nba_team": away, "opp": home, "home": 0})
        rows.append({"date": date, "week": week, "nba_team": home, "opp": away, "home": 1})
    rows.sort(key=lambda r: (r["date"], r["nba_team"]))
    if len(rows) < 400:
        raise RuntimeError("NBA schedule looked too short (%d rows)" % len(rows))
    return rows


def _games_cdn():
    data = json.loads(util.fetch(NBA_SCHEDULE, headers={"Referer": "https://www.nba.com/", "Origin": "https://www.nba.com"}))
    out = []
    for day in data["leagueSchedule"]["gameDates"]:
        for g in day.get("games", []):
            if not str(g.get("gameId", "")).startswith("002"):
                continue
            date = (g.get("gameDateEst") or "")[:10]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                m = re.match(r"(\d{2})/(\d{2})/(\d{4})", day.get("gameDate", ""))
                if not m:
                    continue
                date = "%s-%s-%s" % (m.group(3), m.group(1), m.group(2))
            away = util.nba_code((g.get("awayTeam") or {}).get("teamTricode"))
            home = util.nba_code((g.get("homeTeam") or {}).get("teamTricode"))
            out.append((date, away, home))
    return out


def _games_bref(end_year):
    out = []
    for month in MONTHS:
        try:
            html = util.fetch(BREF_MONTH % (end_year, month))
        except RuntimeError:
            continue
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            d = re.search(r'data-stat="date_game"[^>]*csk="(\d{4})(\d{2})(\d{2})', row)
            v = re.search(r'data-stat="visitor_team_name"[^>]*>.*?/teams/([A-Z]{3})/', row, re.S)
            h = re.search(r'data-stat="home_team_name"[^>]*>.*?/teams/([A-Z]{3})/', row, re.S)
            if d and v and h:
                out.append(("%s-%s-%s" % d.groups(), util.nba_code(v.group(1)), util.nba_code(h.group(1))))
    if not out:
        raise RuntimeError("Basketball-Reference schedule not readable")
    return out
