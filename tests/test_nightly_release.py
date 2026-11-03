"""验证官方编号与源码绑定、打包内容及本地发布边界。"""

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

from scripts import build_pipeline as pipeline
from scripts import upstream_release as upstream
from scripts.build_support import BuildSettings
from scripts.release_artifacts import createPackage, retainPackage, verifyDllImage

SOURCE_SHA = "d1461375aee4ec3f313170f8eaad12064eb542d9"
PINNED_TAG = f"nightly-01424-{SOURCE_SHA}"
LATER_TAG = f"nightly-01425-{SOURCE_SHA}"
ROOT = Path(__file__).resolve().parents[1]


class NightlyReleaseTests(unittest.TestCase):
    def testConflictingLocalPackageIsPreservedAndCandidateIsRetained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "REFramework-Nightly-01436.zip"
            temporary = root / "candidate.zip"
            package.write_bytes(b"existing-package")
            temporary.write_bytes(b"new-package")
            with self.assertRaises(ValueError):
                retainPackage(temporary, package, root)
            self.assertEqual(package.read_bytes(), b"existing-package")
            candidates = list((root / "outputs/build-candidates").glob("*.zip"))
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].read_bytes(), b"new-package")

    def testPinnedTagDeterminesBothNumberAndSourceWithoutNetwork(self):
        opener = Mock()
        release = upstream.resolveRelease({"UPSTREAM_RELEASE_TAG": PINNED_TAG}, opener)
        self.assertEqual((release.number, release.sourceSha), ("01424", SOURCE_SHA))
        opener.assert_not_called()

    def testInvalidPinnedTagsAndMismatchedShaStopBeforeNetwork(self):
        invalidTags = (
            "",
            " " + PINNED_TAG,
            PINNED_TAG + "\n",
            "prefix-" + PINNED_TAG,
            PINNED_TAG + "-suffix",
            "nightly-1424-" + SOURCE_SHA,
            "nightly-０１４２４-" + SOURCE_SHA,
            "nightly-01424-" + SOURCE_SHA.upper(),
        )
        for tag in invalidTags:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                upstream.resolveRelease({"UPSTREAM_RELEASE_TAG": tag}, Mock())
        with self.assertRaises(ValueError):
            upstream.resolveRelease({"UPSTREAM_RELEASE_TAG": PINNED_TAG, "UPSTREAM_SHA": "a" * 40})

    def testLatestReleaseAndFallbackBothKeepTheTagSourceSha(self):
        opener = Mock(return_value=io.BytesIO(json.dumps({"tag_name": LATER_TAG}).encode()))
        self.assertEqual(upstream.resolveRelease({}, opener).tag, LATER_TAG)
        tags = f"unrelated-object-sha\trefs/tags/{PINNED_TAG}\nother-sha\trefs/tags/{LATER_TAG}\n"
        with patch.object(upstream, "runCommand", return_value=tags):
            release = upstream.resolveRelease({}, Mock(side_effect=OSError("接口暂时不可用")))
        self.assertEqual((release.tag, release.sourceSha), (LATER_TAG, SOURCE_SHA))

    def testPackageCarriesTheSameSourceIdentityAndCorrectChecksum(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = BuildSettings(root, root / "source", root / "work", root / "output")
            dll = settings.workDirectory / "build/bin/REFramework/dinput8.dll"
            reward = root / "assets/wechat-reward-qr.jpg"
            licensePath = settings.sourceDirectory / "LICENSE"
            for path in (dll, reward, licensePath):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture-content")
            (root / "translations.txt").write_bytes(b"Enable=fixture")
            (root / "hash_dict.txt").write_bytes(b"12345678\tfixture")
            release = upstream.UpstreamRelease.fromTag(PINNED_TAG)
            package, checksum, digest = createPackage(settings, release, "REFramework")
            self.assertEqual(package.name, "REFramework-Nightly-01424.zip")
            self.assertEqual(digest, hashlib.sha256(package.read_bytes()).hexdigest())
            self.assertEqual(checksum.read_text("ascii"), f"{digest}  {package.name}\n")
            with ZipFile(package) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read("dinput8.dll"), dll.read_bytes())
                self.assertIn("LICENSE-REFramework.txt", archive.namelist())
                manifest = json.loads(archive.read("build-manifest.json"))
                self.assertEqual(manifest["upstreamSha"], SOURCE_SHA)
                self.assertEqual(
                    manifest["translationSha256"],
                    hashlib.sha256((root / "translations.txt").read_bytes()).hexdigest(),
                )

    def testNativePackageImageValidationRejectsWrongMachineAndIncompleteImages(self):
        image = bytearray(256)
        image[:2] = b"MZ"
        image[0x3C:0x40] = (0x80).to_bytes(4, "little")
        image[0x80:0x84] = b"PE\0\0"
        image[0x84:0x86] = (0x8664).to_bytes(2, "little")
        image[0x96:0x98] = (0x2000).to_bytes(2, "little")
        image[0x98:0x9A] = (0x20B).to_bytes(2, "little")
        verifyDllImage(image)
        image[0x84:0x86] = (0x14C).to_bytes(2, "little")
        for content in (image, b"incomplete"):
            with self.assertRaises(ValueError):
                verifyDllImage(content)

    def testLocalBuildDoesNotPublishUnlessExplicitlyRequested(self):
        release = upstream.UpstreamRelease.fromTag(PINNED_TAG)
        with (
            patch.object(pipeline, "resolveRelease", return_value=release),
            patch.object(pipeline, "buildLocalizedPackage", return_value=()),
            patch.object(pipeline, "publishPackage") as publish,
        ):
            self.assertEqual(pipeline.main([]), 0)
            publish.assert_not_called()

    def testCheckOnlyDoesNotBuildOrLoseChineseOutput(self):
        output = io.StringIO()
        release = upstream.UpstreamRelease.fromTag(PINNED_TAG)
        with (
            patch.object(pipeline, "resolveRelease", return_value=release),
            patch.object(pipeline, "buildLocalizedPackage") as build,
            redirect_stdout(output),
        ):
            self.assertEqual(pipeline.main(["--check-only"]), 0)
            build.assert_not_called()
        self.assertIn("官方版本", output.getvalue())
        self.assertIn(PINNED_TAG, output.getvalue())

    def testWorkflowPinsSourceAndTagAndDispatchesAfterSkippedBuild(self):
        workflow = (ROOT / ".github/workflows/build-release.yml").read_text("utf-8")
        self.assertIn("ref: $" + "{{ needs.decide.outputs.upstream_sha }}", workflow)
        self.assertIn("UPSTREAM_SHA: $" + "{{ needs.decide.outputs.upstream_sha }}", workflow)
        self.assertIn("UPSTREAM_RELEASE_TAG: $" + "{{ needs.decide.outputs.upstream_release_tag }}", workflow)
        self.assertIn("REF_OUTPUT_DIR: $" + "{{ github.workspace }}", workflow)
        self.assertIn("", workflow)
        self.assertIn("needs: [decide, build]", workflow)
        self.assertIn("if: always() && needs.decide.result == 'success'", workflow)


if __name__ == "__main__":
    unittest.main()
