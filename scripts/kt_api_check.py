"""Read-only contract audit by default. --mutate uses one disposable campaign."""
import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from dotenv import dotenv_values


def client_from_env(path):
    credentials = dotenv_values(path)
    base = credentials.get("KT_BASE_URL") or ""
    key = credentials.get("KT_API_KEY")
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or not key):
        raise ValueError("Expected an HTTPS tracker origin and an API key in the env file")
    print("Tracker:", parsed.hostname)
    return httpx.Client(base_url=base.rstrip("/") + "/admin_api/v1/",
                        headers={"Api-Key": key}, timeout=15)


def probe(client, method, path, *, label=None, **kwargs):
    response = client.request(method, path, **kwargs)
    print(label or f"{method} {path}", response.status_code)
    if not response.is_success or not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def items(data):
    return data if isinstance(data, list) else (data or {}).get("items", [])


def describe_report(data):
    if isinstance(data, dict):
        print("  meta:", data.get("meta"), "row fields:",
              sorted({key for row in data.get("rows", []) if isinstance(row, dict) for key in row}),
              "rows:", len(data.get("rows", [])))


def audit(client):
    today = date.today()
    period = {"from": (today - timedelta(days=6)).isoformat(), "to": today.isoformat()}
    describe_report(probe(client, "POST", "report/build", json={
        "range": period, "group_by": ["offer_id"]}))
    describe_report(probe(client, "GET", "report/build",
                          params={**period, "group_by[]": "offer_id"}))
    describe_report(probe(client, "POST", "report/build", label="POST report with dimensions",
                          json={"range": period, "dimensions": ["offer_id", "day"],
                                "measures": ["clicks"]}))
    campaign_data = probe(client, "GET", "campaigns", params={"limit": 5})
    campaigns = items(campaign_data)
    if campaigns:
        cid = campaigns[0]["id"]
        for path, params in [(f"campaigns/{cid}/streams", {}), ("streams", {"campaign_id": cid})]:
            streams = items(probe(client, "GET", path, params=params, label=f"GET {path.replace(str(cid), '{id}')}"))
            if streams:
                print("  stream fields:", sorted(streams[0]))
    offer_data = probe(client, "GET", "offers", params={"limit": 5})
    offers = items(offer_data)
    print("Accessible offers in sample:", len(offers))
    if offers:
        offer = probe(client, "GET", f"offers/{offers[0]['id']}", label="GET one complete offer")
        if isinstance(offer, dict):
            print("  offer fields and types:", {k: type(v).__name__ for k, v in sorted(offer.items())})
            print("  lifecycle values:", {k: offer[k] for k in ("state", "status") if k in offer})
    if campaign_data is None or offer_data is None:
        raise RuntimeError("Unable to read the tracker contract")


def name_for_check():
    return f"wrappertest-{datetime.now(timezone.utc):%Y%m%d}-{uuid4().hex[:8]}"


def clean_campaign(client, campaign_id, name):
    current = client.get(f"campaigns/{campaign_id}")
    if not current.is_success or current.json().get("name") != name:
        raise RuntimeError(f"Unable to confirm ownership for cleanup: {name}")
    deleted = client.delete(f"campaigns/{campaign_id}")
    after = client.get(f"campaigns/{campaign_id}")
    listing = client.get("campaigns")
    present = (listing.is_success
               and any(c["id"] == campaign_id for c in items(listing.json())))
    print("Cleanup:", deleted.status_code, "GET after:", after.status_code,
          "visible in campaign list:", present)
    if not deleted.is_success or not listing.is_success or present:
        raise RuntimeError(f"Unable to confirm cleanup: {name}")


def checked(response):
    response.raise_for_status()
    return response.json()


def audit_put(client):
    offers = items(checked(client.get("offers", params={"limit": 5})))
    offer = next(o for o in offers if o.get("status", o.get("state")) == "active")
    name = name_for_check()
    print("Disposable campaign:", name, flush=True)
    cid = None
    try:
        refs = {}
        for path, field, params in (("domains", "domain_id", {}),
                                   ("groups", "group_id", {"type": "campaigns"}),
                                   ("traffic_sources", "traffic_source_id", {})):
            refs[field] = items(checked(client.get(path, params=params)))[0]["id"]
        campaign = checked(client.post("campaigns", json={
            "name": name, "alias": name.rsplit("-", 1)[-1], "type": "position", **refs}))
        cid = campaign["id"]
        stream = checked(client.post("streams", json={
            "campaign_id": cid, "name": "Contract check", "type": "regular", "position": 1,
            "schema": "landings", "action_type": "http",
            "filters": [{"name": "country", "mode": "accept", "payload": ["PE"]}],
            "offers": [{"offer_id": offer["id"], "share": 100, "state": "active"}]}))
        sid = stream["id"]
        before = checked(client.get(f"streams/{sid}"))
        update = client.put(f"streams/{sid}", json={
            "offers": [{"offer_id": offer["id"], "share": 100, "state": "active"}]})
        print("Own stream PUT offers only:", update.status_code)
        update.raise_for_status()
        after = checked(client.get(f"streams/{sid}"))
        fields = ("name", "type", "weight", "schema", "action_type", "action_payload", "filters")
        for field in fields:
            print(f"  {field}: {'preserved' if before.get(field) == after.get(field) else 'changed'}")
    finally:
        if cid is None:
            # POST may have reached the server even if its reply was lost.
            listing = client.get("campaigns")
            listing.raise_for_status()
            cid = next((c["id"] for c in items(listing.json()) if c.get("name") == name), None)
        if cid is not None:
            clean_campaign(client, cid, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--mutate", action="store_true")
    args = parser.parse_args()
    try:
        with client_from_env(args.env) as client:
            if args.mutate:
                audit_put(client)
            else:
                audit(client)
    except (httpx.HTTPError, ValueError, RuntimeError, StopIteration, KeyError, IndexError) as exc:
        # Avoid printing request headers, upstream bodies or credentials on failure.
        print("Check failed:", str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
        if isinstance(exc, httpx.HTTPStatusError):
            print("HTTP status:", exc.response.status_code)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
