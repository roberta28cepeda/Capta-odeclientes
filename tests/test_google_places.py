from unittest.mock import MagicMock, patch

from src.prospecting.google_places import (
    GooglePlacesError,
    Lead,
    find_leads_without_website,
    get_place_details,
    search_place_ids,
)


def _mock_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_search_place_ids_single_page():
    session = MagicMock()
    session.get.return_value = _mock_response(
        {
            "status": "OK",
            "results": [{"place_id": "p1"}, {"place_id": "p2"}],
        }
    )

    result = search_place_ids("dentista em SP", "fake-key", max_results=10, session=session)

    assert result == ["p1", "p2"]
    session.get.assert_called_once()


def test_search_place_ids_follows_pagination_until_max_results():
    session = MagicMock()
    page1 = _mock_response(
        {
            "status": "OK",
            "results": [{"place_id": f"p{i}"} for i in range(20)],
            "next_page_token": "token-2",
        }
    )
    page2 = _mock_response(
        {
            "status": "OK",
            "results": [{"place_id": f"q{i}"} for i in range(20)],
        }
    )
    session.get.side_effect = [page1, page2]

    with patch("src.prospecting.google_places.time.sleep"):
        result = search_place_ids("dentista em SP", "fake-key", max_results=25, session=session)

    assert len(result) == 25
    assert session.get.call_count == 2


def test_search_place_ids_raises_on_bad_status():
    session = MagicMock()
    session.get.return_value = _mock_response(
        {"status": "REQUEST_DENIED", "error_message": "bad key"}
    )

    try:
        search_place_ids("x", "bad-key", session=session)
        assert False, "expected GooglePlacesError"
    except GooglePlacesError as exc:
        assert "REQUEST_DENIED" in str(exc)


def test_get_place_details_maps_fields():
    session = MagicMock()
    session.get.return_value = _mock_response(
        {
            "status": "OK",
            "result": {
                "name": "Padaria Central",
                "formatted_address": "Rua X, 123",
                "formatted_phone_number": "(11) 1234-5678",
                "rating": 4.5,
                "user_ratings_total": 10,
                "url": "https://maps.google.com/?cid=1",
            },
        }
    )

    lead = get_place_details("p1", "fake-key", session=session)

    assert lead.name == "Padaria Central"
    assert lead.website is None
    assert lead.has_website is False


def test_lead_has_website_true_when_present():
    lead = Lead(
        place_id="p1",
        name="X",
        address=None,
        phone=None,
        rating=None,
        user_ratings_total=None,
        maps_url=None,
        website="https://example.com",
    )
    assert lead.has_website is True


def test_find_leads_without_website_filters_results():
    with patch("src.prospecting.google_places.search_place_ids", return_value=["p1", "p2"]):
        leads_by_id = {
            "p1": Lead("p1", "Com site", None, None, None, None, None, "https://a.com"),
            "p2": Lead("p2", "Sem site", None, None, None, None, None, None),
        }
        with patch(
            "src.prospecting.google_places.get_place_details",
            side_effect=lambda pid, api_key, session=None: leads_by_id[pid],
        ):
            leads = find_leads_without_website("padaria em SP", "fake-key")

    assert len(leads) == 1
    assert leads[0].name == "Sem site"
