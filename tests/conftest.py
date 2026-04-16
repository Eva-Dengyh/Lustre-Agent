"""Pytest fixtures and configuration."""

import os
import sys
from pathlib import Path
from typing import Generator

import pytest

# Ensure src is on path
SRC_ROOT = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(SRC_ROOT))
