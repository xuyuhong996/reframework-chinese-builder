"""新成品发布后通知私有发布端，N网密钥与上传逻辑留在私有仓库。"""

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

SOURCE_REPOSITORY = "xuyuhong996/reframework-chinese-builder"
PUBLISH_REPOSITORY = "xuyuhong996/reframework-nexus-publisher"
SOURCE_RELEASE_URL = f"https://api.github.com/repos/{SOURCE_REPOSITORY}/releases"
DISPATCH_URL = (
    f"https://api.github.com/repos/{PUBLISH_REPOSITORY}/actions/workflows/publish-nexus.yml/dispatches"
)
PUBLISH_RUN_PREFIX = f"https://github.com/{PUBLISH_REPOSITORY}/actions/runs/"
TAG_PATTERN = r"build-[0-9a-f]{12}"
API_VERSION = "2026-03-10"
REQUEST_TIMEOUT_SECONDS = 30
EXPECTED_PACKAGE_COUNT = 1
HASH_PREFIX_LENGTH = 12
SUCCESS_EXIT_CODE = 0
FAILURE_EXIT_CODE = 1


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


openRequest = build_opener(NoRedirectHandler()).open


@dataclass(frozen=True)
class NotifySettings:
    releaseTag: str
    publishToken: str
    sourceToken: str = ""
    checkOnly: bool = False


def report(message):
    print(message)
    summaryPath = os.environ.get("GITHUB_STEP_SUMMARY")
    if summaryPath:
        with Path(summaryPath).open("a", encoding="utf-8") as summary:
            summary.write(message + "\n\n")


def requestHeaders(token):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "reframework-chinese-builder",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def validateSettings(settings):
    if settings.releaseTag and not re.fullmatch(TAG_PATTERN, settings.releaseTag):
        raise ValueError("通知的发布标签格式无效。")
    if not settings.publishToken.strip():
        raise ValueError("缺少 NEXUS_PUBLISH_TOKEN，无法通知私有发布项目。")
    if any(
        character in token for token in (settings.publishToken, settings.sourceToken) for character in "\r\n"
    ):
        raise ValueError("GitHub 凭据格式无效。")


def readRelease(settings, opener):
    suffix = f"tags/{settings.releaseTag}" if settings.releaseTag else "latest"
    request = Request(f"{SOURCE_RELEASE_URL}/{suffix}", headers=requestHeaders(settings.sourceToken))
    with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        release = json.load(response)
    tag = release.get("tag_name", "")
    if not isinstance(tag, str) or not re.fullmatch(TAG_PATTERN, tag):
        raise ValueError("公开成品的发布标签无效。")
    if settings.releaseTag and tag != settings.releaseTag:
        raise ValueError("成品标签与本次通知不一致。")
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("草稿和测试发布不能通知 N网正式同步。")
    title = re.fullmatch(r"REFramework-Nightly-汉化-([0-9]{5})", release.get("name") or "")
    if not title:
        raise ValueError("通知对象不是正式汉化成品。")
    packageName = f"REFramework-Nightly-{title.group(1)}.zip"
    packages = [asset for asset in release.get("assets", []) if asset.get("name") == packageName]
    if len(packages) != EXPECTED_PACKAGE_COUNT or packages[0].get("state") != "uploaded":
        raise ValueError("成品 ZIP 尚未完整发布，停止通知。")
    digest = packages[0].get("digest") or ""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or tag != f"build-{digest[7:][:HASH_PREFIX_LENGTH]}":
        raise ValueError("成品摘要与发布标签不一致，停止通知。")
    return tag


def notifyNexus(settings, opener=openRequest):
    validateSettings(settings)
    tag = readRelease(settings, opener)
    # 版本标签用于追踪；发布端自主读取最新成品，迟到的旧通知不会要求回退。
    payload = {"ref": "main", "inputs": {"source_tag": tag, "check_only": str(settings.checkOnly).lower()}}
    request = Request(
        DISPATCH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={**requestHeaders(settings.publishToken), "Content-Type": "application/json"},
        method="POST",
    )
    # 写入结果未知时不盲目重发；可查私有运行记录，定时检查继续负责补漏。
    with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        result = json.load(response)
    runId = result.get("workflow_run_id")
    if type(runId) is not int or runId <= 0 or result.get("html_url") != f"{PUBLISH_RUN_PREFIX}{runId}":
        raise ValueError("通知已提交但运行标识未确认，请先核对私有项目记录，勿盲目重复通知。")
    mode = "仅检查版本，不上传" if settings.checkOnly else "同步最新成品"
    report(f"成品 `{tag}` 的通知已接收（{mode}）：[查看私有发布任务]({result['html_url']})。")
    report("通知成功与 N网上传成功分别记录；最终结果以私有任务的回读核验为准。")
    return result


def main():
    try:
        checkOnly = os.environ.get("CHECK_ONLY", "false").lower()
        if checkOnly not in ("true", "false"):
            raise ValueError("仅检查参数必须为 true 或 false。")
        settings = NotifySettings(
            os.environ.get("RELEASE_TAG", "").strip(),
            os.environ.get("NEXUS_PUBLISH_TOKEN", ""),
            os.environ.get("GITHUB_TOKEN", ""),
            checkOnly == "true",
        )
        notifyNexus(settings)
    except HTTPError as error:
        report(f"N网通知失败：GitHub 返回 HTTP {error.code}，请检查通知凭据权限或工作流状态。")
        error.close()
        return FAILURE_EXIT_CODE
    except ValueError as error:
        report(f"N网通知失败：{error}")
        return FAILURE_EXIT_CODE
    except (OSError, KeyError, TypeError):
        report("N网通知结果未确认，请先核对私有任务记录；定时检查仍会补漏，本任务不自动重放通知。")
        return FAILURE_EXIT_CODE
    return SUCCESS_EXIT_CODE


if __name__ == "__main__":
    sys.exit(main())
