"""Build GameZune.exe (or the app for whatever system this runs on):

    pip install -r manager/requirements.txt pyinstaller
    python manager/build.py

One file, in build-app/dist/, carrying the Zune launcher (dist/TortOS) and
scripts/zunesync.py, so the card can be set up from it alone.
"""
import os
import sys

import PyInstaller.__main__

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "build-app")
ICO = os.path.join(HERE, "gamezune.ico")


def main():
    sep = os.pathsep
    PyInstaller.__main__.run([
        os.path.join(HERE, "GameZune.pyw"),
        "--noconfirm", "--onefile", "--windowed", "--name", "GameZune",
        "--icon", ICO,
        "--paths", HERE, "--paths", os.path.join(ROOT, "scripts"),
        "--hidden-import", "zunesync",
        "--add-data", os.path.join(ROOT, "dist", "TortOS") + sep + "TortOS",
        "--add-data", ICO + sep + ".",
        "--distpath", os.path.join(OUT, "dist"),
        "--workpath", os.path.join(OUT, "work"),
        "--specpath", OUT,
    ] + sys.argv[1:])


if __name__ == "__main__":
    main()
