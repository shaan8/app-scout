"""Chart and metadata sources. Each function returns plain dicts with the fields the pipeline uses."""

from urllib.parse import urlencode

from .http import Fetcher

SENSOR_TOWER = "https://app.sensortower.com/api/ios/category_rankings"
APPLE_RSS = "https://rss.marketingtools.apple.com/api/v2/{country}/apps/{feed}/100/apps.json"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup"

# The public Sensor Tower endpoint caps each chart at 25 entries.
SENSOR_TOWER_LIMIT = 25
LOOKUP_BATCH = 100


def sensor_tower_rankings(fetch: Fetcher, country: str, category: int, date: str) -> list[dict]:
    query = urlencode({"offset": 0, "limit": SENSOR_TOWER_LIMIT, "category": category,
                       "country": country, "date": date, "device": "iphone"})
    data = fetch.get_json(f"{SENSOR_TOWER}?{query}").get("data", {})
    rows = []
    for chart, entries in data.items():
        for e in entries:
            rows.append({
                "source": "sensortower",
                "country": country,
                "category": category,
                "chart": chart,
                "rank": e["rank"],
                "previous_rank": e.get("previous_rank"),
                "app_id": e["app_id"],
                "name": e["name"],
                "publisher_id": e["publisher_id"],
                "publisher_name": e["publisher_name"],
                "monthly_revenue_usd": (e.get("humanized_worldwide_last_month_revenue") or {}).get("revenue"),
                "monthly_revenue": (e.get("humanized_worldwide_last_month_revenue") or {}).get("string"),
                "monthly_downloads": (e.get("humanized_worldwide_last_month_downloads") or {}).get("string"),
            })
    return rows


def apple_top_charts(fetch: Fetcher, country: str) -> list[dict]:
    rows = []
    for feed, chart in (("top-free", "free"), ("top-paid", "paid")):
        results = fetch.get_json(APPLE_RSS.format(country=country.lower(), feed=feed))["feed"].get("results", [])
        for rank, e in enumerate(results, start=1):
            rows.append({
                "source": "apple",
                "country": country,
                "category": 0,
                "chart": chart,
                "rank": rank,
                "previous_rank": None,
                "app_id": int(e["id"]),
                "name": e["name"],
                "publisher_id": None,
                "publisher_name": e["artistName"],
                "monthly_revenue_usd": None,
                "monthly_revenue": None,
                "monthly_downloads": None,
            })
    return rows


def lookup_apps(fetch: Fetcher, app_ids: list[int], country: str) -> dict[int, dict]:
    """App Store metadata keyed by app id. Apps missing from this storefront are absent."""
    found = {}
    for batch in _chunks(sorted(app_ids), LOOKUP_BATCH):
        query = urlencode({"id": ",".join(map(str, batch)), "country": country.lower()})
        for r in fetch.get_json(f"{ITUNES_LOOKUP}?{query}")["results"]:
            if r.get("wrapperType") == "software":
                found[r["trackId"]] = r
    return found


def lookup_portfolios(fetch: Fetcher, artist_ids: list[int], country: str) -> dict[int, list[dict]]:
    """Every app each developer account has in this storefront."""
    portfolios: dict[int, list[dict]] = {a: [] for a in artist_ids}
    # Each artist can return up to 200 apps, so keep batches small to stay under the response cap.
    for batch in _chunks(sorted(artist_ids), 10):
        query = urlencode({"id": ",".join(map(str, batch)), "entity": "software",
                           "limit": 200, "country": country.lower()})
        for r in fetch.get_json(f"{ITUNES_LOOKUP}?{query}")["results"]:
            if r.get("wrapperType") == "software" and r.get("artistId") in portfolios:
                portfolios[r["artistId"]].append(r)
    return portfolios


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]
