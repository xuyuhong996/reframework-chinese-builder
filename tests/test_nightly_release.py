"""验证固定官方发布编号及工作流源码绑定，不执行联网或真实构建。"""

import importlib.util
import io
import os
import re
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "d1461375aee4ec3f313170f8eaad12064eb542d9"
PINNED_TAG = f"nightly-01424-{SOURCE_SHA}"
LATER_TAG = f"nightly-01425-{SOURCE_SHA}"
SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "nightly_build_script", REPOSITORY_ROOT / "build_chinese.py"
)
buildScript = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(buildScript)


class NightlyReleaseTests(unittest.TestCase):
    def testPinnedTagDoesNotQueryNetwork(self):
        with (
            patch.dict(os.environ, {"UPSTREAM_RELEASE_TAG": PINNED_TAG}, clear=True),
            patch.object(buildScript, "requests", create=True) as requestClient,
            patch.object(buildScript.subprocess, "run") as runCommand,
        ):
            requestClient.get.return_value = SimpleNamespace(
                status_code=200, json=lambda: {"tag_name": LATER_TAG}
            )
            self.assertEqual(buildScript.get_nightly_number(), "01424")
            requestClient.get.assert_not_called()
            runCommand.assert_not_called()

    def testInvalidPinnedTagFailsWithoutNetwork(self):
        invalidTags = (
            "", " " + PINNED_TAG, PINNED_TAG + "\n", "prefix-" + PINNED_TAG,
            PINNED_TAG + "-suffix", "nightly-1424-" + SOURCE_SHA,
            "nightly-001424-" + SOURCE_SHA, "nightly-０１４２４-" + SOURCE_SHA,
            "nightly-01424-" + SOURCE_SHA.upper(),
            "nightly-01424-" + SOURCE_SHA[:-1], "nightly-01424",
        )
        for suppliedTag in invalidTags:
            with (
                self.subTest(tag=suppliedTag),
                patch.dict(os.environ, {"UPSTREAM_RELEASE_TAG": suppliedTag}, clear=True),
            ):
                self.assertInvalidTagStopsBeforeNetwork()

    def assertInvalidTagStopsBeforeNetwork(self):
        errorOutput = io.StringIO()
        with (
            patch.object(buildScript, "requests", create=True) as requestClient,
            patch.object(buildScript.subprocess, "run") as runCommand,
        ):
            with redirect_stderr(errorOutput), self.assertRaises(SystemExit) as failure:
                buildScript.get_nightly_number()
            self.assertNotEqual(failure.exception.code, 0)
            self.assertIn("UPSTREAM_RELEASE_TAG 格式无效", errorOutput.getvalue())
            requestClient.get.assert_not_called()
            runCommand.assert_not_called()

    def testWithoutPinnedTagUsesLatestRelease(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(buildScript, "requests", create=True) as requestClient,
            patch.object(buildScript.subprocess, "run") as runCommand,
        ):
            requestClient.get.return_value = SimpleNamespace(
                status_code=200, json=lambda: {"tag_name": LATER_TAG}
            )
            self.assertEqual(buildScript.get_nightly_number(), "01425")
            requestClient.get.assert_called_once()
            runCommand.assert_not_called()

    def testWithoutPinnedTagUsesRemoteTagsWhenApiFails(self):
        remoteTags = f"{SOURCE_SHA}\trefs/tags/{PINNED_TAG}\n{SOURCE_SHA}\trefs/tags/{LATER_TAG}\n"
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(buildScript, "requests", create=True) as requestClient,
            patch.object(buildScript.subprocess, "run") as runCommand,
        ):
            requestClient.get.side_effect = RuntimeError("模拟官方接口暂时不可用")
            runCommand.return_value = SimpleNamespace(stdout=remoteTags.encode("utf-8"))
            self.assertEqual(buildScript.get_nightly_number(), "01425")
            runCommand.assert_called_once()

    def testWorkflowPinsSourceAndPackageToSameDecision(self):
        workflowText = (REPOSITORY_ROOT / ".github/workflows/build-release.yml").read_text("utf-8")
        decisionText, buildText = workflowText.split("\n  build:\n", 1)
        self.assertIn('"$upstream_release_tag" =~ ^nightly-([0-9]{5})-([0-9a-f]{40})$', decisionText)
        self.assertIn("upstream_sha=${BASH_REMATCH[2]}", decisionText)
        for outputName in ("upstream_release_tag", "upstream_sha"):
            self.assertIn(f'{outputName}: ${{{{ steps.interval.outputs.{outputName} }}}}', decisionText)
            self.assertIn(f'echo "{outputName}=${outputName}" >> "$GITHUB_OUTPUT"', decisionText)
        sourceStep, buildStep, releaseStep = self.getWorkflowSteps(buildText)
        self.assertIn("repository: praydog/REFramework", sourceStep)
        self.assertIn("ref: ${{ needs.decide.outputs.upstream_sha }}", sourceStep)
        self.assertIn("path: REFramework-src", sourceStep)
        self.assertIn("submodules: recursive", sourceStep)
        self.assertIn("UPSTREAM_SHA: ${{ needs.decide.outputs.upstream_sha }}", buildStep)
        expectedTag = "UPSTREAM_RELEASE_TAG: ${{ needs.decide.outputs.upstream_release_tag }}"
        self.assertIn(expectedTag, buildStep)
        self.assertIn(expectedTag, releaseStep)

    def getWorkflowSteps(self, buildText):
        def findStep(stepName):
            pattern = rf"(?ms)^      - name: {re.escape(stepName)}\n.*?(?=^      - |\Z)"
            foundStep = re.search(pattern, buildText)
            self.assertIsNotNone(foundStep, f"缺少工作流步骤：{stepName}")
            return foundStep.group()

        return (
            findStep("Checkout matching official source"),
            findStep("Build localized ZIP"),
            findStep("Create historical release"),
        )


if __name__ == "__main__":
    unittest.main()
