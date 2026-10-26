"""Find contact details on the pages a developer lists on its own App Store and Sensor Tower entries.

Neither store publishes emails or social handles. Both publish the developer's website, and Apple requires a
privacy policy URL, so every contact here is one the developer put on a page it named as its own.
"""

import html
import re
from urllib.parse import urljoin, urlsplit

from .http import Fetcher

SENSOR_TOWER_APP = "https://app.sensortower.com/api/ios/apps/{app_id}?country={country}"
MAX_PAGES_PER_APP = 6

# Same-site pages worth reading for contact details, besides the ones the stores link to.
CONTACT_PATHS = re.compile(r"/(about|team|contact|company|press|founder|support|help|imprint|impressum|legal)\b", re.I)
EXTERNAL_LINK = re.compile(r'(?:aria-label="([^"]*)"\s+)?data-test-id="external-link"\s+href="([^"]+)"')
HREF = re.compile(r'href=["\']([^"\'#]+)', re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}")

SOCIAL = {
    "x": re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/(?:#!/)?@?([A-Za-z0-9_]{1,15})(?=[/?\"'\s]|$)", re.I),
    "linkedin": re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(in|company|school)/([A-Za-z0-9\-_%.]{2,100})", re.I),
    "threads": re.compile(r"https?://(?:www\.)?threads\.(?:net|com)/@([A-Za-z0-9_.]{1,30})", re.I),
}
# Paths and handles that are site features or the hosting platform's own accounts, not the developer.
IGNORED_HANDLES = {
    "x": {"share", "intent", "home", "i", "search", "hashtag", "login", "signup", "explore", "settings", "tos",
          "privacy", "appstore", "apple", "googleplay", "x", "twitter", "framer", "webflow", "wix", "carrd",
          "notionhq", "squarespace", "shopify", "wordpress", "godaddy", "vercel", "github", "termly_io",
          "iubenda", "privacypolicies", "freeprivacypolicy"},
    "linkedin": {"company/linkedin", "company/framer", "company/webflow-inc-", "company/wix-com",
                 "company/termly", "company/iubenda", "company/apple", "company/google"},
    "threads": {"threads", "instagram", "meta"},
}
IGNORED_EMAIL = re.compile(
    r"(\.(png|jpe?g|gif|svg|webp|ico|css|js)$)|@(example|domain|email|yourdomain|yourcompany|company|sentry|"
    r"[a-z0-9.-]*sentry\.io|wixpress|wix|godaddy|squarespace|framer|webflow|termly|iubenda|apple|"
    r"privacypolicies|freeprivacypolicy|2x|3x)\.|^(no-?reply|donotreply|mailer-daemon|user|name|you|your|email)@|example|^[0-9a-f]{24,}@",
    re.I,
)
STORE_HOSTS = ("apple.com", "mzstatic.com", "sensortower.com")
# Profiles here are recorded as contacts but not crawled: the pages are script-rendered and say nothing new.
SOCIAL_HOSTS = ("x.com", "twitter.com", "linkedin.com", "threads.net", "threads.com", "instagram.com",
                "facebook.com", "tiktok.com", "youtube.com")


def official_urls(fetch: Fetcher, app: dict, use_sensor_tower: bool = True) -> list[dict]:
    """URLs the developer listed as its own: [{"url", "source", "kind"}]."""
    urls = []
    if app.get("seller_url"):
        urls.append({"url": app["seller_url"], "source": "App Store lookup", "kind": "website"})

    if app.get("app_url"):
        page = fetch.get_page(app["app_url"])
        for label, href in EXTERNAL_LINK.findall(page["text"]):
            kind = "privacy policy" if "privacy" in label.lower() or "/privacy" in href.lower() else "website"
            urls.append({"url": html.unescape(href), "source": "App Store page", "kind": kind})

    if use_sensor_tower and not any(u["kind"] == "website" for u in urls):
        country = app["markets"][0] if app.get("markets") else "US"
        try:
            detail = fetch.get_json(SENSOR_TOWER_APP.format(app_id=app["app_id"], country=country))
        except Exception:
            detail = {}
        for field, kind in (("website_url", "website"), ("support_url", "support")):
            if detail.get(field):
                urls.append({"url": detail[field], "source": "Sensor Tower", "kind": kind})

    seen, unique = set(), []
    for u in urls:
        key = u["url"].rstrip("/").lower()
        host = urlsplit(u["url"]).hostname or ""
        if key and key not in seen and u["url"].startswith("http") and not host.endswith(STORE_HOSTS):
            seen.add(key)
            unique.append(u)
    return unique


def crawl(fetch: Fetcher, seeds: list[dict]) -> list[dict]:
    """Fetch the official URLs plus a few same-site contact/about pages linked from them."""
    pages, queued = [], {s["url"] for s in seeds}
    queue = [dict(s) for s in seeds]
    while queue and len(pages) < MAX_PAGES_PER_APP:
        item = queue.pop(0)
        if (urlsplit(item["url"]).hostname or "").endswith(SOCIAL_HOSTS):
            continue
        page = fetch.get_page(item["url"])
        pages.append({**item, **page})
        if page["status"] != 200 or item["kind"] == "linked page":
            continue
        site = urlsplit(page["final_url"]).hostname
        for href in HREF.findall(page["text"]):
            link = urljoin(page["final_url"], html.unescape(href))
            parts = urlsplit(link)
            if parts.hostname == site and CONTACT_PATHS.search(parts.path) and link not in queued:
                queued.add(link)
                queue.append({"url": link, "source": item["source"], "kind": "linked page"})
    return pages


def extract(page: dict) -> list[dict]:
    """Contacts on one page: [{"type", "value", "url"}]."""
    text = html.unescape(page.get("text") or "")
    found = []
    for email in set(EMAIL.findall(text)):
        email = email.lower().rstrip(".")
        if not IGNORED_EMAIL.search(email):
            found.append({"type": "email", "value": email, "url": f"mailto:{email}"})

    for m in SOCIAL["x"].finditer(text):
        handle = m.group(1)
        if handle.lower() not in IGNORED_HANDLES["x"]:
            found.append({"type": "x", "value": f"@{handle}", "url": f"https://x.com/{handle}"})
    for m in SOCIAL["linkedin"].finditer(text):
        kind, slug = m.group(1).lower(), m.group(2).rstrip(".")
        if f"{kind}/{slug}".lower() not in IGNORED_HANDLES["linkedin"]:
            found.append({"type": "linkedin", "value": f"{kind}/{slug}", "url": f"https://www.linkedin.com/{kind}/{slug}"})
    for m in SOCIAL["threads"].finditer(text):
        handle = m.group(1).rstrip(".")
        if handle.lower() not in IGNORED_HANDLES["threads"]:
            found.append({"type": "threads", "value": f"@{handle}", "url": f"https://www.threads.com/@{handle}"})
    return found


def discover(fetch: Fetcher, app: dict, use_sensor_tower: bool = True) -> dict:
    """All contacts for one app, merged across pages, each with the pages it was found on."""
    seeds = official_urls(fetch, app, use_sensor_tower)
    pages = crawl(fetch, seeds)
    merged: dict[tuple, dict] = {}
    # A profile the developer gave Apple as its website is a contact in itself, sourced from the listing.
    for seed in seeds:
        for c in extract({"text": seed["url"]}):
            merged.setdefault((c["type"], c["value"].lower()), {**c, "found_on": [app.get("app_url") or seed["url"]]})
    for page in pages:
        if page["status"] != 200:
            continue
        for c in extract(page):
            key = (c["type"], c["value"].lower())
            entry = merged.setdefault(key, {**c, "found_on": []})
            if page["final_url"] not in entry["found_on"]:
                entry["found_on"].append(page["final_url"])
    return {
        "official_urls": seeds,
        "pages": [{"url": p["url"], "status": p["status"], "kind": p["kind"], "source": p["source"]} for p in pages],
        "contacts": list(merged.values()),
    }
