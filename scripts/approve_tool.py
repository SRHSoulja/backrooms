#!/usr/bin/env python3
"""Human step: approve a resident's tool proposal into tools/. See scripts/resident_tools.py."""
try:
    from scripts.resident_tools import main
except ImportError:
    from resident_tools import main

if __name__ == "__main__":
    main()
