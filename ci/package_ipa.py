import hashlib
import json
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

config = json.loads(Path("build.json").read_text())
app = Path(os.environ["LUMAPOCKET_APP"]) / "build/ios/iphoneos/Runner.app"
assert app.is_dir()
info = plistlib.loads((app / "Info.plist").read_bytes())
assert info["CFBundleIdentifier"] == config["bundleIdentifier"]
assert not (app / "embedded.mobileprovision").exists()
executable = app / info["CFBundleExecutable"]
architectures = subprocess.check_output(["xcrun", "lipo", "-archs", str(executable)], text=True).strip()
assert "arm64" in architectures.split()
exports = subprocess.check_output(["xcrun", "dyld_info", "-exports", str(executable)], text=True)
for symbol in ["nai_qwen_count_json", "nai_qwen_count_free"]:
    assert symbol in exports, "Required offline tokenizer symbol was stripped: " + symbol
for framework in ["App", "Flutter"]:
    assert (app / "Frameworks" / (framework + ".framework") / framework).is_file()
library_report = None
if "bundledWorkflowLibrary" in config:
    assets = app / "Frameworks/App.framework/flutter_assets"
    library = assets / "assets/data/mobile_library/library.json"
    library_manifest = json.loads((assets / "assets/data/mobile_library/manifest.json").read_text())
    expected = config["bundledWorkflowLibrary"]
    assert hashlib.sha256(library.read_bytes()).hexdigest() == expected["librarySha256"] == library_manifest["librarySha256"]
    content = json.loads(library.read_text())
    assert len(content["artists"]) == expected["artists"]
    assert len(content["wildcards"]) == expected["wildcards"]
    assert len(library_manifest["images"]) == expected["bundledPreviewImages"]
    for name, sha256 in library_manifest["images"].items():
        assert name.startswith("assets/data/mobile_library/images/") and ".." not in Path(name).parts
        assert hashlib.sha256((assets / name).read_bytes()).hexdigest() == sha256
    library_report = {**expected, "verifiedInAppBundle": True}
out = Path(os.environ["RUNNER_TEMP"]) / "lumapocket-out"
out.mkdir(exist_ok=True)
payload = Path(os.environ["RUNNER_TEMP"]) / "lumapocket-payload" / "Payload"
payload.mkdir(parents=True, exist_ok=True)
shutil.copytree(app, payload / "Runner.app", symlinks=True)
version = str(info["CFBundleShortVersionString"]) + "+" + str(info["CFBundleVersion"])
ipa = out / ("LumaPocket_" + version + "_unsigned.ipa")
subprocess.run(["ditto", "-c", "-k", "--keepParent", str(payload), str(ipa)], check=True)
digest = hashlib.sha256(ipa.read_bytes()).hexdigest().upper()
(ipa.with_suffix(ipa.suffix + ".SHA256.txt")).write_text(digest + "  " + ipa.name + "\n")
report = {"displayName": info["CFBundleDisplayName"], "bundleIdentifier": info["CFBundleIdentifier"], "version": version, "architectures": architectures, "requiresLocalSigning": True, "tokenizerSymbolsExported": True, "sha256": digest, "bytes": ipa.stat().st_size}
if library_report is not None:
    report["bundledWorkflowLibrary"] = library_report
(out / "build-report.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
