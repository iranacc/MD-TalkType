"""Launcher: double-click to run MD-TalkType from source (no console window)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dictation.app import main  # noqa: E402

main()
