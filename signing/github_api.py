"""Read only successful owner builds; strip API credentials on redirects."""
import hashlib
import json
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from common import SigningError

REPOSITORY = "anjaymi/LumaPocket"
REPOSITORY_ID = 1435778522


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        if urlsplit(new_url).scheme != "https":
            raise SigningError("insecure_artifact_redirect")
        redirected = super().redirect_request(request, fp, code, message, headers, new_url)
        if urlsplit(new_url).hostname != "api.github.com":
            redirected.remove_header("Authorization")
        return redirected


def trusted_run(run, workflow_id):
    return (run.get("conclusion") == "success" and run.get("status") == "completed"
            and run.get("head_branch") == "main" and run.get("workflow_id") == workflow_id
            and run.get("head_repository", {}).get("id") == REPOSITORY_ID
            and run.get("actor", {}).get("login") == "anjaymi"
            and run.get("event") in ("push", "workflow_dispatch", "schedule"))


class GitHub:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(SafeRedirect())

    def get(self, path, binary=False):
        url = "https://api.github.com/repos/" + REPOSITORY + "/" + path
        request = urllib.request.Request(url, headers={"Authorization": "Bearer " + self.token,
            "User-Agent": "LumaPocket-self-test", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with self.opener.open(request, timeout=90) as response:
                data = response.read(512 * 1024 * 1024 + 1)
                if len(data) > 512 * 1024 * 1024:
                    raise SigningError("artifact_too_large")
        except (urllib.error.URLError, TimeoutError):
            raise SigningError("github_download_unavailable") from None
        return data if binary else json.loads(data)

    def artifact(self, workflow, name):
        workflow_id = self.get("actions/workflows/" + workflow)["id"]
        runs = self.get(f"actions/workflows/{workflow_id}/runs?branch=main&status=completed&per_page=30")
        for run in runs.get("workflow_runs", []):
            if not trusted_run(run, workflow_id):
                continue
            artifacts = self.get(f"actions/runs/{int(run['id'])}/artifacts?per_page=100")["artifacts"]
            for item in artifacts:
                if item.get("name") == name and not item.get("expired"):
                    return run, item
        return None

    def download_artifact(self, item, destination):
        digest = item.get("digest", "")
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise SigningError("artifact_digest_missing")
        data = self.get(f"actions/artifacts/{int(item['id'])}/zip", binary=True)
        if hashlib.sha256(data).hexdigest() != digest[7:]:
            raise SigningError("artifact_digest_mismatch")
        Path(destination).write_bytes(data)

    def restore_state(self, destination, root):
        found = self.artifact("free-signing.yml", "LumaPocket-free-sign")
        if found is None:
            return False
        _, item = found
        package = Path(root) / "previous-signing.zip"
        self.download_artifact(item, package)
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            allowed = {"signing-state.tar.gz.gpg", "LumaPocket_signed.ipa.gpg", "signing-report.json", "diagnostics.log.gpg"}
            if len(names) != len(set(names)) or not set(names) <= allowed or "signing-state.tar.gz.gpg" not in names:
                raise SigningError("unexpected_signing_artifact")
            Path(destination).write_bytes(archive.read("signing-state.tar.gz.gpg"))
        return True

    def unsigned(self, state, build):
        state = Path(state)
        metadata = state / "unsigned-build.json"
        if metadata.is_file() and (state / "unsigned.ipa").is_file():
            previous = json.loads(metadata.read_text())
            if previous.get("build") == build and hashlib.sha256((state / "unsigned.ipa").read_bytes()).hexdigest() == previous.get("sha256"):
                return False
        found = self.artifact("ios.yml", "LumaPocket-iOS-unsigned")
        if found is None:
            raise SigningError("unsigned_build_required")
        run, item = found
        revision = run["head_sha"]
        if not isinstance(revision, str) or len(revision) != 40 or not all(c in "0123456789abcdef" for c in revision):
            raise SigningError("invalid_build_revision")
        actual_build = self.get("contents/build.json?ref=" + revision)
        import base64
        if json.loads(base64.b64decode(actual_build["content"])) != build:
            raise SigningError("current_unsigned_build_required")
        package = state / "unsigned-download.zip"
        self.download_artifact(item, package)
        with zipfile.ZipFile(package) as archive:
            expected = "LumaPocket_" + build["applicationVersion"] + "_unsigned.ipa"
            if set(archive.namelist()) != {expected, expected + ".SHA256.txt", "build-report.json"}:
                raise SigningError("unexpected_unsigned_artifact")
            data = archive.read(expected)
            report = json.loads(archive.read("build-report.json"))
            digest = hashlib.sha256(data).hexdigest()
            if digest.upper() != report.get("sha256") or report.get("bundleIdentifier") != build["bundleIdentifier"]:
                raise SigningError("unsigned_ipa_digest_mismatch")
            (state / "unsigned.ipa").write_bytes(data)
        metadata.write_text(json.dumps({"build": build, "sha256": digest, "runId": run["id"]}))
        return True
