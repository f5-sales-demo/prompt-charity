"""Fallback helpers: exact checksums and bounded, fail-closed XC polling."""

# Native CLI filename convention.
# pylint: disable=invalid-name

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
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


# Effective permission tests, never policy-binding inference, define this protocol.
IAM_PERMISSION = "iam.serviceAccounts.getAccessToken"
COMPUTE_PERMISSIONS = (
    "compute.instances.create",
    "compute.instances.get",
    "compute.instances.list",
    "compute.instances.update",
    "compute.instances.delete",
    "compute.instances.setMetadata",
    "compute.instances.setTags",
    "compute.instances.setLabels",
    "compute.disks.create",
    "compute.disks.get",
    "compute.disks.list",
    "compute.disks.use",
    "compute.disks.delete",
    "compute.disks.resize",
    "compute.networks.create",
    "compute.networks.get",
    "compute.networks.list",
    "compute.networks.update",
    "compute.networks.delete",
    "compute.networks.use",
    "compute.networks.updatePolicy",
    "compute.subnetworks.create",
    "compute.subnetworks.get",
    "compute.subnetworks.list",
    "compute.subnetworks.update",
    "compute.subnetworks.delete",
    "compute.subnetworks.use",
    "compute.firewalls.create",
    "compute.firewalls.get",
    "compute.firewalls.list",
    "compute.firewalls.update",
    "compute.firewalls.delete",
    "compute.routers.create",
    "compute.routers.get",
    "compute.routers.list",
    "compute.routers.update",
    "compute.routers.delete",
    "compute.globalOperations.get",
    "compute.regionOperations.get",
    "compute.zoneOperations.get",
)
IAM_GATES = (
    "identity_selection",
    "impersonation_access",
    "deployment_permissions",
    "apis_quota_project",
    "cli_adc_authentication",
)
SELECTION_FIELDS = (
    "caller",
    "service_account",
    "service_account_project",
    "deployment_project",
    "quota_project",
    "credential_method",
)
METHODS = {"existing-adc", "impersonated-adc", "provider-impersonation", "json-key"}
PROPAGATION_SECONDS = 600


def validate_selection(selection: dict) -> None:
    """Reject command/URL injection and incomplete selected identities."""
    project_pattern = r"[a-z][a-z0-9-]{4,62}"
    email_pattern = r"[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+"
    valid = (
        set(selection) == set(SELECTION_FIELDS)
        and all(isinstance(value, str) for value in selection.values())
        and re.fullmatch(
            rf"(?:user|serviceAccount):{email_pattern}", selection["caller"]
        )
        and selection["credential_method"] in METHODS
        and all(
            re.fullmatch(project_pattern, selection[field])
            for field in (
                "deployment_project",
                "quota_project",
            )
        )
    )
    account = selection.get("service_account", "")
    if account:
        valid = (
            valid
            and bool(
                re.fullmatch(
                    rf"[a-z][a-z0-9-]*@{project_pattern}\.iam\.gserviceaccount\.com",
                    account,
                )
            )
            and account.endswith(
                f"@{selection['service_account_project']}.iam.gserviceaccount.com"
            )
        )
    else:
        valid = valid and not selection.get("service_account_project")
        valid = valid and selection.get("credential_method") == "existing-adc"
    if not valid:
        msg = "Invalid or incomplete IAM identity selection"
        raise ValueError(msg)


def permission_result(
    response: tuple[int | None, bytes], required: list[str]
) -> tuple[str, str]:
    """Return missing permissions only after a validated effective response."""
    status, body = response
    if status != HTTPStatus.OK:
        return (
            "UNKNOWN",
            "permission transport/HTTP failure; investigate authentication and policy",
        )
    try:
        payload = json.loads(body)
        permissions = payload.get("permissions", [])
        if (
            not isinstance(payload, dict)
            or "error" in payload
            or not isinstance(permissions, list)
        ):
            return "UNKNOWN", "invalid permission response"
        if any(not isinstance(value, str) for value in permissions):
            return "UNKNOWN", "invalid permission response"
        missing = sorted(set(required) - set(permissions))
        if missing:
            return "BLOCKED", "missing effective permissions: " + ", ".join(missing)
    except (ValueError, TypeError, AttributeError):
        return "UNKNOWN", "invalid permission response"
    return "PASS", "all requested effective permissions returned"


