"""Lance UN profil de charge local, manuellement (utile pour tester une signature).

    python -m labtest.run_scenario ddos --duration 60
    python -m labtest.run_scenario brute_force --duration 60 --base http://127.0.0.1:8088

N'écrit pas d'étiquette et ne collecte rien : voir collect_session.py pour la session complète.
"""
import argparse
import json
import time

from .guard import TargetRefused
from .patterns import PATTERNS


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("pattern", choices=sorted(PATTERNS))
    p.add_argument("--base", default="http://127.0.0.1:8088", help="point d'entrée local (le WAF)")
    p.add_argument("--duration", type=float, default=60.0)
    args = p.parse_args()

    print(f"profil « {args.pattern} » pendant {args.duration:.0f} s sur {args.base}")
    start = time.time()
    try:
        summary = PATTERNS[args.pattern](args.base, args.duration)
    except TargetRefused as exc:
        raise SystemExit(str(exc))
    summary["seconds"] = round(time.time() - start, 1)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
