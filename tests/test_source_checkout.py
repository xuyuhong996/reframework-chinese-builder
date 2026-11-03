"""验证本地构建按指定提交取源码，遇到已有修改时保留文件。"""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import source_checkout as checkout
from scripts.build_support import BuildSettings
from scripts.upstream_release import SOURCE_REPOSITORY, UpstreamRelease

SOURCE_SHA = "a" * 40
RELEASE = UpstreamRelease.fromTag(f"nightly-01436-{SOURCE_SHA}")


class SourceCheckoutTests(unittest.TestCase):
    def testCheckoutUsesTheExactNightlyShaWithoutResetOrClean(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "source.txt").write_text("保留源码", encoding="utf-8")
            settings = BuildSettings(root, source, root / "work", root / "output")
            with (
                patch.object(checkout, "initializeSource", return_value=True),
                patch.object(checkout, "runCommand", return_value=SOURCE_SHA) as command,
            ):
                checkout.checkoutSource(settings, RELEASE)
            arguments = [call.args[0] for call in command.call_args_list]
            self.assertIn(["git", "fetch", "--depth", "1", "origin", SOURCE_SHA], arguments)
            self.assertIn(["git", "checkout", "--detach", SOURCE_SHA], arguments)
            self.assertFalse(
                any("reset" in items or "clean" in items or "master" in items for items in arguments)
            )
            self.assertEqual((settings.workDirectory / "source.txt").read_text("utf-8"), "保留源码")

    def testDirtySourceAndNonRepositoryDirectoryArePreserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            file = directory / "existing.txt"
            file.write_text("原有修改", encoding="utf-8")
            with self.assertRaises(ValueError):
                checkout.initializeSource(directory)
            subprocess.run(["git", "init", "--quiet", str(directory)], check=True)
            subprocess.run(
                ["git", "-C", str(directory), "remote", "add", "origin", SOURCE_REPOSITORY], check=True
            )
            with self.assertRaises(ValueError):
                checkout.initializeSource(directory)
            self.assertEqual(file.read_text("utf-8"), "原有修改")


if __name__ == "__main__":
    unittest.main()
