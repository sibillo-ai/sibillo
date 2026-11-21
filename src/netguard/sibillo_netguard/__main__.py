"""`python -m sibillo_netguard` keeps the egress table; `... check` is its health check (ADR-0053)."""

from __future__ import annotations

import os
import sys

from sibillo_netguard.guard import ConfigurationError, configuration_from, healthy, run


def main(argv: list[str]) -> int:
    if argv == ["check"]:
        return 0 if healthy() else 1
    if argv:
        print(f"usage: python -m sibillo_netguard [check], not {' '.join(argv)}", file=sys.stderr)
        return 2
    try:
        configuration = configuration_from(dict(os.environ))
    except ConfigurationError as error:
        print(f"sibillo-netguard: configuration error: {error}", file=sys.stderr)
        return 2
    return run(configuration)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