def iam_preflight(
    selection: dict,
    observe: Callable[[str], tuple[str, str]],
    now: Callable[[], str] | None = None,
) -> dict:
    """Collect five gates; observers return sanitized, fixed-vocabulary evidence."""
    validate_selection(selection)
    stamp = (now or (lambda: datetime.now(UTC).isoformat()))()
    targets = (
        selection["caller"],
        selection["service_account"] or selection["caller"],
        selection["deployment_project"],
        selection["quota_project"],
        selection["service_account"] or selection["caller"],
    )
    owners = (
        "operator",
        "IAM team",
        "project IAM team",
        "project/API team",
        "operator",
    )
    actions = (
        "confirm caller, Terraform identity and credential method",
        "investigate exact caller access on the requested service account",
        "review missing permissions using approved custom roles",
        "review API state, quota identity and regional capacity",
        "approve scoped local setup and verify CLI/ADC independently",
    )
    gates: list[dict] = []
    for gate, target, owner, action in zip(
        IAM_GATES, targets, owners, actions, strict=True
    ):
        status, reason = observe(gate)
        if status not in {"PASS", "BLOCKED", "UNKNOWN"}:
            status, reason = "UNKNOWN", "invalid observation status"
        if gates and gates[0]["status"] != "PASS" and gate != "identity_selection":
            status, reason = (
                "UNKNOWN",
                "identity selection unverified; dependent evidence invalid",
            )
        gates.append(
            {
                "gate": gate,
                "status": status,
                "reason": reason,
                "caller": selection["caller"],
                "target_resource": target,
                "owner": owner,
                "next_action": "continue read-only discovery"
                if status == "PASS"
                else action,
                "observed_at": stamp,
            }
        )
    return {"schema_version": 1, "selection": dict(selection), "gates": gates}


def iam_team_request(result: dict) -> dict | None:
    """Build one private administrator handoff without an automatic IAM write."""
    failed = [gate for gate in result["gates"] if gate["status"] != "PASS"]
    if not failed:
        return None
    selection = result["selection"]
    command = None
    impersonation = result["gates"][1]
    if (
        impersonation["status"] == "BLOCKED"
        and IAM_PERMISSION in impersonation["reason"]
    ):
        command = [
            "gcloud",
            "iam",
            "service-accounts",
            "add-iam-policy-binding",
            selection["service_account"],
            "--project=" + selection["service_account_project"],
            "--member=" + selection["caller"],
            "--role=roles/iam.serviceAccountTokenCreator",
        ]
    return {
        "selection": dict(selection),
        "observations": failed,
        "administrator_command_argv": command,
        "required_role": "roles/iam.serviceAccountTokenCreator" if command else None,
        "instruction": "Grant to the caller, not the service account itself. Preserve approved custom roles; investigate UNKNOWN evidence before any grant.",
        "recheck": "After administrator confirmation, rerun all five gates every 30 seconds for at most ten minutes. Timeout pauses; group changes may take longer.",
    }


