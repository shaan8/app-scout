import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from . import contacts, report, sources, verify
from .config import CATEGORIES, COUNTRIES, Thresholds
from .filter import classify
from .http import Fetcher

log = logging.getLogger("scout")

APPLE_FEED_MAX_LAG_DAYS = 3
# Weight of (latest-day score - first-day score) in a multi-day trend score: apps that are climbing rank higher.
RISE_WEIGHT = 0.5


def window(end: str, days: int) -> list[str]:
    """The chart dates covered by a run, newest first."""
    last = date.fromisoformat(end)
    return [(last - timedelta(days=i)).isoformat() for i in range(days)]


def collect_rankings(fetch: Fetcher, dates: list[str], countries: list[str]) -> list[dict]:
    rows = []
    for day in dates:
        for country in countries:
            for category in CATEGORIES:
                try:
                    rows += [{**r, "date": day} for r in sources.sensor_tower_rankings(fetch, country, category, day)]
                except Exception as e:
                    log.warning("sensortower %s %s/%s failed: %s", day, country, category, e)
        log.info("charts for %s collected", day)
    # Apple's feeds only show today's chart, so they count only when the window ends close to today.
    if date.fromisoformat(dates[0]) >= date.today() - timedelta(days=APPLE_FEED_MAX_LAG_DAYS):
        for country in countries:
            try:
                rows += [{**r, "date": dates[0]} for r in sources.apple_top_charts(fetch, country)]
            except Exception as e:
                log.warning("apple rss %s failed: %s", country, e)
    return rows


def appearance_score(row: dict) -> float:
    """Chart position plus upward movement. Apple feeds have 100 slots and no history, so they weigh less."""
    if row["source"] == "apple":
        return 0.5 * (101 - row["rank"]) / 100
    position = (26 - row["rank"]) / 25
    prev = row["previous_rank"]
    momentum = 0.5 if prev is None else max(0, min(prev - row["rank"], 25)) / 25
    return position + momentum


def aggregate(rows: list[dict], dates: list[str]) -> dict[int, dict]:
    """One record per app. Over a multi-day window the score is the average day plus a bonus for rising."""
    apps: dict[int, dict] = {}
    for r in sorted(rows, key=lambda r: r["date"], reverse=True):
        app = apps.setdefault(r["app_id"], {
            "app_id": r["app_id"], "name": r["name"], "publisher_name": r["publisher_name"],
            "monthly_revenue_usd": None, "monthly_revenue": None, "monthly_downloads": None, "rows": [],
        })
        app["rows"].append(r)
        if r["source"] == "sensortower":
            for k in ("monthly_revenue_usd", "monthly_revenue", "monthly_downloads"):
                app[k] = app[k] if app[k] is not None else r[k]

    latest, earliest = dates[0], dates[-1]
    for app in apps.values():
        rows_ = app.pop("rows")
        daily = defaultdict(float)
        best_by_day = {}
        for r in rows_:
            daily[r["date"]] += appearance_score(r)
            best_by_day[r["date"]] = min(best_by_day.get(r["date"], r["rank"]), r["rank"])
        rise = max(0.0, daily.get(latest, 0.0) - daily.get(earliest, 0.0)) if len(dates) > 1 else 0.0
        charted = sorted(best_by_day)
        app.update({
            "trend_score": round(sum(daily.values()) / len(dates) + RISE_WEIGHT * rise, 2),
            "markets": sorted({r["country"] for r in rows_}, key=COUNTRIES.index),
            "best_rank": min(r["rank"] for r in rows_),
            "appearances": len(rows_),
            "categories": sorted({CATEGORIES[r["category"]] for r in rows_}),
            "days_charting": len(charted),
            "first_seen": charted[0],
            # Positive means the app's best chart position improved between its first and last day in the window.
            "rank_change": best_by_day[charted[0]] - best_by_day[charted[-1]] if len(charted) > 1 else None,
        })
    return apps


def storefront(app: dict) -> str:
    return "US" if "US" in app["markets"] else app["markets"][0]


