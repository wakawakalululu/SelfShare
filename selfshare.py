#!/usr/bin/env python
"""Direct launcher: `python selfshare.py <command>` works without installing."""

from __future__ import annotations

import sys

from selfshare.cli import main

if __name__ == "__main__":
    sys.exit(main())