def save_iam_checkpoint(
    path: Path,
    prompt: Path,
    result: dict,
    approvals: dict,
    installations: list[str],
    deadline: float | None = None,
) -> None:
    """Save only selected protocol fields after separate local-setup approval."""
    if approvals.get("local_setup") is not True:
        msg = "Explicit local setup approval required for a checkpoint"
        raise ValueError(msg)
    if path.parent.stat().st_mode & 0o077 or path.is_symlink():
        msg = "Checkpoint parent must be private and target must not be a symlink"
        raise ValueError(msg)
    allowed = {"iam_administration", "local_setup", "deployment"}
    if set(approvals) - allowed or any(
        not isinstance(value, bool) for value in approvals.values()
    ):
        msg = "Approvals must be scoped boolean records"
        raise ValueError(msg)
    # Installation records are SHA256 receipts, not free-form secret-bearing logs.
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in installations):
        msg = "Installation receipts must be SHA256 digests"
        raise ValueError(msg)
    checkpoint = {
        "schema_version": 1,
        "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
        "selection": result["selection"],
        "gates": result["gates"],
        "outstanding_request": iam_team_request(result),
        "approvals": approvals,
        "installation_receipts": installations,
        "propagation_deadline": deadline,
    }
    # Caller passes only results generated by this module, never raw responses.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(checkpoint, stream, indent=2)


def resume_iam_checkpoint(
    path: Path, prompt: Path, selection: dict, observe: Callable[[str], tuple[str, str]]
) -> dict:
    """Always obtain fresh gates; identity or prompt changes revoke deployment approval."""
    if (
        path.is_symlink()
        or path.stat().st_mode & 0o077
        or path.parent.stat().st_mode & 0o077
    ):
        msg = "Checkpoint and parent must be private"
        raise ValueError(msg)
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    result = iam_preflight(selection, observe)
    changed = (
        checkpoint["selection"] != selection
        or checkpoint["prompt_sha256"]
        != hashlib.sha256(prompt.read_bytes()).hexdigest()
    )
    approvals = dict(checkpoint["approvals"])
    if changed:
        approvals["deployment"] = False
    return {
        "preflight": result,
        "approvals": approvals,
        "selection_or_prompt_changed": changed,
        "installation_receipts": checkpoint["installation_receipts"],
        "propagation_deadline": checkpoint["propagation_deadline"],
    }


