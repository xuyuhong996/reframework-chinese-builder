"""执行工作流中的真实发布脚本，使用替身命令验证上传前置条件。"""

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "build-release.yml"
POWERSHELL_PATH = shutil.which("pwsh")
PACKAGE_CONTENT = b"localized-framework-fixture"
PACKAGE_HASH = hashlib.sha256(PACKAGE_CONTENT).hexdigest()
SOURCE_SHA = "d4611aef1d63effd3a736bdf9404ea702428017d"
BUILDER_SHA = "a" * 40
UPSTREAM_TAG = f"nightly-01433-{SOURCE_SHA}"
PACKAGE_NAME = "REFramework-Nightly-01433.zip"
RELEASE_PACKAGE_NAME = PACKAGE_NAME
HASH_PREFIX_LENGTH = 12
SUCCESS_EXIT_CODE = 0
FAILURE_EXIT_CODE = 1
OUTPUT_SPLIT_COUNT = 1
COMMAND_TIMEOUT_SECONDS = 30
FAKE_GH_SCRIPT = """
$ErrorActionPreference = 'Stop'
function git {
    Add-Content -LiteralPath $env:GH_CALLS_FILE -Value ("git " + ($args -join ' '))
    $exitCode = if ($args -contains 'push') { $env:GIT_PUSH_EXIT_CODE } else { $env:GIT_TAG_EXIT_CODE }
    $global:LASTEXITCODE = [int]$exitCode
}
function gh {
    $commandText = $args -join ' '
    Add-Content -LiteralPath $env:GH_CALLS_FILE -Value $commandText
    if ($args -contains 'view') {
        $global:LASTEXITCODE = [int]$env:GH_VIEW_EXIT_CODE
        return
    }
    $global:LASTEXITCODE = [int]$env:GH_CREATE_EXIT_CODE
}
"""


def extractStepScript(stepName):
    workflowText = WORKFLOW_PATH.read_text("utf-8")
    _, stepMarker, remainingText = workflowText.partition(f"      - name: {stepName}\n")
    if not stepMarker:
        raise ValueError(f"缺少工作流步骤：{stepName}")
    stepText = re.split(r"(?m)^      - |^  [A-Za-z_]+:", remainingText, maxsplit=1)[0]
    _, runMarker, scriptText = stepText.partition("        run: |\n")
    if not runMarker:
        raise ValueError(f"工作流步骤没有可执行脚本：{stepName}")
    return textwrap.dedent(scriptText)


def readOutputs(directory):
    outputPath = Path(directory) / "outputs.txt"
    return dict(line.split("=", OUTPUT_SPLIT_COUNT) for line in outputPath.read_text("utf-8").splitlines())


