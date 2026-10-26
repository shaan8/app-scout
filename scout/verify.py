"""Check every discovered contact before it reaches the shortlist.

Each contact gets a list of named checks and one status:
  verified  every check that can run passed, and it ties back to the developer's own domain or name
  likely    found on an official page and not contradicted, but at least one check could not confirm it
  rejected  a check failed (no mail server, profile does not exist, unrelated account)
"""

import json
import re
from urllib.parse import quote, urlsplit

from .contacts import EMAIL
from .http import Fetcher

DNS_OVER_HTTPS = "https://cloudflare-dns.com/dns-query?name={name}&type={type}"
X_OEMBED = "https://publish.twitter.com/oembed?url={url}"

FREEMAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com", "icloud.com",
            "me.com", "proton.me", "protonmail.com", "qq.com", "163.com", "126.com", "naver.com", "daum.net",
            "kakao.com", "yahoo.co.jp", "gmx.com", "aol.com", "foxmail.com", "hey.com"}
# Hosts where the site belongs to a platform, so a matching email domain proves nothing.
SHARED_HOSTS = ("notion.site", "notion.so", "github.io", "vercel.app", "netlify.app", "wixsite.com", "carrd.co",
                "framer.website", "framer.ai", "webflow.io", "sites.google.com", "blogspot.com", "linktr.ee",
                "wordpress.com", "pages.dev", "web.app", "firebaseapp.com", "tilda.ws", "super.site",
                "medium.com", "gitbook.io", "freeprivacypolicy.com", "termsfeed.com", "privacypolicies.com")
SECOND_LEVEL = {"co.uk", "com.tw", "org.tw", "net.tw", "idv.tw", "co.jp", "ne.jp", "or.jp", "co.kr", "or.kr",
                "com.sg", "com.hk", "co.in", "com.vn", "com.au", "co.nz", "com.cn", "com.br", "com.my", "co.id"}
# A page listing this many unrelated accounts of one type is a directory or blog, not the developer's links.
MAX_UNMATCHED_PER_TYPE = 2


def registrable_domain(host: str) -> str:
    labels = host.lower().strip(".").removeprefix("www.").split(".")
    n = 3 if ".".join(labels[-2:]) in SECOND_LEVEL else 2
    return ".".join(labels[-n:])


def owned_domains(app: dict, official_urls: list[dict]) -> set[str]:
    domains = set()
    for u in official_urls:
        host = urlsplit(u["url"]).hostname or ""
        if host and not host.endswith(SHARED_HOSTS):
            domains.add(registrable_domain(host))
    return domains


def name_tokens(app: dict, domains: set[str]) -> set[str]:
    """Lowercase words of 3+ characters that identify this developer or app."""
    words = set()
    for text in (app.get("name"), app.get("seller_name"), app.get("publisher_name")):
        words |= {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 3}
    words |= {d.split(".")[0] for d in domains}
    generic = {"app", "apps", "the", "inc", "llc", "ltd", "limited", "co", "corp", "games", "game", "studio",
               "studios", "labs", "tech", "technology", "technologies", "software", "mobile", "media",
               "pte", "and", "for", "with", "your", "free", "pro", "plus", "online", "group", "company"}
    return words - generic


def brand_match(handle: str, tokens: set[str]) -> bool:
    h = re.sub(r"[^a-z0-9]", "", handle.lower())
    return len(h) >= 3 and any(t in h or h in t for t in tokens)


def dns_records(fetch: Fetcher, name: str, rtype: str) -> list[str] | None:
    """Record data, [] for none, None when the lookup itself failed."""
    try:
        data = fetch.get_json(DNS_OVER_HTTPS.format(name=quote(name), type=rtype),
                              headers={"Accept": "application/dns-json"})
    except Exception:
        return None
    if data.get("Status") not in (0, 3):  # 0 NOERROR, 3 NXDOMAIN
        return None
    return [a["data"] for a in data.get("Answer", []) if a.get("type") == {"MX": 15, "A": 1}[rtype]]


def x_account_exists(fetch: Fetcher, handle: str) -> bool | None:
    page = fetch.get_page(X_OEMBED.format(url=quote(f"https://x.com/{handle}", safe="")))
    if page["status"] == 200:
        try:
            return "twitter-timeline" in json.loads(page["text"]).get("html", "")
        except ValueError:
            return None
    return False if page["status"] == 404 else None


