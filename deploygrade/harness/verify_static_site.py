"""Fail-closed local validation of Vercel's checked-in static dashboard input.

This deliberately does not claim a Vercel preview or deployed endpoint check. Those
checks require configured Vercel credentials and an external deployment target.
"""

from html.parser import HTMLParser
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]


class _LocalAssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if tag == "script" and name == "src" or tag == "link" and name == "href":
                if value:
                    self.assets.append(value)


def _fail(message):
    raise ValueError(message)


def main():
    config_path = ROOT / "vercel.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_directory = config.get("outputDirectory")
    if not isinstance(output_directory, str) or not output_directory:
        _fail("vercel.json must declare a non-empty outputDirectory")

    output = (ROOT / output_directory).resolve()
    if ROOT not in output.parents:
        _fail("vercel outputDirectory must remain inside the repository")
    index = output / "index.html"
    if not index.is_file():
        _fail("Vercel outputDirectory must contain index.html")

    parser = _LocalAssetParser()
    parser.feed(index.read_text(encoding="utf-8"))
    if not parser.assets:
        _fail("dashboard index.html must reference local assets")
    for asset in parser.assets:
        if asset.startswith(("http://", "https://", "//", "#", "data:")):
            continue
        asset_path = (output / asset.lstrip("/")).resolve()
        if output not in asset_path.parents:
            _fail(f"dashboard asset escapes outputDirectory: {asset}")
        if not asset_path.is_file():
            _fail(f"dashboard asset does not exist: {asset}")
    print(f"Static Vercel input validated: {output.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Static Vercel input validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
