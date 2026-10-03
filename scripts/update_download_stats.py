"""记录真实的 GitHub 汉化包下载量，并生成 README 使用的趋势图。"""

import argparse
import copy
import json
import math
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

API_BASE_URL = "https://api.github.com"
API_VERSION = "2026-03-10"
DEFAULT_REPOSITORY = "xuyuhong996/reframework-chinese-builder"
REQUEST_TIMEOUT_SECONDS = 30
PAGE_SIZE = 100
FIRST_PAGE = 1
ZERO_COUNT = 0
ONE_POINT = 1
DISPLAY_DAYS = 90
TIMEZONE_OFFSET_HOURS = 8
CHINA_TIMEZONE = timezone(timedelta(hours=TIMEZONE_OFFSET_HOURS))
ROOT_PATH = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT_PATH / "assets" / "download-history.json"
SVG_PATH = ROOT_PATH / "assets" / "downloads.svg"
METRIC_DESCRIPTION = "GitHub 汉化 ZIP 累计下载，含已记录历史包"
GRID_SEGMENTS = 4
NICE_STEPS = (1, 2, 2.5, 5, 10)
DECIMAL_BASE = 10
NUMBER_PRECISION = 2
MIDPOINT_DIVISOR = 2
CARD_WIDTH = 720
CARD_HEIGHT = 412
CARD_RADIUS = 20
CARD_PADDING = 32
CHART_LEFT = 78
CHART_RIGHT = 674
CHART_TOP = 152
CHART_BOTTOM = 292
DATE_LABEL_Y = 324
TITLE_Y = 48
SUBTITLE_Y = 78
LEGEND_Y = 119
FOOTER_Y = 359
DETAIL_Y = 386
LABEL_GAP = 12
POINT_RADIUS = 5
LINE_WIDTH = 3
GRID_WIDTH = 1
FONT_TITLE = 28
FONT_TOTAL = 42
FONT_BODY = 18
FONT_AXIS = 18
TEXT_BASELINE_OFFSET = 6
EMPTY_STATE_Y = 229
COLORS = {
    "background": "#f8fafc",
    "border": "#e2e8f0",
    "text": "#0f172a",
    "muted": "#64748b",
    "grid": "#e2e8f0",
    "accent": "#0891b2",
}


def fetchPage(url, token, opener):
    """只向 GitHub 官方接口发送凭据；失败时直接停止统计。"""
    parsedUrl = urlparse(url)
    if parsedUrl.scheme != "https" or parsedUrl.netloc != "api.github.com":
        raise ValueError("分页地址不是 GitHub 官方接口。")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "reframework-chinese-builder-download-stats",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        items = json.loads(response.read().decode("utf-8"))
        linkHeader = response.headers.get("Link", "")
    if not isinstance(items, list):
        raise TypeError("GitHub 接口没有返回列表，保留原有统计文件。")
    nextLink = re.search(r'<([^>]+)>;\s*rel="next"', linkHeader)
    return items, nextLink.group(ONE_POINT) if nextLink else None


def fetchItems(url, token, opener=urlopen):
    """遵循接口分页链接，避免只统计第一页发布。"""
    allItems = []
    visitedUrls = set()
    while url:
        if url in visitedUrls:
            raise ValueError("GitHub 分页链接重复，保留原有统计文件。")
        visitedUrls.add(url)
        items, nextUrl = fetchPage(url, token, opener)
        allItems.extend(items)
        url = nextUrl
    return allItems


