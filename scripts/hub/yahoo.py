"""Yahoo Fantasy API (read only). OAuth 2.0 refresh-token flow; answers are read as XML."""
import base64
import json
import os
import urllib.parse
import xml.etree.ElementTree as ET

from . import util

TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API = "https://fantasysports.yahooapis.com/fantasy/v2"
REDIRECT = "https://localhost:8080"
SCORING = {"5": "FG%", "8": "FT%", "10": "3PTM", "12": "PTS", "15": "REB", "16": "AST", "17": "ST", "18": "BLK", "19": "TO"}
LOWER_IS_BETTER = {"19"}
IL_SLOTS = {"IL", "IL+"}


def mask(value):
    """Hide a secret in the public GitHub Actions log."""
    if value and os.environ.get("GITHUB_ACTIONS"):
        print("::add-mask::" + value)


def _token_request(fields):
    cid = os.environ.get("YAHOO_CLIENT_ID", "").strip()
    secret = os.environ.get("YAHOO_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        raise RuntimeError("Yahoo keys are missing (YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET secrets).")
    basic = base64.b64encode(("%s:%s" % (cid, secret)).encode()).decode()
    body = urllib.parse.urlencode({"redirect_uri": REDIRECT, **fields}).encode()
    try:
        text = util.fetch(TOKEN_URL, headers={"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"}, data=body)
    except RuntimeError as e:
        raise RuntimeError("Yahoo sign-in failed (%s). Run the 'Yahoo login' workflow again." % e) from None
    out = json.loads(text)
    if not out.get("access_token"):
        raise RuntimeError("Yahoo sign-in failed. Run the 'Yahoo login' workflow again.")
    mask(out.get("access_token"))
    mask(out.get("refresh_token"))
    return out


def exchange_code(code):
    """One-time login: turn the code from the localhost address into tokens."""
    return _token_request({"grant_type": "authorization_code", "code": code})


class Client:
    def __init__(self, cfg):
        self.cfg = cfg
        self.league = cfg["league_key"]
        self.token = None
        self.new_refresh = None

    def login(self):
        refresh = os.environ.get("YAHOO_REFRESH_TOKEN", "").strip()
        if not refresh:
            raise RuntimeError("No Yahoo login saved yet. Run the 'Yahoo login' workflow first.")
        out = _token_request({"grant_type": "refresh_token", "refresh_token": refresh})
        self.token = out["access_token"]
        if out.get("refresh_token") and out["refresh_token"] != refresh:
            self.new_refresh = out["refresh_token"]

    def get(self, resource):
        if not self.token:
            self.login()
        text = util.fetch(API + resource, headers={"Authorization": "Bearer " + self.token})
        return parse_xml(text)

    # ---- league ----
    def diagnose(self):
        """Explain a 401/403: which NBA leagues can this Yahoo login see?"""
        try:
            root = self.get("/users;use_login=1/games;game_codes=nba/leagues")
        except RuntimeError as e:
            return "The Yahoo login itself is not accepted (%s). Check the app has Fantasy Sports Read, then redo Yahoo login." % e
        seen = ["%s (%s, %s)" % ((lg.findtext("league_key") or "").strip(), (lg.findtext("name") or "").strip(), (lg.findtext("season") or "").strip())
                for lg in root.iter("league")]
        if not seen:
            return "This Yahoo login is in no NBA leagues. Redo Yahoo login while signed into the Yahoo account that plays in the UBE League."
        return "This Yahoo login can see: %s. Put the right one in config/league.json as league_key." % "; ".join(seen[-6:])

    def meta(self):
        try:
            root = self.get("/league/%s" % self.league)
        except RuntimeError as e:
            if " 401 " in str(e) or " 403 " in str(e):
                raise RuntimeError("%s. %s" % (e, self.diagnose())) from None
            raise
        lg = root.find("league")
        g = lambda k: (lg.findtext(k) or "").strip()
        return {"name": g("name"), "current_week": int(g("current_week") or 1), "start_week": int(g("start_week") or 1),
                "end_week": int(g("end_week") or 0), "is_finished": g("is_finished") == "1", "season": g("season"),
                "game_code": g("game_code"), "draft_status": g("draft_status")}

    def game_weeks(self):
        game = self.league.split(".")[0]
        root = self.get("/game/%s/game_weeks" % game)
        out = []
        for w in root.iter("game_week"):
            if w.findtext("week") and w.findtext("start") and w.findtext("end"):
                out.append({"week": int(w.findtext("week")), "start": w.findtext("start").strip(), "end": w.findtext("end").strip()})
        return out

    def scoreboard(self, week):
        root = self.get("/league/%s/scoreboard;week=%d" % (self.league, week))
        return [parse_matchup(m) for m in root.iter("matchup")]

    def standings(self):
        root = self.get("/league/%s/standings" % self.league)
        out = []
        for t in root.iter("team"):
            ts = t.find("team_standings")
            tot = ts.find("outcome_totals") if ts is not None else None
            g = lambda k: int(util.num(tot.findtext(k) if tot is not None else 0))
            out.append({"team_id": (t.findtext("team_id") or "").strip(), "name": (t.findtext("name") or "").strip(),
                        "rank": int(util.num(ts.findtext("rank") if ts is not None else 0)), "w": g("wins"), "l": g("losses"), "t": g("ties"),
                        "waiver": int(util.num(t.findtext("waiver_priority"))) or None})
        return out

    def rosters(self):
        root = self.get("/league/%s/teams/roster" % self.league)
        teams = []
        for t in root.iter("team"):
            players = []
            roster = t.find("roster")
            for p in (roster.iter("player") if roster is not None else []):
                name = (p.findtext("name/full") or "").strip()
                if not name:
                    continue
                players.append({"player": name, "player_key": (p.findtext("player_key") or "").strip(),
                                "nba_team": util.nba_code(p.findtext("editorial_team_abbr")),
                                "pos": (p.findtext("display_position") or "").replace(" ", ""),
                                "yahoo_status": (p.findtext("status") or "").strip().upper(),
                                "note": (p.findtext("injury_note") or p.findtext("status_full") or "").strip(),
                                "slot": (p.findtext("selected_position/position") or "").strip().upper()})
            nick = ""
            for m in t.iter("manager"):
                nick = (m.findtext("nickname") or "").strip()
                break
            teams.append({"team_id": (t.findtext("team_id") or "").strip(), "name": (t.findtext("name") or "").strip(), "nickname": nick, "players": players})
        if len(teams) < 2 or sum(len(t["players"]) for t in teams) == 0:
            raise RuntimeError("Yahoo returned no rosters.")
        return teams

    def pending_trades(self, my_team_id):
        """Accepted trades waiting for the league vote. Proposals that are not accepted yet are never shown."""
        team_key = "%s.t.%s" % (self.league, my_team_id)
        last = None
        for res in ("/league/%s/transactions;types=pending_trade;team_key=%s" % (self.league, team_key),
                    "/league/%s/transactions;types=pending_trade" % self.league):
            try:
                root = self.get(res)
            except RuntimeError as e:
                last = e
                continue
            return [parse_trade(tr) for tr in root.iter("transaction") if (tr.findtext("status") or "").strip().lower() == "accepted"]
        raise last

    def season_stats(self, player_keys):
        """Season totals for players, as per-game stat lines (for new players that Hashtagbasketball does not list)."""
        out = {}
        keys = [k for k in player_keys if k]
        for i in range(0, len(keys), 20):
            root = self.get("/league/%s/players;player_keys=%s/stats" % (self.league, ",".join(keys[i:i + 20])))
            for p in root.iter("player"):
                stats = {s.findtext("stat_id"): (s.findtext("value") or "") for s in p.iter("stat")}
                gp = util.num(stats.get("0"))
                if gp <= 0:
                    continue
                pair = lambda v: [util.num(x) for x in (v.split("/") + ["0", "0"])[:2]]
                fgm, fga = pair(stats.get("9004003", ""))
                ftm, fta = pair(stats.get("9007006", ""))
                per = lambda v: round(v / gp, 1)
                out[(p.findtext("player_key") or "").strip()] = {
                    "fgm": per(fgm), "fga": per(fga), "ftm": per(ftm), "fta": per(fta), "tpm": per(util.num(stats.get("10"))),
                    "pts": per(util.num(stats.get("12"))), "reb": per(util.num(stats.get("15"))), "ast": per(util.num(stats.get("16"))),
                    "stl": per(util.num(stats.get("17"))), "blk": per(util.num(stats.get("18"))), "tov": per(util.num(stats.get("19"))), "gp": int(gp)}
        return out


def parse_xml(text):
    root = ET.fromstring(text)
    for node in root.iter():
        if isinstance(node.tag, str) and "}" in node.tag:
            node.tag = node.tag.split("}", 1)[1]
    return root


def parse_matchup(m):
    status = (m.findtext("status") or "").strip().lower()
    teams = []
    for t in m.iter("team"):
        stats = {s.findtext("stat_id"): (s.findtext("value") or "").strip() for s in t.iter("stat")}
        teams.append({"team_key": (t.findtext("team_key") or "").strip(), "team_id": (t.findtext("team_id") or "").strip(),
                      "name": (t.findtext("name") or "").strip(), "stats": stats})
    wins = {t["team_key"]: 0 for t in teams}
    winners = list(m.iter("stat_winner"))
    if status == "preevent" or len(teams) != 2:
        cats = [None, None]
    else:
        if winners:
            for w in winners:
                if (w.findtext("stat_id") or "").strip() in SCORING and (w.findtext("is_tied") or "0").strip() != "1":
                    key = (w.findtext("winner_team_key") or "").strip()
                    if key in wins:
                        wins[key] += 1
        else:
            a, b = teams
            for sid in SCORING:
                va, vb = a["stats"].get(sid, ""), b["stats"].get(sid, "")
                if va in ("", "-") or vb in ("", "-"):
                    continue
                va, vb = util.num(va), util.num(vb)
                if va == vb:
                    continue
                better_a = va < vb if sid in LOWER_IS_BETTER else va > vb
                wins[(a if better_a else b)["team_key"]] += 1
        cats = [wins[t["team_key"]] for t in teams]
    return {"week": int(util.num(m.findtext("week"))), "status": status, "teams": teams, "cats": cats,
            "is_playoffs": (m.findtext("is_playoffs") or "0").strip() == "1",
            "week_start": (m.findtext("week_start") or "").strip(), "week_end": (m.findtext("week_end") or "").strip()}


def parse_trade(tr):
    key = (tr.findtext("transaction_key") or "").strip()
    trader = (tr.findtext("trader_team_key") or "").strip()
    tradee = (tr.findtext("tradee_team_key") or "").strip()
    gets = {trader: [], tradee: []}
    for p in tr.iter("player"):
        name = (p.findtext("name/full") or "").strip()
        dest = (p.findtext("transaction_data/destination_team_key") or "").strip()
        if name and dest in gets:
            gets[dest].append(name)
    tid = lambda k: k.split(".t.")[-1] if ".t." in k else ""
    return {"key": key, "team_a_id": tid(trader), "team_b_id": tid(tradee), "a_gets": gets[trader], "b_gets": gets[tradee]}
