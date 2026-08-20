"""CLI: find local businesses without a website, ready to pitch.

Usage:
    python -m src.prospecting.cli --query "dentista" --location "São Paulo, SP" --output leads.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

from dotenv import load_dotenv

from src.prospecting.google_places import GooglePlacesError, find_leads_without_website

CSV_FIELDS = [
    "name",
    "phone",
    "address",
    "rating",
    "user_ratings_total",
    "maps_url",
    "place_id",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find local businesses without a website.")
    parser.add_argument("--query", required=True, help='Business category, e.g. "dentista"')
    parser.add_argument("--location", required=True, help='e.g. "São Paulo, SP"')
    parser.add_argument("--max-results", type=int, default=60, help="Max results to scan (up to 60)")
    parser.add_argument("--output", default="leads.csv", help="Path to write the CSV of leads")
    parser.add_argument("--api-key", default=None, help="Overrides GOOGLE_PLACES_API_KEY env var")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)

    api_key = args.api_key or os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        print(
            "Missing API key. Set GOOGLE_PLACES_API_KEY in your .env or pass --api-key.",
            file=sys.stderr,
        )
        return 1

    search_query = f"{args.query} em {args.location}"
    print(f"Buscando: {search_query!r} (até {args.max_results} resultados)...")

    try:
        leads = find_leads_without_website(search_query, api_key, max_results=args.max_results)
    except GooglePlacesError as exc:
        print(f"Erro na Places API: {exc}", file=sys.stderr)
        return 1

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for lead in leads:
            writer.writerow(
                {
                    "name": lead.name,
                    "phone": lead.phone or "",
                    "address": lead.address or "",
                    "rating": lead.rating if lead.rating is not None else "",
                    "user_ratings_total": lead.user_ratings_total or "",
                    "maps_url": lead.maps_url or "",
                    "place_id": lead.place_id,
                }
            )

    print(f"{len(leads)} leads sem site salvos em {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
