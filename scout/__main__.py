import argparse
import logging
from datetime import date, timedelta
from pathlib import Path

from .config import COUNTRIES
from .pipeline import run, run_contacts, window


def main() -> None:
    parser = argparse.ArgumentParser(prog="scout", description="Find founder-built apps trending in US and Asian App Store charts.")
    parser.add_argument("--date", default=(date.today() - timedelta(days=2)).isoformat(),
                        help="chart date, YYYY-MM-DD (default: two days ago, the latest complete day)")
    parser.add_argument("--days", type=int, default=1,
                        help="number of days of charts to look back over, ending at --date (default 1)")
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--cache", type=Path, default=Path(".cache"))
    parser.add_argument("--no-cache", action="store_true", help="ignore cached responses")
    commands = parser.add_subparsers(dest="command", required=True)

    charts = commands.add_parser("charts", help="collect charts, filter, write apps.json and the workbook")
    charts.add_argument("--countries", default=",".join(COUNTRIES), help="comma-separated storefront codes")

    contacts = commands.add_parser("contacts", help="find and verify contacts for apps from a charts run")
    contacts.add_argument("--limit", type=int, default=200, help="top N apps per tier to search (default 200)")
    contacts.add_argument("--tiers", default="founder,small_company", help="comma-separated tiers to search")

    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out_dir = args.out / (args.date if args.days == 1 else f"{args.date}_{args.days}d")

    if args.command == "charts":
        counts = run(window(args.date, args.days), out_dir, args.cache, [c.strip().upper() for c in args.countries.split(",")],
                     use_cache=not args.no_cache)
    else:
        counts = run_contacts(out_dir, args.cache, args.tiers.split(","), args.limit, use_cache=not args.no_cache)
    print(f"{out_dir}: " + ", ".join(f"{n} {k}" for k, n in counts.items()))


if __name__ == "__main__":
    main()
