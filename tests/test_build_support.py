"""覆盖 Windows 英文环境下的中文构建输出。"""

import io
import unittest
from unittest.mock import patch

from scripts import build_support


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


if __name__ == "__main__":
    unittest.main()
