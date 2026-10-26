from datetime import datetime, timezone

from scout.config import Thresholds
from scout.filter import big_publisher_match, classify, is_company_seller

NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)
T = Thresholds()


def app(**kw):
    return {"name": "Some App", "publisher_name": "Some Dev", "seller_name": "Jane Doe", "release_date": "2026-06-01T07:00:00Z",
            "monthly_revenue_usd": 5000, **kw}


def portfolio(n, first="2025-01-01T00:00:00Z"):
    return [{"releaseDate": first}] + [{"releaseDate": "2026-01-01T00:00:00Z"}] * (n - 1)


def test_company_markers():
    assert is_company_seller("OAKEVER GAMES PTE. LTD.")
    assert is_company_seller("Grand Games A.Ş.")
    assert is_company_seller("Partiful, Inc.")
    assert is_company_seller("Lux Optics Incorporated")
    assert is_company_seller("Trautmann & Dorre GbR")
    assert is_company_seller("MARSBY TEKNOLOJI ANONIM SIRKETI")
    assert is_company_seller("KAN ONLINE ENTERTAINMENT JOINT STOCK COMPANY")
    assert is_company_seller("株式会社ミクシィ")
    assert is_company_seller("騰訊科技有限公司")
    assert not is_company_seller("Jane Doe")
    assert not is_company_seller("Nguyen Van An")


def test_big_publisher_word_boundaries():
    assert big_publisher_match("Google LLC") == "google"
    assert big_publisher_match("Meta Platforms, Inc.") == "meta platforms"
    assert big_publisher_match("King.com Ltd.") == "king com"
    assert big_publisher_match("Hangzhou DeepSeek Artificial Intelligence Co., Ltd") == "deepseek"
    assert big_publisher_match("Pineapple Studio") is None
    assert big_publisher_match("Targeted Labs") is None


def test_individual_account_is_founder():
    result = classify(app(), portfolio(1), T, NOW)
    assert result["tier"] == "founder"
    assert result["individual_account"]


def test_small_young_company_is_founder():
    # Peeps: Kardomo, Inc., 4 apps, account about 1.3 years old.
    result = classify(app(name="Peeps", seller_name="Kardomo, Inc."), portfolio(4, first="2025-07-01T00:00:00Z"), T, NOW)
    assert result["tier"] == "founder"


def test_new_high_revenue_company_is_not_founder():
    result = classify(app(seller_name="EVOLENS TECHNOLOGY LIMITED", monthly_revenue_usd=500_000),
                      portfolio(1, first="2026-09-01T00:00:00Z"), T, NOW)
    assert result["tier"] == "small_company"
    assert "check who is behind it" in result["reasons"][0]


def test_ai_wrappers_excluded():
    for name in ["Chat GTP tiếng Việt - AI Chat", "ChatNow・Chatbot AI", "Chatbot App - AIアシスタント",
                 "Genora AI – Chat Bot Assistant", "Ask AI - Chat with GPT-5"]:
        result = classify(app(name=name), portfolio(1), T, NOW)
        assert result["tier"] == "excluded", name
        assert result["reasons"][0].startswith("generic AI chat wrapper"), name
    assert classify(app(name="BingBang: Daily Companion"), portfolio(1), T, NOW)["tier"] == "founder"


def test_older_company_is_small_company():
    result = classify(app(seller_name="Tiny Labs LLC"), portfolio(6, first="2021-01-01T00:00:00Z"), T, NOW)
    assert result["tier"] == "small_company"


def test_missing_seller_is_not_individual():
    result = classify(app(seller_name=None), None, T, NOW)
    assert result["tier"] == "small_company"
    assert not result["individual_account"]
    assert result["reasons"] == []


def test_exclusions_report_every_reason():
    result = classify(app(publisher_name="TikTok Ltd.", monthly_revenue_usd=10_000_000,
                          release_date="2018-01-01T00:00:00Z"), portfolio(40), T, NOW)
    assert result["tier"] == "excluded"
    assert len(result["reasons"]) == 4


def test_established_studio_excluded():
    result = classify(app(), portfolio(8, first="2015-03-01T00:00:00Z"), T, NOW)
    assert result["tier"] == "excluded"
    assert "8 apps" in result["reasons"][0]
