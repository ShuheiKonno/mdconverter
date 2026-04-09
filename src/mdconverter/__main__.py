"""Module entry point: ``python -m mdconverter`` launches the GUI."""

from __future__ import annotations

import sys


def main() -> int:
    # Import lazily so that import errors are reported after Python has
    # finished setting up the interpreter, which improves error messages
    # on Windows when bundled with PyInstaller.
    from mdconverter.app import launch

    return launch()


if __name__ == "__main__":
    sys.exit(main())
