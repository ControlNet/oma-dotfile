"""`python3 -m omadotfile [--oauth] [--all]`: install from the checkout this package is in."""

from pathlib import Path
import sys

from omadotfile.legacy import main

main(sys.argv[1:], repo_path=Path(__file__).resolve().parent.parent)
