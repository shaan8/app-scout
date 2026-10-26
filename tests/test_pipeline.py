from scout.pipeline import aggregate, window


def row(day, rank, prev=None, app_id=1, country="US"):
    return {"source": "sensortower", "date": day, "country": country, "category": 0, "chart": "free",
            "rank": rank, "previous_rank": prev, "app_id": app_id, "name": "A", "publisher_name": "P",
            "monthly_revenue_usd": 5000, "monthly_revenue": "$5k-$50k", "monthly_downloads": "5k-50k"}


def test_window_is_newest_first():
    assert window("2026-10-24", 3) == ["2026-10-24", "2026-10-23", "2026-10-22"]


def test_single_day_score_matches_appearance_sum():
    [app] = aggregate([row("2026-10-24", 1, prev=1)], ["2026-10-24"]).values()
    assert app["trend_score"] == 1.0
    assert app["rank_change"] is None


def test_climber_beats_faller_with_same_ranks():
    dates = window("2026-10-24", 3)
    climber = [row("2026-10-22", 20, 20, 1), row("2026-10-23", 10, 20, 1), row("2026-10-24", 2, 10, 1)]
    faller = [row("2026-10-22", 2, 2, 2), row("2026-10-23", 10, 2, 2), row("2026-10-24", 20, 10, 2)]
    apps = aggregate(climber + faller, dates)
    assert apps[1]["trend_score"] > apps[2]["trend_score"]
    assert apps[1]["rank_change"] == 18 and apps[2]["rank_change"] == -18
    assert apps[1]["days_charting"] == 3 and apps[1]["first_seen"] == "2026-10-22"
