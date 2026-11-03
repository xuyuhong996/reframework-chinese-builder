"""覆盖 Windows 英文环境下的中文构建输出。"""

import io
import unittest
from unittest.mock import patch

from scripts import build_support, release_artifacts


class BuildSupportTests(unittest.TestCase):
    def testChineseLogDoesNotFailOnWindowsAnsiStreams(self):
        output = io.BytesIO()
        stream = io.TextIOWrapper(output, encoding="cp1252")
        try:
            with patch("sys.stdout", stream):
                build_support.log("词库构建完成")
            self.assertIn("词库构建完成", output.getvalue().decode("utf-8"))
        finally:
            stream.detach()

    def testPackageVerificationCanWriteToWindowsAnsiStreams(self):
        output = io.BytesIO()
        stream = io.TextIOWrapper(output, encoding="cp1252")
        arguments = [
            "verify",
            "candidate.zip",
            "--upstream-tag",
            "nightly-01436-" + "a" * 40,
            "--builder-sha",
            "b" * 40,
        ]
        try:
            with (
                patch("sys.stdout", stream),
                patch("sys.argv", arguments),
                patch.object(release_artifacts, "buildSourceIdentity", return_value={}),
                patch.object(release_artifacts, "verifyPackage"),
            ):
                release_artifacts.main()
            self.assertIn("验证通过", output.getvalue().decode("utf-8"))
        finally:
            stream.detach()


if __name__ == "__main__":
    unittest.main()