def validateCount(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < ZERO_COUNT:
        raise ValueError("下载次数必须是非负整数。")
    return value


def readAssetCounts(releases):
    """只统计公开发布的 ZIP 包；校验文件和源码自动下载链接不计入。"""
    assetCounts = {}
    for release in releases:
        if release.get("draft", False):
            continue
        for asset in release["assets"]:
            if not asset["name"].lower().endswith(".zip"):
                continue
            if asset.get("state", "uploaded") != "uploaded":
                continue
            assetId = str(asset["id"])
            count = validateCount(asset["download_count"])
            previousCount = assetCounts.get(assetId, {}).get("downloadCount", ZERO_COUNT)
            assetCounts[assetId] = {
                "name": asset["name"],
                "downloadCount": max(previousCount, count),
            }
    return assetCounts


def fetchAssetCounts(repository, token, opener=urlopen):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("仓库名称必须采用 owner/repo 格式。")
    url = f"{API_BASE_URL}/repos/{repository}/releases?per_page={PAGE_SIZE}&page={FIRST_PAGE}"
    return readAssetCounts(fetchItems(url, token, opener))


def emptyHistory(repository):
    return {
        "repository": repository,
        "timezone": "Asia/Shanghai",
        "metric": METRIC_DESCRIPTION,
        "assets": {},
        "history": [],
    }


def validateHistory(data, repository):
    """损坏或不属于当前仓库的历史记录不得被静默重置。"""
    if data.get("repository") != repository:
        raise ValueError("统计历史所属仓库不匹配。")
    if not isinstance(data.get("assets"), dict) or not isinstance(data.get("history"), list):
        raise TypeError("统计历史结构不完整。")
    for assetId, asset in data["assets"].items():
        if not assetId.isdigit() or not isinstance(asset.get("name"), str):
            raise ValueError("历史资产信息不完整。")
        validateCount(asset["downloadCount"])
    dates = []
    for sample in data["history"]:
        sampleDate = date.fromisoformat(sample["date"]).isoformat()
        if sampleDate != sample["date"]:
            raise ValueError("历史日期必须采用 YYYY-MM-DD 格式。")
        dates.append(sampleDate)
        validateCount(sample["total"])
    if dates != sorted(set(dates)):
        raise ValueError("历史记录的日期重复或顺序错误。")
    if data["history"]:
        latestTotal = sum(asset["downloadCount"] for asset in data["assets"].values())
        if data["history"][-ONE_POINT]["total"] != latestTotal:
            raise ValueError("历史累计值与资产计数不一致。")
    return data


def readHistory(path, repository):
    if not path.exists():
        return emptyHistory(repository)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("统计历史必须是 JSON 对象。")
    return validateHistory(data, repository)


def updateHistory(previous, assetCounts, now):
    """同日覆盖采样点；删除旧包不会抹去已经观测到的下载次数。"""
    if now.tzinfo is None:
        raise ValueError("采样时间必须包含时区。")
    chinaTime = now.astimezone(CHINA_TIMEZONE)
    sampleDate = chinaTime.date().isoformat()
    result = copy.deepcopy(previous)
    if result["history"] and result["history"][-ONE_POINT]["date"] > sampleDate:
        raise ValueError("采样日期早于已有记录，保留原有历史。")
    for assetId, asset in assetCounts.items():
        previousCount = result["assets"].get(assetId, {}).get("downloadCount", ZERO_COUNT)
        result["assets"][assetId] = {
            "name": asset["name"],
            "downloadCount": max(previousCount, validateCount(asset["downloadCount"])),
        }
    total = sum(asset["downloadCount"] for asset in result["assets"].values())
    sample = {"date": sampleDate, "total": total}
    if result["history"] and result["history"][-ONE_POINT]["date"] == sampleDate:
        result["history"][-ONE_POINT] = sample
    else:
        result["history"].append(sample)
    result["updatedAt"] = chinaTime.isoformat(timespec="seconds")
    return result


def recentHistory(history):
    if not history:
        return []
    latestDate = date.fromisoformat(history[-ONE_POINT]["date"])
    startDate = latestDate - timedelta(days=DISPLAY_DAYS - ONE_POINT)
    return [sample for sample in history if date.fromisoformat(sample["date"]) >= startDate]


def chartScale(history):
    maxCount = max((sample["total"] for sample in history), default=ZERO_COUNT)
    targetStep = max(ONE_POINT, maxCount / GRID_SEGMENTS)
    magnitude = DECIMAL_BASE ** math.floor(math.log10(targetStep))
    step = next(value * magnitude for value in NICE_STEPS if value * magnitude >= targetStep)
    return int(step * GRID_SEGMENTS)


def textElement(position, value, size=FONT_BODY, attributes=""):
    x, y = position
    return f'<text x="{x}" y="{y}" font-size="{size}" {attributes}>{escape(str(value))}</text>'


def lineElement(start, end, color=COLORS["grid"]):
    return (
        f'<line x1="{start[ZERO_COUNT]}" y1="{start[ONE_POINT]}" '
        f'x2="{end[ZERO_COUNT]}" y2="{end[ONE_POINT]}" '
        f'stroke="{color}" stroke-width="{GRID_WIDTH}" />'
    )


def chartAxes(history, yMax):
    elements = []
    for index in range(GRID_SEGMENTS + ONE_POINT):
        fraction = index / GRID_SEGMENTS
        y = round(CHART_BOTTOM - fraction * (CHART_BOTTOM - CHART_TOP), NUMBER_PRECISION)
        count = int(fraction * yMax)
        elements.append(lineElement((CHART_LEFT, y), (CHART_RIGHT, y)))
        elements.append(textElement(
            (CHART_LEFT - LABEL_GAP, y + TEXT_BASELINE_OFFSET), f"{count:,}", FONT_AXIS,
            f'text-anchor="end" fill="{COLORS["muted"]}"',
        ))
    if len(history) == ONE_POINT:
        elements.append(textElement(
            ((CHART_LEFT + CHART_RIGHT) / MIDPOINT_DIVISOR, DATE_LABEL_Y),
            history[ZERO_COUNT]["date"], FONT_AXIS, 'text-anchor="middle"',
        ))
    elif history:
        elements.append(textElement((CHART_LEFT, DATE_LABEL_Y), history[ZERO_COUNT]["date"], FONT_AXIS))
        elements.append(textElement(
            (CHART_RIGHT, DATE_LABEL_Y), history[-ONE_POINT]["date"], FONT_AXIS, 'text-anchor="end"',
        ))
    return "\n".join(elements)


def chartPoints(history, yMax):
    firstDate = date.fromisoformat(history[ZERO_COUNT]["date"])
    daySpan = (date.fromisoformat(history[-ONE_POINT]["date"]) - firstDate).days
    points = []
    for sample in history:
        offset = (date.fromisoformat(sample["date"]) - firstDate).days
        fraction = offset / daySpan if daySpan else ONE_POINT / MIDPOINT_DIVISOR
        x = CHART_LEFT + fraction * (CHART_RIGHT - CHART_LEFT)
        y = CHART_BOTTOM - sample["total"] / yMax * (CHART_BOTTOM - CHART_TOP)
        points.append((round(x, NUMBER_PRECISION), round(y, NUMBER_PRECISION)))
    return points


def chartSeries(history, yMax):
    if not history:
        return textElement(
            ((CHART_LEFT + CHART_RIGHT) / MIDPOINT_DIVISOR, EMPTY_STATE_Y),
            "暂无下载记录", FONT_BODY, f'text-anchor="middle" fill="{COLORS["muted"]}"',
        )
    points = chartPoints(history, yMax)
    elements = []
    if len(points) > ONE_POINT:
        coordinates = " L ".join(f"{x},{y}" for x, y in points)
        elements.append(
            f'<path d="M {coordinates}" fill="none" stroke="{COLORS["accent"]}" '
            f'stroke-width="{LINE_WIDTH}" stroke-linejoin="round" stroke-linecap="round" />'
        )
    x, y = points[-ONE_POINT]
    elements.append(f'<circle cx="{x}" cy="{y}" r="{POINT_RADIUS}" fill="{COLORS["accent"]}" />')
    if len(points) == ONE_POINT:
        elements.append(textElement(
            ((CHART_LEFT + CHART_RIGHT) / MIDPOINT_DIVISOR, CHART_BOTTOM - FONT_BODY),
            "首日真实采样，后续每天更新", FONT_BODY,
            f'text-anchor="middle" fill="{COLORS["muted"]}"',
        ))
    return "\n".join(elements)


def chartHeader(data):
    history = data["history"]
    total = history[-ONE_POINT]["total"] if history else ZERO_COUNT
    elements = [textElement((CARD_PADDING, TITLE_Y), "汉化包下载趋势", FONT_TITLE, 'font-weight="700"')]
    elements.append(textElement(
        (CARD_PADDING, SUBTITLE_Y), f"最近 {DISPLAY_DAYS} 天的真实累计记录", FONT_BODY,
        f'fill="{COLORS["muted"]}"',
    ))
    elements.append(textElement(
        (CHART_RIGHT, TITLE_Y), f"{total:,}", FONT_TOTAL,
        f'text-anchor="end" font-weight="700" fill="{COLORS["accent"]}"',
    ))
    elements.append(textElement(
        (CHART_RIGHT, SUBTITLE_Y), "累计下载次数", FONT_BODY,
        f'text-anchor="end" fill="{COLORS["muted"]}"',
    ))
    elements.append(textElement((CHART_LEFT, LEGEND_Y), "累计汉化包下载", FONT_BODY, f'fill="{COLORS["accent"]}"'))
    return "\n".join(elements)


def chartFooter(data):
    history = data["history"]
    startDate = history[ZERO_COUNT]["date"] if history else "首次采样后"
    updatedDate = history[-ONE_POINT]["date"] if history else "暂无"
    elements = [textElement(
        (CARD_PADDING, FOOTER_Y), "仅统计 GitHub 汉化 ZIP，含已记录历史包的下载。", FONT_BODY,
        f'fill="{COLORS["muted"]}"',
    )]
    elements.append(textElement(
        (CARD_PADDING, DETAIL_Y), f"记录起点：{startDate} · 更新：{updatedDate}（北京时间）", FONT_BODY,
        f'fill="{COLORS["muted"]}"',
    ))
    return "\n".join(elements)


def renderSvg(data):
    history = recentHistory(data["history"])
    yMax = chartScale(history)
    description = (
        "每天记录 GitHub 发布中 ZIP 附件的累计下载次数。"
        "包含已观测后删除的历史包，不含校验文件、网盘和自动源码下载，不代表独立用户数。"
        "历史趋势从首次采样日起记录，缺少采样的日期没有补造下载数据。"
    )
    elements = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" '
            f'viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}" role="img" aria-labelledby="chart-title chart-desc">'
        ),
        '<title id="chart-title">REFramework 汉化包下载趋势</title>',
        f'<desc id="chart-desc">{escape(description)}</desc>',
        (
            f'<rect width="{CARD_WIDTH}" height="{CARD_HEIGHT}" rx="{CARD_RADIUS}" '
            f'fill="{COLORS["background"]}" stroke="{COLORS["border"]}" />'
        ),
        f'<g font-family="system-ui, -apple-system, Segoe UI, Microsoft YaHei, sans-serif" fill="{COLORS["text"]}">',
        chartHeader(data),
        chartAxes(history, yMax),
        chartSeries(history, yMax),
        chartFooter(data),
        "</g></svg>",
    ]
    return "\n".join(elements) + "\n"


