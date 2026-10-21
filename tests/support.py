"""Locate PC-testable board modules without requiring a connected board."""
from pathlib import Path
import sys

VERSION_DIR = Path(__file__).resolve().parents[1]
DEVICE_DIR = VERSION_DIR / "device"
HOST_DIR = VERSION_DIR / "host"
PROJECT_ROOT = VERSION_DIR.parent
sys.path.insert(0, str(DEVICE_DIR))
sys.path.insert(0, str(HOST_DIR))
