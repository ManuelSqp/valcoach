"""Habit tracker and practice plan, from hand-made game rows."""
from datetime import date

from nexus.stats import habits, practice


def _row(i, alone_far, traded, fd=1, fk=1):
    return {"source": "full", "started_at": f"2026-10-{i + 1:02d}T20:00:00Z", "rounds": 20, "deaths": 10, "kills": 12,
            "traded_deaths": traded, "fk": fk, "fd": fd, "kast": 15, "shots": [10, 40, 5],
            "iso": {"attack": [6, 1, 6, alone_far], "defense": [6, 0, 4, 0]},
            "deaths_at": [["attack", "B Main", 0, 0]] * 4 + [["defense", "A Site", 0, 0]] * 6}


def test_habit_goes_away_and_coach_tip_is_checked():
    rows = [_row(i, 6, 2) for i in range(20)] + [_row(20 + i, 1, 2) for i in range(10)]
    coach = [{"text": "You died alone on attack too often", "fix": "", "date": "2026-10-20T23:00:00Z", "source": "Report", "url": "/r"},
             {"text": "Call the rotate earlier", "fix": "", "date": "2026-10-20T23:00:00Z", "source": "Report", "url": "/r"},
             {"text": "Call the rotate earlier", "fix": "", "date": "2026-10-10T23:00:00Z", "source": "Report", "url": "/r"}]
    h = habits.track(rows, coach)
    by = {x["key"]: x for x in h["habits"]}
    assert by["alone"]["status"] == "gone" and by["alone"]["before"] > 0.5 and by["alone"]["now"] < 0.2
    assert by["alone"]["coach"][0]["verdict"] == "better since"
    assert by["untraded"]["status"] == "same"                         # 80 % untraded throughout
    assert h["spot"] == "A Site" and by["spot"]["title"].startswith("Dying at A Site")
    assert h["notes"][0]["text"] == "Call the rotate earlier" and h["notes"][0]["times"] == 2
    assert [x["key"] for x in h["problems"]] and "alone" not in [x["key"] for x in h["problems"]]


def test_practice_plan_uses_habits_map_and_strats():
    members = {"a": {"problems": [{"key": "untraded", "title": "Deaths nobody trades"}]},
               "b": {"problems": [{"key": "untraded", "title": "Deaths nobody trades"}, {"key": "aim", "title": "Low headshot rate"}]}}
    th = practice.team_habits(members)
    assert th[0]["key"] == "untraded" and th[0]["who"] == ["a", "b"]
    ctx = {"map": "Lotus", "strats": {"attack": ["A split"], "defense": []}, "lineups": {"Sova": 2}, "habits": th,
           "personal": {}, "review": {"title": "the Lotus review", "url": "/rv"}, "match_days": [5], "focus": True}
    plan = practice.build("2026-W45", date(2026, 11, 2), {"days": [1, 4], "time": "19:00", "minutes": 90}, ctx)
    d1, d2 = plan["days"]
    kinds1 = [i["kind"] for i in d1["items"]]
    assert d1["label"].startswith("Tue") and kinds1[0] == "warmup" and "habit" in kinds1 and "review" in kinds1
    assert any("A split" in i["detail"] for i in d1["items"])                      # attack strats on day 1
    assert any(i["kind"] == "prep" for i in d2["items"])                            # Fri, the day before Sat's match
    assert any("No defense strat" in i["detail"] for i in d2["items"])
    assert all(sum(i["minutes"] for i in d["items"]) <= 90 for d in plan["days"])
    assert practice.progress(plan) == (0, len(d1["items"]) + len(d2["items"]))
    assert "Practice this week" in practice.discord_text(plan, "Squad")
