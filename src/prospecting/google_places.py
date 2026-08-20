"""Client for finding local businesses via the Google Places API (legacy)."""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

DETAIL_FIELDS = "name,formatted_address,formatted_phone_number,website,rating,user_ratings_total,url"

# Google requires a short delay before a next_page_token becomes valid.
NEXT_PAGE_DELAY_SECONDS = 2

RETRYABLE_STATUSES = {"OK", "ZERO_RESULTS"}


class GooglePlacesError(RuntimeError):
    """Raised when the Places API returns a non-recoverable status."""


@dataclass
class Lead:
    place_id: str
    name: str
    address: str | None
    phone: str | None
    rating: float | None
    user_ratings_total: int | None
    maps_url: str | None
    website: str | None

    @property
    def has_website(self) -> bool:
        return bool(self.website)


def search_place_ids(
    query: str,
    api_key: str,
    max_results: int = 60,
    session: requests.Session | None = None,
) -> list[str]:
    """Return up to `max_results` place_ids matching a free-text query.

    The Places Text Search endpoint returns at most 20 results per page and
    up to 3 pages (60 results) total.
    """
    session = session or requests.Session()
    place_ids: list[str] = []
    params = {"query": query, "key": api_key}

    while len(place_ids) < max_results:
        response = session.get(TEXT_SEARCH_URL, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")

        if status not in RETRYABLE_STATUSES:
            raise GooglePlacesError(
                f"Places text search failed: {status} - {payload.get('error_message', '')}"
            )

        for result in payload.get("results", []):
            place_ids.append(result["place_id"])
            if len(place_ids) >= max_results:
                break

        next_page_token = payload.get("next_page_token")
        if not next_page_token or len(place_ids) >= max_results:
            break

        # The token isn't immediately usable; Google needs a moment to activate it.
        time.sleep(NEXT_PAGE_DELAY_SECONDS)
        params = {"pagetoken": next_page_token, "key": api_key}

    return place_ids


def get_place_details(
    place_id: str,
    api_key: str,
    session: requests.Session | None = None,
) -> Lead:
    session = session or requests.Session()
    params = {"place_id": place_id, "fields": DETAIL_FIELDS, "key": api_key}
    response = session.get(DETAILS_URL, params=params, timeout=10)
    response.raise_for_status()
    payload = response.json()
    status = payload.get("status")

    if status != "OK":
        raise GooglePlacesError(
            f"Places details failed for {place_id}: {status} - {payload.get('error_message', '')}"
        )

    result = payload.get("result", {})
    return Lead(
        place_id=place_id,
        name=result.get("name", ""),
        address=result.get("formatted_address"),
        phone=result.get("formatted_phone_number"),
        rating=result.get("rating"),
        user_ratings_total=result.get("user_ratings_total"),
        maps_url=result.get("url"),
        website=result.get("website"),
    )


def find_leads_without_website(
    query: str,
    api_key: str,
    max_results: int = 60,
) -> list[Lead]:
    """Search for businesses matching `query` and return only those with no website."""
    session = requests.Session()
    place_ids = search_place_ids(query, api_key, max_results=max_results, session=session)
    leads = [get_place_details(pid, api_key, session=session) for pid in place_ids]
    return [lead for lead in leads if not lead.has_website]
