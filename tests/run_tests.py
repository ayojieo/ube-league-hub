#!/usr/bin/env python3
"""Dry runs of the update scripts with made-up Google Sheet / ESPN / Hashtagbasketball / NBA answers.
Nothing here touches the internet or the real data: everything runs in a temporary copy of the repo.
Run:  python3 tests/run_tests.py"""
import contextlib
import datetime as dt
import io
import json
import os
import re
import shutil
import subprocess
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
DISPLAY = os.path.join(WORK, "config", "display_names.json")
if os.path.exists(DISPLAY):
    os.remove(DISPLAY)  # the fixture uses the Yahoo names; display names are tested on their own below
cfg_path = os.path.join(WORK, "config", "league.json")
os.environ.update(UBE_ROOT=WORK)
os.environ.pop("GITHUB_STEP_SUMMARY", None)
sys.path.insert(0, os.path.join(WORK, "scripts"))
from hub import util  # noqa: E402
import update  # noqa: E402
import new_season  # noqa: E402

checks = {"pass": 0, "fail": 0}
SHEET_STATUS = {"postevent": "Final", "midevent": "In progress", "preevent": "Not started"}


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
    """The fake league, served the way the Google Sheet web app serves it (?tab=league), plus ESPN, Hashtagbasketball and NBA."""

    def __init__(self):
        self.teams = load("teams")
        self.name = {t["team_id"]: t["team"] for t in self.teams}
        self.tid = {t["team"]: t["team_id"] for t in self.teams}
        self.rosters = {t["team_id"]: [] for t in self.teams}
        for r in load("rosters"):
            st = {"Out": "O", "Day-to-day": "GTD", "Questionable": "Q"}.get(r["status"], "")
            self.rosters[self.tid[r["team"]]].append({"player": r["player"], "nba": r["nba_team"], "pos": r["pos"], "slot": "IL" if r["il"] else "Util", "status": st})
        self.schedule = load("schedule")
        self.week_status = {1: "postevent", 2: "postevent", 3: "postevent", 4: "postevent"}
        self.scores = {"W4-1": (4, 5, 0), "W4-2": (3, 5, 1), "W4-3": (4, 5, 0), "W4-4": (4, 4, 1), "W4-5": (6, 3, 0)}
        self.all_weeks = False      # True: the Scores tab also lists future pairings (Not started), as for a new season
        self.standings = [(t["team_id"], i + 1, 20 - i, 10 + i, i % 2) for i, t in enumerate(self.teams)]
        self.trades = []
        self.players = {p["player"]: p for p in load("players")}
        self.htb_names = [p["player"] for p in load("players") if p["htb_rank"] is not None]
        self.fail = set()
        self.extra_htb = {}
        self.yahoo_calls = 0
        self.sheet_calls = 0
        self.sheet_fail = False
        self.edit = None            # function(sheet answer) -> changed answer
        self.pasted = "2026-11-16T07:05:00.000Z"
        self.espn = [("Tyrese Haliburton", "Out", "OUT", "Hamstring", "", "Left", "2026-11-22"), ("Collin Murray-Boyles", "Day-To-Day", "GTD", "Illness", "", "", "2026-11-17"),
                     ("Jalen Duren", "Out", "OUT", "Hamstring", "Strain", "", "2026-11-24"), ("Nobody Rostered", "Out", "OUT", "Knee", "", "", "2026-12-01"),
                     ("Mark Williams", "Out", "OUT", "Shoulder", "Surgery", "", "2027-02-03"), ("Someone Else", "Out", "OUT", "Ankle", "", "", None), ("Another Guy", "Day-To-Day", "GTD", "Back", "", "", None)]

    # --- the Google Sheet (?tab=league) ---
    def sheet(self):
        scores = []
        for r in self.schedule:
            status = self.week_status.get(r["week"], "preevent")
            if status == "preevent":
                if self.all_weeks:
                    scores.append({"week": str(r["week"]), "team_a": r["team_a"], "cats_a": "", "cats_b": "", "team_b": r["team_b"], "status": "Not started"})
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
        if "yahoo" in url.lower():
            self.yahoo_calls += 1
            raise AssertionError("Yahoo must never be called: " + url)
        if "script.google.com" in url:
            self.sheet_calls += 1
            assert url.endswith("tab=league"), url
            if self.sheet_fail:
                raise RuntimeError("HTTP 500 for " + url.split("?")[0])
            answer = self.sheet()
            return json.dumps(self.edit(answer) if self.edit else answer)
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
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = update.main()
    return code, buf.getvalue()


