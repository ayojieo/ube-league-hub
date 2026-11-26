"""League data from the Google Sheet (the hub's only league source; Yahoo's API is not available to us).

Reads the sheet's web app (config/site.json market_url, with ?tab=league) and turns the Scores, Standings, Rosters
and Trades tabs into the shapes build.py works with. Team names in the sheet are the Yahoo team names.
Bad rows are skipped and listed in problems; the old data for them is kept. Nothing here writes files."""
import json
import os
import re
import unicodedata

from . import build, util

HEAD = {"scores": ["week", "team_a", "cats_a", "cats_b", "team_b", "status"],
        "standings": ["rank", "team", "w", "l", "t"],
        "rosters": ["team", "player", "nba_team", "pos", "slot", "status"],
        "trades": ["team_a", "a_gets", "team_b", "b_gets", "processes"]}
MAX_ROSTER = 18  # 10 starters + 3 bench + 5 IL
SLOTS = {s.upper(): s.upper() for s in ("PG", "SG", "G", "SF", "PF", "F", "C", "Util", "BN", "IL", "IL+")}
POSITIONS = ("PG", "SG", "G", "SF", "PF", "F", "C")
STATUS_WORDS = {"OUT": "O", "QUESTIONABLE": "Q", "DAY-TO-DAY": "DTD", "DAY TO DAY": "DTD", "HEALTHY": "", "PROBABLE": "P",
                "INJURED": "INJ", "SUSPENDED": "SUSP"}
STATUS_CODES = build.OUT_CODES | build.DTD_CODES | {"Q"}
SCORE_STATUS = {"final": "postevent", "in progress": "midevent", "inprogress": "midevent", "live": "midevent", "not started": "preevent"}
BACK = {"Final": "postevent", "In progress": "midevent", "Not started": "preevent"}
OLD_STATUS = {"Out": "O", "Questionable": "Q", "Day-to-day": "DTD"}


def sheet_url():
    try:
        with open(os.path.join(util.CONFIG, "site.json"), encoding="utf-8") as f:
            return str(json.load(f).get("market_url") or "").strip()
    except (OSError, ValueError):
        return ""


def fetch(url=None):
    """The league tabs as sent by the sheet's web app. Raises RuntimeError when the sheet cannot be read."""
    url = sheet_url() if url is None else url
    if not url:
        raise RuntimeError("config/site.json has no market_url (the Google Sheet web app link).")
    text = util.fetch(url + ("&" if "?" in url else "?") + "tab=league")
    try:
        data = json.loads(text)
    except ValueError:
        raise RuntimeError("the web app did not send data. Check it is deployed with access set to Anyone.") from None
    if not isinstance(data, dict) or not data.get("ok"):
        raise RuntimeError("the web app reported an error (%s)." % str((data or {}).get("error", "unknown") if isinstance(data, dict) else "unknown")[:120])
    if not any(isinstance(data.get(k), list) for k in HEAD):
        raise RuntimeError("the web app is still the old version (no league tabs). In Apps Script: paste the new Code.gs, run setup, "
                           "then Deploy > Manage deployments > pencil > Version: New version > Deploy.")
    return data


def team_key(name):
    """Team name key: ignores capitals, accents, apostrophes, spaces and punctuation."""
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def clean(value):
    return re.sub(r"\s+", " ", str("" if value is None else value)).strip()


def to_int(text):
    t = clean(text)
    if re.fullmatch(r"\d+(\.0+)?", t):
        return int(float(t))
    return None


def tab_rows(data, tab, stop_at_end):
    """Rows of one tab as clean text. Skips blank rows and repeated header rows. A row that only says END ends the
    tab (anything below it is an old paste) when stop_at_end is set; otherwise END rows are just skipped."""
    head = HEAD[tab]
    out = []
    for raw in data.get(tab) or []:
        if not isinstance(raw, dict):
            continue
        row = {k: clean(raw.get(k)) for k in head}
        if not any(row.values()):
            continue
        first = str(raw.get(head[0]) or "")
        if not any(row[k] for k in head[1:]) and ("\t" in first or "|" in first):
            # a pasted line that stayed in column A: split it on tabs or | so it still counts
            parts = [clean(x) for x in re.split(r"\t|\|", first.strip().strip("|"))]
            row = {k: (parts[i] if i < len(parts) else "") for i, k in enumerate(head)}
        if row[head[0]].upper() == "END" and not any(row[k] for k in head[1:]):
            if stop_at_end:
                break
            continue
        if row[head[0]].lower() == head[0] and row[head[1]].lower() == head[1]:
            continue
        out.append(row)
    return out