def linkedin_page_exists(fetch: Fetcher, path: str) -> bool | None:
    if not path.startswith("company/"):
        return None  # personal profiles need a login to view
    page = fetch.get_page(f"https://www.linkedin.com/{path}")
    if page["status"] == 404:
        return False
    title = re.search(r"<title[^>]*>([^<]*)", page["text"] or "")
    return True if page["status"] == 200 and title and "|" in title.group(1) else None


def verify_email(fetch: Fetcher, contact: dict, domains: set[str], tokens: set[str]) -> dict:
    email = contact["value"]
    checks = {"syntax": bool(EMAIL.fullmatch(email))}
    domain = email.rsplit("@", 1)[-1]
    mx = dns_records(fetch, domain, "MX")
    checks["mail_server"] = None if mx is None else bool(mx) or bool(dns_records(fetch, domain, "A"))
    if registrable_domain(domain) in domains:
        relation = "first-party"
    elif domain in FREEMAIL:
        relation = "free mail"
    elif brand_match(registrable_domain(domain).split(".")[0], tokens):
        relation = "related domain"
    else:
        relation = "third party"
    checks["domain"] = relation

    if not checks["syntax"] or checks["mail_server"] is False:
        status, note = "rejected", "invalid address" if not checks["syntax"] else f"{domain} has no mail server"
    elif relation == "third party":
        # Privacy policies name their vendors (privacy@amazon.com, dpo@some-sdk.com); those aren't the developer.
        status, note = "rejected", f"{domain} is unrelated to the developer, likely a vendor named in the policy"
    elif checks["mail_server"] and relation == "first-party":
        status, note = "verified", f"on the developer's domain, {domain} accepts mail"
    else:
        status = "likely"
        note = {"free mail": "personal mailbox listed on an official page",
                "related domain": f"{domain} matches the developer's name but isn't its listed website"}.get(
                    relation, "mail server lookup failed")
    return {**contact, "checks": checks, "status": status, "note": note}


def verify_social(fetch: Fetcher, contact: dict, tokens: set[str], unmatched_of_type: int) -> dict:
    kind, value = contact["type"], contact["value"]
    handle = value.lstrip("@").split("/")[-1]
    exists = {"x": lambda: x_account_exists(fetch, handle),
              "linkedin": lambda: linkedin_page_exists(fetch, value),
              "threads": lambda: None}[kind]()
    matched = brand_match(handle, tokens)
    checks = {"exists": exists, "name_match": matched}

    if exists is False:
        status, note = "rejected", "profile does not exist"
    elif not matched and unmatched_of_type > MAX_UNMATCHED_PER_TYPE:
        status, note = "rejected", "one of many unrelated accounts on the page"
    elif exists and matched:
        status, note = "verified", "profile exists and matches the app or developer name"
    else:
        reasons = []
        if exists is None:
            reasons.append(f"{kind} profile existence can't be checked without login")
        if not matched:
            reasons.append("handle doesn't match the app or developer name")
        status, note = "likely", "; ".join(reasons)
    return {**contact, "checks": checks, "status": status, "note": note}


def verify(fetch: Fetcher, app: dict, discovered: dict) -> list[dict]:
    domains = owned_domains(app, discovered["official_urls"])
    tokens = name_tokens(app, domains)
    unmatched = {}
    for c in discovered["contacts"]:
        if c["type"] != "email" and not brand_match(c["value"].lstrip("@").split("/")[-1], tokens):
            unmatched[c["type"]] = unmatched.get(c["type"], 0) + 1

    results = []
    for c in discovered["contacts"]:
        if c["type"] == "email":
            results.append(verify_email(fetch, c, domains, tokens))
        else:
            results.append(verify_social(fetch, c, tokens, unmatched.get(c["type"], 0)))
    return results


STATUS_RANK = {"verified": 0, "likely": 1, "rejected": 2}


# Mailboxes for legal or data-protection requests: real, but the wrong door for an investor.
COMPLIANCE_MAILBOX = re.compile(r"^(privacy|dpo|gdpr|legal|abuse|security|dmca|copyright|compliance|data)[._-]?[a-z]*@")


def best_per_type(verified: list[dict]) -> dict[str, dict]:
    """The strongest non-rejected contact of each type."""
    def rank(c):
        compliance = c["type"] == "email" and bool(COMPLIANCE_MAILBOX.match(c["value"]))
        return STATUS_RANK[c["status"]], compliance, -len(c["found_on"])

    best = {}
    for c in sorted(verified, key=rank):
        if c["status"] != "rejected":
            best.setdefault(c["type"], c)
    return best
