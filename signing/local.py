"""Interactive authorization stays on the owner's computer, outside CI logs."""
import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from apple import Apple
from common import SigningError, run_private
from github_api import GitHub, REPOSITORY
from local_key import state_key
from profile import identity_from
from storage import crypt, export_state, extract_state
from tool import check, install

HERE = Path(__file__).resolve().parent


def gh(arguments, data=None):
    env = os.environ.copy()
    env["GODEBUG"] = "http2client=0"
    result = subprocess.run(["gh", *arguments], input=data, capture_output=True, timeout=120, env=env)
    if result.returncode:
        raise SigningError("github_cli_failed_check_gh_auth_status")
    return result.stdout


def client():
    return GitHub(gh(["auth", "token"]).decode().strip())


def authorize(home, args, password):
    # TemporaryDirectory is explicitly rooted beneath the private local state directory.
    with tempfile.TemporaryDirectory(prefix="authorize-", dir=home) as temporary:
        root = Path(temporary).resolve()
        if not root.is_relative_to(home.resolve()):
            raise SigningError("unexpected_local_work_directory")
        previous = home / "bootstrap-state.gpg"
        if previous.exists():
            raw = root / "previous.tar.gz"
            crypt(previous, raw, password, root, decrypt=True)
            extract_state(raw, root)
            identity = identity_from(root / "identity.json")
        else:
            session_password = secrets.token_urlsafe(48)
            identity = {"schema": 1, "sessionPassword": session_password,
                        "p12Password": session_password, "machinePassword": secrets.token_urlsafe(48),
                        "anisetteURL": args.anisette_url}
            identity["deviceUdid"] = args.udid or input("iPhone UDID (from Apple Devices/iTunes): ").strip()
        apple_id = args.apple_id or input("Apple Account email: ").strip()
        if not apple_id or "@" not in apple_id:
            raise SigningError("apple_account_required")
        tool = install(home / "tool")
        print("Enter your Apple password and verification code in the signing tool's local prompts.")
        run_private([str(tool), "dev", "login", "--apple-id", apple_id,
                     "--encrypt-password", identity["sessionPassword"],
                     "--machine-password", identity["machinePassword"],
                     "--machine-path", str(root / "machine.dat"),
                     "--server", identity["anisetteURL"], "--strict"], root, "local_apple_authorization",
                    timeout=900, interactive=True)
        active = root / "config/.sidesign/session/session.dat"
        if not active.is_file() or active.read_bytes()[:4] != b"SS02":
            raise SigningError("portable_authorization_session_missing")
        shutil.copy2(active, root / "session.dat")
        Apple(tool, root, identity).bootstrap()
        identity_from(root / "identity.json")
        export_state(root, home / "bootstrap-state.gpg", password, root)
    print("Authorized state saved locally with encryption. Apple password was not stored.")
    publish(home, password)


def publish(home, password):
    metadata = json.loads(gh(["repo", "view", REPOSITORY, "--json", "databaseId,nameWithOwner"]))
    if metadata.get("databaseId") != 1435778522 or metadata.get("nameWithOwner") != REPOSITORY:
        raise SigningError("dedicated_repository_required")
    seed = base64.b64encode((home / "bootstrap-state.gpg").read_bytes())
    if len(seed) > 45000:
        raise SigningError("bootstrap_exceeds_github_secret_limit")
    github = client()
    before = {run["id"] for run in github.get("actions/workflows/free-signing.yml/runs?event=workflow_dispatch&branch=main&per_page=20").get("workflow_runs", [])}
    gh(["secret", "set", "IOS_SIGNING_PASSPHRASE", "--repo", REPOSITORY], password.encode())
    gh(["secret", "set", "IOS_SIGNING_STATE_BASE64", "--repo", REPOSITORY], seed)
    gh(["workflow", "run", "free-signing.yml", "--repo", REPOSITORY,
        "-f", "mode=renew", "-f", "reset_state=true"])
    print("Manual signing run started: https://github.com/anjaymi/LumaPocket/actions")
    print("Waiting for the first verified cloud signature before enabling daily checks...")
    import time
    deadline = time.monotonic() + 1200
    target = None
    while time.monotonic() < deadline:
        if target is None:
            runs = github.get("actions/workflows/free-signing.yml/runs?event=workflow_dispatch&branch=main&per_page=20").get("workflow_runs", [])
            target = next((run["id"] for run in reversed(runs) if run["id"] not in before), None)
        if target is not None:
            run = github.get("actions/runs/" + str(target))
            if run.get("status") == "completed":
                if run.get("conclusion") != "success":
                    raise SigningError("first_manual_signing_failed_check_actions")
                enable(home, expected_run=target)
                return
        time.sleep(20)
    raise SigningError("manual_run_still_pending_run_enable_after_success")