def reset(display=None):
    shutil.rmtree(os.path.join(WORK, "data"))
    shutil.copytree(FIXTURE, os.path.join(WORK, "data"))
    json.dump(json.load(open(os.path.join(REPO, "config", "league.json"))), open(cfg_path, "w"))
    if display:
        json.dump(display, open(DISPLAY, "w", encoding="utf-8"))
    elif os.path.exists(DISPLAY):
        os.remove(DISPLAY)


def league_week():
    """A week of roster moves, an IL move and a trade."""
    lw = World()
    lw.rosters["1"] = [p for p in lw.rosters["1"] if p["player"] != "Toumani Camara"]
    lw.rosters["1"].append({"player": "Listed Rookie", "nba": "NY", "pos": "C", "slot": "BN", "status": ""})
    lw.extra_htb["Listed Rookie"] = {"fgm": 5.0, "fga": 9.0, "ftm": 2.0, "fta": 3.0, "tpm": 0.5, "pts": 12.5, "reb": 8.0, "ast": 1.5, "stl": 0.7, "blk": 1.6, "tov": 1.4, "value": 1.11, "gp": 11}
    for p in lw.rosters["1"]:
        if p["player"] == "Anthony Black":
            p["slot"] = "IL+"
    lw.rosters["3"][0]["status"] = "Q"
    lw.trades = [("accepted", "8", "9", ["Karl-Anthony Towns"], ["Derrick White", "Devin Booker"]), ("proposed", "1", "3", ["Secret Offer"], ["Hidden Player"])]
    return lw


# ============ 1. Monday run: everything works ============
print("1. Monday run (Nov 16): the sheet and every other source answer")
w = league_week()
start = snapshot()
mg0 = load("managers")
taglines = {m["team"]: m["tagline"] for m in mg0}
summaries = {m["team"]: m["summary"] for m in mg0}
hal, paulo = "1", "3"
w.rosters[hal].append({"player": "Brand Newguy", "nba": "SA", "pos": "SG,SF", "slot": "BN", "status": ""})   # add: not in HTB -> no stats, capped
outside = next(p for p in load("players") if p["htb_rank"] is None and not p["il"] and p["status"] != "Out")
code, out = run(w, "2026-11-16")
check("exit code 0", code == 0, out)
check("the sheet is read once; Yahoo is never called", w.sheet_calls == 1 and w.yahoo_calls == 0, (w.sheet_calls, w.yahoo_calls))
sched = load("schedule")
w4 = {r["matchup"]: r for r in sched if r["week"] == 4}
check("Week 4 marked Final with the sheet's scores", all(r["status"] == "Final" for r in w4.values()) and (w4["W4-1"]["cats_a"], w4["W4-1"]["cats_b"]) == (4, 5) and (w4["W4-4"]["cats_a"], w4["W4-4"]["cats_b"]) == (4, 4), w4)
w5 = [r for r in sched if r["week"] == 5]
check("Week 5 is the live week by date, no scores yet; later weeks not started", all(r["status"] == "In progress" and r["cats_a"] is None for r in w5) and all(r["status"] == "Not started" for r in sched if r["week"] > 5), w5)
check("matchup ids and team order kept", [(r["matchup"], r["team_a"], r["team_b"]) for r in sched] == [(r["matchup"], r["team_a"], r["team_b"]) for r in json.loads(start["schedule.json"])])
check("rivalry weeks kept", sorted({r["week"] for r in sched if r["rivalry"]}) == [2, 6, 12, 16, 19])
st = load("standings")
check("standings format (pct and gb computed)", {k: st[0][k] for k in ("rank", "team", "manager", "w", "l", "t", "record", "pct", "gb")} == {"rank": 1, "team": "The Haliban", "manager": "Allen", "w": 20, "l": 10, "t": 0, "record": "20-10-0", "pct": ".667", "gb": "-"}
      and st[1]["gb"] == "1" and st[1]["pct"] == ".629" and st[2]["gb"] == "2", st[:3])
