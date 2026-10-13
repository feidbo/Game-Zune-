"""Game Zune for the computer. Double-click on Windows (with Python), or run
GameZune.exe, built from this by .github/workflows/windows-app.yml."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gamezune.app import main  # noqa: E402

main()
