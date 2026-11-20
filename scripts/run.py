"""Unified runner; each project keeps its own Python environment."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def validate(project, root=None):
    path = (root or ROOT) / "config.local.json"
    if not path.exists():
        raise ValueError("Copy config.example.json to config.local.json and fill in product configuration")
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Expected a configuration object")
    fields = ("api_base_url", "health_path") if project == "api" else ("base_url", "expected_title")
    for field in fields:
        if not isinstance(config.get(field), str) or not config[field].strip():
            raise ValueError(f"Missing configuration: {field}")
    url = urlparse(config[fields[0]])
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
        raise ValueError("Base URL must be HTTP(S) and must not contain credentials")
    if project == "api" and (not config["health_path"].startswith("/") or config["health_path"].startswith("//")):
        raise ValueError("health_path must be origin-relative")
    return config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["verify", "product", "doctor"])
    parser.add_argument("--project", choices=["api", "ui", "all"], default="all")
    args = parser.parse_args()
    projects = ["api", "ui"] if args.project == "all" else [args.project]
    failed = False
    try:
        if args.mode == "product":
            for project in projects:
                validate(project)
        for project in projects:
            python = ROOT / project / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            if not python.exists():
                raise ValueError(f"Missing environment: {python}; run scripts/bootstrap.py")
            if args.mode == "doctor":
                subprocess.run([str(python), "-m", "pip", "check"], check=True)
            else:
                output = ROOT / "outputs" / project
                output.mkdir(parents=True, exist_ok=True)
                suite = "tests/framework" if args.mode == "verify" else "testcases"
                result = subprocess.run([str(python), "-m", "pytest", suite, f"--junitxml={output / (args.mode + '.xml')}"], cwd=ROOT / project)
                failed |= result.returncode != 0
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
