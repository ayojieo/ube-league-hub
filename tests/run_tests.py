#!/usr/bin/env python3
"""Dry runs of the update scripts with made-up Yahoo / Google Sheet / ESPN / Hashtagbasketball / NBA answers.
Nothing here touches the internet or the real data: everything runs in a temporary copy of the repo.
Run:  python3 tests/run_tests.py"""
import copy
import datetime as dt
import importlib
import json
import os
import shutil
import sys
import tempfile
from xml.sax.saxutils import escape

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORK = tempfile.mkdtemp(prefix="ube-test-")
FIXTURE = os.path.join(REPO, "tests", "fixtures", "data")  # the hub's data on Nov 16 2026, so the checks do not depend on live data
for item in ("config", "scripts", "archive", "index.html", "page.html", "shim.js", "shim.css"):
    src = os.path.join(REPO, item)
    (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, os.path.join(WORK, item))
shutil.copytree(FIXTURE, os.path.join(WORK, "data"))
SOURCES = os.path.join(WORK, "config", "sources.json")
with open(SOURCES, "w", encoding="utf-8") as f:
    f.write('{"league_data": "yahoo"}\n')
DISPLAY = os.path.join(WORK, "config", "display_names.json")
SAVED_DISPLAY = open(DISPLAY, encoding="utf-8").read() if os.path.exists(DISPLAY) else None
if SAVED_DISPLAY is not None:
    os.remove(DISPLAY)
os.environ.update(UBE_ROOT=WORK, YAHOO_CLIENT_ID="id", YAHOO_CLIENT_SECRET="secret", YAHOO_REFRESH_TOKEN="refresh-1",
                  NEW_REFRESH_TOKEN_FILE=os.path.join(WORK, "new_token.txt"))
os.environ.pop("GITHUB_STEP_SUMMARY", None)
sys.path.insert(0, os.path.join(WORK, "scripts"))
from hub import util, yahoo  # noqa: E402
import update  # noqa: E402
import new_season  # noqa: E402

NS = 'xml:lang="en-US" yahoo:uri="/fantasy/v2/x" time="30ms" copyright="Yahoo" refresh_rate="60" xmlns:yahoo="http://www.yahooapis.com/v1/base.rng" xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng"'
LEAGUE = "478.l.211732"
checks = {"pass": 0, "fail": 0}


def check(name, ok, detail=""):
    checks["pass" if ok else "fail"] += 1
    print(("  ok   " if ok else "  FAIL ") + name + ((" -> " + str(detail)) if detail and not ok else ""))


