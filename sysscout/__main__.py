"""Entry point for `python -m sysscout`.

Python runs this file when the package is executed as a module.
It stays tiny on purpose: all real logic lives in cli.py so tests can
import it without accidentally running the program.
"""

from sysscout.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
