#!/usr/bin/env python3
"""
Diagnostic script to inspect the raw PetSafe API responses.

Usage (with refresh token — recommended, handles expired id_tokens automatically):
  python3 diagnose_api.py --email you@example.com --refresh-token <refresh_token> --access-token <access_token>

Usage (with a fresh id_token if it's less than ~1 hour old):
  python3 diagnose_api.py --email you@example.com --id-token <id_token>

Tokens live in your HA instance at:
  <ha-config>/.storage/core.config_entries
  -> find the "petsafe" entry -> data keys: token, refresh_token, access_token
"""

import argparse
import asyncio
import json
import sys

import petsafe


async def main():
    parser = argparse.ArgumentParser(description="Diagnose PetSafe API responses")
    parser.add_argument("--email", required=True, help="PetSafe account email")
    parser.add_argument("--id-token", default=None, help="PetSafe id_token (JWT) — stored as 'token' in HA")
    parser.add_argument("--refresh-token", default=None, help="PetSafe refresh_token")
    parser.add_argument("--access-token", default=None, help="PetSafe access_token")
    parser.add_argument("--days", type=int, default=7, help="Days of messages to fetch (default: 7)")
    parser.add_argument("--feeder-index", type=int, default=0, help="Which feeder to inspect (0-indexed)")
    parser.add_argument("--dump-feeder-data", action="store_true", help="Also dump raw feeder data")
    args = parser.parse_args()

    client = petsafe.PetSafeClient(
        email=args.email,
        id_token=args.id_token,
        refresh_token=args.refresh_token,
        access_token=args.access_token,
    )

    print("=== Fetching feeders ===")
    feeders = await client.get_feeders()
    print(f"Found {len(feeders)} feeder(s):")
    for i, f in enumerate(feeders):
        print(f"  [{i}] {f.friendly_name} (thing_name: {f.api_name})")

    if not feeders:
        print("No feeders found!")
        sys.exit(1)

    feeder = feeders[args.feeder_index]
    print(f"\nInspecting feeder: {feeder.api_name}")

    if args.dump_feeder_data:
        print("\n=== Raw feeder data ===")
        print(feeder.to_json())

    print(f"\n=== Messages endpoint (days={args.days}) ===")
    url = f"smart-feed/feeders/{feeder.api_name}/messages?days={args.days}"
    print(f"URL: https://platform.cloud.petsafe.net/{url}")
    response = await client.api_get(url)
    messages = response.json()

    print(f"\nResponse type: {type(messages).__name__}")
    if isinstance(messages, list):
        print(f"Message count: {len(messages)}")
        if messages:
            print("\nFirst message structure:")
            print(json.dumps(messages[0], indent=2))
            print("\nLooking for FEED_DONE messages...")
            feed_done = [m for m in messages if m.get("message_type") == "FEED_DONE"]
            print(f"Found {len(feed_done)} FEED_DONE messages")
            if feed_done:
                print("\nmessages[0]  (list-start, what library returns):")
                print(json.dumps(feed_done[0], indent=2))
                print("\nmessages[-1] (list-end):")
                print(json.dumps(feed_done[-1], indent=2))
                # Sort by payload.time to find true last feeding
                by_time = sorted(feed_done, key=lambda m: m.get("payload", {}).get("time", 0))
                print(f"\nOldest FEED_DONE (by payload.time): {by_time[0].get('created_at')}  time={by_time[0]['payload']['time']}")
                print(f"Newest FEED_DONE (by payload.time): {by_time[-1].get('created_at')}  time={by_time[-1]['payload']['time']}")
            else:
                print("\nAll unique message_type values found:")
                types = {m.get("message_type", "<none>") for m in messages}
                for t in sorted(types):
                    count = sum(1 for m in messages if m.get("message_type") == t)
                    print(f"  {t}: {count} messages")
                print("\nFirst 5 messages:")
                print(json.dumps(messages[:5], indent=2))
    else:
        print("\nFull response:")
        print(json.dumps(messages, indent=2))

    print("\n=== get_last_feeding() result ===")
    last = await feeder.get_last_feeding()
    print(f"Result: {json.dumps(last, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