def load(name):
    with open(os.path.join(WORK, "data", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def snapshot():
    return {n: open(os.path.join(WORK, "data", n), encoding="utf-8").read() for n in sorted(os.listdir(os.path.join(WORK, "data")))}


# ---------- a fake world built from the starting data ----------
class World:
    def __init__(self):
        self.teams = load("teams")
        self.name = {t["team_id"]: t["team"] for t in self.teams}
        self.tid = {t["team"]: t["team_id"] for t in self.teams}
        self.rosters = {t["team_id"]: [] for t in self.teams}
        self.keys = {}
        for i, r in enumerate(load("rosters")):
            self.keys[r["player"]] = "478.p.%d" % (5000 + i)
            st = {"Out": "O", "Day-to-day": "GTD", "Questionable": "Q"}.get(r["status"], "")
            self.rosters[self.tid[r["team"]]].append({"player": r["player"], "nba": r["nba_team"], "pos": r["pos"], "slot": "IL" if r["il"] else "Util", "status": st})
        self.schedule = load("schedule")
        self.current_week = 5
        self.finished = False
        self.week_status = {1: "postevent", 2: "postevent", 3: "postevent", 4: "postevent"}
        self.scores = {"W4-1": (4, 5, 0), "W4-2": (3, 5, 1), "W4-3": (4, 5, 0), "W4-4": (4, 4, 1), "W4-5": (6, 3, 0)}
        self.standings = [(t["team_id"], i + 1, 20 - i, 10 + i, i % 2) for i, t in enumerate(self.teams)]
        self.trades = []
        self.players = {p["player"]: p for p in load("players")}
        self.htb_names = [p["player"] for p in load("players") if p["htb_rank"] is not None]
        self.fail = set()
        self.extra_htb = {}
        self.yahoo_stats = {}
        self.espn = [("Tyrese Haliburton", "Out", "OUT", "Hamstring", "", "Left", "2026-11-22"), ("Collin Murray-Boyles", "Day-To-Day", "GTD", "Illness", "", "", "2026-11-17"),
                     ("Jalen Duren", "Out", "OUT", "Hamstring", "Strain", "", "2026-11-24"), ("Nobody Rostered", "Out", "OUT", "Knee", "", "", "2026-12-01"),
                     ("Mark Williams", "Out", "OUT", "Shoulder", "Surgery", "", "2027-02-03"), ("Someone Else", "Out", "OUT", "Ankle", "", "", None), ("Another Guy", "Day-To-Day", "GTD", "Back", "", "", None)]

    # --- Yahoo XML ---
    def xml(self, body):
        return '<?xml version="1.0" encoding="UTF-8"?>\n<fantasy_content %s>%s</fantasy_content>' % (NS, body)

    def league_meta(self):
        return "<league_key>%s</league_key><league_id>211732</league_id><name>UBE League</name><draft_status>postdraft</draft_status><num_teams>10</num_teams><current_week>%d</current_week><start_week>1</start_week><end_week>22</end_week><game_code>nba</game_code><season>2026</season>%s" % (
            LEAGUE, self.current_week, "<is_finished>1</is_finished>" if self.finished else "")

    def team_head(self, tid):
        return "<team_key>%s.t.%s</team_key><team_id>%s</team_id><name>%s</name><waiver_priority>%s</waiver_priority><managers><manager><manager_id>%s</manager_id><nickname>Nick%s</nickname></manager></managers>" % (
            LEAGUE, tid, tid, escape(self.name[tid]), tid, tid, tid)

    def scoreboard(self, week):
        status = self.week_status.get(week, "midevent" if week == self.current_week and week in self.week_status else "preevent")
        out = []
        for r in [x for x in self.schedule if x["week"] == week]:
            a, b = self.tid[r["team_a"]], self.tid[r["team_b"]]
            wa, wb, ties = self.scores.get(r["matchup"], (r["cats_a"] or 0, r["cats_b"] or 0, 9 - (r["cats_a"] or 0) - (r["cats_b"] or 0)))
            winners = ""
            if status != "preevent":
                ids = ["5", "8", "10", "12", "15", "16", "17", "18", "19"]
                seq = [a] * wa + [b] * wb + [None] * ties
                winners = "<stat_winners>" + "".join(
                    "<stat_winner><stat_id>%s</stat_id>%s</stat_winner>" % (sid, "<is_tied>1</is_tied>" if w is None else "<winner_team_key>%s.t.%s</winner_team_key>" % (LEAGUE, w))
                    for sid, w in zip(ids, seq)) + "</stat_winners>"
            teams = "".join("<team>%s<team_points><coverage_type>week</coverage_type><week>%d</week><total>%s</total></team_points><team_stats><stats><stat><stat_id>9004003</stat_id><value>200/420</value></stat><stat><stat_id>5</stat_id><value>.476</value></stat><stat><stat_id>12</stat_id><value>%d</value></stat></stats></team_stats></team>" % (
                self.team_head(t), week, w, 500 + int(t)) for t, w in ((a, wa), (b, wb)))
            out.append("<matchup><week>%d</week><week_start>2026-11-16</week_start><week_end>2026-11-22</week_end><status>%s</status><is_playoffs>0</is_playoffs><is_consolation>0</is_consolation>%s<teams count=\"2\">%s</teams></matchup>" % (week, status, winners, teams))
        return self.xml("<league>%s<scoreboard><week>%d</week><matchups count=\"%d\">%s</matchups></scoreboard></league>" % (self.league_meta(), week, len(out), "".join(out)))

    def standings_xml(self):
        teams = "".join("<team>%s<team_standings><rank>%d</rank><playoff_seed>%d</playoff_seed><outcome_totals><wins>%d</wins><losses>%d</losses><ties>%d</ties><percentage>.5</percentage></outcome_totals><games_back>-</games_back></team_standings></team>" % (
            self.team_head(tid), rank, rank, w, l, t) for tid, rank, w, l, t in self.standings)
        return self.xml("<league>%s<standings><teams count=\"10\">%s</teams></standings></league>" % (self.league_meta(), teams))

    def player_xml(self, p, extra=""):
        first, _, last = p["player"].partition(" ")
        return "<player><player_key>%s</player_key><player_id>1</player_id><name><full>%s</full><first>%s</first><last>%s</last></name><editorial_team_abbr>%s</editorial_team_abbr><display_position>%s</display_position>%s%s</player>" % (
            self.keys.setdefault(p["player"], "478.p.%d" % (9000 + len(self.keys))), escape(p["player"]), escape(first), escape(last), p.get("nba", "FA"), p.get("pos", "PG"),
            ("<status>%s</status><status_full>Out</status_full><injury_note>Knee</injury_note>" % p["status"]) if p.get("status") else "", extra)

    def rosters_xml(self):
        teams = ""
        for t in self.teams:
            players = "".join(self.player_xml(p, "<selected_position><coverage_type>date</coverage_type><date>2026-11-16</date><position>%s</position></selected_position>" % p["slot"]) for p in self.rosters[t["team_id"]])
            teams += "<team>%s<roster><coverage_type>date</coverage_type><date>2026-11-16</date><players count=\"1\">%s</players></roster></team>" % (self.team_head(t["team_id"]), players)
        return self.xml("<league>%s<teams count=\"10\">%s</teams></league>" % (self.league_meta(), teams))

    def trades_xml(self):
        out = ""
        for i, (status, a, b, a_gets, b_gets) in enumerate(self.trades, 1):
            players = "".join(self.player_xml({"player": n}, "<transaction_data><type>pending_trade</type><source_team_key>%s.t.%s</source_team_key><destination_team_key>%s.t.%s</destination_team_key></transaction_data>" % (LEAGUE, s, LEAGUE, d))
                              for names, s, d in ((a_gets, b, a), (b_gets, a, b)) for n in names)
            out += "<transaction><transaction_key>%s.pt.%d</transaction_key><type>pending_trade</type><status>%s</status><trader_team_key>%s.t.%s</trader_team_key><tradee_team_key>%s.t.%s</tradee_team_key><players>%s</players></transaction>" % (
                LEAGUE, i, status, LEAGUE, a, LEAGUE, b, players)
        return self.xml("<league>%s<transactions count=\"%d\">%s</transactions></league>" % (self.league_meta(), len(self.trades), out))

    def stats_xml(self, keys):
        by_key = {v: k for k, v in self.keys.items()}
        out = ""
        for k in keys:
            s = self.yahoo_stats.get(by_key.get(k))
            if not s:
                continue
            stats = "".join("<stat><stat_id>%s</stat_id><value>%s</value></stat>" % kv for kv in s.items())
            out += "<player><player_key>%s</player_key><name><full>%s</full></name><player_stats><coverage_type>season</coverage_type><stats>%s</stats></player_stats></player>" % (k, escape(by_key[k]), stats)
        return self.xml("<league>%s<players count=\"1\">%s</players></league>" % (self.league_meta(), out))

    def weeks_xml(self):
        out, start = "", dt.date(2026, 10, 20)
        for w in range(1, 23):
            end = dt.date(2026, 10, 25) if w == 1 else start + dt.timedelta(days=6)
            out += "<game_week><week>%d</week><display_name>%d</display_name><start>%s</start><end>%s</end></game_week>" % (w, w, start, end)
            start = end + dt.timedelta(days=1)
        return self.xml("<game><game_key>478</game_key><game_weeks count=\"22\">%s</game_weeks></game>" % out)

    # --- other sources ---
    def espn_json(self):
        teams = {}
        for name, status, fs, kind, detail, side, ret in self.espn:
            d = {"fantasyStatus": {"description": fs, "abbreviation": fs}, "type": kind}
            if detail:
                d["detail"] = detail
            if side:
                d["side"] = side
            if ret:
                d["returnDate"] = ret
            teams.setdefault("Team", []).append({"id": "1", "longComment": "long", "shortComment": "short", "status": status, "date": "2026-11-14T03:20Z",
                                                 "athlete": {"displayName": name, "status": {"id": "1", "name": "Active"}}, "type": {"description": status.lower()}, "details": d})
        return json.dumps({"timestamp": "x", "status": "success", "injuries": [{"id": "1", "displayName": k, "injuries": v} for k, v in teams.items()]})

    def rss(self):
        items = "".join("<item><title><![CDATA[Headline %d]]></title><description><![CDATA[d]]></description><link><![CDATA[https://www.espn.com/nba/story/_/id/%d/x]]></link><pubDate>Sat, 14 Nov 2026 %02d:13:13 EST</pubDate><guid isPermaLink=\"false\"><![CDATA[US-%d]]></guid></item>" % (i, i, i, i) for i in range(1, 15))
        return '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title><![CDATA[www.espn.com - NBA]]></title><link>https://www.espn.com</link>%s</channel></rss>' % items

    def htb_html(self):
        head = "<tr><th>R#</th><th>PLAYER</th><th>POS</th><th>TEAM</th><th>GP</th><th>MPG</th><th>FG%</th><th>FT%</th><th>3PM</th><th>PTS</th><th>TREB</th><th>AST</th><th>STL</th><th>BLK</th><th>TO</th><th>TOTAL</th></tr>"
        lines = [(n, self.players[n]) for n in self.htb_names if n in self.players] + list(self.extra_htb.items())
        i = 0
        filler = 0
        while len(lines) < 200:
            filler += 1
            lines.append(("Free Agent%s" % ("x" * filler), {"fgm": 3, "fga": 7, "ftm": 1, "fta": 2, "tpm": 1, "pts": 8, "reb": 3, "ast": 2, "stl": .5, "blk": .3, "tov": 1, "value": -1.0, "gp": 9}))
        rows = ""
        for i, (name, p) in enumerate(lines[:200], 1):
            if i % 12 == 1:
                rows += head
            plain = name.replace("ć", "c").replace("Ş", "S").replace("ü", "u").replace("ë", "e").replace("’", "'")
            rows += "<tr><td>%d</td><td><span><a href=\"/1/player\">%s</a></span><span><a href=\"/1/player\">%s. %s</a></span></td><td>PG</td><td>SA</td><td>%s</td><td>30.1</td><td>%.3f (%.1f/%.1f)</td><td>%.3f (%.1f/%.1f)</td><td>%.1f</td><td>%.1f</td><td>%.1f</td><td>%.1f</td><td>%.1f</td><td>%.1f</td><td>%.1f</td><td>%.2f</td></tr>" % (
                i, escape(plain), plain[0], escape(plain.split(" ")[-1]), p.get("gp") or 9, p["fgm"] / max(p["fga"], .1), p["fgm"], p["fga"], p["ftm"] / max(p["fta"], .1), p["ftm"], p["fta"],
                p["tpm"], p["pts"], p["reb"], p["ast"], p["stl"], p["blk"], p["tov"], p["value"])
        return "<html><body><table><tr><td>filters</td></tr></table><div>Loading...</div><table id=\"ContentPlaceHolder1_GridView1\" class=\"table\">%s</table></body></html>" % rows

    def nba_json(self):
        teams = sorted(util.NBA_TEAMS)
        days, d, n = [], dt.date(2026, 10, 6), 0
        while d <= dt.date(2027, 4, 11):
            games = []
            for j in range(0, 14, 2):
                a, h = teams[(n + j) % 30], teams[(n + j + 1) % 30]
                n += 1
                pre = d < dt.date(2026, 10, 20)
                games.append({"gameId": ("001" if pre else "002") + "26%05d" % n, "gameDateEst": "%sT00:00:00Z" % d, "gameDateTimeEst": "%sT19:30:00Z" % d, "weekNumber": 1,
                              "homeTeam": {"teamTricode": h}, "awayTeam": {"teamTricode": a}})
            days.append({"gameDate": d.strftime("%m/%d/%Y 00:00:00"), "games": games})
            d += dt.timedelta(days=1)
        return json.dumps({"meta": {}, "leagueSchedule": {"seasonYear": "2026-27", "leagueId": "00", "gameDates": days}})

    # --- router ---
    def fetch(self, url, headers=None, data=None, timeout=40):
        def boom(tag):
            if tag in self.fail:
                raise RuntimeError("HTTP 503 for %s" % url.split("?")[0])
        if "oauth2/get_token" in url:
            boom("yahoo")
            body = data.decode()
            assert "Basic " in headers["Authorization"]
            return json.dumps({"access_token": "access-1", "refresh_token": "refresh-2" if "authorization_code" in body or getattr(self, "rotate", False) else "refresh-1", "expires_in": 3600})
        if "fantasysports.yahooapis.com" in url:
            boom("yahoo")
            assert headers["Authorization"] == "Bearer access-1"
            path = url.split("/fantasy/v2")[1]
            if "/game_weeks" in path:
                return self.weeks_xml()
            if "scoreboard;week=" in path:
                return self.scoreboard(int(path.split("week=")[1]))
            if path.endswith("/standings"):
                return self.standings_xml()
            if path.endswith("/teams/roster"):
                return self.rosters_xml()
            if "transactions;types=pending_trade" in path:
                boom("trades")
                if "team_key=" not in path:
                    raise RuntimeError("HTTP 400 for transactions")
                return self.trades_xml()
            if "/players;player_keys=" in path:
                return self.stats_xml(path.split("player_keys=")[1].split("/")[0].split(","))
            if path == "/league/" + LEAGUE:
                return self.xml("<league>%s</league>" % self.league_meta())
            raise AssertionError("unexpected Yahoo call " + path)
        if "site.api.espn.com" in url and "injuries" in url:
            boom("espn")
            return self.espn_json()
        if "espn.com/nba/injuries" in url:
            boom("espn")
            return "<html></html>"
        if "espn.com/espn/rss" in url:
            boom("news")
            return self.rss()
        if "site.api.espn.com" in url and "news" in url:
            boom("news")
            return "{}"
        if "hashtagbasketball.com" in url:
            boom("htb")
            return self.htb_html()
        if "cdn.nba.com" in url:
            boom("nba")
            return self.nba_json()
        if "basketball-reference.com" in url:
            raise RuntimeError("HTTP 403 for bref")
        raise AssertionError("unexpected url " + url)


def run(world, today, force=""):
    util.fetch = world.fetch
    os.environ["UBE_TODAY"] = today
    os.environ["UBE_FORCE"] = force
    if os.path.exists(os.environ["NEW_REFRESH_TOKEN_FILE"]):
        os.remove(os.environ["NEW_REFRESH_TOKEN_FILE"])
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = update.main()
    return code, buf.getvalue()


# ============ 1. Monday run: everything works ============
print("1. Monday run (Nov 16): all sources answer")
w = World()
start = snapshot()
taglines = {m["team"]: m["tagline"] for m in load("managers")}
hal, paulo = "1", "3"
w.rosters[hal] = [p for p in w.rosters[hal] if p["player"] != "Toumani Camara"]                      # drop
w.rosters[hal].append({"player": "Brand Newguy", "nba": "SA", "pos": "SG,SF", "slot": "BN", "status": ""})   # add: not in HTB -> Yahoo stats
w.rosters[hal].append({"player": "Listed Rookie", "nba": "NY", "pos": "C", "slot": "BN", "status": ""})      # add: in HTB top 200
w.extra_htb["Listed Rookie"] = {"fgm": 5.0, "fga": 9.0, "ftm": 2.0, "fta": 3.0, "tpm": 0.5, "pts": 12.5, "reb": 8.0, "ast": 1.5, "stl": 0.7, "blk": 1.6, "tov": 1.4, "value": 1.11, "gp": 11}
w.yahoo_stats["Brand Newguy"] = {"0": "10", "9004003": "40/100", "9007006": "20/25", "10": "15", "12": "115", "15": "33", "16": "21", "17": "9", "18": "2", "19": "12"}
for p in w.rosters[hal]:
    if p["player"] == "Anthony Black":
        p["slot"] = "IL+"                                                                              # IL move
w.trades = [("accepted", "8", "9", ["Karl-Anthony Towns"], ["Derrick White", "Devin Booker"]), ("proposed", "1", "3", ["Secret Offer"], ["Hidden Player"])]
outside = next(p for p in load("players") if p["htb_rank"] is None and not p["il"] and p["status"] != "Out")
code, out = run(w, "2026-11-16")
check("exit code 0", code == 0, out)
sched = load("schedule")
w4 = {r["matchup"]: r for r in sched if r["week"] == 4}
check("Week 4 marked Final with Yahoo scores", all(r["status"] == "Final" for r in w4.values()) and (w4["W4-1"]["cats_a"], w4["W4-1"]["cats_b"]) == (4, 5) and (w4["W4-4"]["cats_a"], w4["W4-4"]["cats_b"]) == (4, 4), w4)
w5 = [r for r in sched if r["week"] == 5]
check("Week 5 is the live week, no scores yet", all(r["status"] == "In progress" and r["cats_a"] is None for r in w5), w5)
check("matchup ids and team order kept", [(r["matchup"], r["team_a"], r["team_b"]) for r in sched] == [(r["matchup"], r["team_a"], r["team_b"]) for r in json.loads(start["schedule.json"])])
check("rivalry weeks kept", sorted({r["week"] for r in sched if r["rivalry"]}) == [2, 6, 12, 16, 19])
st = load("standings")
check("standings format", st[0] == {"rank": 1, "team": "The Haliban", "manager": "Allen", "w": 20, "l": 10, "t": 0, "record": "20-10-0", "pct": ".667", "gb": "-", "waiver": 1}
      and st[1]["gb"] == "1" and st[1]["pct"] == ".629" and st[2]["gb"] == "2", st[:3])
ro, pl = load("rosters"), {p["player"]: p for p in load("players")}
check("drop and adds applied", "Toumani Camara" not in pl and "Brand Newguy" in pl and "Listed Rookie" in pl)
check("roster row order follows Yahoo", [r["player"] for r in ro if r["team"] == "The Haliban"] == [p["player"] for p in w.rosters[hal]])
check("IL slot -> il and avail 0 (not from injuries)", pl["Anthony Black"]["il"] == "IL" and pl["Anthony Black"]["avail"] == 0 and all((p["avail"] == 0) == (p["il"] == "IL") for p in pl.values()))
check("new player in Hashtagbasketball gets its line", pl["Listed Rookie"]["value"] == 1.11 and pl["Listed Rookie"]["pts"] == 12.5 and pl["Listed Rookie"]["htb_rank"] is not None and pl["Listed Rookie"]["role"] == "Bigs" and pl["Listed Rookie"]["nba_team"] == "NYK")
bn = pl["Brand Newguy"]
check("new player outside top 200: Yahoo averages and the -2.3 cap", (bn["pts"], bn["fgm"], bn["fga"], bn["ftm"], bn["tpm"], bn["value"], bn["htb_rank"], bn["nba_team"], bn["role"]) == (11.5, 4.0, 10.0, 2.0, 1.5, -2.3, None, "SAS", "Wings"), bn)
check("healthy player outside top 200 capped at -2.3", pl[outside["player"]]["value"] <= -2.3)
check("accented names match Hashtagbasketball", pl["Nikola Jokić"]["htb_date"] == "2026-11-16" and pl["Alperen Şengün"]["htb_date"] == "2026-11-16")
check("stats unchanged where Hashtagbasketball gave the same line", pl["Nikola Jokić"]["pts"] == w.players["Nikola Jokić"]["pts"])
inj = {r["player"]: r for r in load("injuries")}
check("ESPN injuries: Out with return date", inj["Tyrese Haliburton"] == {"player": "Tyrese Haliburton", "nba_team": "IND", "ube_team": "The Haliban", "status": "Out", "est_return": "Nov 22", "detail": "Left hamstring"} and pl["Tyrese Haliburton"]["out_until"] == "2026-11-22", inj.get("Tyrese Haliburton"))
check("ESPN game-time decision -> Questionable, no out_until", inj["Collin Murray-Boyles"]["status"] == "Questionable" and pl["Collin Murray-Boyles"]["out_until"] is None)
check("only rostered players listed", "Nobody Rostered" not in inj and all(r["player"] in pl for r in inj.values()))
tr = load("trades")
check("pending trades: accepted only, proposals never shown", len(tr) == 1 and tr[0] == {"deal": "T1", "team_a": "Nathan's Nifty Team", "a_gets": "Karl-Anthony Towns", "team_b": "JJ's Official Team", "b_gets": "Derrick White, Devin Booker", "processes": "Pending vote"}, tr)
nw = load("news")
check("news: 10 headlines, no angle, newest last (page shows it first)", len(nw) == 10 and all(r["angle"] == "" and r["url"].startswith("https://") for r in nw) and nw[-1]["headline"] == "Headline 14" and nw[0]["date"] == "Nov 14", nw[-1])
games = load("nba_games")
check("NBA schedule: regular season only, weeks 1-22, both teams per game", {g["week"] for g in games} == set(range(1, 23)) and min(g["date"] for g in games) == "2026-10-20" and len(games) % 2 == 0 and set(games[0]) == {"date", "week", "nba_team", "opp", "home"})
mg = load("managers")
check("taglines untouched", {m["team"]: m["tagline"] for m in mg} == taglines)
import subprocess
model = json.loads(subprocess.run(["node", os.path.join(WORK, "scripts", "rank.js")], capture_output=True, text=True, env=os.environ).stdout)
power = {r["team"]: r["power_rank"] for r in model["power"]}
check("team cards recomputed from the page's model", all(m["overall_rank"] == power[m["team"]] for m in mg) and [m["overall_rank"] for m in mg] == list(range(1, 11)))
ranks = {(r["team"], r["cat"]): r["rank"] for r in model["profiles"]}
m0 = mg[0]
best = sorted(util.CATS, key=lambda c: (ranks[(m0["team"], c)], util.CATS.index(c)))[:3]
check("playbook = top 3 categories; punts ranked 8th-10th", m0["playbook"] == " · ".join(best) and all(ranks[(m["team"], c)] >= 8 or len(m["punt"].split(", ")) == 1 for m in mg for c in m["punt"].split(", ")), m0)
check("summary wording", all(m["summary"].endswith(".") and ("Best " in m["summary"] or " in " in m["summary"]) for m in mg), [m["summary"] for m in mg])
log = load("log")
old_log = json.loads(start["log.json"])
check("one changelog row added, numbering continues", len(log) == len(old_log) + 1 and log[-1]["version"] == "1.38" and log[-1]["date"] == "2026-11-16" and log[-1]["change"].startswith("Week 4 final"), log[-1])
check("refresh key unchanged -> nothing saved", not os.path.exists(os.environ["NEW_REFRESH_TOKEN_FILE"]))
check("report lists sources", "Yahoo: scores" in out and "Hashtagbasketball stats (200 players)" in out and "Problems" not in out, out)
check("no token in output", "access-1" not in out and "refresh-1" not in out)

print("2. Same answers again: nothing changes")
snap = snapshot()
code, out = run(w, "2026-11-16")
check("no file changed, no new changelog row", snapshot() == snap and code == 0, [k for k in snap if snapshot().get(k) != snap[k]])
check("report says nothing changed", "**Changed:** nothing" in out, out)

print("3. Tuesday: live scores move, Hashtagbasketball not read again")
w.week_status[5] = "midevent"
w.scores.update({"W5-1": (5, 3, 1)})
w.fail = {"htb"}  # would fail if it were called
code, out = run(w, "2026-11-17")
r = next(x for x in load("schedule") if x["matchup"] == "W5-1")
check("live Week 5 score written", (r["cats_a"], r["cats_b"], r["status"]) == (5, 3, "In progress") and code == 0, r)
check("Hashtagbasketball skipped on a non-Monday", "Hashtagbasketball" not in out, out)
check("changelog: live scores", load("log")[-1]["change"].startswith("Week 5 live scores"), load("log")[-1])

print("4. One source down at a time: old data stays")
w.fail = {"espn", "news", "nba", "htb", "trades"}
before_run = snapshot()
w.rosters[paulo][0]["status"] = "O"
code, out = run(w, "2026-11-23", force="schedule")
check("run still succeeds (Yahoo ok)", code == 0, out)
check("headlines, schedule, trades and Hashtagbasketball stats kept", all(snapshot()[f] == before_run[f] for f in ("news.json", "nba_games.json", "trades.json", "htb.json")))
check("stats not zeroed when Hashtagbasketball fails", all(load("players")[i]["pts"] == json.loads(before_run["players.json"])[i]["pts"] for i in range(20)))
check("problems reported", all(s in out for s in ("ESPN injuries failed", "Headlines failed", "NBA schedule failed", "Hashtagbasketball", "Pending trades")), out)
check("with ESPN down, Yahoo status is used and return dates kept", {p["player"]: p for p in load("players")}[w.rosters[paulo][0]["player"]]["status"] == "Out" and {p["player"]: p for p in load("players")}["Mark Williams"]["out_until"] == "2027-02-03")

print("5. Yahoo down: run fails loudly, other sources still update, rosters untouched")
w.fail = {"yahoo"}
w.espn.append(("Bam Adebayo", "Out", "OUT", "Knee", "", "", "2026-12-20"))
before_run = snapshot()
code, out = run(w, "2026-11-24")
check("exit code 1 so GitHub emails", code == 1 and "Yahoo:" in out, out)
check("rosters, schedule, standings untouched", all(snapshot()[f] == before_run[f] for f in ("schedule.json", "standings.json", "teams.json")) and [r["player"] for r in load("rosters")] == [r["player"] for r in json.loads(before_run["rosters.json"])])
check("injuries still refreshed", {p["player"]: p for p in load("players")}["Bam Adebayo"]["out_until"] == "2026-12-20" and any(r["player"] == "Bam Adebayo" for r in load("injuries")))
check("avail still follows IL slots only", {p["player"]: p for p in load("players")}["Bam Adebayo"]["avail"] == 1)

print("6. A manager renames a team; refresh key rotates")
w.fail = set()
w.name["5"] = "Davao Dragons"
w.rotate = True
code, out = run(w, "2026-11-25")
blob = "".join(snapshot()[f] for f in ("schedule.json", "standings.json", "rosters.json", "players.json", "managers.json", "injuries.json", "teams.json"))
check("new name everywhere, old name gone", "DAVRAA Boys" not in blob and "Davao Dragons" in blob and code == 0)
check("tagline follows the renamed team", next(m for m in load("managers") if m["team"] == "Davao Dragons")["tagline"] == taglines["DAVRAA Boys"])
check("changelog mentions the rename", "DAVRAA Boys is now Davao Dragons" in load("log")[-1]["change"], load("log")[-1])
check("new refresh key handed to the workflow, never printed", open(os.environ["NEW_REFRESH_TOKEN_FILE"]).read() == "refresh-2" and "refresh-2" not in out)
w.rotate = False

print("7. Schedule changed on Yahoo (new pairings for a week)")
w16 = [r for r in w.schedule if r["week"] == 16]
w16[0]["team_b"], w16[1]["team_b"] = w16[1]["team_b"], w16[0]["team_b"]
for r in w.schedule:
    for k in ("team_a", "team_b"):
        r[k] = "Davao Dragons" if r[k] == "DAVRAA Boys" else r[k]
w.tid["Davao Dragons"] = "5"
code, out = run(w, "2026-11-30")
got = [(r["team_a"], r["team_b"], r["rivalry"]) for r in load("schedule") if r["week"] == 16]
check("week rebuilt with the new pairings, rivalry kept", {frozenset(x[:2]) for x in got} == {frozenset((r["team_a"], r["team_b"])) for r in w16} and all(x[2] == "Rivalry week" for x in got) and code == 0, got)

print("8. Season ends: archive, clear, stop")
w.finished = True
code, out = run(w, "2027-04-05")
arch = os.path.join(WORK, "archive", "2026-27")
check("archive holds the page and the final data", all(os.path.exists(os.path.join(arch, f)) for f in ("index.html", "page.html", "shim.js", "shim.css", "data/players.json", "config/site.json")) and len(json.load(open(os.path.join(arch, "data", "players.json")))) > 100)
check("archive is marked read-only and listed", json.load(open(os.path.join(arch, "config", "site.json"))) == {"archived": True, "season": "2026-27"} and json.load(open(os.path.join(WORK, "archive", "index.json"))) == ["2026-27"])
check("live data cleared, season marked over", all(load(n) == [] for n in util.PAGE_DATASETS) and load("state")["season_over"] is True and "Season over" in out)
snap = snapshot()
code, out = run(w, "2027-04-06")
check("daily update does nothing until a new season starts", code == 0 and snapshot() == snap and "season is over" in out, out)

print("9. New season")
cfg_path = os.path.join(WORK, "config", "league.json")
cfg = json.load(open(cfg_path))
cfg.update(season=2027, week1_start="2027-10-19", week2_start="2027-10-25", season_end="2028-04-02", league_key=LEAGUE)
json.dump(cfg, open(cfg_path, "w"))
w.finished = False
w.current_week = 1
w.week_status = {}
w.scores = {}
os.environ["UBE_TODAY"] = "2027-10-18"
util.fetch = w.fetch
import io
import contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = new_season.main()
check("new season built", code == 0 and len(load("schedule")) == 95 and len(load("players")) > 100 and load("log") == [{"version": "1.0", "date": "2027-10-18", "change": "Season 2027-28 started."}] and load("state")["season_over"] is False, buf.getvalue())
check("taglines carried over by manager", {m["manager"]: m["tagline"] for m in load("managers")}["Allen"] == "Dirty Work")
check("all weeks reset", all(r["cats_a"] is None for r in load("schedule")) and [r["status"] for r in load("schedule") if r["week"] == 1][0] == "In progress")
check("Weekly Slate date in the page moved to the new season", "const s = new Date(2027, 9, 25 + (w - 2) * 7);" in open(os.path.join(WORK, "page.html"), encoding="utf-8").read())

print("10. First-time Yahoo login")
import yahoo_login
os.environ["YAHOO_CODE"] = "https://localhost:8080/?code=abc123xyz&state=1"
os.remove(os.environ["NEW_REFRESH_TOKEN_FILE"]) if os.path.exists(os.environ["NEW_REFRESH_TOKEN_FILE"]) else None
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = yahoo_login.main()
check("code exchanged, key saved to file, only 'ok' printed", code == 0 and open(os.environ["NEW_REFRESH_TOKEN_FILE"]).read() == "refresh-2" and buf.getvalue().strip() == "ok", buf.getvalue())

print("11. Display names (config/display_names.json), with Yahoo down")
shutil.rmtree(os.path.join(WORK, "data"))
shutil.copytree(FIXTURE, os.path.join(WORK, "data"))
json.dump(json.load(open(os.path.join(REPO, "config", "league.json"))), open(cfg_path, "w"))
with open(DISPLAY, "w", encoding="utf-8") as f:
    f.write(SAVED_DISPLAY or '{"1": "Team Hali", "4": "Team Luka"}')
w2 = World()
w2.fail = {"yahoo"}
code, out = run(w2, "2026-11-17")
blob = "".join(open(os.path.join(WORK, "data", f), encoding="utf-8").read() for f in os.listdir(os.path.join(WORK, "data")) if f != "htb.json")
check("old names gone from every data file, changelog included", all(x not in blob for x in ("Haliban", "Cotton Pickers")), [x for x in ("Haliban", "Cotton Pickers") if x in blob])
check("new names used", "Team Hali" in blob and "Team Luka" in blob and {t["team_id"]: t["team"] for t in load("teams")}["4"] == "Team Luka")
check("tagline kept for renamed team", next(m for m in load("managers") if m["team"] == "Team Hali")["tagline"] == "Dirty Work")
check("changelog row does not repeat the old names", "display names updated" in load("log")[-1]["change"] and "Haliban" not in load("log")[-1]["change"], load("log")[-1])
w2.fail = set()
for tid, n in (("1", "Team Hali"), ("4", "Team Luka")):
    pass
code, out = run(w2, "2026-11-18")
blob = "".join(open(os.path.join(WORK, "data", f), encoding="utf-8").read() for f in ("schedule.json", "standings.json", "rosters.json", "teams.json"))
check("Yahoo's own names do not come back once Yahoo works", "Haliban" not in blob and "Cotton Pickers" not in blob and "Team Hali" in blob and code == 0, out)


# ======================================================================================================
# Google Sheet as the league source (config/sources.json: "league_data": "sheet")
# ======================================================================================================
SHEET_STATUS = {"postevent": "Final", "midevent": "In progress"}


class SheetWorld(World):
    """The same fake league, also served the way the Google Sheet web app serves it (?tab=league)."""

    def __init__(self):
        super().__init__()
        self.yahoo_calls = 0
        self.sheet_calls = 0
        self.sheet_fail = False
        self.edit = None            # function(sheet answer) -> changed answer
        self.pasted = "2026-11-16T07:05:00.000Z"

    def sheet(self):
        scores = []
        for r in self.schedule:
            status = self.week_status.get(r["week"], "preevent")
            if status == "preevent":
                continue
            wa, wb, _ = self.scores.get(r["matchup"], (r["cats_a"] or 0, r["cats_b"] or 0, 0))
            scores.append({"week": str(r["week"]), "team_a": r["team_a"], "cats_a": str(wa), "cats_b": str(wb), "team_b": r["team_b"], "status": SHEET_STATUS[status]})
        standings = [{"rank": str(rank), "team": self.name[tid], "w": str(w), "l": str(l), "t": str(t)} for tid, rank, w, l, t in self.standings]
        rosters = [{"team": self.name[t["team_id"]], "player": p["player"], "nba_team": p["nba"], "pos": p["pos"].replace(",", ", "), "slot": p["slot"], "status": p["status"]}
                   for t in self.teams for p in self.rosters[t["team_id"]]]
        trades = [{"team_a": self.name[a], "a_gets": ", ".join(ag), "team_b": self.name[b], "b_gets": ", ".join(bg), "processes": ""}
                  for status, a, b, ag, bg in self.trades if status == "accepted"]
        return {"ok": True, "updated": self.pasted, "teams": [{"team_id": t["team_id"], "name": self.name[t["team_id"]]} for t in self.teams],
                "scores": scores, "standings": standings, "rosters": rosters + [{"team": "END"}], "trades": trades}

    def fetch(self, url, headers=None, data=None, timeout=40):
        if "script.google.com" in url:
            self.sheet_calls += 1
            assert url.endswith("tab=league"), url
            if self.sheet_fail:
                raise RuntimeError("HTTP 500 for " + url.split("?")[0])
            answer = self.sheet()
            return json.dumps(self.edit(answer) if self.edit else answer)
        if "yahoo" in url:
            self.yahoo_calls += 1
        return super().fetch(url, headers, data, timeout)


def reset(source, display=None):
    shutil.rmtree(os.path.join(WORK, "data"))
    shutil.copytree(FIXTURE, os.path.join(WORK, "data"))
    json.dump(json.load(open(os.path.join(REPO, "config", "league.json"))), open(cfg_path, "w"))
    with open(SOURCES, "w", encoding="utf-8") as f:
        json.dump({"league_data": source}, f)
    if display:
        json.dump(display, open(DISPLAY, "w", encoding="utf-8"))
    elif os.path.exists(DISPLAY):
        os.remove(DISPLAY)


def league_week():
    """The same week of roster moves, an IL move and a trade, for both sources."""
    lw = SheetWorld()
    lw.rosters["1"] = [p for p in lw.rosters["1"] if p["player"] != "Toumani Camara"]
    lw.rosters["1"].append({"player": "Listed Rookie", "nba": "NY", "pos": "C", "slot": "BN", "status": ""})
    lw.extra_htb["Listed Rookie"] = {"fgm": 5.0, "fga": 9.0, "ftm": 2.0, "fta": 3.0, "tpm": 0.5, "pts": 12.5, "reb": 8.0, "ast": 1.5, "stl": 0.7, "blk": 1.6, "tov": 1.4, "value": 1.11, "gp": 11}
    for p in lw.rosters["1"]:
        if p["player"] == "Anthony Black":
            p["slot"] = "IL+"
    lw.rosters["3"][0]["status"] = "Q"
    lw.trades = [("accepted", "8", "9", ["Karl-Anthony Towns"], ["Derrick White", "Devin Booker"]), ("proposed", "1", "3", ["Secret Offer"], ["Hidden Player"])]
    return lw


print("12. Google Sheet source builds the same files as Yahoo")
reset("yahoo")
wy = league_week()
code_y, out_y = run(wy, "2026-11-16")
from_yahoo = {k: json.loads(v) for k, v in snapshot().items()}
reset("sheet")
ws = league_week()
taglines = {m["team"]: m["tagline"] for m in load("managers")}
code_s, out_s = run(ws, "2026-11-16")
from_sheet = {k: json.loads(v) for k, v in snapshot().items()}
check("both runs succeed", code_y == 0 and code_s == 0, out_s)
check("Yahoo is never called in sheet mode", ws.yahoo_calls == 0 and ws.sheet_calls == 1 and wy.yahoo_calls > 0 and wy.sheet_calls == 0, (ws.yahoo_calls, ws.sheet_calls))
same = ["schedule.json", "rosters.json", "players.json", "trades.json", "managers.json", "teams.json", "nba_games.json", "news.json", "htb.json"]
check("schedule, rosters, players, trades, team cards identical", all(from_sheet[f] == from_yahoo[f] for f in same), [f for f in same if from_sheet[f] != from_yahoo[f]])
no_detail = lambda rows: [{k: v for k, v in r.items() if k != "detail"} for r in rows]
inj_s = {r["player"]: r for r in from_sheet["injuries.json"]}
old_inj = {r["player"]: r for r in json.load(open(os.path.join(FIXTURE, "injuries.json")))}
check("injuries identical; ESPN detail used, else the last known detail is kept (the sheet has no injury note)",
      no_detail(from_sheet["injuries.json"]) == no_detail(from_yahoo["injuries.json"]) and inj_s["Tyrese Haliburton"]["detail"] == "Left hamstring"
      and inj_s["Trey Murphy III"]["detail"] == old_inj["Trey Murphy III"]["detail"] != "", inj_s["Trey Murphy III"])
no_waiver = lambda rows: [{k: v for k, v in r.items() if k != "waiver"} for r in rows]
check("standings identical (pct and gb computed the same way)", no_waiver(from_sheet["standings.json"]) == no_waiver(from_yahoo["standings.json"]) and from_sheet["standings.json"][1]["pct"] == ".629" and from_sheet["standings.json"][1]["gb"] == "1")
check("waiver order kept from before (the sheet has no waiver column)", {r["team"]: r["waiver"] for r in from_sheet["standings.json"]} == {r["team"]: r["waiver"] for r in json.load(open(os.path.join(FIXTURE, "standings.json")))})
sched = load("schedule")
check("Week 4 Final from the sheet; Week 5 live by today's date with no scores; later weeks not started",
      all(r["status"] == "Final" for r in sched if r["week"] == 4) and all(r["status"] == "In progress" and r["cats_a"] is None for r in sched if r["week"] == 5)
      and all(r["status"] == "Not started" for r in sched if r["week"] > 5))
pl = {p["player"]: p for p in load("players")}
check("IL slot, positions and NBA code read from the sheet", pl["Anthony Black"]["il"] == "IL" and pl["Anthony Black"]["avail"] == 0 and pl["Listed Rookie"]["nba_team"] == "NYK" and pl["Listed Rookie"]["pos"] == "C"
      and pl["Listed Rookie"]["role"] == "Bigs" and all("," not in p["pos"] or " " not in p["pos"] for p in pl.values()))
check("roster order follows the sheet rows", [r["player"] for r in load("rosters") if r["team"] == "The Haliban"] == [p["player"] for p in ws.rosters["1"]])
check("taglines untouched", {m["team"]: m["tagline"] for m in load("managers")} == taglines)
log_s, log_y = load("log")[-1]["change"], from_yahoo["log.json"][-1]["change"]
check("changelog says the league changes came from the sheet", "(from Google Sheet)" in log_s and log_s.startswith("Week 4 final; standings") and "(from Google Sheet)" not in log_y, log_s)
st = load("state")
check("state: league_source and last-pasted time", st["league_source"] == "sheet" and st["league_updated"] == ws.pasted and from_yahoo["state.json"]["league_source"] == "yahoo" and from_yahoo["state.json"]["league_updated"].endswith("Z"), st)
check("summary names the source", "**League data source:** Google Sheet" in out_s and "**League data source:** Yahoo" in out_y and "Google Sheet: scores" in out_s and "Problems" not in out_s, out_s)
snap = snapshot()
code, out = run(ws, "2026-11-16")
check("same sheet again: nothing changes", code == 0 and snapshot() == snap and "**Changed:** nothing" in out, [k for k in snap if snapshot()[k] != snap[k]])
ws.pasted = "2026-11-16T09:00:00.000Z"
code, out = run(ws, "2026-11-16")
check("sheet pasted again with the same data: only the pasted time moves", load("state")["league_updated"] == ws.pasted and all(snapshot()[k] == snap[k] for k in snap if k != "state.json"))

print("13. Sheet: bad rows are reported and skipped, old data kept")
before_run = snapshot()
old_w5 = {r["matchup"]: r for r in load("schedule") if r["week"] == 5}


def bad_rows(a):
    w5 = [r for r in ws.schedule if r["week"] == 5]
    w3 = [r for r in ws.schedule if r["week"] == 3][0]
    a["scores"] += [
        {"week": "5", "team_a": w5[0]["team_a"], "cats_a": "5", "cats_b": "3", "team_b": w5[0]["team_b"], "status": "In progress"},        # good
        {"week": "5", "team_a": w5[1]["team_b"], "cats_a": "2", "cats_b": "6", "team_b": w5[1]["team_a"], "status": "in progress"},        # good, sides swapped
        {"week": "5", "team_a": w5[2]["team_a"], "cats_a": "6", "cats_b": "4", "team_b": w5[2]["team_b"], "status": "In progress"},        # 10 categories
        {"week": "5", "team_a": "Nobody FC", "cats_a": "5", "cats_b": "4", "team_b": w5[3]["team_b"], "status": "In progress"},             # unknown team
        {"week": "5", "team_a": w5[3]["team_a"], "cats_a": "5", "cats_b": "4", "team_b": w5[4]["team_b"], "status": "In progress"},        # not a matchup that week
        {"week": "25", "team_a": w5[0]["team_a"], "cats_a": "5", "cats_b": "4", "team_b": w5[0]["team_b"], "status": "Final"},              # no such week
        {"week": "1", "team_a": "The Haliban", "cats_a": "1", "cats_b": "1", "team_b": "Nathaniel's Notable Team", "status": "In progress"},  # reopen a Final week
        {"week": "week", "team_a": "team_a", "cats_a": "cats_a", "cats_b": "cats_b", "team_b": "team_b", "status": "status"},               # pasted header row
        {"week": "2", "team_a": "the haliban", "cats_a": "3", "cats_b": "6", "team_b": "PAULOS PERFECT TEAM", "status": "Final"},           # Final score corrected, sloppy names
        {"week": "3 | %s | 7 | 2 | %s | Final" % (w3["team_a"], w3["team_b"]), "team_a": "", "cats_a": "", "cats_b": "", "team_b": "", "status": ""},  # whole line in column A
    ]
    a["standings"][3]["team"] = "Mystery Team"
    rows = [r for r in a["rosters"] if r["team"] != "END"]
    for r in rows:
        if r["player"] == "Jalen Johnson":
            r["team"] = "Halibans"                                                                        # unknown team: he stays where he was
        if r["player"] == "Dyson Daniels":
            r["slot"], r["status"] = "Bench", "Maybe"                                                     # unknown slot and status
    rows.append({"team": "The Haliban", "player": "Nikola Jokic", "nba_team": "DEN", "pos": "C", "slot": "C", "status": ""})   # on two teams
    rows.append({"team": "The Haliban", "player": "Bam Adebayo", "nba_team": "MIA", "pos": "PF,C", "slot": "BN", "status": ""})  # listed twice
    rows += [{"team": "Yaxel and Em", "player": "Extra Man %s" % "abcdefgh"[i], "nba_team": "LAL", "pos": "SF", "slot": "BN", "status": ""} for i in range(6)]
    rows.append({"team": "END", "player": "", "nba_team": "", "pos": "", "slot": "", "status": ""})
    rows.append({"team": "Yaxel and Em", "player": "Old Paste Guy", "nba_team": "LAL", "pos": "SF", "slot": "BN", "status": ""})   # below END: ignored
    a["rosters"] = rows
    a["trades"] += [{"team_a": "Nobody FC", "a_gets": "X", "team_b": "The Haliban", "b_gets": "Y", "processes": ""},
                    {"team_a": "DAVRAA Boys", "a_gets": "Player One,Player Two", "team_b": "Yaxel and Em", "b_gets": "Player Three", "processes": "Nov 18"}]
    return a


ws.edit = bad_rows
code, out = run(ws, "2026-11-17")
check("run still succeeds (the sheet was read)", code == 0, out)
sched = {r["matchup"]: r for r in load("schedule")}
w5 = [r for r in load("schedule") if r["week"] == 5]
check("good rows applied, team order kept when sides are swapped", (w5[0]["cats_a"], w5[0]["cats_b"]) == (5, 3) and (w5[1]["cats_a"], w5[1]["cats_b"]) == (6, 2) and w5[0]["status"] == "In progress", w5[:2])
check("10 categories, unknown team, wrong pairing: rows skipped", all(r["cats_a"] is None and r["status"] == "In progress" for r in w5[2:]) and len(w5) == 5
      and "add up to 9 or less" in out and 'unknown team "Nobody FC"' in out and "is not a matchup on the schedule" in out and "the week must be 1 to 19" in out, out)
check("a Final week is never reopened", sched["W1-1"]["status"] == "Final" and (sched["W1-1"]["cats_a"], sched["W1-1"]["cats_b"]) == (5, 4) and "is already Final" in out)
check("a Final score can be corrected; names match without capitals or apostrophes", (sched["W2-1"]["cats_a"], sched["W2-1"]["cats_b"], sched["W2-1"]["status"]) == (3, 6, "Final"), sched["W2-1"])
check("a line that stayed in column A (separated by |) still counts", (sched["W3-1"]["cats_a"], sched["W3-1"]["cats_b"]) == (7, 2), sched["W3-1"])
check("standings with an unknown team: previous standings kept", snapshot()["standings.json"] == before_run["standings.json"] and 'Standings: unknown team "Mystery Team"' in out and "Kept the previous standings" in out)
ro = load("rosters")
team_of = {}
for r in ro:
    team_of.setdefault(r["player"], []).append(r["team"])
check("unknown team row skipped, player stays on his team", team_of["Jalen Johnson"] == ["The Haliban"] and 'unknown team "Halibans" for Jalen Johnson' in out)
check("player on two teams: reported, kept on his old team, accents ignored", team_of["Nikola Jokić"] == ["Paulo's Perfect Team"] and "Nikola Jokić is on two teams" in out and "Nikola Jokic" not in team_of)
check("player listed twice on one team: once", team_of["Bam Adebayo"] == ["The Haliban"] and "Bam Adebayo is listed twice" in out)
check("unknown slot and status reported", 'unknown slot "Bench" for Dyson Daniels' in out and 'unknown status "Maybe" for Dyson Daniels' in out and {p["player"]: p for p in load("players")}["Dyson Daniels"]["il"] == "")
check("more than 18 players: warned", "Yaxel and Em has" in out and "the most a team can hold is 18" in out)
check("rows below END ignored", "Old Paste Guy" not in team_of)
check("new players outside Hashtagbasketball: no stats, capped, no Yahoo fallback",
      {p["player"]: p for p in load("players")}["Extra Man a"]["source"] == "No stats yet (not in Hashtagbasketball top 200)" and {p["player"]: p for p in load("players")}["Extra Man a"]["value"] == -2.3 and ws.yahoo_calls == 0)
tr = load("trades")
check("trades: bad row skipped, good rows numbered in order", [t["deal"] for t in tr] == ["T1", "T2"] and tr[1] == {"deal": "T2", "team_a": "DAVRAA Boys", "a_gets": "Player One, Player Two", "team_b": "Yaxel and Em", "b_gets": "Player Three", "processes": "Nov 18"}
      and "Trades: unknown team" in out, tr)

print("14. Sheet: empty tabs, new pairings, sheet down")
before_run = snapshot()


def empty_rosters(a):
    a["rosters"] = [{"team": "END"}]
    a["standings"] = []
    return a


ws.edit = empty_rosters
code, out = run(ws, "2026-11-18")
check("empty Rosters tab keeps the rosters (never wiped)", code == 0 and [r["player"] for r in load("rosters")] == [r["player"] for r in json.loads(before_run["rosters.json"])] and "Rosters tab is empty" in out, out)
check("empty Standings tab keeps the standings", snapshot()["standings.json"] == before_run["standings.json"] and "Standings tab is empty" in out)


def one_team_missing(a):
    a["rosters"] = [r for r in a["rosters"] if r["team"] != "DAVRAA Boys"]
    return a


ws.edit = one_team_missing
code, out = run(ws, "2026-11-18")
check("a team with no rows keeps its roster", len([r for r in load("rosters") if r["team"] == "DAVRAA Boys"]) == len(ws.rosters["5"]) and "no rows for DAVRAA Boys" in out, out)


def new_pairings(a):
    w16 = [dict(r) for r in ws.schedule if r["week"] == 16]
    w16[0]["team_b"], w16[1]["team_b"] = w16[1]["team_b"], w16[0]["team_b"]
    a["scores"] += [{"week": "16", "team_a": r["team_a"], "cats_a": "", "cats_b": "", "team_b": r["team_b"], "status": ""} for r in w16]
    a["wanted"] = [[r["team_a"], r["team_b"]] for r in w16]
    return a


ws.edit = new_pairings
code, out = run(ws, "2026-11-18")
got = [(r["team_a"], r["team_b"], r["rivalry"], r["status"]) for r in load("schedule") if r["week"] == 16]
want = {frozenset(x) for x in new_pairings(ws.sheet())["wanted"]}
check("a whole week with new pairings is rebuilt, rivalry kept", {frozenset(x[:2]) for x in got} == want and all(x[2] == "Rivalry week" and x[3] == "Not started" for x in got) and len(load("schedule")) == 95, got)

ws.edit = None
ws.sheet_fail = True
ws.espn.append(("Bam Adebayo", "Out", "OUT", "Knee", "", "", "2026-12-20"))
before_run = snapshot()
code, out = run(ws, "2026-11-19")
check("sheet cannot be read: exit code 1 so GitHub emails", code == 1 and "Google Sheet: HTTP 500" in out and ws.yahoo_calls == 0, out)
check("league files untouched, injuries still refreshed", all(snapshot()[f] == before_run[f] for f in ("schedule.json", "standings.json", "trades.json", "teams.json"))
      and [r["player"] for r in load("rosters")] == [r["player"] for r in json.loads(before_run["rosters.json"])] and any(r["player"] == "Bam Adebayo" for r in load("injuries")))
check("pasted time not moved when the sheet was not read", load("state")["league_updated"] == json.loads(before_run["state.json"])["league_updated"])
ws.sheet_fail = False
ws.edit = lambda a: {"ok": True, "rows": []}
code, out = run(ws, "2026-11-19")
check("old web app version (market only): clear message", code == 1 and "still the old version" in out and "New version" in out, out)
ws.edit = lambda a: {"ok": False, "error": "missing tabs: Scores. Run setup in Apps Script"}
code, out = run(ws, "2026-11-19")
check("tabs missing: message passed on", code == 1 and "missing tabs: Scores" in out, out)
ws.edit = None

print("15. Sheet: display names; switching back to Yahoo")
reset("sheet", {"1": "Team Hali", "4": "Team Luka"})
ws = league_week()


def display_in_sheet(a):
    for r in a["rosters"]:
        if r["team"] == "The Haliban":
            r["team"] = "Team Hali"          # the hub's name is accepted too
    return a


ws.edit = display_in_sheet
code, out = run(ws, "2026-11-16")
blob = "".join(open(os.path.join(WORK, "data", f), encoding="utf-8").read() for f in os.listdir(os.path.join(WORK, "data")) if f != "htb.json")
check("display names applied to sheet data (Yahoo names in the sheet)", code == 0 and "Haliban" not in blob and "Cotton Pickers" not in blob and "Team Hali" in blob and "Team Luka" in blob and "Problems" not in out, out)
check("display name typed in the sheet is accepted", len([r for r in load("rosters") if r["team"] == "Team Hali"]) == len(ws.rosters["1"]))
check("tagline kept", next(m for m in load("managers") if m["team"] == "Team Hali")["tagline"] == "Dirty Work")
ws.name["5"] = "Davao Dragons"   # renamed on the Info tab; the tabs still use the old name in places
for r in ws.schedule:
    for k in ("team_a", "team_b"):
        r[k] = "Davao Dragons" if r[k] == "DAVRAA Boys" else r[k]
ws.edit = None
code, out = run(ws, "2026-11-17")
blob = "".join(snapshot()[f] for f in ("schedule.json", "standings.json", "rosters.json", "players.json", "managers.json", "teams.json"))
check("team renamed on the Info tab: new name everywhere", code == 0 and "DAVRAA Boys" not in blob and "Davao Dragons" in blob and "DAVRAA Boys is now Davao Dragons" in load("log")[-1]["change"], out)
with open(SOURCES, "w", encoding="utf-8") as f:
    f.write('{"league_data": "Sheets"}')
ws.name["5"] = "DAVRAA Boys"
ws.tid["Davao Dragons"] = "5"
code, out = run(ws, "2026-11-18")
check("a wrong word in sources.json falls back to Yahoo and says so", "league_data must be" in out and "**League data source:** Yahoo" in out and ws.yahoo_calls > 0 and code == 0, out)
check("state follows the source", load("state")["league_source"] == "yahoo")
os.remove(DISPLAY)
if SAVED_DISPLAY is not None:
    with open(DISPLAY, "w", encoding="utf-8") as f:
        f.write(SAVED_DISPLAY)

shutil.rmtree(WORK, ignore_errors=True)
print("\n%d passed, %d failed" % (checks["pass"], checks["fail"]))
sys.exit(1 if checks["fail"] else 0)