check("waiver order kept from before (the sheet has no waiver column)", {r["team"]: r["waiver"] for r in st} == {r["team"]: r["waiver"] for r in json.load(open(os.path.join(FIXTURE, "standings.json")))})
ro, pl = load("rosters"), {p["player"]: p for p in load("players")}
check("drop and adds applied", "Toumani Camara" not in pl and "Brand Newguy" in pl and "Listed Rookie" in pl)
check("roster row order follows the sheet", [r["player"] for r in ro if r["team"] == "The Haliban"] == [p["player"] for p in w.rosters[hal]])
check("IL slot -> il and avail 0 (not from injuries)", pl["Anthony Black"]["il"] == "IL" and pl["Anthony Black"]["avail"] == 0 and all((p["avail"] == 0) == (p["il"] == "IL") for p in pl.values()))
check("positions and NBA code cleaned", pl["Listed Rookie"]["nba_team"] == "NYK" and pl["Listed Rookie"]["pos"] == "C" and all(" " not in p["pos"] for p in pl.values()))
check("new player in Hashtagbasketball gets its line", pl["Listed Rookie"]["value"] == 1.11 and pl["Listed Rookie"]["pts"] == 12.5 and pl["Listed Rookie"]["htb_rank"] is not None and pl["Listed Rookie"]["role"] == "Bigs")
bn = pl["Brand Newguy"]
check("new player outside top 200: no stats yet and the -2.3 cap", (bn["pts"], bn["value"], bn["htb_rank"], bn["nba_team"], bn["role"], bn["source"]) == (0.0, -2.3, None, "SAS", "Wings", "No stats yet (not in Hashtagbasketball top 200)"), bn)
check("healthy player outside top 200 capped at -2.3", pl[outside["player"]]["value"] <= -2.3)
check("accented names match Hashtagbasketball", pl["Nikola Jokić"]["htb_date"] == "2026-11-16" and pl["Alperen Şengün"]["htb_date"] == "2026-11-16")
check("stats unchanged where Hashtagbasketball gave the same line", pl["Nikola Jokić"]["pts"] == w.players["Nikola Jokić"]["pts"])
inj = {r["player"]: r for r in load("injuries")}
check("ESPN injuries: Out with return date", inj["Tyrese Haliburton"] == {"player": "Tyrese Haliburton", "nba_team": "IND", "ube_team": "The Haliban", "status": "Out", "est_return": "Nov 22", "detail": "Left hamstring"} and pl["Tyrese Haliburton"]["out_until"] == "2026-11-22", inj.get("Tyrese Haliburton"))
check("ESPN game-time decision -> Questionable, no out_until", inj["Collin Murray-Boyles"]["status"] == "Questionable" and pl["Collin Murray-Boyles"]["out_until"] is None)
check("only rostered players listed", "Nobody Rostered" not in inj and all(r["player"] in pl for r in inj.values()))
tr = load("trades")
check("pending trades from the Trades tab", len(tr) == 1 and tr[0] == {"deal": "T1", "team_a": "Nathan's Nifty Team", "a_gets": "Karl-Anthony Towns", "team_b": "JJ's Official Team", "b_gets": "Derrick White, Devin Booker", "processes": "Pending vote"}, tr)
nw = load("news")
check("news: 10 headlines, no angle, newest last (page shows it first)", len(nw) == 10 and all(r["angle"] == "" and r["url"].startswith("https://") for r in nw) and nw[-1]["headline"] == "Headline 14" and nw[0]["date"] == "Nov 14", nw[-1])
games = load("nba_games")
check("NBA schedule: regular season only, weeks 1-22, both teams per game", {g["week"] for g in games} == set(range(1, 23)) and min(g["date"] for g in games) == "2026-10-20" and len(games) % 2 == 0 and set(games[0]) == {"date", "week", "nba_team", "opp", "home"})
mg = load("managers")
check("nicknames and descriptions untouched", {m["team"]: m["tagline"] for m in mg} == taglines and {m["team"]: m["summary"] for m in mg} == summaries)
model = json.loads(subprocess.run(["node", os.path.join(WORK, "scripts", "rank.js")], capture_output=True, text=True, env=os.environ).stdout)
power = {r["team"]: r["power_rank"] for r in model["power"]}
check("power rank from the page's model", all(m["overall_rank"] == power[m["team"]] for m in mg) and [m["overall_rank"] for m in mg] == list(range(1, 11)))
ranks = {(r["team"], r["cat"]): r["rank"] for r in model["profiles"]}


