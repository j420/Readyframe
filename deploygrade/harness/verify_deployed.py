"""Verify a configured deployed endpoint without pretending static checks are a release."""
import json
import os
import sys
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from deploygrade.engine.contracts import validate_artifact


def deployed_demo_url(origin: str) -> str:
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("DEPLOYGRADE_DEPLOYED_URL must be an HTTPS origin without query or fragment")
    return urljoin(origin.rstrip("/") + "/", "api/demo?profile=mature")


def verify(origin: str, *, opener=urlopen) -> dict:
    request = Request(deployed_demo_url(origin), headers={"Accept": "application/json"})
    with opener(request, timeout=15) as response:
        if response.status != 200:
            raise ValueError(f"deployed demo returned HTTP {response.status}")
        if response.headers.get_content_type() != "application/json":
            raise ValueError("deployed demo did not return application/json")
        payload = json.loads(response.read().decode("utf-8"))
    validate_artifact(payload)
    if payload["flywheel"]["refit"]["status"] != "PUBLISHED":
        raise ValueError("deployed demo flywheel did not publish the approved refit")
    return payload


def main() -> None:
    origin = os.environ.get("DEPLOYGRADE_DEPLOYED_URL")
    if not origin:
        raise ValueError("DEPLOYGRADE_DEPLOYED_URL is required for deployed endpoint verification")
    verify(origin)
    print("Deployed DeployGrade demo endpoint verified")


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        print(f"Deployed endpoint verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
