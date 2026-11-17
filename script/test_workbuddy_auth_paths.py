#!/usr/bin/env python3
"""Verify shipped WorkBuddy auth-path functions with two temporary AppDuo clones.

Usage: python3 script/test_workbuddy_auth_paths.py [WORKBUDDY_APP]
Requires macOS, clang, node, and a built AppDuoCLI (override APPDUO_CLI).
Only reads vendor code, not account files. All session/logout fixtures are fake
and created beneath a temporary directory. Does NOT test two real logins.
"""
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
CLI = Path(os.environ.get("APPDUO_CLI", REPO / ".build/debug/AppDuoCLI")).resolve()


def run(*args, env=None):
    result = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, env=env)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def read_asar(archive, names):
    with archive.open("rb") as stream:
        _, header_size, _, string_size = struct.unpack("<4I", stream.read(16))
        header = json.loads(stream.read(string_size))
        result = {}
        for name in names:
            item = header
            for part in name.split("/"):
                item = item["files"][part]
            if item.get("unpacked"):
                result[name] = Path(str(archive) + ".unpacked", name).read_text()
            else:
                stream.seek(8 + header_size + int(item["offset"]))
                result[name] = stream.read(item["size"]).decode()
        return result


def block(source, marker):
    """Extract these known vendor functions; fail closed if their layout changes.

    Their literal strings contain no unbalanced braces. This intentionally isn't
    a general JavaScript parser and is only used against the tested functions.
    """
    if source.count(marker) != 1:
        raise RuntimeError(f"Vendor layout changed: expected one {marker!r}")
    start = source.index(marker)
    depth = 1
    for end in range(start + len(marker), len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise RuntimeError(f"Unterminated vendor function: {marker}")


def main():
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node is required")
    app = Path(sys.argv[1] if len(sys.argv) > 1 else "/Applications/WorkBuddy.app")
    names = ["main/module-base.js", "main/file-authentication-storage.js",
             "main/workbuddy-product-config.js", "main/legacy-auth-session-migrator.js"]
    sources = read_asar(app / "Contents/Resources/app.asar", names)
    functions = [
        block(sources[names[0]], "getBasePath(){"),
        block(sources[names[1]], "async getAuthSavePath(){"),
        block(sources[names[2]], "function getSharedAuthDirectory(){"),
        block(sources[names[3]], "function getLegacyWorkbuddyIdeVscdbPath(e={}){"),
    ]
    with tempfile.TemporaryDirectory(prefix="appduo-workbuddy-auth-paths-") as temporary:
        root = Path(temporary)
        source = root / "Source.app"
        (source / "Contents/MacOS").mkdir(parents=True)
        (source / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "com.tencent.workbuddy.mac", "CFBundleName": "WorkBuddy",
            "CFBundleExecutable": "Original", "CFBundlePackageType": "APPL"}))
        c = root / "home.c"
        c.write_text('#include <stdio.h>\n#include <stdlib.h>\nint main(void) { puts(getenv("HOME")); return 0; }\n')
        run("/usr/bin/xcrun", "clang", c, "-o", source / "Contents/MacOS/Original")
        probe = root / "paths.cjs"
        probe.write_text("""
const os = require('node:os'), path = require('node:path');
const vn = os, yn = path, D = {jn: 'CodeBuddyExtension'}, s = path, o = os, r = os, i = path;
const getWorkbuddyAuthenticationConfiguration = () => ({id: 'appduo-test-account'});
const base = ({%s}).getBasePath();
const auth = ({%s}).getAuthSavePath;
%s
%s
(async () => console.log(JSON.stringify({
  auth: await auth.call({filePathService: {sharedDataPath: path.join(base, 'Data', 'Public')}}),
  productAuth: path.join(getSharedAuthDirectory(), 'appduo-test-account.info'),
  legacy: getLegacyWorkbuddyIdeVscdbPath()
})))().catch(e => {console.error(e); process.exitCode=1;});
""" % tuple(functions))
        homes = [root / "OriginalHome"]
        homes[0].mkdir()
        for name in ("Account A", "Account B"):
            run(CLI, "clone", source, "--name", name, "--root", root / "State")
            clone = root / "State/Apps" / (name + ".app")
            metadata = plistlib.loads((clone / "Contents/Info.plist").read_bytes())
            home = Path(run(clone / "Contents/MacOS" / metadata["CFBundleExecutable"]).strip())
            if home != root / "State/Data" / name / "Home":
                raise AssertionError("Clone launcher did not isolate HOME")
            homes.append(home)
        paths = []
        for home in homes:
            environment = dict(os.environ, HOME=str(home))
            environment.pop("ELECTRON_RUN_AS_NODE", None)
            resolved = json.loads(run(node, probe, env=environment))
            if resolved["auth"] != resolved["productAuth"]:
                raise AssertionError("Auth service and product config disagree")
            for value in resolved.values():
                Path(value).relative_to(home)
            paths.append(resolved)
        assert len({p["auth"] for p in paths}) == 3
        assert len({p["legacy"] for p in paths}) == 3
        # Exercise login files and logout markers, never real tokens or accounts.
        auth_files = [Path(p["auth"]) for p in paths]
        markers = [Path(str(p) + ".logged-out") for p in auth_files]
        for index, file in enumerate(auth_files):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(json.dumps({"fixture": f"fake-account-{index}"}))
        before = [p.read_bytes() for p in auth_files]
        markers[1].write_text("fake logout of Account A")
        auth_files[1].unlink()
        assert auth_files[0].read_bytes() == before[0]
        assert auth_files[2].read_bytes() == before[2]
        assert not markers[0].exists() and not markers[2].exists()
        print("PASS: shipped FilePathService, auth storage, product config and legacy paths use separate HOMEs")
        print("PASS: two native clone launchers keep separate auth files and logout markers")
        print("PASS: fake logout of clone A leaves fake original and clone B sessions untouched")
        print("Boundary: no real credentials read; no real account login/logout performed")


if __name__ == "__main__":
    main()