def pills_ok(m):
    green, red = m["playbook"].split(" · "), m["punt"].split(" · ")
    r = {c: ranks[(m["team"], c)] for c in util.CATS}
    top, low = sum(1 for c in util.CATS if r[c] <= 3), sum(1 for c in util.CATS if r[c] >= 8)
    good = len(green) == max(3, min(4, top)) and len(red) == max(3, min(4, low)) and "Punt" not in m["punt"] and not set(green) & set(red)
    good = good and min(r[c] for c in util.CATS if c not in green) >= max(r[c] for c in green)   # nothing better left out
    good = good and max(r[c] for c in util.CATS if c not in red) <= min(r[c] for c in red)      # nothing worse left out
    return good


check("green pill = 3-4 strongest, red pill = 3-4 weakest, no 'Punt'", all(pills_ok(m) for m in mg), [(m["team"], m["playbook"], m["punt"], {c: ranks[(m["team"], c)] for c in util.CATS}) for m in mg if not pills_ok(m)])
log = load("log")
old_log = json.loads(start["log.json"])
check("one changelog row added, numbering continues, says the sheet", len(log) == len(old_log) + 1 and log[-1]["version"] == "1.38" and log[-1]["date"] == "2026-11-16"
      and log[-1]["change"].startswith("Week 4 final; standings") and "(from Google Sheet)" in log[-1]["change"], log[-1])
check("state: last-pasted time", load("state")["league_source"] == "sheet" and load("state")["league_updated"] == w.pasted)
check("report lists sources", "**League data source:** Google Sheet (last pasted: %s)" % w.pasted in out and "Google Sheet: scores" in out and "Hashtagbasketball stats (200 players)" in out and out.split("**Problems:**")[-1].strip() == "- No stats found yet for: Brand Newguy", out)

print("2. Same answers again: nothing changes")
snap = snapshot()
code, out = run(w, "2026-11-16")
check("no file changed, no new changelog row", snapshot() == snap and code == 0, [k for k in snap if snapshot().get(k) != snap[k]])
check("report says nothing changed", "**Changed:** nothing" in out, out)
w.pasted = "2026-11-16T09:00:00.000Z"
code, out = run(w, "2026-11-16")
check("pasted again with the same data: only the pasted time moves", load("state")["league_updated"] == w.pasted and all(snapshot()[k] == snap[k] for k in snap if k != "state.json"))

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
w.fail = {"espn", "news", "nba", "htb"}
before_run = snapshot()
w.rosters[paulo][0]["status"] = "O"
code, out = run(w, "2026-11-23", force="schedule")
check("run still succeeds (the sheet was read)", code == 0, out)
check("headlines, schedule and Hashtagbasketball stats kept", all(snapshot()[f] == before_run[f] for f in ("news.json", "nba_games.json", "htb.json")))
check("stats not zeroed when Hashtagbasketball fails", all(load("players")[i]["pts"] == json.loads(before_run["players.json"])[i]["pts"] for i in range(20)))
check("problems reported", all(s in out for s in ("ESPN injuries failed", "Headlines failed", "NBA schedule failed", "Hashtagbasketball")), out)
check("with ESPN down, the sheet's status is used and return dates kept", {p["player"]: p for p in load("players")}[w.rosters[paulo][0]["player"]]["status"] == "Out" and {p["player"]: p for p in load("players")}["Mark Williams"]["out_until"] == "2027-02-03")

print("5. A manager renames a team (Info tab)")
w.fail = set()
w.name["5"] = "Davao Dragons"
for r in w.schedule:
    for k in ("team_a", "team_b"):
        r[k] = "Davao Dragons" if r[k] == "DAVRAA Boys" else r[k]
w.tid["Davao Dragons"] = "5"
code, out = run(w, "2026-11-25")
blob = "".join(snapshot()[f] for f in ("schedule.json", "standings.json", "rosters.json", "players.json", "managers.json", "injuries.json", "teams.json"))
check("new name everywhere, old name gone", "DAVRAA Boys" not in blob and "Davao Dragons" in blob and code == 0, out)
check("nickname follows the renamed team", next(m for m in load("managers") if m["team"] == "Davao Dragons")["tagline"] == taglines["DAVRAA Boys"])
check("changelog mentions the rename", "DAVRAA Boys is now Davao Dragons" in load("log")[-1]["change"], load("log")[-1])

