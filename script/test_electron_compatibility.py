#!/usr/bin/env python3
"""CLI integration regressions for hosts without XCTest (macOS + clang required).

Build first: swift build --product AppDuoCLI
Run: python3 script/test_electron_compatibility.py
Override the binary with APPDUO_CLI if needed. All apps and data are temporary.
"""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CLI = Path(os.environ.get("APPDUO_CLI", REPO / ".build/debug/AppDuoCLI")).resolve()


def run(*args):
    result = subprocess.run([str(arg) for arg in args], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(f"Command failed ({result.returncode}): {args}\n{result.stdout}\n{result.stderr}")
    return result.stdout


class ElectronCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CLI.is_file():
            raise RuntimeError("Build AppDuoCLI first, or set APPDUO_CLI")
        cls.toolchain = tempfile.TemporaryDirectory(prefix="appduo-electron-fixtures-")
        cls.tools = Path(cls.toolchain.name)
        code = cls.tools / "fixture.c"
        code.write_text('#include <stdio.h>\nint main(int argc, char **argv) { puts(argv[0]); return 0; }\n')
        cls.executable = cls.tools / "Original"
        cls.library = cls.tools / "Electron Framework"
        run("/usr/bin/xcrun", "clang", "-Wl,-headerpad,0x1000", code, "-o", cls.executable)
        run("/usr/bin/xcrun", "clang", "-dynamiclib", code, "-o", cls.library)

    @classmethod
    def tearDownClass(cls):
        cls.toolchain.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="appduo-electron-regression-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "Source.app"
        self.state = self.root / "State"
        self.destination = self.state / "Apps/Clone.app"
        self.plist = self.source / "Contents/Info.plist"
        (self.source / "Contents/MacOS").mkdir(parents=True)
        shutil.copy2(self.executable, self.source / "Contents/MacOS/Original")
        self.write_plist(self.plist, {"CFBundleIdentifier": "com.atb.test", "CFBundleExecutable": "Original", "CFBundlePackageType": "APPL", "CFBundleName": "WorkBuddy"})

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def write_plist(path, values):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plistlib.dumps(values))

    def add_electron(self):
        framework = self.source / "Contents/Frameworks/Electron Framework.framework"
        version = framework / "Versions/A"
        (version / "Resources").mkdir(parents=True)
        shutil.copy2(self.library, version / "Electron Framework")
        self.write_plist(version / "Resources/Info.plist", {"CFBundleIdentifier": "com.atb.test.framework", "CFBundleExecutable": "Electron Framework", "CFBundlePackageType": "FMWK"})
        (framework / "Versions/Current").symlink_to("A")
        (framework / "Resources").symlink_to("Versions/Current/Resources")
        (framework / "Electron Framework").symlink_to("Versions/Current/Electron Framework")
        helper = self.source / "Contents/Frameworks/WorkBuddy Helper.app"
        (helper / "Contents/MacOS").mkdir(parents=True)
        shutil.copy2(self.executable, helper / "Contents/MacOS/WorkBuddy Helper")
        self.write_plist(helper / "Contents/Info.plist", {"CFBundleIdentifier": "com.atb.test.helper", "CFBundleExecutable": "WorkBuddy Helper", "CFBundlePackageType": "APPL"})
        return helper

    def clone(self):
        run(CLI, "clone", self.source, "--name", "Clone", "--display-name", "中文分身", "--root", self.state)
        return plistlib.loads((self.destination / "Contents/Info.plist").read_bytes())

    def verify(self):
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", self.destination)

    def test_electron_names_and_helpers_survive_create_and_update(self):
        source_helper = self.add_electron()
        original_plist = self.plist.read_bytes()
        info = self.clone()
        self.assertEqual(info["CFBundleName"], "WorkBuddy")
        self.assertEqual(info["CFBundleDisplayName"], "中文分身")
        helper = self.destination / "Contents/Frameworks/WorkBuddy Helper.app/Contents/MacOS/WorkBuddy Helper"
        self.assertTrue(helper.is_file())
        self.assertFalse(helper.is_symlink())
        self.assertFalse((self.destination / "Contents/MacOS/Clone").is_symlink())
        self.assertIn("/Contents/MacOS/Clone", run(self.destination / "Contents/MacOS" / info["CFBundleExecutable"]))
        marker = self.state / "Data/Clone/keep.txt"
        marker.write_text("existing profile")
        before = json.loads((self.state / "clones.json").read_text())[0]
        run(CLI, "update", "Clone", "--root", self.state)
        after = json.loads((self.state / "clones.json").read_text())[0]
        self.assertEqual(before["configuration"]["id"], after["configuration"]["id"])
        self.assertEqual(before["createdAt"], after["createdAt"])
        self.assertEqual(marker.read_text(), "existing profile")
        self.assertEqual(self.plist.read_bytes(), original_plist)
        self.assertTrue((source_helper / "Contents/MacOS/WorkBuddy Helper").is_file())
        self.assertFalse(helper.is_symlink())
        self.verify()

    def test_electron_missing_name_stays_missing(self):
        self.add_electron()
        original = plistlib.loads(self.plist.read_bytes())
        original.pop("CFBundleName")
        self.write_plist(self.plist, original)
        self.assertNotIn("CFBundleName", self.clone())
        self.verify()

    def test_native_process_naming_is_unchanged(self):
        helper = self.source / "Contents/Helpers/tool"
        helper.parent.mkdir(parents=True)
        shutil.copy2(self.executable, helper)
        self.assertEqual(self.clone()["CFBundleName"], "中文分身")
        self.assertTrue((self.destination / "Contents/Helpers/tool").is_symlink())
        self.assertTrue((self.destination / "Contents/Helpers/Clone-tool").is_file())
        self.verify()

    def test_legacy_workbuddy_environment_migration_preserves_overrides(self):
        self.add_electron()
        original = plistlib.loads(self.plist.read_bytes())
        original["CFBundleIdentifier"] = "com.tencent.workbuddy.mac"
        self.write_plist(self.plist, original)
        self.clone()
        record_file = self.state / "clones.json"
        records = json.loads(record_file.read_text())
        config = records[0]["configuration"]
        config["recipe"]["environment"] = {"HOME": "{{ATB_DATA_DIR}}/CustomHome"}
        config["recipe"]["arguments"] = ["--user-data-dir={{ATB_DATA_DIR}}"]
        record_file.write_text(json.dumps(records))
        marker = self.state / "Data/Clone/keep.txt"
        marker.write_text("do not delete")
        run(CLI, "update", "Clone", "--root", self.state)
        after = json.loads(record_file.read_text())[0]
        environment = after["configuration"]["recipe"]["environment"]
        self.assertEqual(environment["HOME"], "{{ATB_DATA_DIR}}/CustomHome")
        self.assertEqual(environment["WORKBUDDY_CONFIG_DIR"], "{{ATB_DATA_DIR}}/Config")
        self.assertEqual(environment["CODEBUDDY_CONFIG_DIR"], "{{ATB_DATA_DIR}}/Config")
        self.assertEqual(environment["WORKBUDDY_USER_DATA_DIR"], "{{ATB_DATA_DIR}}/UserData")
        self.assertEqual(after["createdAt"], records[0]["createdAt"])
        self.assertEqual(after["configuration"]["dataDirectory"], config["dataDirectory"])
        self.assertEqual(marker.read_text(), "do not delete")
        self.verify()


if __name__ == "__main__":
    unittest.main(verbosity=2)
