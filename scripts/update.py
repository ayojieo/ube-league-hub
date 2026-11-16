#!/usr/bin/env python3
"""Daily update for the UBE League Hub. Each source is independent: if one fails, the others still update
and the old data for the failed one is kept. Exits with an error only when Yahoo could not be read."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hub import build, season, sources, util, yahoo  # noqa: E402


def summary(lines):
    text = "\n".join(lines) + "\n"
    print(text)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write(text)


def roster_changes(old, new):
    was = {(r["player"], r["team"]): r for r in old or []}
    now = {(r["player"], r["team"]): r for r in new}
    moves = len(set(now) - set(was)) + len({p for p, _ in was} - {p for p, _ in now})
    il = sum(1 for k in set(now) & set(was) if now[k].get("il") != was[k].get("il"))
    return moves, il


def main():
    cfg = util.load_config()
    today = util.today(cfg)
    label = season.label(cfg)
    state = util.read("state", {}) or {}
    if state.get("season_over"):
        summary(["## UBE League Hub", "The %s season is over. Edit config/league.json and run **New season** to start the next one." % state.get("season", label)])
        return 0

    files = {name: util.read(name, []) or [] for name in util.PAGE_DATASETS}
    before = {name: util.dump(files[name]) for name in files}
    teams = util.read("teams", []) or []
    weeks = util.read("weeks", []) or []
    htb = {util.norm(r["player"]): r for r in (util.read("htb", []) or [])}
    alias = build.aliases()
    notes, problems, done = [], [], []
    monday = today.weekday() == 0
    force = os.environ.get("UBE_FORCE", "").split(",")

    # ---------- Yahoo ----------
    y = yahoo.Client(cfg)
    meta, y_teams, yahoo_ok, y_stats = None, None, False, {}
    try:
        meta = y.meta()
        y_teams = y.rosters()
        teams, renames = build.team_names(teams, y_teams, cfg)
        build.rename_everywhere(renames, files)
        for old, new in renames.items():
            notes.append("team renamed: %s is now %s" % (old, new))
        names = {t["team_id"]: t["team"] for t in teams}
        managers = {t["team_id"]: t["manager"] for t in teams}
        cur, last = meta["current_week"], cfg["regular_season_last_week"]

        want = {cur, cur - 1} | {r["week"] for r in files["schedule"] if r["week"] < cur and r["status"] != "Final"}
        if monday or "schedule" in force or not files["schedule"]:
            want |= set(range(cur, last + 1))
        was_final = {r["week"] for r in files["schedule"] if r["status"] == "Final"}
        old_scores = {r["matchup"]: (r["cats_a"], r["cats_b"]) for r in files["schedule"]}
        for w in sorted(x for x in want if 1 <= x <= last):
            try:
                files["schedule"] = build.apply_scoreboard(files["schedule"], w, y.scoreboard(w), names, cfg, cur)
            except Exception as e:  # one week failing should not stop the rest
                problems.append("Week %d scores: %s" % (w, e))
        for w in sorted({r["week"] for r in files["schedule"] if r["status"] == "Final"} - was_final):
            notes.append("Week %d final" % w)
        if any(r["status"] == "In progress" and old_scores.get(r["matchup"]) != (r["cats_a"], r["cats_b"]) for r in files["schedule"]):
            notes.append("Week %d live scores" % cur)

        files["standings"] = build.standings_rows(y.standings(), names, managers)
        try:
            files["trades"] = build.trade_rows(y.pending_trades(cfg["my_team_id"]), names)
        except Exception as e:
            problems.append("Pending trades: %s (kept the previous list)" % e)
        try:
            need = build.players_needing_yahoo_stats(y_teams, files["players"], htb, alias)
            y_stats = y.season_stats(need) if need else {}
        except Exception as e:
            problems.append("Yahoo stats for new players: %s" % e)
        if monday or not weeks or "schedule" in force:
            try:
                weeks = y.game_weeks() or weeks
            except Exception:
                pass  # falls back to Monday-Sunday weeks
        yahoo_ok = True
        done.append("Yahoo: scores, standings, rosters, IL slots, trades")
    except Exception as e:
        problems.append("Yahoo: %s" % e)

    # ---------- injuries, news ----------
    espn = None
    try:
        espn = sources.injuries()
        done.append("ESPN injuries")
    except Exception as e:
        problems.append("%s (kept the previous injuries)" % e)
    try:
        files["news"] = sources.news()
        done.append("Headlines")
    except Exception as e:
        problems.append("%s (kept the previous headlines)" % e)

    # ---------- Hashtagbasketball (Mondays) ----------
    dates = [p.get("htb_date") for p in files["players"] if p.get("htb_date") and p.get("htb_rank") is not None]
    last_htb = max(dates) if dates else None
    due = "htb" in force or last_htb is None or (monday and last_htb != today.isoformat()) or (today - dt.date.fromisoformat(last_htb)).days >= 8
    fresh_htb = None
    if due:
        try:
            fresh_htb = sources.hashtag()
            for line in fresh_htb.values():
                line["date"] = today.isoformat()
            htb = fresh_htb
            done.append("Hashtagbasketball stats (%d players)" % len(fresh_htb))
        except Exception as e:
            problems.append("%s (kept last week's stats)" % e)

    # ---------- rosters, players, injuries ----------
    old_rosters = files["rosters"]
    if yahoo_ok:
        rosters, players, injuries, new_players = build.build_rosters(y_teams, names, files["players"], espn, htb, y_stats, today, label, alias)
        moves, il_moves = roster_changes(old_rosters, rosters)
        if moves:
            notes.append("%d roster move%s" % (moves, "" if moves == 1 else "s"))
        if il_moves:
            notes.append("IL moves")
        files["rosters"], files["players"], files["injuries"] = rosters, players, injuries
        missing = [p["player"] for p in players if p["player"] in new_players and p["source"].startswith("No stats")]
        if missing:
            problems.append("No stats found yet for: %s" % ", ".join(missing))
    elif espn is not None and files["players"]:
        files["injuries"] = build.apply_injuries_only(files["rosters"], files["players"], espn, today, alias)
    if fresh_htb:
        build.apply_htb(files["players"], fresh_htb, today, label, alias)
        notes.append("Hashtagbasketball stats refresh")
    build.apply_cap(files["players"])

    # ---------- NBA schedule ----------
    horizon = (today + dt.timedelta(days=21)).isoformat()
    covered = max((g["date"] for g in files["nba_games"]), default="")
    if monday or "schedule" in force or covered < min(horizon, cfg["season_end"]):
        try:
            files["nba_games"] = sources.nba_games(cfg, weeks)
            done.append("NBA schedule")
        except Exception as e:
            problems.append("%s (kept the previous schedule)" % e)

    # ---------- write, team cards, changelog ----------
    for name in ("injuries", "news", "nba_games", "trades"):
        if util.dump(files[name]) != before[name]:
            notes.append({"injuries": "injuries", "news": "news", "nba_games": "NBA schedule", "trades": "pending trades"}[name])
    if util.dump(files["standings"]) != before["standings"]:
        notes.insert(0, "standings")
    for name in util.PAGE_DATASETS:
        if name not in ("managers", "log"):
            util.write(name, files[name])
    util.write("teams", teams)
    if weeks:
        util.write("weeks", weeks)
    if htb:
        util.write("htb", sorted(htb.values(), key=lambda r: r["htb_rank"]))
    try:
        if files["players"] and teams:
            files["managers"] = build.manager_rows(files["managers"], teams, build.run_model())
            util.write("managers", files["managers"])
    except Exception as e:
        problems.append("Team cards: %s (kept the previous cards)" % e)

    changed = [n for n in util.PAGE_DATASETS if n != "log" and util.dump(files[n]) != before[n]]
    if changed:
        order = ["Week", "standings", "roster", "IL moves", "pending trades", "Hashtag", "NBA schedule", "injuries", "news", "team renamed"]
        notes = sorted(dict.fromkeys(notes), key=lambda n: next((i for i, k in enumerate(order) if n.startswith(k)), 99))
        text = "; ".join(notes) if notes else "team cards"
        files["log"] = files["log"] + [{"version": build.next_version(files["log"]), "date": today.isoformat(), "change": text[:1].upper() + text[1:] + "."}]
        util.write("log", files["log"])
        state.update(season=label, season_over=False, updated=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        util.write("state", state)

    # ---------- season end ----------
    ended = False
    over_date = dt.date.fromisoformat(cfg["season_end"]) + dt.timedelta(days=2)
    if (yahoo_ok and meta and meta["is_finished"]) or today > over_date:
        season.archive(cfg)
        ended = True

    # ---------- refresh token, report ----------
    target = os.environ.get("NEW_REFRESH_TOKEN_FILE")
    if y.new_refresh and target:
        with open(target, "w", encoding="utf-8") as f:
            f.write(y.new_refresh)

    lines = ["## UBE League Hub: daily update (%s)" % today.isoformat(), ""]
    lines.append("**Changed:** " + ("; ".join(notes) if changed and notes else ("team cards" if changed else "nothing")))
    lines.append("")
    lines.append("**Read OK:** " + (", ".join(done) if done else "nothing"))
    if problems:
        lines += ["", "**Problems:**"] + ["- " + p for p in problems]
    if ended:
        lines += ["", "**Season over.** The final hub was saved under archive/%s and live data was cleared. Run **New season** when the next league is ready." % label]
    summary(lines)
    return 0 if yahoo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