print("6. Season ends: archive, clear, stop")
code, out = run(w, "2027-04-07")
arch = os.path.join(WORK, "archive", "2026-27")
check("archive holds the page and the final data", all(os.path.exists(os.path.join(arch, f)) for f in ("index.html", "page.html", "shim.js", "shim.css", "data/players.json", "config/site.json")) and len(json.load(open(os.path.join(arch, "data", "players.json")))) > 100)
check("archive is marked read-only and listed", json.load(open(os.path.join(arch, "config", "site.json"))) == {"archived": True, "season": "2026-27"} and json.load(open(os.path.join(WORK, "archive", "index.json"))) == ["2026-27"])
check("live data cleared, season marked over", all(load(n) == [] for n in util.PAGE_DATASETS) and load("state")["season_over"] is True and "Season over" in out)
snap = snapshot()
calls = w.sheet_calls
code, out = run(w, "2027-04-08")
check("daily update does nothing until a new season starts (sheet not read)", code == 0 and snapshot() == snap and "season is over" in out and w.sheet_calls == calls, out)

print("7. New season from the sheet")
cfg = json.load(open(cfg_path))
cfg.update(season=2027, week1_start="2027-10-19", week2_start="2027-10-25", season_end="2028-04-02")
json.dump(cfg, open(cfg_path, "w"))
w.week_status = {}
w.scores = {}
w.all_weeks = True                        # the new league's pairings pasted into Scores (Not started)
w.standings = []                          # Standings tab still empty: everyone starts 0-0
os.environ["UBE_TODAY"] = "2027-10-18"
util.fetch = w.fetch
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = new_season.main()
check("new season built", code == 0 and len(load("schedule")) == 95 and len(load("players")) > 100 and load("log") == [{"version": "1.0", "date": "2027-10-18", "change": "Season 2027-28 started."}] and load("state")["season_over"] is False, buf.getvalue())
check("nicknames carried over by manager", {m["manager"]: m["tagline"] for m in load("managers")}["Allen"] == taglines["The Haliban"])
check("all weeks reset, Week 1 live", all(r["cats_a"] is None for r in load("schedule")) and [r["status"] for r in load("schedule") if r["week"] == 1][0] == "In progress")
check("standings start at 0-0", all(r["w"] == 0 and r["l"] == 0 for r in load("standings")) and len(load("standings")) == 10)
check("Weekly Slate date in the page moved to the new season", "const s = new Date(2027, 9, 25 + (w - 2) * 7);" in open(os.path.join(WORK, "page.html"), encoding="utf-8").read())
check("Yahoo never called", w.yahoo_calls == 0)
shutil.copy2(os.path.join(REPO, "page.html"), os.path.join(WORK, "page.html"))

print("8. Display names (config/display_names.json)")
reset({"1": "Team Hali", "4": "Team Luka"})
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
check("nickname kept for the renamed team", next(m for m in load("managers") if m["team"] == "Team Hali")["tagline"] == taglines["The Haliban"])
check("changelog row does not repeat the old names", "Haliban" not in load("log")[-1]["change"], load("log")[-1])

reset()
ws = league_week()
code, out = run(ws, "2026-11-16")
print("9. Sheet: bad rows are reported and skipped, old data kept")
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

print("10. Sheet: empty tabs, new pairings, sheet down")
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

print("11. Nothing left of Yahoo's API")
used = []
for top in ("scripts", ".github", "config", "apps-script"):
    for base, _, files in os.walk(os.path.join(REPO, top)):
        for f in files:
            text = open(os.path.join(base, f), encoding="utf-8", errors="ignore").read()
            if re.search(r"yahooapis|api\.login\.yahoo|oauth|refresh_token|sources\.json", text, re.I) or re.search(r"YAHOO_[A-Z]", text):
                used.append(os.path.relpath(os.path.join(base, f), REPO))
check("no Yahoo API call, secret or source switch in scripts, workflows, config or Code.gs", not used, used)
check("Yahoo-only files removed", not any(os.path.exists(os.path.join(REPO, f)) for f in ("scripts/hub/yahoo.py", "scripts/yahoo_login.py", ".github/workflows/yahoo-login.yml", "setup.html", "config/sources.json")))

shutil.rmtree(WORK, ignore_errors=True)
print("\n%d passed, %d failed" % (checks["pass"], checks["fail"]))
sys.exit(1 if checks["fail"] else 0)
