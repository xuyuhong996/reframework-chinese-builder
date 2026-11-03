"""从当前仓库识别发布归属，不把项目原作者地址当作发布目标。"""

import re
from urllib.parse import urlsplit

from scripts.build_support import runCommand

REPOSITORY_PATTERN = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"


def repositoryFromRemote(remote):
    if remote.startswith("git@github.com:"):
        repository = remote.removeprefix("git@github.com:")
    else:
        parsed = urlsplit(remote)
        if parsed.scheme not in ("https", "ssh") or parsed.hostname != "github.com":
            raise ValueError("发布需要当前仓库具有明确的 GitHub origin 地址。")
        if parsed.query or parsed.fragment:
            raise ValueError("GitHub origin 地址不能带查询参数或片段。")
        repository = parsed.path.lstrip("/")
    repository = repository.rstrip("/").removesuffix(".git")
    if not re.fullmatch(REPOSITORY_PATTERN, repository):
        raise ValueError("无法从 origin 地址识别唯一的 GitHub 仓库。")
    return repository


def currentRepository(directory, required=True):
    try:
        remote = runCommand(["git", "remote", "get-url", "origin"], directory)
        return repositoryFromRemote(remote)
    except (OSError, RuntimeError, ValueError):
        if required:
            raise ValueError("无法识别发布目标；请在自己的 GitHub 克隆仓库中发布。") from None
        return None
