"""覆盖副本构建、发布和署名归属，禁止默认发布到原作者仓库。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import localization_identity as identity
from scripts import release_artifacts as artifacts
from scripts import repository_identity as repository
from scripts.build_support import BuildSettings
from scripts.upstream_release import UpstreamRelease

FORK_REPOSITORY = "another-owner/chinese-builder"
FORK_URL = f"https://github.com/{FORK_REPOSITORY}"
BUILDER_SHA = "b" * 40
RELEASE = UpstreamRelease.fromTag("nightly-01436-" + "a" * 40)


class RepositoryIdentityTests(unittest.TestCase):
    def testHttpsAndSshOriginsBothResolveTheForkRepository(self):
        for remote in (
            FORK_URL + ".git/",
            FORK_URL + ".git",
            f"git@github.com:{FORK_REPOSITORY}.git",
            f"ssh://git@github.com/{FORK_REPOSITORY}.git",
        ):
            self.assertEqual(repository.repositoryFromRemote(remote), FORK_REPOSITORY)

    def testAmbiguousOrNonGithubOriginsCannotBecomePublicationTargets(self):
        for remote in (
            "",
            "/local/repository",
            "https://example.com/owner/repo",
            FORK_URL + "/extra",
            FORK_URL + "?token=secret",
        ):
            with self.subTest(remote=remote), self.assertRaises(ValueError):
                repository.repositoryFromRemote(remote)

    def testExplicitPublicationUsesTheForkAndDoesNotPushSource(self):
        root = Path("fixture")
        settings = BuildSettings(root, root / "source", root / "work", root / "dist")
        artifact = (root / "package.zip", root / "package.sha256", "a" * 64)

        def command(arguments, cwd=None):
            return BUILDER_SHA if arguments[:3] == ["git", "rev-parse", "HEAD"] else ""

        with (
            patch.object(artifacts, "currentRepository", return_value=FORK_REPOSITORY),
            patch.object(artifacts, "runCommand", side_effect=command) as run,
        ):
            artifacts.publishPackage(artifact, RELEASE, settings)
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[arguments.index("--repo") + 1], FORK_REPOSITORY)
        self.assertEqual(arguments[arguments.index("--target") + 1], BUILDER_SHA)
        self.assertFalse(any("push" in call.args[0] for call in run.call_args_list))

    def testForkIdentityPreservesOriginalAuthorAndShowsActualBuildRepository(self):
        with tempfile.TemporaryDirectory() as directory:
            header = identity.writeBuildIdentity(directory, RELEASE.number, projectUrl=FORK_URL).read_text(
                "utf-8"
            )
        self.assertIn(f"汉化作者：{identity.LOCALIZATION_AUTHOR}", header)
        self.assertIn(FORK_URL, header)


if __name__ == "__main__":
    unittest.main()
