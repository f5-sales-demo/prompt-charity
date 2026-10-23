"""Fallback helpers: exact checksums and bounded, fail-closed XC polling."""

# Native CLI filename convention.
# pylint: disable=invalid-name

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path

CHECKSUM_COLUMNS = 2
MAX_FAILURES = 3
MAX_TIMEOUT = 3600


def newest_release(releases: list[dict]) -> dict:
    """Select the latest published release, including prereleases."""
    candidates = [
        release
        for release in releases
        if not release.get("draft") and release.get("published_at")
    ]
    if not candidates:
        msg = "No published non-draft provider release"
        raise ValueError(msg)
    return max(candidates, key=lambda release: release["published_at"])


def platform_asset(release: dict, platform: str) -> dict:
    """Require a unique asset for the discovered native platform."""
    matches = [
        asset
        for asset in release.get("assets", [])
        if asset["name"].endswith(f"_{platform}.zip")
    ]
    if len(matches) != 1:
        msg = f"No unique supported provider asset for {platform}"
        raise ValueError(msg)
    return matches[0]


def release_manifest(pages: list, platform: str) -> dict:
    """Resolve paginated release data to one native archive and checksum file."""
    releases = [release for page in pages for release in page]
    release = newest_release(releases)
    tag = release["tag_name"]
    version = tag.removeprefix("v")
    archive = platform_asset(release, platform)
    sums = f"terraform-provider-f5xc_{version}_SHA256SUMS"
    if sum(asset["name"] == sums for asset in release.get("assets", [])) != 1:
        msg = "Missing or duplicate exact checksum file asset"
        raise ValueError(msg)
    return {
        "tag": tag,
        "version": version,
        "platform": platform,
        "archive": archive["name"],
        "checksums": sums,
        "asset_digest": archive.get("digest"),
    }


def verify_checksum(archive: Path, checksums: str) -> None:
    """Verify one exact checksum entry before trusting archive bytes."""
    matches = []
    for line in checksums.splitlines():
        parts = line.split()
        if (
            len(parts) == CHECKSUM_COLUMNS
            and parts[1].removeprefix("*") == archive.name
        ):
            matches.append(parts[0])
    if len(matches) != 1 or not re.fullmatch(r"[0-9a-fA-F]{64}", matches[0]):
        msg = "Missing, duplicate or malformed exact asset checksum"
        raise ValueError(msg)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != matches[0].lower():
        msg = "CHECKSUM MISMATCH; do not extract or install"
        raise ValueError(msg)


def redact(text: str, secrets: list[str]) -> str:
    """Redact known secrets and JWT-shaped values from a sanitized excerpt."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(
        r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED_JWT]", text
    )
    return re.sub(r"(APIToken\s+|Bearer\s+)[^\s\"']+", r"\1[REDACTED]", text)


# Each response class has a separate fail-closed return.
# pylint: disable=too-many-return-statements
def classify(status: int | None, body: bytes) -> tuple[str, str]:  # noqa: PLR0911
    """Distinguish validated success, pending, auth, transport and response failure."""
    if status is None:
        return "TRANSPORT_ERROR", "request failed"
    if status in {401, 403}:
        return "AUTH_ERROR", str(status)
    if status != HTTPStatus.OK:
        return "HTTP_ERROR", str(status)
    try:
        payload = json.loads(body)
        state = payload["spec"]["site_state"]
        if not isinstance(state, str) or not state:
            return "INVALID", "missing state"
    except (ValueError, KeyError, TypeError):
        return "INVALID", "invalid JSON or site-state shape"
    if state == "ONLINE":
        return "ONLINE", state
    if state in {"FAILED", "ERROR_IN_ORCHESTRATION"}:
        return "FAILED", state
    if state in {"WAITING_FOR_REGISTRATION", "PROVISIONING", "UPGRADING"}:
        return "PENDING", state
    return "INVALID", "unrecognized site state"


def poll(
    fetch: Callable[[], tuple[int | None, bytes]],
    timeout: float = MAX_TIMEOUT,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    emit: Callable[[str], None] = print,
) -> int:
    """0 ONLINE, 2 timeout, 1 terminal/auth/repeated response failure."""
    start = monotonic()
    failures = 0
    while monotonic() - start < timeout:
        poll_started = monotonic()
        status, body = fetch()
        kind, detail = classify(status, body)
        elapsed = monotonic() - start
        emit(f"elapsed={elapsed:.0f}s {kind} {detail}")
        if elapsed >= timeout:
            break
        if kind == "ONLINE":
            return 0
        if kind in {"FAILED", "AUTH_ERROR"}:
            return 1
        failures = (
            failures + 1 if kind in {"INVALID", "TRANSPORT_ERROR", "HTTP_ERROR"} else 0
        )
        if failures >= MAX_FAILURES:
            emit("STOP repeated response failures; preserve evidence and diagnose")
            return 1
        sleep(max(0, min(poll_started + 30, start + timeout) - monotonic()))
    emit("TIMEOUT registration incomplete; preserve evidence and bound diagnostics")
    return 2


def main() -> None:
    """Run a checksum check or poll with private evidence and a fixed deadline."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    release = commands.add_parser("release")
    release.add_argument("pages", type=Path)
    release.add_argument("--platform", required=True)
    checksum = commands.add_parser("checksum")
    checksum.add_argument("archive", type=Path)
    checksum.add_argument("checksums", type=Path)
    polling = commands.add_parser("poll")
    polling.add_argument("site")
    polling.add_argument(
        "--timeout-seconds",
        type=int,
        default=3600,
        help="Remaining original registration budget, never restart at 60 minutes",
    )
    polling.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "release":
        manifest = release_manifest(
            json.loads(args.pages.read_text(encoding="utf-8")), args.platform
        )
        print(json.dumps(manifest, sort_keys=True))
        return
    if args.command == "checksum":
        verify_checksum(args.archive, args.checksums.read_text(encoding="utf-8"))
        print("Exact asset checksum verified")
        return
    if not 0 < args.timeout_seconds <= MAX_TIMEOUT:
        parser.error("Timeout must be the remaining original budget, 1..3600 seconds")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", args.site):
        parser.error("Invalid site name")
    base = os.environ.get("F5XCProvider_URL", "").rstrip("/")  # noqa: SIM112 - provider-defined name
    token = os.environ.get("F5XCProvider_API_TOKEN", "")  # noqa: SIM112 - provider-defined name
    if not base.startswith("https://") or not base.endswith("/api") or not token:
        parser.error("Private HTTPS /api URL and API token environment are required")
    os.umask(0o077)
    args.evidence_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.evidence_dir.stat().st_mode & 0o077:
        parser.error("Evidence directory must be private (0700)")
    url = f"{base}/config/namespaces/system/sites/{args.site}"
    sequence = 0

    def fetch() -> tuple[int | None, bytes]:
        nonlocal sequence
        sequence += 1
        request = urllib.request.Request(  # noqa: S310 - HTTPS /api URL validated above
            url, headers={"Authorization": f"APIToken {token}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:  # noqa: S310 - HTTPS URL validated above
                status, body = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
        except (OSError, urllib.error.URLError):
            status, body = None, b""
        stamp = time.time_ns()
        target = args.evidence_dir / f"poll-{stamp}-{sequence}.json"
        target.write_text(
            json.dumps(
                {
                    "time_ns": stamp,
                    "status": status,
                    "body": body.decode("utf-8", errors="replace"),
                }
            ),
            encoding="utf-8",
        )
        return status, body

    raise SystemExit(poll(fetch, timeout=args.timeout_seconds))


if __name__ == "__main__":
    main()