def signed_artifact(home):
    github = client()
    found = github.artifact("free-signing.yml", "LumaPocket-free-sign")
    if found is None:
        raise SigningError("successful_manual_signing_run_required")
    run, artifact = found
    package = home / "signed-artifact.zip"
    github.download_artifact(artifact, package)
    with zipfile.ZipFile(package) as archive:
        report = json.loads(archive.read("signing-report.json"))
        if report.get("status") != "signed" or report.get("signatureChecksPassed") is not True or report.get("runId") != run["id"]:
            raise SigningError("successful_verified_signing_run_required")
    return package, report


def enable(home, expected_run=None):
    _, report = signed_artifact(home)
    if expected_run is not None and report["runId"] != expected_run:
        raise SigningError("current_manual_run_not_verified")
    if hashlib.sha256((home / "bootstrap-state.gpg").read_bytes()).hexdigest() != report.get("bootstrapStateSha256"):
        raise SigningError("current_authorization_not_verified")
    import datetime as dt
    if dt.datetime.fromisoformat(report["expiresAt"]) <= dt.datetime.now(dt.timezone.utc):
        raise SigningError("fresh_verified_signing_run_required")
    gh(["variable", "set", "FREE_SIGNING_ENABLED", "--repo", REPOSITORY, "--body", "true"])
    print("Daily expiry checks enabled (10:37 Hong Kong time, subject to GitHub scheduling).")


def download(home, password):
    package, report = signed_artifact(home)
    encrypted = home / "signed.ipa.gpg"
    with zipfile.ZipFile(package) as archive:
        encrypted.write_bytes(archive.read("LumaPocket_signed.ipa.gpg"))
    destination = home / ("LumaPocket_" + report["version"] + "_signed.ipa")
    crypt(encrypted, destination, password, home, decrypt=True)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != report["sha256"]:
        raise SigningError("signed_ipa_digest_mismatch")
    print("Verified signed IPA: " + str(destination))
    print("Install/refresh on the registered iPhone. The cloud run does not install it remotely.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "authorize", "publish", "enable", "download", "disable"])
    parser.add_argument("--home", type=Path, default=HERE.parent / ".lumapocket-signing")
    parser.add_argument("--udid")
    parser.add_argument("--apple-id")
    parser.add_argument("--anisette-url", default="https://ani.sidestore.io")
    args = parser.parse_args()
    home = args.home.resolve()
    if home == HERE.parent or home == HERE:
        raise SigningError("private_subdirectory_required")
    if home.is_relative_to(HERE.parent) and not home.is_relative_to(HERE.parent / ".lumapocket-signing"):
        raise SigningError("use_ignored_private_state_directory")
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.command == "check":
        print(json.dumps(check(home / "tool")))
    elif args.command == "enable":
        enable(home)
    elif args.command == "disable":
        gh(["variable", "set", "FREE_SIGNING_ENABLED", "--repo", REPOSITORY, "--body", "false"])
        print("Daily signing disabled.")
    else:
        password = state_key(home, create=args.command == "authorize")
        if args.command == "authorize":
            authorize(home, args, password)
        elif args.command == "publish":
            publish(home, password)
        else:
            download(home, password)


if __name__ == "__main__":
    try:
        main()
    except SigningError as error:
        print("Signing helper stopped: " + str(error))
        sys.exit(1)
