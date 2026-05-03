import json
import time
import requests
import argparse
import sys
import uuid
from datetime import datetime, timezone

def main():
    parser = argparse.ArgumentParser(description="Seed IMS with failure events")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of IMS API")
    parser.add_argument("--file", default="scripts/seed_failure_event.json", help="Path to JSON seed file")
    args = parser.parse_args()

    api_url = f"{args.url}/api/v1/signals"

    try:
        with open(args.file, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to read file {args.file}: {e}")
        sys.exit(1)

    print(f"Starting scenario: {data.get('scenario', 'Unknown')}")

    for event in data.get("events", []):
        delay_ms = event.get("delay_ms", 0)
        if delay_ms > 0:
            print(f"Waiting {delay_ms} ms before next event...")
            time.sleep(delay_ms / 1000.0)

        signals = event.get("signals", [])
        for signal_template in signals:
            print(f"Sending 100+ signals for {signal_template['component_id']} to trigger Work Item creation...")
            
            # Send 105 signals to hit the >=100 threshold
            for i in range(105):
                payload = dict(signal_template)
                payload["signal_id"] = str(uuid.uuid4())
                payload["timestamp"] = datetime.now(timezone.utc).isoformat()
                
                try:
                    res = requests.post(api_url, json=payload)
                    if res.status_code not in (200, 202):
                        print(f"Failed to post signal: {res.status_code} {res.text}")
                except Exception as e:
                    print(f"Request failed: {e}")
            
            print(f"Finished sending for {signal_template['component_id']}")

if __name__ == "__main__":
    main()
