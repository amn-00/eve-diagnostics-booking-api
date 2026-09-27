def test_admin_can_create_centre_and_offer_test(client, catalog):
    r = client.get(f"/centres/{catalog['centre']['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Eve Diagnostics Sector 62"
    assert len(body["tests"]) == 1
    assert body["tests"][0]["test"]["name"] == "Complete Blood Count"
    assert body["tests"][0]["price"] == "499.00"


def test_regular_user_cannot_manage_centres(client, user_headers):
    r = client.post(
        "/centres/", json={"name": "X", "city": "Delhi", "address": "Y"}, headers=user_headers
    )
    assert r.status_code == 403
    assert client.post("/tests/", json={"name": "X-Ray"}, headers=user_headers).status_code == 403


def test_anonymous_cannot_manage_centres(client):
    r = client.post("/centres/", json={"name": "X", "city": "Delhi", "address": "Y"})
    assert r.status_code == 401


def test_duplicate_centre_in_same_city(client, admin_headers, catalog):
    r = client.post(
        "/centres/",
        json={"name": "Eve Diagnostics Sector 62", "city": "Noida", "address": "somewhere else"},
        headers=admin_headers,
    )
    assert r.status_code == 409


def test_cannot_offer_same_test_twice(client, admin_headers, catalog):
    r = client.post(
        f"/centres/{catalog['centre']['id']}/tests",
        json={"test_id": catalog["test"]["id"], "price": "599.00"},
        headers=admin_headers,
    )
    assert r.status_code == 409


def test_offer_unknown_test_or_centre(client, admin_headers, catalog):
    r = client.post(
        f"/centres/{catalog['centre']['id']}/tests",
        json={"test_id": 9999, "price": "100.00"},
        headers=admin_headers,
    )
    assert r.status_code == 404
    r = client.post(
        "/centres/9999/tests", json={"test_id": catalog["test"]["id"], "price": "100.00"}, headers=admin_headers
    )
    assert r.status_code == 404


def test_price_must_be_positive(client, admin_headers, catalog):
    for bad_price in ["0", "-10", "12.345"]:
        r = client.post(
            f"/centres/{catalog['centre']['id']}/tests",
            json={"test_id": catalog["not_offered_test"]["id"], "price": bad_price},
            headers=admin_headers,
        )
        assert r.status_code == 422, bad_price


def test_list_centres_filters_and_pagination(client, admin_headers, catalog):
    for i in range(3):
        client.post(
            "/centres/",
            json={"name": f"Lab {i}", "city": "Delhi", "address": f"Street {i}"},
            headers=admin_headers,
        )

    r = client.get("/centres/", params={"city": "delhi", "limit": 2})
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2

    r = client.get("/centres/", params={"test_id": catalog["test"]["id"]})
    assert [c["name"] for c in r.json()["items"]] == ["Eve Diagnostics Sector 62"]

    assert client.get("/centres/", params={"limit": 500}).status_code == 422


def test_get_missing_centre(client):
    assert client.get("/centres/12345").status_code == 404


def test_search_tests(client, catalog):
    r = client.get("/tests/", params={"q": "blood"})
    assert [t["name"] for t in r.json()["items"]] == ["Complete Blood Count"]
