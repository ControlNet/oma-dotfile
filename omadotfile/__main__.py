"""`python3 -m omadotfile [--oauth] [--all]`: install from the checkout this package is in."""

import sys

from omadotfile.cli import main

main(sys.argv[1:])