@unittest.skipUnless(POWERSHELL_PATH, "工作流脚本需要 PowerShell，Windows 构建环境会执行这些测试。")
class GitHubReleaseTests(unittest.TestCase):
    def runStep(self, directory, stepName, overrides=None):
        environment = (
            os.environ.copy()
            | {
                "GITHUB_REPOSITORY": "xuyuhong996/reframework-chinese-builder",
                "GITHUB_SHA": BUILDER_SHA,
                "UPSTREAM_RELEASE_TAG": UPSTREAM_TAG,
                "GITHUB_OUTPUT": str(Path(directory) / "outputs.txt"),
                "GITHUB_STEP_SUMMARY": str(Path(directory) / "summary.md"),
                "GH_CALLS_FILE": str(Path(directory) / "calls.txt"),
                "GH_VIEW_EXIT_CODE": str(FAILURE_EXIT_CODE),
                "GH_CREATE_EXIT_CODE": str(SUCCESS_EXIT_CODE),
                "GIT_TAG_EXIT_CODE": str(SUCCESS_EXIT_CODE),
                "GIT_PUSH_EXIT_CODE": str(SUCCESS_EXIT_CODE),
                "GH_TOKEN": "",
            }
            | (overrides or {})
        )
        scriptPath = Path(directory) / "workflow-step.ps1"
        scriptPath.write_text(FAKE_GH_SCRIPT + extractStepScript(stepName), "utf-8")
        return subprocess.run(
            [POWERSHELL_PATH, "-NoProfile", "-NonInteractive", "-File", str(scriptPath)],
            cwd=directory,
            env=environment,
            capture_output=True,
            encoding="utf-8",
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )

    def testSuccessfulNewReleaseUsesExactlyThePublishedPackageAndHash(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / PACKAGE_NAME).write_bytes(PACKAGE_CONTENT)
            result = self.runStep(directory, "Create historical release")
            self.assertEqual(result.returncode, SUCCESS_EXIT_CODE, result.stderr)
            outputs = readOutputs(directory)
            self.assertEqual(outputs["created"], "true")
            packagePath = Path(directory) / PACKAGE_NAME
            self.assertEqual(packagePath.name, RELEASE_PACKAGE_NAME)
            self.assertEqual(packagePath.read_bytes(), PACKAGE_CONTENT)
            calls = (Path(directory) / "calls.txt").read_text("utf-8")
            self.assertIn(f"release create build-{PACKAGE_HASH[:HASH_PREFIX_LENGTH]}", calls)
            self.assertIn(str(packagePath.resolve()).casefold(), calls.casefold())
            self.assertIn(f"tag --annotate build-{PACKAGE_HASH[:HASH_PREFIX_LENGTH]} {BUILDER_SHA}", calls)
            self.assertIn(f"git push origin refs/tags/build-{PACKAGE_HASH[:HASH_PREFIX_LENGTH]}", calls)
            self.assertIn("--verify-tag --latest", calls)
            self.assertIn("--title REFramework-Nightly-汉化-01433", calls)
            self.assertEqual(
                Path(f"{packagePath}.sha256").read_text("ascii").strip(),
                f"{PACKAGE_HASH}  {RELEASE_PACKAGE_NAME}",
            )

    def testExistingReleaseIsNotPublishedAgain(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / PACKAGE_NAME).write_bytes(PACKAGE_CONTENT)
            result = self.runStep(
                directory,
                "Create historical release",
                {
                    "GH_VIEW_EXIT_CODE": str(SUCCESS_EXIT_CODE),
                },
            )
            self.assertEqual(result.returncode, SUCCESS_EXIT_CODE, result.stderr)
            self.assertEqual(readOutputs(directory), {"created": "false"})
            self.assertNotIn("release create", (Path(directory) / "calls.txt").read_text("utf-8"))

    def testFailedGithubReleaseStopsTheWorkflow(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / PACKAGE_NAME).write_bytes(PACKAGE_CONTENT)
            result = self.runStep(
                directory,
                "Create historical release",
                {
                    "GH_CREATE_EXIT_CODE": str(FAILURE_EXIT_CODE),
                },
            )
            self.assertNotEqual(result.returncode, SUCCESS_EXIT_CODE)
            self.assertEqual(readOutputs(directory), {"created": "false"})
            self.assertIn("GitHub 新包发布失败", result.stderr)

    def testMissingPackageStopsBeforeAnyPublishCommand(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.runStep(directory, "Create historical release")
            self.assertNotEqual(result.returncode, SUCCESS_EXIT_CODE)
            self.assertEqual(readOutputs(directory), {"created": "false"})
            self.assertFalse((Path(directory) / "calls.txt").exists())

    def testDifferentNightlyAndLegacyPackagesAreNotPublished(self):
        for filename in (
            "REFramework-Nightly-01434.zip",
            "REFramework-01433.zip",
            "REF Nightly 01433 -前置汉化版.zip",
        ):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                (Path(directory) / filename).write_bytes(PACKAGE_CONTENT)
                result = self.runStep(directory, "Create historical release")
                self.assertNotEqual(result.returncode, SUCCESS_EXIT_CODE)
                self.assertEqual(readOutputs(directory), {"created": "false"})
                self.assertFalse((Path(directory) / "calls.txt").exists())

    def testTagFailureStopsBeforeCreatingARelease(self):
        for exitVariable in ("GIT_TAG_EXIT_CODE", "GIT_PUSH_EXIT_CODE"):
            with self.subTest(variable=exitVariable), tempfile.TemporaryDirectory() as directory:
                (Path(directory) / PACKAGE_NAME).write_bytes(PACKAGE_CONTENT)
                result = self.runStep(
                    directory,
                    "Create historical release",
                    {
                        exitVariable: str(FAILURE_EXIT_CODE),
                    },
                )
                self.assertNotEqual(result.returncode, SUCCESS_EXIT_CODE)
                self.assertEqual(readOutputs(directory), {"created": "false"})
                self.assertNotIn("release create", (Path(directory) / "calls.txt").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
