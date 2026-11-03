"""一次确定官方 Nightly 编号和源码提交，整个构建过程复用同一结果。"""

import json
import os
import re
from dataclasses import dataclass
from urllib.request import Request, urlopen

from scripts.build_support import runCommand

NIGHTLY_API = "https://api.github.com/repos/praydog/REFramework-nightly/releases/latest"
NIGHTLY_REPOSITORY = "https://github.com/praydog/REFramework-nightly.git"
SOURCE_REPOSITORY = "https://github.com/praydog/REFramework.git"
TAG_PATTERN = r"nightly-(?P<number>[0-9]{5})-(?P<sha>[0-9a-f]{40})"
REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class UpstreamRelease:
    tag: str
    number: str
    sourceSha: str

    @classmethod
    def fromTag(cls, tag):
        match = re.fullmatch(TAG_PATTERN, tag)
        if not match:
            raise ValueError("UPSTREAM_RELEASE_TAG 格式无效，无法确定官方编号与源码。")
        return cls(tag, match.group("number"), match.group("sha"))


def latestRelease(opener=urlopen):
    request = Request(NIGHTLY_API, headers={"User-Agent": "REFramework-Chinese-Builder"})
    with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return UpstreamRelease.fromTag(json.load(response)["tag_name"])


def latestRemoteTag():
    output = runCommand(["git", "ls-remote", "--tags", "--refs", NIGHTLY_REPOSITORY])
    tags = re.findall(r"refs/tags/(nightly-[0-9]{5}-[0-9a-f]{40})$", output, re.MULTILINE)
    releases = [UpstreamRelease.fromTag(tag) for tag in tags]
    if not releases:
        raise ValueError("无法获取有效的官方 Nightly 标签。")
    return max(releases, key=lambda release: int(release.number))


def resolveRelease(environment=None, opener=urlopen):
    environment = os.environ if environment is None else environment
    if "UPSTREAM_RELEASE_TAG" in environment:
        release = UpstreamRelease.fromTag(environment["UPSTREAM_RELEASE_TAG"])
    else:
        try:
            release = latestRelease(opener)
        except (OSError, ValueError, KeyError):
            release = latestRemoteTag()
    suppliedSha = environment.get("UPSTREAM_SHA")
    if suppliedSha is not None and suppliedSha != release.sourceSha:
        raise ValueError("UPSTREAM_SHA 与官方 Nightly 标签中的提交不一致，已停止构建。")
    return release
