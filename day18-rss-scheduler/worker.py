"""One-shot jobs for a systemd timer or local Task Scheduler."""

import argparse
import json
from feed_store import collect
from digest import build_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", nargs="?", choices=("collect", "digest"), default="collect")
    args = parser.parse_args()
    try:
        result = collect() if args.job == "collect" else build_digest()
    except ValueError as exc:
        if args.job != "digest" or str(exc) != "No new articles since the previous digest":
            raise
        result = {"skipped": "no new articles since the previous digest"}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
