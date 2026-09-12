"""Contract for the EulerStream regional gift-catalog sync.

Verified against the live API on 2026-09-02:

* ``GET /webcast/gifts?region=XX&webcast_language=en&redirect=false`` returns
  ``{"code":200,"url":"<signed R2 url>"}``; the blob behind that URL is
  ``{"data": {"gifts": [...], ...}}`` in the same shape as TikTok's own
  ``/gift/list/``, icons on ``p16-webcast.tiktokcdn.com``.
* Unioning 20 regions yields 1767 unique gifts vs 701 in one room panel, and
  recovers the region-locked ``Game Controller`` (6581 / 7569).
* ``RU`` and ``IN`` return HTTP 422 — a partial sync must still succeed.
* Plain ``urllib`` gets 403 ``error code: 1010`` from Cloudflare; a browser
  User-Agent is required.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gift_catalog
import gift_catalog_sync


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class FakeClient:
    """Stands in for httpx.Client: records calls, replays scripted responses."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        for matcher, response in self.routes:
            if matcher(url, params or {}):
                return response() if callable(response) else response
        return FakeResponse(404, {"error": "unrouted"})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def gift_row(gift_id, name, coins, icon="https://p16-webcast.tiktokcdn.com/img/x~tplv-obj.webp"):
    return {
        "id": gift_id,
        "name": name,
        "diamond_count": coins,
        "icon": {"url_list": [icon]},
        "image": {"url_list": [icon]},
    }


def signed_url_route(region, signed):
    def matcher(url, params):
        return url.endswith("/webcast/gifts") and params.get("region") == region
    return matcher, FakeResponse(200, {"code": 200, "url": signed})


def blob_route(signed, gifts):
    def matcher(url, params):
        return url == signed
    return matcher, FakeResponse(200, {"data": {"gifts": gifts}})


