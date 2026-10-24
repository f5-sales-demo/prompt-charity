"""Fail-closed checksum, polling, redaction and provider release selection tests."""

# Standard-library unittest keeps the shell test entrypoint dependency-free.
# ruff: noqa: INP001, PT009, PT027
# pylint: disable=invalid-name
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shlex
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "support", Path(__file__).resolve().parents[1] / "scripts/gcp-ce-support.py"
)
assert spec is not None
assert spec.loader is not None
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


class SupportTests(unittest.TestCase):
    def test_checksum_requires_exact_unique_match(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "asset.zip"
            archive.write_bytes(b"candidate")
            digest = hashlib.sha256(b"candidate").hexdigest()
            support.verify_checksum(archive, f"{digest}  asset.zip\n")
            for sums in [
                f"{digest}  other-asset.zip",
                f"{digest}  asset.zip\n{digest}  asset.zip",
                "bad asset.zip",
                f"{'0' * 64}  asset.zip",
            ]:
                with self.assertRaises(ValueError):
                    support.verify_checksum(archive, sums)

    def test_prerelease_included_and_draft_excluded(self):
        releases = [
            {"tag_name": "v0.9.7", "draft": False, "published_at": "2026-01-01"},
            {
                "tag_name": "v0.9.8-rc.1",
                "draft": False,
                "prerelease": True,
                "published_at": "2026-02-01",
            },
            {"tag_name": "v1.0.0", "draft": True, "published_at": "2026-03-01"},
        ]
        self.assertEqual(support.newest_release(releases)["tag_name"], "v0.9.8-rc.1")
        with self.assertRaises(ValueError):
            support.platform_asset(
                {"assets": [{"name": "linux_amd64.zip"}]}, "linux_arm64"
            )

    def test_release_manifest_checks_native_asset_and_checksum_file(self):
        releases: list[dict] = [
            {
                "tag_name": "v0.9.8-rc.1",
                "published_at": "2026-02-01",
                "draft": False,
                "assets": [
                    {"name": "terraform-provider-f5xc_0.9.8-rc.1_linux_amd64.zip"},
                    {"name": "terraform-provider-f5xc_0.9.8-rc.1_SHA256SUMS"},
                ],
            }
        ]
        manifest = support.release_manifest([releases], "linux_amd64")
        self.assertEqual(manifest["version"], "0.9.8-rc.1")
        with self.assertRaises(ValueError):
            support.release_manifest([releases], "linux_arm64")
        releases[0]["assets"].pop()
        with self.assertRaises(ValueError):
            support.release_manifest([releases], "linux_amd64")

    def test_latest_preview_on_later_page_never_falls_back_to_old_asset(self):
        old = {
            "tag_name": "v0.9.7",
            "published_at": "2026-01-01",
            "draft": False,
            "assets": [
                {"name": "terraform-provider-f5xc_0.9.7_darwin_arm64.zip"},
                {"name": "terraform-provider-f5xc_0.9.7_SHA256SUMS"},
            ],
        }
        newest: dict = {
            "tag_name": "v0.9.8-rc.1",
            "published_at": "2026-02-01",
            "draft": False,
            "prerelease": True,
            "assets": [
                {"name": "terraform-provider-f5xc_0.9.8-rc.1_darwin_arm64.zip"},
                {"name": "terraform-provider-f5xc_0.9.8-rc.1_SHA256SUMS"},
            ],
        }
        self.assertEqual(
            support.release_manifest([[old], [newest]], "darwin_arm64")["version"],
            "0.9.8-rc.1",
        )
        newest["assets"].pop(0)
        with self.assertRaises(ValueError):
            support.release_manifest([[old], [newest]], "darwin_arm64")

    def test_response_classification(self):
        for status, body, result in [
            (200, b'{"spec":{"site_state":"ONLINE"}}', "ONLINE"),
            (200, b'{"spec":{"site_state":"UPGRADING"}}', "PENDING"),
            (200, b"{}", "INVALID"),
            (200, b"bad", "INVALID"),
            (200, b'{"spec":{"site_state":"UNKNOWN"}}', "INVALID"),
            (401, b"{}", "AUTH_ERROR"),
            (503, b"{}", "HTTP_ERROR"),
            (200, b'{"spec":{"site_state":"FAILED"}}', "FAILED"),
        ]:
            self.assertEqual(support.classify(status, body)[0], result)

    def poll(self, responses, timeout=60):
        clock = [0.0]
        output: list[str] = []

        def sleep(seconds):
            clock[0] += seconds

        def fetch():
            return responses.pop(0) if len(responses) > 1 else responses[0]

        result = support.poll(
            fetch,
            timeout=timeout,
            monotonic=lambda: clock[0],
            sleep=sleep,
            emit=output.append,
        )
        return result, output

    def test_pending_timeout_is_nonzero(self):
        result, output = self.poll([(200, b'{"spec":{"site_state":"UPGRADING"}}')])
        self.assertEqual(result, 2)
        self.assertTrue(any("elapsed=30s" in line for line in output))
        self.assertIn("TIMEOUT", output[-1])

    def test_transport_failure_is_not_success(self):
        result, output = self.poll([(None, b"")])
        self.assertNotEqual(result, 0)
        self.assertTrue(any("TRANSPORT_ERROR" in line for line in output))

    def test_auth_and_invalid_stop(self):
        for response in [(401, b"{}"), (200, b"not json")]:
            result, _ = self.poll([response])
            self.assertNotEqual(result, 0)

    def test_online_only_success(self):
        self.assertEqual(
            self.poll(
                [
                    (200, b'{"spec":{"site_state":"UPGRADING"}}'),
                    (200, b'{"spec":{"site_state":"ONLINE"}}'),
                ],
                timeout=90,
            )[0],
            0,
        )

    def test_transient_online_regression_restarts_stability(self):
        result, output = self.poll(
            [
                (200, b'{"spec":{"site_state":"ONLINE"}}'),
                (200, b'{"spec":{"site_state":"PROVISIONING"}}'),
                (200, b'{"spec":{"site_state":"ONLINE"}}'),
                (200, b'{"spec":{"site_state":"ONLINE"}}'),
            ],
            timeout=120,
        )
        self.assertEqual(result, 0)
        self.assertTrue(any("elapsed=90s ONLINE" in line for line in output))
        self.assertEqual(sum(line.startswith("WAIT ONLINE") for line in output), 2)

    def test_response_failure_interrupts_online_stability(self):
        result, output = self.poll(
            [
                (200, b'{"spec":{"site_state":"ONLINE"}}'),
                (None, b""),
                (200, b'{"spec":{"site_state":"ONLINE"}}'),
                (200, b'{"spec":{"site_state":"ONLINE"}}'),
            ],
            timeout=120,
        )
        self.assertEqual(result, 0)
        self.assertTrue(any("elapsed=90s ONLINE" in line for line in output))

    def test_online_stability_does_not_extend_original_deadline(self):
        result, output = self.poll(
            [
                (200, b'{"spec":{"site_state":"PROVISIONING"}}'),
                (200, b'{"spec":{"site_state":"ONLINE"}}'),
            ]
        )
        self.assertEqual(result, 2)
        self.assertIn("TIMEOUT", output[-1])

    def test_online_observations_must_be_at_least_thirty_seconds_apart(self):
        clock = [0.0]
        observations: list[float] = []

        def fetch():
            if not observations:
                clock[0] += 20
            observations.append(clock[0])
            return 200, b'{"spec":{"site_state":"ONLINE"}}'

        def sleep(seconds):
            clock[0] += seconds

        result = support.poll(
            fetch,
            timeout=120,
            monotonic=lambda: clock[0],
            sleep=sleep,
            emit=lambda _: None,
        )
        self.assertEqual(result, 0)
        self.assertEqual(observations, [20, 30, 60])

    def test_redaction(self):
        raw = "Authorization: APIToken secret-value eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.signature F5XCProvider_API_TOKEN=other-secret"
        cleaned = support.redact(raw, ["secret-value", "other-secret"])
        self.assertNotIn("secret-value", cleaned)
        self.assertNotIn("other-secret", cleaned)
        self.assertNotIn("eyJhbG", cleaned)


class IamTests(unittest.TestCase):  # pylint: disable=too-many-public-methods
    def setUp(self):
        self.selection = {
            "caller": "user:operator@example.com",
            "service_account": "ce@example-project.iam.gserviceaccount.com",
            "service_account_project": "example-project",
            "deployment_project": "example-deployment",
            "quota_project": "example-quota",
            "credential_method": "impersonated-adc",
        }
        self.requests = []
        self.responses = {}
        self.sentinel = "SYNTHETIC_CREDENTIAL_SENTINEL_DO_NOT_PUBLISH"
        self.clock = [0.0]

    def adapter(self):
        sentinel = self.sentinel
        selection = self.selection
        requests = self.requests
        responses = self.responses

        class FixtureTransport:
            def command_token(self, argv):
                if "application-default" in argv:
                    return sentinel + "-adc"
                return sentinel + "-caller"

            def adc_metadata(self):
                return responses.get(
                    "adc_metadata",
                    {
                        "type": "impersonated_service_account",
                        "quota_project_id": selection["quota_project"],
                    },
                )

            def token_identity(self, token):
                if token == sentinel + "-caller":
                    return responses.get(
                        "caller_identity", selection["caller"].split(":", 1)[1]
                    )
                if responses.get("require_email_scope") and not any(
                    url.endswith(":generateAccessToken")
                    and "https://www.googleapis.com/auth/userinfo.email"
                    in body.get("scope", [])
                    for url, _, body in requests
                ):
                    return ""
                return selection["service_account"] if token else ""

            def request(self, url, token, data=None):
                requests.append((url, token, data))
                for key, response in responses.items():
                    if key in url:
                        return response
                if url.endswith((":testIamPermissions", "/testIamPermissions")):
                    return 200, json.dumps(
                        {"permissions": data["permissions"]}
                    ).encode()
                if url.endswith(":generateAccessToken"):
                    return 200, json.dumps(
                        {
                            "accessToken": sentinel + "-effective",
                            "expireTime": "2099-01-01T00:00:00Z",
                        }
                    ).encode()
                if "/services/" in url:
                    return 200, b'{"state":"ENABLED"}'
                return 200, json.dumps(
                    {"name": selection["deployment_project"]}
                ).encode()

        transport = FixtureTransport()
        with mock.patch.multiple(
            support.GcpIamObserver,
            command_token=transport.command_token,
            token_identity=transport.token_identity,
        ):
            observer = support.GcpIamObserver(
                self.selection, "f5xc-ce-crt-synthetic-byol"
            )
        observer.command_token = transport.command_token
        observer.token_identity = transport.token_identity
        observer.request = transport.request
        observer.adc_metadata = transport.adc_metadata
        return observer

    def preflight(self):
        return support.iam_preflight(
            self.selection,
            self.adapter().observe,
            now=lambda: "2026-01-01T00:00:00+00:00",
        )

    def test_narrow_and_project_grants_use_effective_access(self):
        for binding_scope in ("service-account", "project"):
            with self.subTest(binding_scope=binding_scope):
                result = self.preflight()
                self.assertTrue(
                    all(
                        gate["status"] == "PASS"
                        for gate in result["gates"]
                        if gate["gate"] != "apis_quota_project"
                    )
                )
                self.assertIsNone(
                    support.iam_team_request(result)["administrator_command_argv"]
                )
                iam = next(
                    request
                    for request in self.requests
                    if "iam.googleapis.com" in request[0]
                )
                self.assertEqual(iam[1], self.sentinel + "-caller")
                self.assertIn(self.selection["service_account"], iam[0])
                compute = next(
                    request
                    for request in self.requests
                    if self.selection["deployment_project"] + ":testIamPermissions"
                    in request[0]
                )
                self.assertEqual(compute[1], self.sentinel + "-effective")

    def test_effective_identity_unverified_cannot_pass_selection(self):
        self.responses["iam.googleapis.com"] = (200, b'{"permissions":[]}')
        result = self.preflight()
        self.assertEqual(result["gates"][0]["status"], "UNKNOWN")
        self.assertEqual(result["gates"][1]["status"], "BLOCKED")
        self.assertIsNotNone(support.iam_team_request(result)["required_role"])

    def test_api_permissions_cannot_pass_unchecked_capacity(self):
        result = self.preflight()
        self.assertEqual(result["gates"][3]["status"], "UNKNOWN")
        self.assertIn("regional capacity", result["gates"][3]["reason"])
        self.assertIsNone(support.iam_team_request(result)["required_role"])
        resumed = support.wait_iam_propagation(
            self.preflight, True, 600, wall_time=lambda: self.clock[0]
        )
        self.assertEqual(resumed["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(resumed["observations"]), 1)

    def test_wrong_principal_binding_does_not_grant_caller(self):
        self.responses["iam.googleapis.com"] = (200, b'{"permissions":[]}')
        result = self.preflight()
        self.assertEqual(result["gates"][1]["status"], "BLOCKED")
        request = support.iam_team_request(result)
        self.assertIn(
            "--member=user:operator@example.com", request["administrator_command_argv"]
        )
        self.assertNotIn(
            "--member=serviceAccount:" + self.selection["service_account"],
            request["administrator_command_argv"],
        )
        self.assertEqual(
            request["required_role"], "roles/iam.serviceAccountTokenCreator"
        )
        self.assertEqual(
            shlex.split(request["administrator_command"]),
            request["administrator_command_argv"],
        )

    def test_impersonation_token_has_verifiable_email_identity(self):
        # Cloud-only tokens can work for compute but omit email in tokeninfo.
        self.responses["require_email_scope"] = True
        self.assertTrue(
            all(
                gate["status"] == "PASS"
                for gate in self.preflight()["gates"]
                if gate["gate"] != "apis_quota_project"
            )
        )

    def test_missing_compute_permissions_preserves_custom_role_request(self):
        self.responses["example-deployment:testIamPermissions"] = (
            200,
            b'{"permissions":["compute.instances.get"]}',
        )
        result = self.preflight()
        self.assertEqual(result["gates"][2]["status"], "BLOCKED")
        request = support.iam_team_request(result)
        self.assertIsNone(request["administrator_command_argv"])
        self.assertNotIn("roles/owner", json.dumps(request).lower())
        self.assertIn("custom roles", request["instruction"])

    def test_readable_external_image_empty_permission_test_needs_approved_probe(self):
        image = "f5xc-ce-crt-synthetic-byol"
        self.responses[image + "/testIamPermissions"] = (200, b"{}")
        self.responses["/images/" + image] = (
            200,
            json.dumps({"name": image, "id": "123", "status": "READY"}).encode(),
        )
        result = self.preflight()
        self.assertEqual(result["gates"][2]["status"], "UNKNOWN")
        self.assertIn("licence probe", result["gates"][2]["reason"])
        self.assertIsNone(support.iam_team_request(result)["required_role"])
        self.assertFalse(any("disks" in url for url, _, _ in self.requests))
        resumed = support.wait_iam_propagation(
            self.preflight, True, 600, wall_time=lambda: self.clock[0]
        )
        self.assertEqual(resumed["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(resumed["observations"]), 1)

    def test_external_image_read_cannot_pass_missing_use_permission(self):
        image = "f5xc-ce-crt-synthetic-byol"
        self.responses[image + "/testIamPermissions"] = (200, b"{}")
        for response in ((200, b"[]"), (200, b'{"name":"wrong"}'), (403, b"{}")):
            with self.subTest(response=response):
                self.responses["/images/" + image] = response
                self.assertEqual(self.preflight()["gates"][2]["status"], "BLOCKED")

    def test_unavailable_policy_and_conditions_do_not_infer_token_creator(self):
        for response in (
            (403, b'{"policy":"unreadable"}'),
            (403, b'{"error":"conditional access denied"}'),
        ):
            with self.subTest(response=response):
                self.responses["iam.googleapis.com"] = response
                result = self.preflight()
                self.assertEqual(result["gates"][1]["status"], "UNKNOWN")
                self.assertIsNone(
                    support.iam_team_request(result)["administrator_command_argv"]
                )
        # Policy inspection is not required if effective tests and requests work.
        self.responses.clear()
        self.responses["getIamPolicy"] = (403, b"unreadable")
        self.assertEqual(self.preflight()["gates"][1]["status"], "PASS")
        self.assertFalse(any("getIamPolicy" in request[0] for request in self.requests))

    def test_disabled_api_and_malformed_api_state(self):
        for body, expected in (
            (b'{"state":"DISABLED"}', "BLOCKED"),
            (b"[]", "UNKNOWN"),
            (b'{"state":"UNKNOWN"}', "UNKNOWN"),
        ):
            with self.subTest(body=body):
                self.responses["/services/"] = (200, body)
                self.assertEqual(self.preflight()["gates"][3]["status"], expected)

    def test_credential_conflicts_and_expired_auth(self):
        with mock.patch.dict(
            os.environ,
            {"GOOGLE_IMPERSONATE_SERVICE_ACCOUNT": self.selection["service_account"]},
            clear=True,
        ):
            self.assertEqual(self.preflight()["gates"][4]["status"], "BLOCKED")
        self.responses["caller_identity"] = ""
        result = self.preflight()
        self.assertTrue(all(gate["status"] == "UNKNOWN" for gate in result["gates"]))
        self.assertIsNone(
            support.iam_team_request(result)["administrator_command_argv"]
        )

    def test_malformed_transport_and_generic_403_are_unknown(self):
        for status, body in (
            (200, b"bad"),
            (200, b"[]"),
            (200, b'{"permissions":"all"}'),
            (200, b'{"error":"denied"}'),
            (200, b'{"permissions":[1]}'),
            (None, b""),
            (403, b"{}"),
        ):
            with self.subTest(status=status, body=body):
                self.responses["iam.googleapis.com"] = (status, body)
                result = self.preflight()
                self.assertEqual(result["gates"][1]["status"], "UNKNOWN")
                self.assertIsNone(
                    support.iam_team_request(result)["administrator_command_argv"]
                )
        self.responses["iam.googleapis.com"] = (200, b"{}")
        self.assertEqual(self.preflight()["gates"][1]["status"], "BLOCKED")

    def test_permission_present_but_invalid_token_is_unknown(self):
        for body in (
            b"{}",
            b"[]",
            b'{"accessToken":"synthetic","expireTime":"2000-01-01T00:00:00Z"}',
            b'{"accessToken":12,"expireTime":"2099-01-01T00:00:00Z"}',
        ):
            with self.subTest(body=body):
                self.responses[":generateAccessToken"] = (200, body)
                self.assertEqual(self.preflight()["gates"][1]["status"], "UNKNOWN")

    def test_no_confirmation_means_no_retry_and_timeout_preserves_evidence(self):
        self.responses["iam.googleapis.com"] = (200, b"{}")

        def sleep(seconds):
            self.clock[0] += seconds

        def recheck():
            return self.preflight()

        result = support.wait_iam_propagation(
            recheck, False, 600, wall_time=lambda: self.clock[0], sleep=sleep
        )
        self.assertEqual(result["status"], "PAUSED")
        self.assertEqual(self.requests, [])
        result = support.wait_iam_propagation(
            recheck, True, 600, wall_time=lambda: self.clock[0], sleep=sleep
        )
        self.assertEqual(result["status"], "PAUSED")
        self.assertEqual(len(result["observations"]), 20)
        self.assertEqual(self.clock[0], 600)
        self.assertIn("correctness unknown", result["reason"])
        # A restart preserves the elapsed deadline and does not retry.
        self.assertEqual(
            support.wait_iam_propagation(
                recheck, True, 600, wall_time=lambda: self.clock[0], sleep=sleep
            )["observations"],
            [],
        )

    def test_checkpoint_approval_resume_invalidation_and_secret_handling(self):
        self.responses["iam.googleapis.com"] = (
            403,
            json.dumps(
                {"error": self.sentinel, "access_token": self.sentinel}
            ).encode(),
        )
        result = self.preflight()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o700)
            prompt = root / "prompt.txt"
            prompt.write_text("synthetic prompt")
            checkpoint = root / "checkpoint.json"
            with self.assertRaises(ValueError):
                support.save_iam_checkpoint(checkpoint, prompt, result, {}, [])
            support.save_iam_checkpoint(
                checkpoint,
                prompt,
                result,
                {"local_setup": True, "deployment": True},
                ["a" * 64],
                deadline=600,
            )
            self.assertEqual(checkpoint.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(self.sentinel, checkpoint.read_text())
            self.assertNotIn(self.sentinel, json.dumps(result))
            self.assertNotIn(
                self.sentinel, json.dumps(support.iam_team_request(result))
            )
            self.responses.clear()
            observer = self.adapter()
            resumed = support.resume_iam_checkpoint(
                checkpoint, prompt, self.selection, observer.observe
            )
            self.assertTrue(
                all(
                    gate["status"] == "PASS"
                    for gate in resumed["preflight"]["gates"]
                    if gate["gate"] != "apis_quota_project"
                )
            )
            self.assertEqual(resumed["installation_receipts"], ["a" * 64])
            self.assertEqual(resumed["propagation_deadline"], 600)
            for field, value in (
                ("caller", "user:other@example.com"),
                ("deployment_project", "example-other"),
                ("quota_project", "example-other"),
                ("credential_method", "provider-impersonation"),
            ):
                selection = dict(self.selection)
                selection[field] = value
                changed = support.resume_iam_checkpoint(
                    checkpoint, prompt, selection, observer.observe
                )
                self.assertTrue(changed["selection_or_prompt_changed"])
                self.assertFalse(changed["approvals"]["deployment"])
            prompt.write_text("revised prompt")
            self.assertFalse(
                support.resume_iam_checkpoint(
                    checkpoint, prompt, self.selection, observer.observe
                )["approvals"]["deployment"]
            )

    def test_planning_approval_is_separate_and_scope_bound(self):
        result = self.preflight()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o700)
            workspace = root / "workspace"
            workspace.mkdir()
            prompt = root / "prompt.txt"
            prompt.write_text("synthetic prompt")
            checkpoint = root / "checkpoint.json"
            scope = {
                "workspace": str(workspace),
                "paths": [
                    ".kiro/specs/gcp-customer-edge/requirements.md",
                    ".kiro/specs/gcp-customer-edge/.config.kiro",
                ],
            }
            with self.assertRaises(ValueError):
                support.save_iam_checkpoint(
                    checkpoint,
                    prompt,
                    result,
                    {"planning_files": True},
                    [],
                    planning_scope=scope,
                )
            self.assertFalse(checkpoint.exists())
            with self.assertRaises(ValueError):
                support.save_iam_checkpoint(
                    checkpoint,
                    prompt,
                    result,
                    {"local_setup": True, "planning_files": True},
                    [],
                )
            support.save_iam_checkpoint(
                checkpoint,
                prompt,
                result,
                {"local_setup": True, "planning_files": True, "deployment": True},
                ["a" * 64],
                deadline=600,
                planning_scope=scope,
            )
            saved = json.loads(checkpoint.read_text())
            self.assertEqual(saved["schema_version"], 2)
            resumed = support.resume_iam_checkpoint(
                checkpoint,
                prompt,
                self.selection,
                self.adapter().observe,
                planning_scope=scope,
            )
            self.assertTrue(resumed["approvals"]["planning_files"])
            self.assertTrue(resumed["approvals"]["deployment"])
            other = root / "other"
            other.mkdir()
            for new_scope in (
                None,
                {**scope, "workspace": str(other)},
                {**scope, "paths": [".kiro/specs/gcp-customer-edge/.config.kiro"]},
            ):
                changed = support.resume_iam_checkpoint(
                    checkpoint,
                    prompt,
                    self.selection,
                    self.adapter().observe,
                    planning_scope=new_scope,
                )
                self.assertTrue(changed["planning_scope_changed"])
                self.assertFalse(changed["approvals"]["planning_files"])
                self.assertFalse(changed["approvals"]["deployment"])
                self.assertEqual(changed["installation_receipts"], ["a" * 64])
                self.assertEqual(changed["propagation_deadline"], 600)
            prompt.write_text("revised prompt")
            changed = support.resume_iam_checkpoint(
                checkpoint,
                prompt,
                self.selection,
                self.adapter().observe,
                planning_scope=scope,
            )
            self.assertFalse(changed["approvals"]["planning_files"])

    def test_planning_scope_rejects_unsafe_paths_and_symlink_changes(self):
        result = self.preflight()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o700)
            workspace = root / "workspace"
            workspace.mkdir()
            prompt = root / "prompt.txt"
            prompt.write_text("synthetic prompt")
            checkpoint = root / "checkpoint.json"
            scope = {
                "workspace": str(workspace),
                "paths": [".kiro/specs/gcp-customer-edge/.config.kiro"],
            }
            for path in (
                ".config.kiro",
                "../.config.kiro",
                ".kiro/../.config.kiro",
                "/outside/.config.kiro",
                "plan.md",
                ".kiro/specs/gcp-customer-edge/secrets.md",
                ".kiro//specs/gcp-customer-edge/tasks.md",
                "..\\.config.kiro",
                self.sentinel,
            ):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    support.save_iam_checkpoint(
                        checkpoint,
                        prompt,
                        result,
                        {"local_setup": True, "planning_files": True},
                        [],
                        planning_scope={**scope, "paths": [path]},
                    )
                self.assertFalse(checkpoint.exists())
            support.save_iam_checkpoint(
                checkpoint,
                prompt,
                result,
                {"local_setup": True, "planning_files": True, "deployment": True},
                [],
                planning_scope=scope,
            )
            (workspace / ".kiro/specs/gcp-customer-edge").mkdir(parents=True)
            (workspace / ".kiro/specs/gcp-customer-edge/.config.kiro").symlink_to(
                root / "outside"
            )
            with self.assertRaises(ValueError):
                support.resume_iam_checkpoint(
                    checkpoint,
                    prompt,
                    self.selection,
                    self.adapter().observe,
                    planning_scope=scope,
                )
            checkpoint.unlink()
            workspace = root / "linked-workspace"
            workspace.mkdir()
            scope["workspace"] = str(workspace)
            (workspace / ".kiro").symlink_to(root)
            with self.assertRaises(ValueError):
                support.save_iam_checkpoint(
                    checkpoint,
                    prompt,
                    result,
                    {"local_setup": True, "planning_files": True},
                    [],
                    planning_scope={
                        **scope,
                        "paths": [".kiro/specs/gcp-customer-edge/tasks.md"],
                    },
                )
            self.assertFalse(checkpoint.exists())

    def test_legacy_checkpoint_never_infers_planning_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o700)
            prompt = root / "prompt.txt"
            prompt.write_text("synthetic prompt")
            checkpoint = root / "checkpoint.json"
            support.save_iam_checkpoint(
                checkpoint,
                prompt,
                self.preflight(),
                {"local_setup": True, "deployment": True},
                ["a" * 64],
                deadline=600,
            )
            saved = json.loads(checkpoint.read_text())
            saved["schema_version"] = 1
            saved.pop("planning_scope")
            checkpoint.write_text(json.dumps(saved))
            resumed = support.resume_iam_checkpoint(
                checkpoint,
                prompt,
                self.selection,
                self.adapter().observe,
            )
            self.assertFalse(resumed["approvals"]["planning_files"])
            self.assertTrue(resumed["approvals"]["deployment"])
            self.assertEqual(resumed["propagation_deadline"], 600)
            saved["schema_version"] = 99
            checkpoint.write_text(json.dumps(saved))
            with self.assertRaises(ValueError):
                support.resume_iam_checkpoint(
                    checkpoint,
                    prompt,
                    self.selection,
                    self.adapter().observe,
                )

    def test_checkpoint_rejects_malformed_planning_scope_and_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o700)
            prompt = root / "prompt.txt"
            prompt.write_text("synthetic prompt")
            checkpoint = root / "checkpoint.json"
            result = self.preflight()
            scope: dict = {
                "workspace": str(root),
                "paths": [".kiro/specs/gcp-customer-edge/tasks.md"],
            }
            for invalid in (
                {},
                {**scope, "workspace": "relative"},
                {**scope, "paths": []},
                {**scope, "paths": scope["paths"] * 2},
                {**scope, "paths": [None]},
                {**scope, "paths": scope["paths"][0]},
                {**scope, "credential": self.sentinel},
            ):
                with self.subTest(scope=invalid), self.assertRaises(ValueError):
                    support.save_iam_checkpoint(
                        checkpoint,
                        prompt,
                        result,
                        {"local_setup": True, "planning_files": True},
                        [],
                        planning_scope=invalid,
                    )
                self.assertFalse(checkpoint.exists())
            support.save_iam_checkpoint(
                checkpoint,
                prompt,
                result,
                {"local_setup": True, "deployment": True},
                [],
            )
            saved = json.loads(checkpoint.read_text())
            for approval in (True, self.sentinel):
                saved["approvals"]["planning_files"] = approval
                checkpoint.write_text(json.dumps(saved))
                with self.assertRaises(ValueError):
                    support.resume_iam_checkpoint(
                        checkpoint,
                        prompt,
                        self.selection,
                        self.adapter().observe,
                    )

    def test_adc_quota_conflicts_and_independent_read(self):
        self.responses["adc_metadata"] = {
            "type": "impersonated_service_account",
            "quota_project_id": "different-quota",
        }
        self.assertEqual(self.preflight()["gates"][4]["status"], "UNKNOWN")
        self.responses.clear()
        self.preflight()
        compute_read = next(
            request
            for request in self.requests
            if request[0]
            == "https://compute.googleapis.com/compute/v1/projects/"
            + self.selection["deployment_project"]
        )
        self.assertEqual(compute_read[1], self.sentinel + "-adc")
        self.selection["credential_method"] = "provider-impersonation"
        self.assertEqual(self.preflight()["gates"][4]["status"], "BLOCKED")

    def test_live_transport_rejects_secret_echo_and_non_google_origin(self):
        observer = self.adapter()
        with mock.patch.object(support.urllib.request, "urlopen") as urlopen:
            request = support.GcpIamObserver.request(
                observer, "https://example.com/", self.sentinel
            )
            self.assertEqual(request, (None, b""))
            urlopen.assert_not_called()
            error = support.urllib.error.HTTPError(
                "https://iam.googleapis.com/",
                403,
                "denied",
                {},
                io.BytesIO(self.sentinel.encode()),
            )
            urlopen.side_effect = error
            request = support.GcpIamObserver.request(
                observer,
                "https://iam.googleapis.com/v1/projects/-/serviceAccounts/"
                + self.selection["service_account"]
                + ":testIamPermissions",
                self.sentinel,
                {"permissions": [support.IAM_PERMISSION]},
            )
            self.assertEqual(request, (403, b""))
            self.assertEqual(
                urlopen.call_args.args[0].get_header("X-goog-user-project"),
                self.selection["quota_project"],
            )

    def test_public_identity_request_omits_quota_header_and_keeps_token_in_body(self):
        observer = self.adapter()
        observer.request = lambda url, token, data=None: support.GcpIamObserver.request(
            observer, url, token, data
        )
        requests = []

        def urlopen(request, timeout):
            requests.append(request)
            if request.get_header("X-goog-user-project"):
                raise support.urllib.error.HTTPError(
                    request.full_url,
                    403,
                    "quota header rejected",
                    {},
                    io.BytesIO(b"{}"),
                )
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.status = 200
            response.read.return_value = json.dumps(
                {"email": self.selection["service_account"]}
            ).encode()
            return response

        with mock.patch.object(support.urllib.request, "urlopen", side_effect=urlopen):
            self.assertEqual(
                support.GcpIamObserver.token_identity(observer, self.sentinel),
                self.selection["service_account"],
            )
        request = requests[0]
        self.assertEqual(request.full_url, "https://oauth2.googleapis.com/tokeninfo")
        self.assertEqual(request.get_method(), "POST")
        self.assertIsNone(request.get_header("X-goog-user-project"))
        self.assertNotIn(self.sentinel, request.full_url)
        self.assertEqual(
            support.urllib.parse.parse_qs(request.data.decode())["access_token"],
            [self.sentinel],
        )

    def test_command_errors_never_print_credentials(self):
        with (
            mock.patch.object(
                support.subprocess,
                "run",
                return_value=SimpleNamespace(
                    returncode=1,
                    stdout=self.sentinel.encode(),
                    stderr=self.sentinel.encode(),
                ),
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(
                support.GcpIamObserver.command_token(
                    ["gcloud", "auth", "print-access-token"]
                ),
                "",
            )
        self.assertNotIn(self.sentinel, output.getvalue())

    def test_propagation_success_does_not_authorize_deployment(self):
        result = support.wait_iam_propagation(
            self.preflight, True, 600, wall_time=lambda: 0, sleep=lambda _seconds: None
        )
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertNotIn("deployment", result)

    def test_selection_injection_or_wrong_owning_project_rejected(self):
        for field, value in (
            ("caller", "user:operator@example.com;echo secret"),
            ("deployment_project", "../../other"),
            ("service_account_project", "different-project"),
        ):
            selection = dict(self.selection)
            selection[field] = value
            with self.assertRaises(ValueError):
                support.validate_selection(selection)


if __name__ == "__main__":
    unittest.main()
