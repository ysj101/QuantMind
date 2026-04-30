"""`python -m quantmind.storage init` で DB 初期化を行う."""

from __future__ import annotations

import sys

from quantmind.storage.connection import init_db


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] != "init":
        print("usage: python -m quantmind.storage init")
        return 2
    path = init_db(verbose=True)
    print(f"DB initialized at: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
