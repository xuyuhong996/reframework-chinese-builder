"""重试尚未成功交接的 N网派发，不重新构建或直接上传文件。"""

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PENDING_MARKER = "<!-- nexus-dispatch: pending -->"
ACCEPTED_MARKER = "<!-- nexus-dispatch: accepted -->"
TAG_PATTERN = r"build-[0-9a-f]{12}"
REQUEST_TIMEOUT_SECONDS = 30
WORKFLOW = "publish-nexus.yml"


@dataclass(frozen=True)
class GitHubClient:
    repository: str
    token: str

    def request(self, path, method="GET", payload=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise ValueError("GitHub 仓库名称无效。")
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "REFramework-Chinese-Builder",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"https://api.github.com/repos/{self.repository}/{path}",
            data=data,
            headers=headers,
            method=method,
        )
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            content = response.read()
        return json.loads(content) if content else None


def findAcceptedRun(publisher, tag):
    page = 1
    while True:
        result = publisher.request(
            f"actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&per_page=100&page={page}"
        )
        runs = result["workflow_runs"]
        matches = [run for run in runs if run.get("display_title") == f"Nexus {tag}"]
        if matches:
            return matches[0]
        if len(runs) < 100:
            return None
        page += 1


def dispatchPending(public, publisher):
    try:
        release = public.request("releases/latest")
    except HTTPError as error:
        if error.code != 404:
            raise
        return "当前仓库尚无公开发布，无需派发。"
    notes = release.get("body") or ""
    if PENDING_MARKER not in notes:
        return "没有尚未交接的 N网派发。"
    tag = release["tag_name"]
    if release.get("draft") or release.get("prerelease") or not re.fullmatch(TAG_PATTERN, tag):
        raise ValueError("N网派发只处理已公开的正式构建标签。")
    existing = findAcceptedRun(publisher, tag)
    if existing is None:
        publisher.request(
            f"actions/workflows/{WORKFLOW}/dispatches",
            "POST",
            {"ref": "main", "inputs": {"release_tag": tag}},
        )
    # 交接后由私有仓库核对目标版本链；后续上传失败仍在私有仓库处理。
    public.request(
        f"releases/{release['id']}", "PATCH", {"body": notes.replace(PENDING_MARKER, ACCEPTED_MARKER)}
    )
    return f"N网工作流已接收 {tag}；相同标签不会重复交接。"


def main():
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not os.environ.get("NEXUS_PUBLISH_TOKEN"):
        message = "N网同步未启用：未配置专用调度令牌。"
        result = 0
    else:
        try:
            message = dispatchPending(
                GitHubClient(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"]),
                GitHubClient(os.environ["NEXUS_PUBLISH_REPOSITORY"], os.environ["NEXUS_PUBLISH_TOKEN"]),
            )
            result = 0
        except (OSError, ValueError, KeyError):
            message = "N网派发未完成；待办标记保留，下次检查会重试。请检查工作流权限及网络。"
            result = 1
    print(message)
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")
    return result


if __name__ == "__main__":
    sys.exit(main())
