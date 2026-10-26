import json

from scout.contacts import extract
from scout.verify import best_per_type, registrable_domain, verify

PAGE = """
<a href="mailto:team@playpeeps.app">Email us</a>  Contact: Hello@PlayPeeps.app.
<img src="logo@2x.png"> noreply@playpeeps.app  you@example.com
<a href="https://x.com/PlayPeepsApp">X</a> <a href="https://twitter.com/intent/tweet?text=hi">Share</a>
<a href="https://www.linkedin.com/company/kardomo/">LinkedIn</a> <a href="https://framer.com">Made in Framer</a>
<a href="https://www.threads.com/@playpeeps.app">Threads</a> <a href="https://twitter.com/framer">framer</a>
"""


class FakeFetcher:
    """DNS answers and profile pages keyed by name, so verification runs without the network."""

    def __init__(self, mx=(), a=(), x_accounts=(), linkedin=()):
        self.mx, self.a, self.x_accounts, self.linkedin = set(mx), set(a), set(x_accounts), set(linkedin)

    def get_json(self, url, headers=None):
        name = url.split("name=")[1].split("&")[0]
        rtype = url.rsplit("type=", 1)[1]
        has = name in (self.mx if rtype == "MX" else self.a)
        return {"Status": 0, "Answer": [{"type": 15 if rtype == "MX" else 1, "data": "x"}] if has else []}

    def get_page(self, url):
        if "publish.twitter.com" in url:
            handle = url.rsplit("%2F", 1)[1]
            if handle in self.x_accounts:
                return {"status": 200, "text": json.dumps({"html": '<a class="twitter-timeline">'})}
            return {"status": 404, "text": ""}
        if "linkedin.com/company/" in url:
            slug = url.rsplit("/", 1)[1]
            return ({"status": 200, "text": f"<title>{slug} | LinkedIn</title>"} if slug in self.linkedin
                    else {"status": 404, "text": ""})
        raise AssertionError(url)


APP = {"name": "Peeps", "seller_name": "Kardomo, Inc.", "publisher_name": "Kardomo, Inc.",
       "app_url": "https://apps.apple.com/tw/app/id6753601581"}
OFFICIAL = [{"url": "https://playpeeps.app", "source": "App Store lookup", "kind": "website"}]


def contacts_of(*items):
    return {"official_urls": OFFICIAL,
            "contacts": [{"type": t, "value": v, "url": "", "found_on": ["https://playpeeps.app"]} for t, v in items]}


def test_extract_keeps_developer_contacts_and_drops_noise():
    found = {(c["type"], c["value"]) for c in extract({"text": PAGE})}
    assert found == {
        ("email", "team@playpeeps.app"), ("email", "hello@playpeeps.app"),
        ("x", "@PlayPeepsApp"), ("linkedin", "company/kardomo"), ("threads", "@playpeeps.app"),
    }


def test_registrable_domain():
    assert registrable_domain("www.shop.example.com.tw") == "example.com.tw"
    assert registrable_domain("playpeeps.app") == "playpeeps.app"


def test_first_party_email_with_mail_server_is_verified():
    [c] = verify(FakeFetcher(mx={"playpeeps.app"}), APP, contacts_of(("email", "team@playpeeps.app")))
    assert c["status"] == "verified"


def test_email_domain_without_mail_server_is_rejected():
    [c] = verify(FakeFetcher(), APP, contacts_of(("email", "team@playpeeps.app")))
    assert c["status"] == "rejected"


def test_free_mail_is_likely_not_verified():
    [c] = verify(FakeFetcher(mx={"gmail.com"}), APP, contacts_of(("email", "kardomo.dev@gmail.com")))
    assert c["status"] == "likely"


def test_vendor_email_in_privacy_policy_is_rejected():
    found = verify(FakeFetcher(mx={"amazon.com", "kardomo.com"}), APP,
                   contacts_of(("email", "privacy@amazon.com"), ("email", "hello@kardomo.com")))
    assert {c["value"]: c["status"] for c in found} == {"privacy@amazon.com": "rejected", "hello@kardomo.com": "likely"}


def test_existing_matching_x_account_is_verified_and_missing_one_rejected():
    found = verify(FakeFetcher(x_accounts={"PlayPeepsApp"}), APP,
                   contacts_of(("x", "@PlayPeepsApp"), ("x", "@peeps_old")))
    assert {c["value"]: c["status"] for c in found} == {"@PlayPeepsApp": "verified", "@peeps_old": "rejected"}


def test_linkedin_company_page_checked_threads_left_likely():
    found = verify(FakeFetcher(linkedin={"kardomo"}), APP,
                   contacts_of(("linkedin", "company/kardomo"), ("threads", "@playpeeps.app")))
    assert {c["type"]: c["status"] for c in found} == {"linkedin": "verified", "threads": "likely"}


def test_page_of_unrelated_accounts_is_rejected():
    handles = [("x", f"@someone{i}") for i in range(4)]
    found = verify(FakeFetcher(x_accounts={f"someone{i}" for i in range(4)}), APP, contacts_of(*handles))
    assert {c["status"] for c in found} == {"rejected"}


def test_best_contact_skips_compliance_mailbox():
    found = verify(FakeFetcher(mx={"playpeeps.app"}), APP,
                   contacts_of(("email", "privacy@playpeeps.app"), ("email", "hi@playpeeps.app")))
    assert best_per_type(found)["email"]["value"] == "hi@playpeeps.app"
