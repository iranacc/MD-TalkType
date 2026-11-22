"""Check for app updates via GitHub Releases API."""
import json
import re
import urllib.request
from typing import Optional

from .branding import APP_VERSION

RELEASES_API = "https://api.github.com/repos/iranacc/MD-TalkType/releases/latest"


def _parse_version(v: str) -> tuple[int, ...]:
    """Extract numeric version components from strings like 'v1.2.0' or '1.2.1'."""
    clean = re.sub(r"^[^\d]*", "", (v or "").strip())
    parts = []
    for p in clean.split("."):
        num = re.match(r"^\d+", p)
        if num:
            parts.append(int(num.group()))
        else:
            break
    return tuple(parts) if parts else (0,)


def check_for_updates(timeout: int = 6) -> dict:
    """Query GitHub Releases API to see if a newer version is available."""
    result = {
        "has_update": False,
        "current_version": APP_VERSION,
        "latest_version": APP_VERSION,
        "release_url": f"https://github.com/iranacc/MD-TalkType/releases",
        "download_url": None,
        "body": "",
        "error": None,
    }
    try:
        req = urllib.request.Request(
            RELEASES_API,
            headers={
                "User-Agent": "MD-TalkType",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tag = data.get("tag_name", "").strip()
        result["latest_version"] = tag.lstrip("v")
        result["release_url"] = data.get("html_url", result["release_url"])
        result["body"] = data.get("body", "")

        # Find .exe asset download URL if present
        for asset in data.get("assets", []):
            url = asset.get("browser_download_url", "")
            if url.lower().endswith(".exe"):
                result["download_url"] = url
                break

        current_v = _parse_version(APP_VERSION)
        latest_v = _parse_version(tag)
        result["has_update"] = latest_v > current_v

    except Exception as e:
        result["error"] = str(e)

    return result
