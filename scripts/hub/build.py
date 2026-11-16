"""Turns source answers into the hub's data files. Every function returns the new rows; nothing here fetches."""
import datetime as dt
import json
import os
import subprocess

from . import util

CAP = -2.3  # value ceiling for healthy players outside Hashtagbasketball's top 200
OUT_CODES = {"O", "OUT", "OFS", "INJ", "NA", "SUSP", "IL", "IR", "PUP"}
DTD_CODES = {"GTD", "DTD", "P", "PROB"}
HTB_SOURCE = "Hashtagbasketball %s per game (%s)"
OUTSIDE_SOURCE = "Outside Hashtagbasketball top 200: prior per-game estimate"
YAHOO_SOURCE = "Yahoo season averages (not in Hashtagbasketball top 200)"


def aliases():
    try:
        with open(os.path.join(util.CONFIG, "aliases.json"), encoding="utf-8") as f:
            return {util.norm(k): util.norm(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def rekey(table, alias):
    """Add alias keys so a source's spelling finds the Yahoo spelling."""
    out = dict(table)
    for src, dest in alias.items():
        if src in table and dest not in out:
            out[dest] = table[src]
    return out


# ---------------- teams ----------------
def team_names(teams_file, yahoo_teams, cfg):
    """Returns (teams rows, {old name: new name}) from Yahoo's current names."""
    managers = {str(k): v for k, v in (cfg.get("managers") or {}).items()}
    old = {str(t["team_id"]): t for t in (teams_file or [])}
    rows, renames = [], {}
    for t in sorted(yahoo_teams, key=lambda x: int(x["team_id"] or 0)):
        tid = str(t["team_id"])
        prev = old.get(tid)
        if prev and prev["team"] != t["name"] and t["name"]:
            renames[prev["team"]] = t["name"]
        manager = managers.get(tid) or (prev or {}).get("manager") or t.get("nickname") or t["name"]
        rows.append({"team_id": tid, "team": t["name"] or (prev or {}).get("team", ""), "manager": manager})
    return rows, renames


def rename_everywhere(renames, files):
    """Apply team renames to every data file held in memory."""
    if not renames:
        return
    fields = {"standings": ["team"], "schedule": ["team_a", "team_b"], "rosters": ["team"], "players": ["team"],
              "managers": ["team"], "trades": ["team_a", "team_b"], "injuries": ["ube_team"]}
    for name, keys in fields.items():
        for row in files.get(name) or []:
            for k in keys:
                if row.get(k) in renames:
                    row[k] = renames[row[k]]


# ---------------- schedule and standings ----------------
STATUS = {"postevent": "Final", "midevent": "In progress", "preevent": "Not started"}


def apply_scoreboard(schedule, week, matchups, names, cfg, current_week):
    """Update one week of the schedule from Yahoo. Keeps matchup ids and team order when the pairings are the same."""
    matchups = [m for m in matchups if len(m["teams"]) == 2 and not m.get("is_playoffs")]
    if not matchups or week > cfg["regular_season_last_week"]:
        return schedule
    rows = [r for r in schedule if r["week"] == week]
    rivalry = "Rivalry week" if week in (cfg.get("rivalry_weeks") or []) else ""
    pairs = [frozenset((r["team_a"], r["team_b"])) for r in rows]
    y_pairs = [frozenset(names.get(t["team_id"], t["name"]) for t in m["teams"]) for m in matchups]
    if set(pairs) != set(y_pairs) or len(rows) != len(matchups):
        rows = []
        for i, m in enumerate(matchups, 1):
            a, b = (names.get(t["team_id"], t["name"]) for t in m["teams"])
            rows.append({"matchup": "W%d-%d" % (week, i), "week": week, "team_a": a, "team_b": b, "cats_a": None, "cats_b": None, "status": "Not started", "rivalry": rivalry})
        schedule = [r for r in schedule if r["week"] != week] + rows
        schedule.sort(key=lambda r: (r["week"], int(str(r["matchup"]).split("-")[-1]) if "-" in str(r["matchup"]) else 0))
    for m in matchups:
        ta, tb = (names.get(t["team_id"], t["name"]) for t in m["teams"])
        row = next(r for r in schedule if r["week"] == week and {r["team_a"], r["team_b"]} == {ta, tb})
        ca, cb = m["cats"] if row["team_a"] == ta else m["cats"][::-1]
        status = STATUS.get(m["status"], row["status"])
        if status == "Not started" and week == current_week:
            status = "In progress"  # the page treats the live week as the current one
        if row["status"] == "Final" and status != "Final":
            continue  # never reopen a finished week
        row["status"] = status
        row["rivalry"] = rivalry
        if status == "Not started":
            row["cats_a"], row["cats_b"] = None, None
        elif ca is not None and cb is not None:
            row["cats_a"], row["cats_b"] = ca, cb
    return schedule


def standings_rows(yahoo, names, managers):
    rows = []
    for t in yahoo:
        w, l, tie = t["w"], t["l"], t["t"]
        games = w + l + tie
        pct = (w + 0.5 * tie) / games if games else 0.0
        rows.append({"rank": t["rank"], "team": names.get(t["team_id"], t["name"]), "manager": managers.get(t["team_id"], ""),
                     "w": w, "l": l, "t": tie, "record": "%d-%d-%d" % (w, l, tie), "_pct": pct, "waiver": t.get("waiver")})
    if any(not r["rank"] for r in rows):
        for i, r in enumerate(sorted(rows, key=lambda r: -r["_pct"]), 1):
            r["rank"] = i
    rows.sort(key=lambda r: r["rank"])
    lead = rows[0] if rows else None
    out = []
    for r in rows:
        gb = ((lead["w"] - r["w"]) + (r["l"] - lead["l"])) / 2
        text = "%.3f" % r["_pct"]
        out.append({"rank": r["rank"], "team": r["team"], "manager": r["manager"], "w": r["w"], "l": r["l"], "t": r["t"], "record": r["record"],
                    "pct": text[1:] if text.startswith("0") else text,
                    "gb": "-" if gb <= 0 else (str(int(gb)) if gb == int(gb) else "%.1f" % gb), "waiver": r["waiver"]})
    return out


# ---------------- rosters, players, injuries ----------------
def yahoo_status(code):
    c = (code or "").upper()
    if not c:
        return "Healthy"
    if c in OUT_CODES:
        return "Out"
    if c == "Q":
        return "Questionable"
    return "Day-to-day"


def build_rosters(yahoo_teams, names, old_players, espn, htb, yahoo_stats, today, season_label, alias):
    """Returns (rosters, players, injuries, notes). espn may be None (source failed): statuses then come from Yahoo
    and the previous return dates are kept."""
    prev = {util.norm(p["player"]): p for p in old_players or []}
    espn_k = rekey(espn, alias) if espn is not None else None
    htb_k = rekey(htb or {}, alias)
    rosters, players, injuries, new_players = [], [], [], []
    for t in yahoo_teams:
        team = names.get(t["team_id"], t["name"])
        for yp in t["players"]:
            key = util.norm(yp["player"])
            il = "IL" if yp["slot"] in ("IL", "IL+") else ""
            role = util.role_of(yp["pos"])
            status = yahoo_status(yp["yahoo_status"])
            out_until, est, detail = None, "—", yp.get("note", "")
            inj = espn_k.get(key) if espn_k is not None else None
            if inj:
                status = inj["status"]
                if status == "Questionable" and yp["yahoo_status"] in OUT_CODES:
                    status = "Out"
                detail = inj["detail"] or detail
                if status == "Out" and inj["return"]:
                    est = util.short_date(dt.date.fromisoformat(inj["return"]))
                    if inj["return"] > today.isoformat():
                        out_until = inj["return"]
            elif espn_k is None and key in prev and status == "Out":
                old = prev[key]
                if old.get("out_until") and old["out_until"] > today.isoformat():
                    out_until = old["out_until"]
                    est = util.short_date(dt.date.fromisoformat(out_until))
            rosters.append({"player": yp["player"], "team": team, "nba_team": yp["nba_team"], "pos": yp["pos"], "role": role,
                            "status": "" if status == "Healthy" else status, "il": il, "new": ""})
            base = {"player": yp["player"], "team": team, "nba_team": yp["nba_team"], "pos": yp["pos"], "role": role, "status": status,
                    "il": il, "avail": 0 if il else 1, "out_until": out_until}
            old = prev.get(key)
            if old:
                stats = {k: old.get(k, 0) for k in util.STAT_KEYS}
                extra = {"value": old.get("value", CAP), "htb_rank": old.get("htb_rank"), "gp": old.get("gp"), "htb_date": old.get("htb_date"), "source": old.get("source", "")}
            else:
                new_players.append(yp["player"])
                line = htb_k.get(key)
                if line:
                    stats = {k: line[k] for k in util.STAT_KEYS}
                    extra = {"value": line["value"], "htb_rank": line["htb_rank"], "gp": line["gp"], "htb_date": line.get("date"),
                             "source": HTB_SOURCE % (season_label, util.short_date(dt.date.fromisoformat(line["date"])) if line.get("date") else "")}
                else:
                    ys = (yahoo_stats or {}).get(yp.get("player_key"))
                    stats = {k: (ys or {}).get(k, 0.0) for k in util.STAT_KEYS}
                    extra = {"value": CAP, "htb_rank": None, "gp": (ys or {}).get("gp"), "htb_date": None,
                             "source": YAHOO_SOURCE if ys else "No stats yet (not in Hashtagbasketball top 200)"}
            row = {**base, **{k: extra[k] for k in ("value",)}, **stats, "htb_rank": extra["htb_rank"], "gp": extra["gp"], "htb_date": extra["htb_date"], "source": extra["source"]}
            # same key order as the hub's players file
            players.append({k: row[k] for k in ["player", "team", "nba_team", "pos", "role", "status", "il", "avail", "out_until", "value",
                                                 *util.STAT_KEYS, "source", "htb_rank", "gp", "htb_date"]})
            if status != "Healthy":
                injuries.append({"player": yp["player"], "nba_team": yp["nba_team"], "ube_team": team, "status": status, "est_return": est, "detail": detail})
    return rosters, players, injuries, new_players


def players_needing_yahoo_stats(yahoo_teams, old_players, htb, alias):
    prev = {util.norm(p["player"]) for p in old_players or []}
    htb_k = rekey(htb or {}, alias)
    return [yp["player_key"] for t in yahoo_teams for yp in t["players"]
            if util.norm(yp["player"]) not in prev and util.norm(yp["player"]) not in htb_k and yp.get("player_key")]


def apply_htb(players, htb, date, season_label, alias):
    """Monday refresh: Hashtagbasketball stats for everyone in its top 200; the cap for healthy players outside it."""
    htb_k = rekey(htb, alias)
    label = util.short_date(date)
    found = 0
    for p in players:
        line = htb_k.get(util.norm(p["player"]))
        if line:
            found += 1
            for k in util.STAT_KEYS:
                p[k] = line[k]
            p.update(value=line["value"], htb_rank=line["htb_rank"], gp=line["gp"], htb_date=date.isoformat(), source=HTB_SOURCE % (season_label, label))
        else:
            p["htb_rank"] = None
            if not p.get("il") and p.get("status") != "Out":
                p["value"] = min(p.get("value", CAP), CAP)
            if str(p.get("source", "")).startswith("Hashtagbasketball"):
                p["source"] = OUTSIDE_SOURCE
    return found


def apply_cap(players):
    for p in players:
        if p.get("htb_rank") is None and not p.get("il") and p.get("status") != "Out":
            p["value"] = min(p.get("value", CAP), CAP)


def apply_injuries_only(rosters, players, espn, today, alias):
    """Used when Yahoo failed: refresh injury statuses on the rosters we already have."""
    espn_k = rekey(espn, alias)
    by = {r["player"]: r for r in rosters}
    injuries = []
    for p in players:
        inj = espn_k.get(util.norm(p["player"]))
        status, out_until, est, detail = "Healthy", None, "—", ""
        if inj:
            status, detail = inj["status"], inj["detail"]
            if status == "Out" and inj["return"]:
                est = util.short_date(dt.date.fromisoformat(inj["return"]))
                if inj["return"] > today.isoformat():
                    out_until = inj["return"]
        p["status"], p["out_until"] = status, out_until
        if p["player"] in by:
            by[p["player"]]["status"] = "" if status == "Healthy" else status
        if status != "Healthy":
            injuries.append({"player": p["player"], "nba_team": p["nba_team"], "ube_team": p["team"], "status": status, "est_return": est, "detail": detail})
    return injuries


# ---------------- trades ----------------
def trade_rows(pending, names):
    rows = []
    for t in pending:
        a, b = names.get(t["team_a_id"]), names.get(t["team_b_id"])
        if not a or not b or not (t["a_gets"] or t["b_gets"]):
            continue
        rows.append({"deal": "T" + (t["key"].split(".")[-1] or str(len(rows) + 1)), "team_a": a, "a_gets": ", ".join(t["a_gets"]),
                     "team_b": b, "b_gets": ", ".join(t["b_gets"]), "processes": "Pending vote"})
    return rows


# ---------------- team cards ----------------
def run_model():
    """Runs the page's own model (scripts/rank.js). Returns {'profiles': [...], 'power': [...]}."""
    out = subprocess.run(["node", os.path.join(util.ROOT, "scripts", "rank.js"), util.DATA], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError("Ranking model failed: %s" % (out.stderr.strip()[:200] or "unknown error"))
    return json.loads(out.stdout)


def manager_rows(old_managers, teams, model):
    """Playbook, punts, summary and power rank from the model. Taglines are never changed here."""
    old = {m["team"]: m for m in old_managers or []}
    power = {r["team"]: r["power_rank"] for r in model["power"]}
    rows = []
    for t in teams:
        ranks = {r["cat"]: r["rank"] for r in model["profiles"] if r["team"] == t["team"]}
        prev = old.get(t["team"], {})
        row = {"team": t["team"], "manager": t["manager"], "tagline": prev.get("tagline", ""), "playbook": prev.get("playbook", ""),
               "punt": prev.get("punt", ""), "summary": prev.get("summary", ""), "overall_rank": power.get(t["team"], prev.get("overall_rank", len(rows) + 1))}
        if len(ranks) == len(util.CATS):
            best = sorted(util.CATS, key=lambda c: (ranks[c], util.CATS.index(c)))
            worst = sorted(util.CATS, key=lambda c: (-ranks[c], util.CATS.index(c)))
            n = len(teams)
            punts = [c for c in worst if ranks[c] >= n - 2][:3] or worst[:1]
            firsts = [c for c in util.CATS if ranks[c] == 1]
            lasts = [c for c in util.CATS if ranks[c] == n]
            row["playbook"] = " · ".join(best[:3])
            row["punt"] = ", ".join(punts)
            row["summary"] = ("Best " + ", ".join(firsts) if firsts else "%s in %s" % (util.ordinal(ranks[best[0]]), best[0])) + "; " + \
                             ("last in " + ", ".join(lasts) if lasts else "%s in %s" % (util.ordinal(ranks[worst[0]]), worst[0])) + "."
        rows.append(row)
    rows.sort(key=lambda r: r["overall_rank"])
    return rows


# ---------------- changelog ----------------
def next_version(log):
    try:
        major, minor = str(log[-1]["version"]).split(".")[:2]
        return "%s.%d" % (major, int(minor) + 1)
    except (IndexError, ValueError, KeyError):
        return "1.0"
