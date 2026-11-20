import argparse
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--project", choices=["api", "ui", "all"], default="all")
selection = parser.parse_args().project
for project in (("api", "ui") if selection == "all" else (selection,)):
    folder = root / project
    python = folder / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(folder / ".venv")], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-e", str(folder)], check=True)
    if project == "ui":
        subprocess.run([str(python), "-m", "playwright", "install", "chromium"], check=True)