class League:
    """One read of the sheet. Collects problems as text lines."""

    def __init__(self, data, teams_file, cfg):
        self.data = data
        self.cfg = cfg
        self.problems = []
        self.updated = clean(data.get("updated"))
        current = {str(t["team_id"]): t["team"] for t in teams_file or []}
        managers = {str(k): str(v) for k, v in (cfg.get("managers") or {}).items()}
        listed = {}
        for t in data.get("teams") or []:
            if isinstance(t, dict) and clean(t.get("team_id")) and clean(t.get("name")):
                listed[clean(t.get("team_id"))] = clean(t.get("name"))
        ids = sorted(set(current) | set(managers) | set(listed), key=lambda x: int(x) if x.isdigit() else 0)
        self.ids = ids
        self.yahoo_names = {tid: listed.get(tid) or current.get(tid) or managers.get(tid, "") for tid in ids}
        shown = build.display_names()
        seen = {}
        for names in (listed, current, shown, managers):  # team names first, manager names last
            for tid, name in names.items():
                key = team_key(name)
                if key and tid in ids:
                    seen.setdefault(key, set()).add(tid)
        self.lookup = {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}

    def team(self, text):
        return self.lookup.get(team_key(text))

    def yahoo_teams(self):
        """Same shape as yahoo.Client.rosters() without players, for build.team_names."""
        return [{"team_id": tid, "name": self.yahoo_names[tid], "nickname": ""} for tid in self.ids]

    # ---------------- scores ----------------
    def scores(self, schedule, names, current_week):
        """Returns the schedule with the Scores tab applied. Weeks that are not in the tab keep their data."""
        cfg = self.cfg
        last = cfg["regular_season_last_week"]
        id_of = {name: tid for tid, name in names.items()}
        by_week = {}
        for r in tab_rows(self.data, "scores", False):
            what = "Scores: week %s, %s vs %s" % (r["week"] or "?", r["team_a"] or "?", r["team_b"] or "?")
            week = to_int(r["week"])
            if week is None or not 1 <= week <= last:
                self.problems.append("%s: the week must be 1 to %d (row skipped)." % (what, last))
                continue
            a, b = self.team(r["team_a"]), self.team(r["team_b"])
            if not a or not b or a == b:
                bad = r["team_a"] if not a else r["team_b"]
                self.problems.append("%s: %s (row skipped)." % (what, "the same team is on both sides" if a and b else 'unknown team "%s"' % bad))
                continue
            ca, cb = to_int(r["cats_a"]), to_int(r["cats_b"])
            blank = not r["cats_a"] and not r["cats_b"]
            if not blank and (ca is None or cb is None or ca + cb > 9):
                self.problems.append("%s: the two scores must be whole numbers that add up to 9 or less (row skipped)." % what)
                continue
            word = r["status"].lower()
            status = SCORE_STATUS.get(word) if word else ("preevent" if blank else "midevent")
            if status is None:
                self.problems.append('%s: status must be Final or In progress, not "%s" (row skipped).' % (what, r["status"]))
                continue
            if status == "postevent" and blank:
                self.problems.append("%s: a Final row needs both scores (row skipped)." % what)
                continue
            if status == "preevent":
                ca, cb = None, None
            by_week.setdefault(week, {})[frozenset((a, b))] = {
                "teams": [{"team_id": a, "name": names.get(a, "")}, {"team_id": b, "name": names.get(b, "")}],
                "cats": [ca, cb], "status": status, "is_playoffs": False}

        for week in sorted(by_week):
            given = by_week[week]
            current = [r for r in schedule if r["week"] == week]
            on_schedule = {frozenset((id_of.get(r["team_a"]), id_of.get(r["team_b"]))): r for r in current}
            pair_text = lambda p: " vs ".join(names.get(t, "?") for t in sorted(p, key=lambda x: int(x) if x.isdigit() else 0))
            rebuild = False
            off = [p for p in given if p not in on_schedule]
            if off:
                whole_week = len(given) * 2 == len(names) and len({t for p in given for t in p}) == len(names)
                if not whole_week:
                    for p in off:
                        self.problems.append("Scores: Week %d: %s is not a matchup on the schedule for that week (row skipped)." % (week, pair_text(p)))
                        del given[p]
                elif any(r["status"] == "Final" for r in current) and any(m["status"] != "postevent" for m in given.values()):
                    self.problems.append("Scores: Week %d is already Final; its new pairings were ignored." % week)
                    continue
                else:
                    rebuild = True
            if not rebuild:
                for p in list(given):
                    if on_schedule[p]["status"] == "Final" and given[p]["status"] != "postevent":
                        self.problems.append("Scores: Week %d: %s is already Final; the row that is not Final was ignored." % (week, pair_text(p)))
                        del given[p]
            if not given:
                continue
            matchups = list(given.values())
            if not rebuild:  # matchups of that week that are not in the tab stay as they are
                for p, row in on_schedule.items():
                    if p not in given:
                        matchups.append({"teams": [{"team_id": id_of.get(row["team_a"]), "name": row["team_a"]}, {"team_id": id_of.get(row["team_b"]), "name": row["team_b"]}],
                                         "cats": [row["cats_a"], row["cats_b"]], "status": BACK.get(row["status"], "preevent"), "is_playoffs": False})
            schedule = build.apply_scoreboard(schedule, week, matchups, names, cfg, current_week)
        for r in schedule:  # the week being played shows as live even before any score is pasted
            if r["week"] == current_week and r["status"] == "Not started":
                r["status"] = "In progress"
        return schedule

    # ---------------- standings ----------------
    def standings(self, old_standings, names):
        """Standings in the Yahoo reader's shape, or None to keep the previous standings."""
        rows = tab_rows(self.data, "standings", True)
        if not rows:
            self.problems.append("Standings tab is empty. Kept the previous standings.")
            return None
        id_of = {name: tid for tid, name in names.items()}
        waiver = {id_of.get(r["team"]): r.get("waiver") for r in old_standings or []}
        out, bad, teams, ranks = [], [], set(), set()
        for r in rows:
            tid = self.team(r["team"])
            if not tid:
                bad.append('unknown team "%s"' % r["team"])
                continue
            rank, w, l = to_int(r["rank"]), to_int(r["w"]), to_int(r["l"])
            t = to_int(r["t"]) if r["t"] else 0
            if None in (rank, w, l, t) or rank < 1:
                bad.append("%s: rank, w, l and t must be whole numbers" % r["team"])
                continue
            if tid in teams:
                bad.append("%s is listed twice" % r["team"])
                continue
            if rank in ranks:
                bad.append("rank %d is used twice" % rank)
                continue
            teams.add(tid)
            ranks.add(rank)
            out.append({"team_id": tid, "name": names.get(tid, r["team"]), "rank": rank, "w": w, "l": l, "t": t, "waiver": waiver.get(tid)})
        if not bad and len(out) != len(names):
            bad.append("%d of %d teams listed" % (len(out), len(names)))
        if bad:
            self.problems.append("Standings: %s. Kept the previous standings." % "; ".join(bad))
            return None
        return out

    # ---------------- rosters ----------------
    def rosters(self, old_rosters, names, old_injuries=None):
        """Rosters in the Yahoo reader's shape (teams with players), or None to keep the current rosters.
        The sheet has no injury note, so the last known injury detail is carried over (ESPN's detail wins when it has one)."""
        rows = tab_rows(self.data, "rosters", True)
        if not rows:
            self.problems.append("Rosters tab is empty. Kept the current rosters.")
            return None
        id_of = {name: tid for tid, name in names.items()}
        old = {util.norm(r["player"]): r for r in old_rosters or []}
        detail = {util.norm(r["player"]): r.get("detail") or "" for r in old_injuries or []}
        from_old = lambda r: {"player": r["player"], "player_key": "", "nba_team": r["nba_team"], "pos": r["pos"], "yahoo_status": OLD_STATUS.get(r.get("status"), ""),
                              "note": detail.get(util.norm(r["player"]), ""), "slot": "IL" if r.get("il") else "BN"}
        team_of, rec_of, lost = {}, {}, []
        order = {tid: [] for tid in self.ids}
        for r in rows:
            if not r["player"]:
                continue
            key = util.norm(r["player"])
            tid = self.team(r["team"])
            if not tid:
                self.problems.append('Rosters: unknown team "%s" for %s (row skipped).' % (r["team"], r["player"]))
                lost.append(key)
                continue
            was = old.get(key)
            name = was["player"] if was else r["player"]
            slot = SLOTS.get(r["slot"].upper(), "") if r["slot"] else "BN"
            if not slot:
                self.problems.append('Rosters: unknown slot "%s" for %s (counted as bench).' % (r["slot"], name))
                slot = "BN"
            status = r["status"].upper().replace(".", "")
            status = STATUS_WORDS.get(status, status)
            if status and status not in STATUS_CODES:
                self.problems.append('Rosters: unknown status "%s" for %s (left blank).' % (r["status"], name))
                status = ""
            pos = ",".join(p for p in re.split(r"[,/;\s]+", r["pos"].upper()) if p in POSITIONS) or (was["pos"] if was else "")
            if not pos:
                self.problems.append("Rosters: no position for %s." % name)
            nba = util.nba_code(r["nba_team"]) or (was["nba_team"] if was else "")
            if nba and nba not in util.NBA_TEAMS:
                self.problems.append('Rosters: unknown NBA team "%s" for %s.' % (r["nba_team"], name))
            rec = {"player": name, "player_key": "", "nba_team": nba, "pos": pos, "yahoo_status": status, "note": detail.get(key, ""), "slot": slot}
            if key in team_of:
                first = team_of[key]
                if first == tid:
                    self.problems.append("Rosters: %s is listed twice on %s (second row skipped)." % (name, names.get(tid, r["team"])))
                    continue
                keep = tid if was and id_of.get(was["team"]) == tid else first
                self.problems.append("Rosters: %s is on two teams (%s and %s). Kept %s." % (name, names.get(first, "?"), names.get(tid, "?"), names.get(keep, "?")))
                if keep == tid:
                    order[first].remove(key)
                    order[tid].append(key)
                    team_of[key], rec_of[key] = tid, rec
                continue
            team_of[key], rec_of[key] = tid, rec
            order[tid].append(key)
        for key in lost:  # a skipped row keeps the player where he was
            was = old.get(key)
            tid = id_of.get(was["team"]) if was else None
            if tid and key not in team_of:
                team_of[key], rec_of[key] = tid, from_old(was)
                order[tid].append(key)
        for tid in self.ids:
            if not order[tid]:
                kept = [r for r in old_rosters or [] if id_of.get(r["team"]) == tid and util.norm(r["player"]) not in team_of]
                self.problems.append("Rosters: no rows for %s. Kept its current roster." % names.get(tid, self.yahoo_names[tid]))
                for r in kept:
                    key = util.norm(r["player"])
                    team_of[key], rec_of[key] = tid, from_old(r)
                    order[tid].append(key)
            elif len(order[tid]) > MAX_ROSTER:
                self.problems.append("Rosters: %s has %d players (the most a team can hold is %d). Check for an old paste left below the new one."
                                     % (names.get(tid, "?"), len(order[tid]), MAX_ROSTER))
        return [{"team_id": tid, "name": self.yahoo_names[tid], "nickname": "", "players": [rec_of[k] for k in order[tid]]} for tid in self.ids]

    # ---------------- trades ----------------
    def trades(self, names):
        """Pending trades as data/trades.json rows, or None when the sheet did not send the tab."""
        if not isinstance(self.data.get("trades"), list):
            return None
        out = []
        tidy = lambda text: ", ".join(x.strip() for x in text.split(",") if x.strip())
        for r in tab_rows(self.data, "trades", True):
            a, b = self.team(r["team_a"]), self.team(r["team_b"])
            if not a or not b or a == b:
                bad = r["team_a"] if not a else r["team_b"]
                self.problems.append("Trades: %s (row skipped)." % ("the same team is on both sides" if a and b else 'unknown team "%s"' % bad))
                continue
            a_gets, b_gets = tidy(r["a_gets"]), tidy(r["b_gets"])
            if not a_gets and not b_gets:
                self.problems.append("Trades: %s and %s: no players listed (row skipped)." % (names.get(a, "?"), names.get(b, "?")))
                continue
            out.append({"deal": "T%d" % (len(out) + 1), "team_a": names[a], "a_gets": a_gets, "team_b": names[b], "b_gets": b_gets,
                        "processes": r["processes"] or "Pending vote"})
        return out
