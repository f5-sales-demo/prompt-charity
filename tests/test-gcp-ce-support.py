"""Fail-closed checksum, polling, redaction and provider release selection tests."""

# Standard-library unittest keeps the shell test entrypoint dependency-free.
# ruff: noqa: INP001, PT009, PT027
# pylint: disable=invalid-name
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

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

    def poll(self, responses):
        clock = [0.0]
        output: list[str] = []

        def sleep(seconds):
            clock[0] += seconds

        def fetch():
            return responses.pop(0) if len(responses) > 1 else responses[0]

        result = support.poll(
            fetch,
            timeout=60,
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
                ]
            )[0],
            0,
        )

    def test_redaction(self):
        raw = "Authorization: APIToken secret-value eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.signature F5XCProvider_API_TOKEN=other-secret"
        cleaned = support.redact(raw, ["secret-value", "other-secret"])
        self.assertNotIn("secret-value", cleaned)
        self.assertNotIn("other-secret", cleaned)
        self.assertNotIn("eyJhbG", cleaned)


if __name__ == "__main__":
    unittest.main()