class TestRegionSync(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "available_gifts.json")

    def test_single_region_populates_the_catalog(self):
        client = FakeClient([
            signed_url_route("ID", "https://blob/id.json"),
            blob_route("https://blob/id.json", [gift_row(6064, "GG", 1)]),
        ])

        stats = gift_catalog_sync.sync_regions(
            self.path, api_key="k", regions=["ID"], client=client)

        self.assertEqual(stats["added"], 1)
        self.assertEqual(stats["regions_ok"], 1)
        self.assertEqual(stats["regions_failed"], 0)
        self.assertEqual(gift_catalog.load_catalog(self.path)[0]["id"], 6064)

    def test_union_across_regions_recovers_a_region_locked_gift(self):
        """The Game Controller case: absent from the room panel, present in US."""
        client = FakeClient([
            signed_url_route("ID", "https://blob/id.json"),
            blob_route("https://blob/id.json", [gift_row(6064, "GG", 1)]),
            signed_url_route("US", "https://blob/us.json"),
            blob_route("https://blob/us.json", [
                gift_row(6064, "GG", 1),
                gift_row(6581, "Game Controller", 100),
            ]),
        ])

        stats = gift_catalog_sync.sync_regions(
            self.path, api_key="k", regions=["ID", "US"], client=client)

        ids = {e["id"] for e in gift_catalog.load_catalog(self.path)}
        self.assertEqual(ids, {6064, 6581})
        self.assertEqual(stats["added"], 2)
        self.assertEqual(stats["regions_ok"], 2)

    def test_a_failing_region_does_not_abort_the_sync(self):
        """RU/IN really do return 422; the other regions must still land."""
        client = FakeClient([
            (lambda u, p: u.endswith("/webcast/gifts") and p.get("region") == "RU",
             FakeResponse(422, {"code": 422, "message": "unsupported region"})),
            signed_url_route("US", "https://blob/us.json"),
            blob_route("https://blob/us.json", [gift_row(6581, "Game Controller", 100)]),
        ])

        stats = gift_catalog_sync.sync_regions(
            self.path, api_key="k", regions=["RU", "US"], client=client)

        self.assertEqual(stats["regions_ok"], 1)
        self.assertEqual(stats["regions_failed"], 1)
        self.assertEqual(stats["added"], 1)
        self.assertIn("RU", stats["failed_regions"])

    def test_blob_fetch_failure_is_counted_as_a_failed_region(self):
        client = FakeClient([
            signed_url_route("US", "https://blob/us.json"),
            (lambda u, p: u == "https://blob/us.json", FakeResponse(403, {"error": "expired"})),
        ])

        stats = gift_catalog_sync.sync_regions(
            self.path, api_key="k", regions=["US"], client=client)

        self.assertEqual(stats["regions_ok"], 0)
        self.assertEqual(stats["regions_failed"], 1)

    def test_sync_sends_the_api_key_and_a_browser_user_agent(self):
        """Cloudflare answers 403 error 1010 to a bare urllib UA — verified."""
        headers = gift_catalog_sync.build_headers("secret-key")

        self.assertEqual(headers["x-api-key"], "secret-key")
        self.assertIn("Mozilla/5.0", headers["User-Agent"])

    def test_sync_without_an_api_key_reports_a_reason_and_writes_nothing(self):
        stats = gift_catalog_sync.sync_regions(self.path, api_key="", regions=["US"], client=None)

        self.assertEqual(stats["regions_ok"], 0)
        self.assertIn("api key", stats["error"].lower())
        self.assertEqual(gift_catalog.load_catalog(self.path), [])

    def test_existing_learned_gifts_survive_a_region_sync(self):
        """A sync must never wipe a creator-exclusive gift like Super GG."""
        gift_catalog.learn_gift(self.path, gift_id=12988, name="Super GG",
                                diamond_count=100, icon_url="https://cdn/s.webp")
        client = FakeClient([
            signed_url_route("US", "https://blob/us.json"),
            blob_route("https://blob/us.json", [gift_row(6581, "Game Controller", 100)]),
        ])

        gift_catalog_sync.sync_regions(self.path, api_key="k", regions=["US"], client=client)

        ids = {e["id"] for e in gift_catalog.load_catalog(self.path)}
        self.assertIn(12988, ids)
        self.assertIn(6581, ids)

    def test_default_region_list_covers_the_verified_productive_regions(self):
        regions = gift_catalog_sync.DEFAULT_REGIONS

        self.assertIn("ID", regions)   # Khito's own region
        self.assertIn("US", regions)
        self.assertIn("GB", regions)   # largest verified catalog (787)
        self.assertNotIn("RU", regions)  # verified HTTP 422
        self.assertNotIn("IN", regions)  # verified HTTP 422


