#!/usr/bin/env python3
"""
Launcher for AirCard Windows.
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from aircard.cli import main

if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
