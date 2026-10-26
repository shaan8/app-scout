from dataclasses import dataclass

COUNTRIES = ["US", "TW", "JP", "KR", "SG", "HK", "IN", "VN"]

# iOS App Store genre ids. 0 is the overall chart.
CATEGORIES = {
    0: "Overall",
    6014: "Games",
    6005: "Social Networking",
    6016: "Entertainment",
    6008: "Photo & Video",
    6011: "Music",
    6004: "Sports",
    6013: "Health & Fitness",
    6012: "Lifestyle",
    6015: "Finance",
    6007: "Productivity",
    6017: "Education",
    6000: "Business",
}

CHARTS = ["free", "grossing", "paid"]


@dataclass(frozen=True)
class Thresholds:
    # Too far along for a pre-seed cheque: a worldwide monthly revenue bucket at or above this is out.
    max_monthly_revenue_usd: int = 1_000_000
    # An app this old is not an idea/MVP/pre-seed product.
    max_app_age_years: float = 4.0
    # A developer account with more apps than this is a studio or a corporate portfolio.
    max_portfolio_apps: int = 15
    # Many apps on an old account means an established studio, even under max_portfolio_apps.
    established_portfolio_apps: int = 6
    established_account_age_years: float = 6.0
    # Startups incorporate, so a company account this small and young still counts as founder-run.
    founder_max_apps: int = 5
    founder_max_account_age_years: float = 3.0
    # ...unless it is this new and already earning this much, the pattern of a publisher's launch entity.
    launch_entity_max_account_age_years: float = 2.0
    launch_entity_min_revenue_usd: int = 500_000


# Matched against publisher and seller names after lowercasing and stripping punctuation.
# Covers groups that the portfolio and age checks miss: new apps launched by large companies.
BIG_PUBLISHERS = [
    "google", "apple", "meta platforms", "instagram", "whatsapp", "facebook", "microsoft", "linkedin",
    "amazon", "netflix", "disney", "spotify", "uber", "airbnb", "paypal", "block inc", "cash app",
    "openai", "anthropic", "deepseek", "moonshot", "zhipu", "minimax", "stepfun", "iflytek", "mistral ai",
    "character ai", "x ai", "x corp", "perplexity", "snap inc", "pinterest", "reddit", "discord",
    "bytedance", "tiktok", "capcut", "lemon inc", "tencent", "netease", "alibaba", "alipay", "ant group",
    "baidu", "kuaishou", "kwai", "pdd", "temu", "shein", "xiaohongshu", "meituan", "jd com",
    "line corporation", "ly corporation", "naver", "kakao", "samsung", "coupang", "viva republica",
    "rakuten", "mercari", "dena", "cyberagent", "cygames", "mixi", "gungho", "sony", "nintendo",
    "bandai namco", "square enix", "sega", "konami", "capcom", "koei tecmo", "ncsoft", "nexon",
    "netmarble", "krafton", "com2us", "smilegate", "pearl abyss", "shift up", "garena", "sea limited",
    "shopee", "grabtaxi", "grab holdings", "gojek", "paytm", "phonepe", "flipkart", "reliance", "jio platforms", "zomato", "swiggy",
    "vng", "zalo", "supercell", "king com", "activision", "blizzard", "electronic arts",
    "take two", "zynga", "rockstar", "ubisoft", "epic games", "roblox", "niantic", "playtika", "scopely",
    "moon active", "playrix", "miniclip", "mihoyo", "hoyoverse", "cognosphere", "lilith", "funplus",
    "century games", "habby", "dream games", "peak games", "rovio", "voodoo", "homa games", "saygames",
    "azur games", "supersonic", "unity technologies", "lion studios", "applovin", "tap4fun", "igg",
    "37games", "yostar", "kepler interactive", "papergames", "kuro games", "level infinite", "walmart", "target corporation", "mcdonald",
    "starbucks", "nike", "adidas", "capital one", "jpmorgan chase", "bank of america", "wells fargo", "robinhood",
    "coinbase", "binance", "duolingo", "match group", "tinder", "bumble", "canva", "adobe", "picsart",
    "bending spoons", "lightricks", "meitu", "inshot", "truecaller", "the college board",
]