class TestEulerCatalogSync(unittest.TestCase):
    """Third source: Euler's ClickHouse gift catalog, 2783 rows, paginated 100/page.

    Covers gifts TikTok has retired from every live panel — Khito received
    ``Spirit of 45`` (9047), ``Live Up`` (1189923), ``Fighting`` (15957) and
    ``Spark ring`` (1189924), none of which appear in any of the 20 regional
    panels. Verified 2026-09-02: the route ignores pageSize above 100 and does
    not count against hourly/daily rate limits.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "available_gifts.json")

    def catalog_client(self, pages):
        """pages: list of gift-row lists, one per page (1-indexed)."""
        def matcher(url, params):
            return url.endswith("/webcast/gifts/catalog")

        def respond():
            page = int(self.last_page)
            rows = pages[page - 1] if 0 < page <= len(pages) else []
            return FakeResponse(200, {
                "code": 200, "gifts": rows, "total": sum(len(p) for p in pages),
                "pageNumber": page, "pageSize": 100, "totalPages": len(pages),
            })

        client = FakeClient([(matcher, respond)])
        original_get = client.get

        def tracking_get(url, params=None, headers=None):
            self.last_page = (params or {}).get("pageNumber", 1)
            return original_get(url, params=params, headers=headers)

        client.get = tracking_get
        self.last_page = 1
        return client

    def euler_row(self, gift_id, name, coins):
        return {"giftId": gift_id, "giftName": name, "diamondCount": coins,
                "giftType": 1,
                "imageUri": "https://assets.cdn.eulerstream.com/gifts/images/abc?fpsig=v1"}

    def test_catalog_sync_walks_every_page(self):
        client = self.catalog_client([
            [self.euler_row(9047, "Spirit of 45", 1)],
            [self.euler_row(15957, "Fighting", 1)],
        ])

        stats = gift_catalog_sync.sync_euler_catalog(self.path, api_key="k", client=client)

        self.assertEqual(stats["added"], 2)
        self.assertEqual(stats["pages"], 2)
        ids = {e["id"] for e in gift_catalog.load_catalog(self.path)}
        self.assertEqual(ids, {9047, 15957})

    def test_catalog_sync_stores_name_and_price_without_a_broken_icon(self):
        """Euler's image host 403s server-side, so no icon must be stored."""
        client = self.catalog_client([[self.euler_row(9047, "Spirit of 45", 1)]])

        gift_catalog_sync.sync_euler_catalog(self.path, api_key="k", client=client)

        entry = gift_catalog.load_catalog(self.path)[0]
        self.assertEqual(entry["name"], "spirit of 45")
        self.assertEqual(entry["diamond_count"], 1)
        self.assertEqual(entry["icon"], "")

    def test_catalog_sync_never_overwrites_a_real_icon(self):
        gift_catalog.learn_gift(self.path, gift_id=9047, name="Spirit of 45",
                                diamond_count=1,
                                icon_url="https://p16-webcast.tiktokcdn.com/img/s.webp")
        client = self.catalog_client([[self.euler_row(9047, "Spirit of 45", 1)]])

        gift_catalog_sync.sync_euler_catalog(self.path, api_key="k", client=client)

        self.assertEqual(gift_catalog.load_catalog(self.path)[0]["icon"],
                         "https://p16-webcast.tiktokcdn.com/img/s.webp")

    def test_catalog_sync_without_a_key_reports_an_error(self):
        stats = gift_catalog_sync.sync_euler_catalog(self.path, api_key="", client=None)
        self.assertIn("api key", stats["error"].lower())
        self.assertEqual(stats["added"], 0)

    def test_catalog_sync_stops_on_an_http_error_but_keeps_earlier_pages(self):
        def matcher(url, params):
            return url.endswith("/webcast/gifts/catalog")

        calls = {"n": 0}

        def respond():
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeResponse(200, {
                    "code": 200, "gifts": [self.euler_row(9047, "Spirit of 45", 1)],
                    "totalPages": 3,
                })
            return FakeResponse(429, {"code": 429, "message": "Too Many Requests"})

        stats = gift_catalog_sync.sync_euler_catalog(
            self.path, api_key="k", client=FakeClient([(matcher, respond)]))

        self.assertEqual(stats["added"], 1)
        self.assertTrue(stats["error"])
        self.assertEqual(len(gift_catalog.load_catalog(self.path)), 1)

    def test_catalog_sync_respects_the_hundred_row_page_cap(self):
        """pageSize above 100 is silently clamped by the API — verified."""
        self.assertLessEqual(gift_catalog_sync.CATALOG_PAGE_SIZE, 100)


class TestRegionSyncIdempotence(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "available_gifts.json")

    def test_sync_is_idempotent(self):
        routes = [
            signed_url_route("US", "https://blob/us.json"),
            blob_route("https://blob/us.json", [gift_row(6581, "Game Controller", 100)]),
        ]
        gift_catalog_sync.sync_regions(self.path, api_key="k", regions=["US"],
                                       client=FakeClient(routes))
        stats = gift_catalog_sync.sync_regions(self.path, api_key="k", regions=["US"],
                                               client=FakeClient(routes))

        self.assertEqual(stats["added"], 0)
        self.assertEqual(stats["updated"], 0)
        self.assertEqual(len(gift_catalog.load_catalog(self.path)), 1)

    def test_blob_shapes_without_a_data_wrapper_are_accepted(self):
        """Defensive: the R2 blob has been seen both wrapped and bare."""
        client = FakeClient([
            signed_url_route("US", "https://blob/us.json"),
            (lambda u, p: u == "https://blob/us.json",
             FakeResponse(200, {"gifts": [gift_row(6581, "Game Controller", 100)]})),
        ])

        stats = gift_catalog_sync.sync_regions(
            self.path, api_key="k", regions=["US"], client=client)

        self.assertEqual(stats["added"], 1)


if __name__ == "__main__":
    unittest.main()