def enrich(fetch: Fetcher, apps: dict[int, dict]) -> None:
    by_country = defaultdict(list)
    for app in apps.values():
        by_country[storefront(app)].append(app["app_id"])
    for country, ids in by_country.items():
        meta = sources.lookup_apps(fetch, ids, country)
        for app_id in ids:
            m = meta.get(app_id, {})
            apps[app_id].update({
                "seller_name": m.get("sellerName"),
                "artist_id": m.get("artistId"),
                "release_date": m.get("releaseDate"),
                "seller_url": m.get("sellerUrl"),
                "app_url": m.get("trackViewUrl", "").split("?")[0] or None,
            })


def screen(fetch: Fetcher, apps: dict[int, dict], t: Thresholds) -> None:
    # Cheap checks first, so the slow per-developer lookups only run for apps still in play.
    pending = defaultdict(set)
    for app in apps.values():
        app.update(classify(app, None, t))
        if app["tier"] != "excluded" and app.get("artist_id"):
            pending[storefront(app)].add(app["artist_id"])

    portfolios = {}
    for country, artist_ids in pending.items():
        portfolios.update(sources.lookup_portfolios(fetch, list(artist_ids), country))

    for app in apps.values():
        if app["tier"] != "excluded" and app.get("artist_id") in portfolios:
            app.update(classify(app, portfolios[app["artist_id"]], t))


def write_outputs(apps: dict[int, dict], rows: list[dict], out_dir: Path, dates: list[str]) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rankings.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    ranked = sorted(apps.values(), key=lambda a: -a["trend_score"])
    (out_dir / "apps.json").write_text(json.dumps(ranked, ensure_ascii=False, indent=1))
    (out_dir / "run.json").write_text(json.dumps({"dates": dates}))
    contacts_path = out_dir / "contacts.json"
    contacts = json.loads(contacts_path.read_text()) if contacts_path.exists() else {}
    report.write_workbook(ranked, contacts, out_dir / f"app-scout-{out_dir.name}.xlsx", dates)
    return {tier: sum(a["tier"] == tier for a in ranked) for tier in ("founder", "small_company", "excluded")}


def make_fetcher(cache_dir: Path, use_cache: bool) -> Fetcher:
    return Fetcher(cache_dir, use_cache=use_cache, min_interval={
        "app.sensortower.com": 4.0, "itunes.apple.com": 3.0, "rss.marketingtools.apple.com": 0.5,
        "apps.apple.com": 1.0, "publish.twitter.com": 1.0, "www.linkedin.com": 3.0, "cloudflare-dns.com": 0.1,
    })


def run(dates: list[str], out_dir: Path, cache_dir: Path, countries: list[str], use_cache: bool = True) -> dict[str, int]:
    fetch = make_fetcher(cache_dir, use_cache)
    rows = collect_rankings(fetch, dates, countries)
    log.info("collected %d chart entries over %d day(s)", len(rows), len(dates))
    apps = aggregate(rows, dates)
    log.info("%d unique apps", len(apps))
    enrich(fetch, apps)
    screen(fetch, apps, Thresholds())
    return write_outputs(apps, rows, out_dir, dates)


def run_contacts(out_dir: Path, cache_dir: Path, tiers: list[str], limit: int, use_cache: bool = True,
                 workers: int = 8) -> dict[str, int]:
    """Discover and verify contacts for the top `limit` apps of each tier, then rebuild the workbook."""
    fetch = make_fetcher(cache_dir, use_cache)
    ranked = json.loads((out_dir / "apps.json").read_text())
    targets = [a for tier in tiers for a in [a for a in ranked if a["tier"] == tier][:limit]]
    log.info("finding contacts for %d apps", len(targets))

    def one(app: dict) -> tuple[int, dict]:
        found = contacts.discover(fetch, app)
        return app["app_id"], {"official_urls": found["official_urls"], "pages": found["pages"],
                               "contacts": verify.verify(fetch, app, found)}

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, (app_id, result) in enumerate(pool.map(one, targets), start=1):
            results[str(app_id)] = result
            if done % 25 == 0:
                log.info("%d/%d apps done", done, len(targets))

    (out_dir / "contacts.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    dates = json.loads((out_dir / "run.json").read_text())["dates"]
    report.write_workbook(ranked, results, out_dir / f"app-scout-{out_dir.name}.xlsx", dates)
    statuses = [c["status"] for r in results.values() for c in r["contacts"]]
    return {s: statuses.count(s) for s in ("verified", "likely", "rejected")}