def wait_iam_propagation(
    recheck: Callable[[], dict],
    confirmed: bool,
    deadline: float,
    wall_time: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Use the original confirmation deadline, including resumed sessions."""
    if not confirmed:
        return {
            "status": "PAUSED",
            "reason": "administrator confirmation required",
            "observations": [],
        }
    if deadline > wall_time() + PROPAGATION_SECONDS:
        msg = "Propagation deadline cannot exceed ten minutes"
        raise ValueError(msg)
    observations = []
    while wall_time() < deadline:
        started = wall_time()
        result = recheck()
        observations.append(result)
        if wall_time() < deadline and all(
            gate["status"] == "PASS" for gate in result["gates"]
        ):
            return {"status": "PASS", "observations": observations}
        sleep(max(0, min(started + 30, deadline) - wall_time()))
    return {
        "status": "PAUSED",
        "reason": "propagation timeout; preserve evidence, grant correctness unknown",
        "observations": observations,
    }


class GcpIamObserver:
    """Read-only live adapter; tokens and raw bodies never enter protocol output."""

    def __init__(self, selection: dict, image_name: str = "") -> None:
        """Capture caller authentication privately in the task environment."""
        validate_selection(selection)
        if image_name and not re.fullmatch(r"f5xc-ce-crt-[a-z0-9-]+", image_name):
            msg = "Invalid selected CE image name"
            raise ValueError(msg)
        self.image_name = image_name
        self.selection = selection
        self.tokens: dict[str, str] = {}
        self.identities: dict[str, str] = {}
        self.token_attempted = False
        caller = selection["caller"].split(":", 1)[1]
        self.tokens["caller"] = self.command_token(
            [
                "gcloud",
                "--account=" + caller,
                "--impersonate-service-account=",
                "auth",
                "print-access-token",
                "--quiet",
            ]
        )
        self.identities["caller"] = self.token_identity(self.tokens["caller"])

    @staticmethod
    def command_token(argv: list[str]) -> str:
        """Capture tokens and errors privately, without inheriting tracing/output."""
        try:
            result = subprocess.run(argv, capture_output=True, timeout=25, check=False)  # noqa: S603 - fixed executable and validated arguments
            return result.stdout.decode().strip() if result.returncode == 0 else ""
        except (OSError, UnicodeError, subprocess.TimeoutExpired):
            return ""

    def request(
        self, url: str, token: str, data: dict | None = None
    ) -> tuple[int | None, bytes]:
        """Use only fixed Google HTTPS API origins; never log requests or errors."""
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "iam.googleapis.com",
            "iamcredentials.googleapis.com",
            "cloudresourcemanager.googleapis.com",
            "serviceusage.googleapis.com",
            "compute.googleapis.com",
            "oauth2.googleapis.com",
        }:
            return None, b""
        if not token:
            return None, b""
        headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "X-Goog-User-Project": self.selection["quota_project"],
        }
        request = urllib.request.Request(  # noqa: S310 - validated HTTPS Google API origin
            url,
            headers=headers,
            data=None if data is None else json.dumps(data).encode(),
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:  # noqa: S310 - internal fixed HTTPS API URLs
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            error.close()
            return error.code, b""  # Never return arbitrary server credential echoes.
        except (OSError, urllib.error.URLError):
            return None, b""

    def token_identity(self, token: str) -> str:
        """Independently verify email through Google's private token-info request."""
        status, body = self.request(
            "https://oauth2.googleapis.com/tokeninfo?access_token="
            + urllib.parse.quote(token, safe=""),
            token,
        )
        try:
            payload = json.loads(body)
            return (
                payload.get("email", "")
                if status == HTTPStatus.OK and isinstance(payload, dict)
                else ""
            )
        except (ValueError, TypeError):
            return ""

    def effective_token(self) -> str:
        """Generate ephemeral impersonation without any IAM policy changes."""
        if self.token_attempted:
            return self.tokens.get("effective", "")
        self.token_attempted = True
        account = self.selection["service_account"]
        if account and self.selection["credential_method"] in {
            "impersonated-adc",
            "provider-impersonation",
        }:
            status, body = self.request(
                "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
                + account
                + ":generateAccessToken",
                self.tokens["caller"],
                {
                    "scope": ["https://www.googleapis.com/auth/cloud-platform"],
                    "lifetime": "600s",
                },
            )
            try:
                payload = json.loads(body)
                token = payload["accessToken"]
                expires = datetime.fromisoformat(payload["expireTime"])
                if (
                    status != HTTPStatus.OK
                    or not isinstance(token, str)
                    or not token
                    or expires <= datetime.now(UTC)
                ):
                    token = ""
            except (ValueError, TypeError, KeyError):
                token = ""
        else:
            token = self.tokens["caller"]
        self.tokens["effective"] = token
        self.identities["effective"] = self.token_identity(token)
        return token

    def permissions(
        self, resource: str, permissions: list[str], identity: str
    ) -> tuple[str, str]:
        """Test permissions against the exact resource and verified identity."""
        token = (
            self.tokens["caller"] if identity == "caller" else self.effective_token()
        )
        expected = (
            self.selection["caller"].split(":", 1)[1]
            if identity == "caller"
            else self.selection["service_account"]
            or self.selection["caller"].split(":", 1)[1]
        )
        if self.identities.get(identity) != expected:
            return (
                "UNKNOWN",
                "authenticated identity unavailable or different from selection",
            )
        suffix = (
            "/testIamPermissions"
            if resource.startswith("https://compute.googleapis.com/")
            else ":testIamPermissions"
        )
        return permission_result(
            self.request(resource + suffix, token, {"permissions": permissions}),
            permissions,
        )

    def observe(self, gate: str) -> tuple[str, str]:  # noqa: PLR0911 - separate fail-closed gates
        """Implement the five-gate observation protocol with fail-closed evidence."""
        if gate == "identity_selection":
            if self.identities["caller"] != self.selection["caller"].split(":", 1)[1]:
                return (
                    "UNKNOWN",
                    "caller authentication expired, unavailable or mismatched",
                )
            return (
                "PASS",
                "caller verified; explicit selection recorded; effective identity checked in dependent gates",
            )
        if gate == "impersonation_access":
            if self.selection["credential_method"] not in {
                "impersonated-adc",
                "provider-impersonation",
            }:
                return "PASS", "impersonation not used by selected method"
            result = self.permissions(
                "https://iam.googleapis.com/v1/projects/-/serviceAccounts/"
                + self.selection["service_account"],
                [IAM_PERMISSION],
                "caller",
            )
            if result[0] == "PASS" and not self.effective_token():
                return (
                    "UNKNOWN",
                    "permission present but short-lived token request failed or was invalid",
                )
            return result
        if gate == "deployment_permissions":
            result = self.permissions(
                "https://cloudresourcemanager.googleapis.com/v1/projects/"
                + self.selection["deployment_project"],
                list(COMPUTE_PERMISSIONS),
                "effective",
            )
            if result[0] != "PASS":
                return result
            if not self.image_name:
                return (
                    "UNKNOWN",
                    "project permissions verified; resolve exact external CE image and test image-use permission",
                )
            return self.permissions(
                "https://compute.googleapis.com/compute/v1/projects/f5-7626-networks-public/global/images/"
                + self.image_name,
                ["compute.images.useReadOnly"],
                "effective",
            )
        if gate == "apis_quota_project":
            return self.api_gate()
        return self.auth_gate()

    def api_gate(self) -> tuple[str, str]:
        """Verify API enabled states and explicit quota-project permission."""
        required_apis = {
            (self.selection["deployment_project"], "compute.googleapis.com"),
            (self.selection["quota_project"], "iamcredentials.googleapis.com"),
        }
        if self.selection["service_account_project"]:
            required_apis.add(
                (self.selection["service_account_project"], "iam.googleapis.com")
            )
        for project, api in sorted(required_apis):
            # Read API configuration as caller; do not use human compute permissions.
            status, body = self.request(
                f"https://serviceusage.googleapis.com/v1/projects/{project}/services/{api}",
                self.tokens["caller"],
            )
            try:
                payload = json.loads(body)
                state = payload.get("state")
                if status != HTTPStatus.OK or state not in {"ENABLED", "DISABLED"}:
                    return "UNKNOWN", "API state unavailable or invalid"
                if state == "DISABLED":
                    return (
                        "BLOCKED",
                        "required API disabled: " + api + " in " + project,
                    )
            except (ValueError, TypeError, AttributeError):
                return "UNKNOWN", "API state unavailable or invalid"
        caller_quota = self.permissions(
            "https://cloudresourcemanager.googleapis.com/v1/projects/"
            + self.selection["quota_project"],
            ["serviceusage.services.use"],
            "caller",
        )
        if caller_quota[0] != "PASS":
            return caller_quota
        result = self.permissions(
            "https://cloudresourcemanager.googleapis.com/v1/projects/"
            + self.selection["quota_project"],
            ["serviceusage.services.use"],
            "effective",
        )
        if result[0] != "PASS":
            return result
        return (
            "PASS",
            "APIs and quota-project permission verified; independently check regional capacity before deployment",
        )

    @staticmethod
    def adc_metadata() -> dict:
        """Extract only non-secret ADC method and quota metadata for verification."""
        config = Path(
            os.environ.get("CLOUDSDK_CONFIG", str(Path.home() / ".config/gcloud"))
        )
        try:
            payload = json.loads(
                (config / "application_default_credentials.json").read_text(
                    encoding="utf-8"
                )
            )
            return {key: payload.get(key) for key in ("type", "quota_project_id")}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def auth_gate(self) -> tuple[str, str]:  # noqa: PLR0911 - explicit credential failure cases
        """Verify ADC independently; unsupported explicit sources remain unknown."""
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get(
            "GOOGLE_CREDENTIALS"
        ):
            return (
                "UNKNOWN",
                "explicit credential source requires independent ADC verification; never fall back",
            )
        if self.selection["credential_method"] == "impersonated-adc" and os.environ.get(
            "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT"
        ):
            return "BLOCKED", "conflicting double impersonation configuration"
        if self.selection["credential_method"] == "json-key":
            return (
                "UNKNOWN",
                "private key ADC requires native credential-aware read-only verification",
            )
        metadata = self.adc_metadata()
        if metadata.get("quota_project_id") != self.selection["quota_project"]:
            return "UNKNOWN", "ADC quota project unverified or different from selection"
        if (
            self.selection["credential_method"] == "provider-impersonation"
            and metadata.get("type") == "impersonated_service_account"
        ):
            return "BLOCKED", "conflicting double impersonation configuration"
        configured_target = os.environ.get("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")
        if configured_target and configured_target != self.selection["service_account"]:
            return "BLOCKED", "configured impersonation target differs from selection"
        adc = self.command_token(
            ["gcloud", "auth", "application-default", "print-access-token", "--quiet"]
        )
        adc_identity = self.token_identity(adc)
        expected = (
            self.selection["service_account"]
            or self.selection["caller"].split(":", 1)[1]
        )
        if self.selection["credential_method"] == "provider-impersonation":
            if adc_identity != self.selection["caller"].split(":", 1)[1]:
                return "UNKNOWN", "primary ADC caller unverified or mismatched"
            # Prove ADC caller can independently generate the selected identity.
            status, body = self.request(
                "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
                + expected
                + ":generateAccessToken",
                adc,
                {
                    "scope": ["https://www.googleapis.com/auth/cloud-platform"],
                    "lifetime": "600s",
                },
            )
            try:
                adc = json.loads(body)["accessToken"] if status == HTTPStatus.OK else ""
                adc_identity = (
                    self.token_identity(adc) if status == HTTPStatus.OK else ""
                )
            except (ValueError, TypeError, KeyError):
                adc_identity = ""
        if self.identities.get("effective") != expected or adc_identity != expected:
            return (
                "UNKNOWN",
                "CLI/ADC authentication expired, unavailable or mismatched",
            )
        status, body = self.request(
            "https://compute.googleapis.com/compute/v1/projects/"
            + self.selection["deployment_project"],
            adc,
        )
        try:
            payload = json.loads(body)
            if (
                status == HTTPStatus.OK
                and payload.get("name") == self.selection["deployment_project"]
            ):
                return (
                    "PASS",
                    "independent CLI/ADC identity and authenticated compute read verified",
                )
        except (ValueError, TypeError, AttributeError):
            pass
        return "UNKNOWN", "authenticated compute read unavailable or invalid"


def run_iam_command(args: argparse.Namespace) -> int:
    """Emit a private structured preflight without workspace files or IAM mutations."""
    selection = {field: getattr(args, field) for field in SELECTION_FIELDS}
    observer = GcpIamObserver(selection, args.image_name)
    result = iam_preflight(selection, observer.observe)
    result["iam_team_request"] = iam_team_request(result)
    print(json.dumps(result, indent=2))
    return 0 if all(gate["status"] == "PASS" for gate in result["gates"]) else 2


def main() -> None:
    """Run a checksum check or poll with private evidence and a fixed deadline."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    iam = commands.add_parser("iam-preflight")
    iam.add_argument(
        "--image-name",
        default="",
        help="Resolved exact f5xc-ce-crt image name; absent image leaves deployment permissions UNKNOWN",
    )
    for field in SELECTION_FIELDS:
        iam.add_argument(
            "--" + field.replace("_", "-"),
            default="",
            required=field not in {"service_account", "service_account_project"},
        )
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
    if args.command == "iam-preflight":
        raise SystemExit(run_iam_command(args))
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
