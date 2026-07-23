#!/usr/bin/env python3
"""Run every verification suite. Exits non-zero if any of them fails.

    python tests/run_all.py

Each suite runs in its own process because they all import the server module and
mutate its module-level configuration; sharing an interpreter would let one suite's
isolated database leak into the next.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["test_auth.py", "test_libraries.py", "test_csrf.py", "test_installer.py",
          "test_sync.py"]


def main():
    failures = []
    for name in SUITES:
        print(f"\n{'=' * 62}\n{name}\n{'=' * 62}")
        result = subprocess.run([sys.executable, os.path.join(HERE, name)])
        if result.returncode != 0:
            failures.append(name)

    print(f"\n{'=' * 62}")
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    print(f"All {len(SUITES)} suites passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
