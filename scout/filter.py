"""Decide whether an app looks founder-built or comes from an established company.

Every exclusion carries a reason string so a reviewer can overrule the filter.
"""

import re
from datetime import datetime, timezone

from .config import BIG_PUBLISHERS, Thresholds

# Legal-entity markers. Apple shows a person's own name as the seller on individual developer
# accounts, so a seller name without any of these is a strong solo-founder signal.
COMPANY_MARKERS = re.compile(
    r"\b(inc|incorporated|llc|l l c|ltd|limited|co|corp|corporation|company|gmbh|ag|sa|sas|sarl|srl|spa|bv|nv|"
    r"pte|pty|plc|oy|oyj|asa|aps|kk|lp|llp|pvt|jsc|tnhh|cổ phần|a ş|sro|zrt|kft|anonim sirketi|anonim şirketi|ltd sti|ltd şti|gbr|ug|kg|ohg|joint stock|ltda|eireli|bhd|sdn|tbk|pt)\b"
    r"|株式会社|有限会社|合同会社|有限公司|股份|公司|주식회사"
)
# Generic AI-chat apps riding on a model brand. The ICP rules out thin ChatGPT wrappers.
AI_WRAPPER = re.compile(
    r"\b(chat ?g[pt]{2}|gpt|openai|chat ?bot|ai chat|chat ai|ask ai|ai assistant)\b"
    r"|ai ?(アシスタント|チャット|助手|聊天|챗봇|비서)"
)
_BIG = re.compile(r"\b(" + "|".join(re.escape(n) for n in BIG_PUBLISHERS) + r")\b")


def normalize(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", name.lower())).strip()


def is_company_seller(seller: str) -> bool:
    return bool(COMPANY_MARKERS.search(normalize(seller)))


def big_publisher_match(*names: str) -> str | None:
    for name in names:
        if name and (m := _BIG.search(normalize(name))):
            return m.group(1)
    return None


def years_since(iso_date: str | None, now: datetime) -> float | None:
    if not iso_date:
        return None
    then = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    return (now - then).days / 365.25


def classify(app: dict, portfolio: list[dict] | None, t: Thresholds, now: datetime | None = None) -> dict:
    """Return {"tier": "founder" | "small_company" | "excluded", "reasons": [...], ...facts}.

    `app` needs: publisher_name, seller_name, release_date, monthly_revenue_usd.
    `portfolio` is the developer's App Store apps; None when the lookup failed.
    """
    now = now or datetime.now(timezone.utc)
    reasons = []

    if match := big_publisher_match(app["publisher_name"], app.get("seller_name")):
        reasons.append(f"known large publisher ({match})")

    if m := AI_WRAPPER.search(normalize(app.get("name") or "")):
        reasons.append(f"generic AI chat wrapper ({m.group(0)})")

    revenue = app.get("monthly_revenue_usd")
    if revenue is not None and revenue >= t.max_monthly_revenue_usd:
        reasons.append(f"monthly revenue bucket starts at ${revenue:,}")

    app_age = years_since(app.get("release_date"), now)
    if app_age is not None and app_age > t.max_app_age_years:
        reasons.append(f"app released {app_age:.1f} years ago")

    portfolio_size = len(portfolio) if portfolio is not None else None
    account_age = None
    if portfolio:
        account_age = max(years_since(p.get("releaseDate"), now) or 0 for p in portfolio)
        if portfolio_size > t.max_portfolio_apps:
            reasons.append(f"developer has {portfolio_size} apps")
        elif portfolio_size >= t.established_portfolio_apps and account_age > t.established_account_age_years:
            reasons.append(f"developer has {portfolio_size} apps, first released {account_age:.1f} years ago")

    facts = {"portfolio_size": portfolio_size,
             "account_age_years": round(account_age, 1) if account_age is not None else None,
             "app_age_years": round(app_age, 1) if app_age is not None else None,
             "individual_account": bool(app.get("seller_name")) and not is_company_seller(app["seller_name"])}

    if reasons:
        return {"tier": "excluded", "reasons": reasons, **facts}

    if facts["individual_account"]:
        return {"tier": "founder", "reasons": ["individual developer account"], **facts}
    if account_age is None or portfolio_size > t.founder_max_apps or account_age > t.founder_max_account_age_years:
        return {"tier": "small_company", "reasons": [], **facts}
    # Big publishers launch games through fresh one-off entities that buy installs from day one,
    # so a new company account that is already earning a lot is more likely backed than founder-run.
    if account_age <= t.launch_entity_max_account_age_years and (revenue or 0) >= t.launch_entity_min_revenue_usd:
        return {"tier": "small_company",
                "reasons": [f"account {account_age:.1f} years old already at ${revenue:,}+/month; check who is behind it"],
                **facts}
    return {"tier": "founder", "reasons": [f"young company account ({portfolio_size} app(s), {account_age:.1f} years)"],
            **facts}
