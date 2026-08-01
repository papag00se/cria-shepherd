#!/usr/bin/env python3
"""Verifier for handles-java — rules shared with the rest of the battery.

See suite/tasks/_handles_verify.py: four deliverables, one point each, and a live test that
must PASS with the network and FAIL without it (checked with an unprivileged network
namespace, the one block that works for every language's HTTP client).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _handles_verify import main  # noqa: E402

if __name__ == "__main__":
    main("handles-java", "java")
