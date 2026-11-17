"""Show the jobs found in alert emails: `make parse FILE=path/to/alert.eml` (or several files)."""

import sys
from pathlib import Path

from app.modules.catalog.parsers import parse_email


def main(paths: list[str]) -> int:
    if not paths:
        print("usage: python -m app.modules.catalog.parsers FILE.eml [FILE.eml …]")
        return 2
    for path in paths:
        result = parse_email(Path(path).read_bytes())
        print(f"\n{path}")
        if result is None:
            print("  no parser recognises this email (it would be marked 'unparsed')")
            continue
        print(f"  parser: {result.parser}   alert: {result.alert_name or '—'}   jobs: {len(result.cards)}")
        for w in result.warnings:
            print(f"  warning: {w}")
        for i, c in enumerate(result.cards, 1):
            print(f"  {i:>2}. {c.title}")
            facts = [
                c.company or "(company not named)",
                c.location,
                c.work_model,
                c.experience,
                c.salary,
                "outside preference" if c.outside_preference else None,
            ]
            print("      " + " · ".join(f for f in facts if f))
            print(f"      {c.source}:{c.source_job_id}   {c.canonical_url or '(no public page)'}")
            if c.description:
                print(f"      description: {len(c.description)} characters")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