def writeStats(data, historyPath, svgPath):
    """两个输出先生成再替换，接口或渲染失败时不改动现有历史。"""
    outputs = {
        historyPath: json.dumps(data, ensure_ascii=False, indent=NUMBER_PRECISION) + "\n",
        svgPath: renderSvg(data),
    }
    temporaryFiles = []
    try:
        for path, content in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
                output.write(content)
                temporaryFiles.append((Path(output.name), path))
        for temporaryPath, path in temporaryFiles:
            temporaryPath.replace(path)
    finally:
        for temporaryPath, _ in temporaryFiles:
            temporaryPath.unlink(missing_ok=True)


def collectStats(repository, token, paths, opener=urlopen):
    historyPath, svgPath = paths
    previous = readHistory(historyPath, repository)
    assetCounts = fetchAssetCounts(repository, token, opener)
    updated = updateHistory(previous, assetCounts, datetime.now(timezone.utc))
    writeStats(updated, historyPath, svgPath)
    return updated


def main():
    parser = argparse.ArgumentParser(description="采样 GitHub 汉化 ZIP 下载量并更新 SVG 趋势图。")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY))
    parser.add_argument("--history", type=Path, default=HISTORY_PATH)
    parser.add_argument("--svg", type=Path, default=SVG_PATH)
    args = parser.parse_args()
    try:
        data = collectStats(args.repository, os.environ.get("GH_TOKEN", ""), (args.history, args.svg))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"下载量统计失败，未提交统计更新：{error}", file=sys.stderr)
        return ONE_POINT
    print(f"已记录 {data['history'][-ONE_POINT]['date']}：累计 {data['history'][-ONE_POINT]['total']} 次下载。")
    return ZERO_COUNT


if __name__ == "__main__":
    raise SystemExit(main())
