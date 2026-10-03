"""验证真实下载采样、历史保存和趋势图的关键边界。"""

import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from xml.etree import ElementTree

from scripts import update_download_stats as stats

REPOSITORY = "xuyuhong996/reframework-chinese-builder"
FIRST_URL = f"{stats.API_BASE_URL}/repos/{REPOSITORY}/releases?per_page={stats.PAGE_SIZE}&page={stats.FIRST_PAGE}"
SECOND_URL = f"{stats.API_BASE_URL}/repos/{REPOSITORY}/releases?per_page={stats.PAGE_SIZE}&page=2"
SERVICE_UNAVAILABLE = 503
SVG_NAMESPACE = {"svg": "http://www.w3.org/2000/svg"}


class FakeResponse(io.BytesIO):
    def __init__(self, payload, nextUrl=None):
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.headers = {"Link": f'<{nextUrl}>; rel="next"'} if nextUrl else {}


def makeAsset(assetId, downloads, name="REFramework.zip"):
    return {"id": assetId, "download_count": downloads, "name": name, "state": "uploaded"}


def makeOpener(pages, calls=None):
    def opener(request, timeout):
        if calls is not None:
            calls.append((request.full_url, timeout))
        payload, nextUrl = pages[request.full_url]
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload, nextUrl)
    return opener


def makeHistory(assets=None, timestamp="2026-10-03T00:00:00+00:00"):
    return stats.updateHistory(
        stats.emptyHistory(REPOSITORY), assets or {}, datetime.fromisoformat(timestamp),
    )


class DownloadStatsTests(unittest.TestCase):
    def testPaginationIncludesPrereleasesAndExcludesDraftAndChecksum(self):
        pages = {
            FIRST_URL: ([
                {"draft": True, "assets": [makeAsset(100, 99)]},
                {"draft": False, "assets": [makeAsset(101, 12), makeAsset(102, 4, "package.zip.sha256")]},
            ], SECOND_URL),
            SECOND_URL: ([{"draft": False, "prerelease": True, "assets": [makeAsset(103, 5)]}], None),
        }
        calls = []
        result = stats.fetchAssetCounts(REPOSITORY, "", makeOpener(pages, calls))
        self.assertEqual(sum(asset["downloadCount"] for asset in result.values()), 17)
        self.assertEqual(set(result), {"101", "103"})
        self.assertEqual([url for url, _ in calls], [FIRST_URL, SECOND_URL])

    def testSameDayUpdatesOnlyOnePointAndDoesNotMutatePrevious(self):
        previous = makeHistory({"101": {"name": "REFramework.zip", "downloadCount": 7}})
        updated = stats.updateHistory(
            previous, {"101": {"name": "REFramework.zip", "downloadCount": 9}},
            datetime.fromisoformat("2026-10-03T03:00:00+00:00"),
        )
        self.assertEqual(updated["history"], [{"date": "2026-10-03", "total": 9}])
        self.assertEqual(previous["history"][0]["total"], 7)

    def testBeijingDateAndDeletedAssetsKeepObservedCounts(self):
        previous = makeHistory({"101": {"name": "REFramework.zip", "downloadCount": 7}})
        updated = stats.updateHistory(
            previous, {"102": {"name": "New.zip", "downloadCount": 3}},
            datetime.fromisoformat("2026-10-03T16:01:00+00:00"),
        )
        self.assertEqual(updated["history"][-1], {"date": "2026-10-04", "total": 10})
        self.assertEqual(updated["assets"]["101"]["downloadCount"], 7)
        self.assertTrue(updated["updatedAt"].endswith("+08:00"))

    def testLowerCounterDoesNotErasePreviouslyObservedDownloads(self):
        previous = makeHistory({"101": {"name": "REFramework.zip", "downloadCount": 7}})
        updated = stats.updateHistory(
            previous, {"101": {"name": "REFramework.zip", "downloadCount": 1}},
            datetime.fromisoformat("2026-10-04T00:00:00+00:00"),
        )
        self.assertEqual(updated["history"][-1]["total"], 7)

    def testEmptyAndSinglePointSvgRemainValidWithoutInventedLine(self):
        for data in [stats.emptyHistory(REPOSITORY), makeHistory({
            "101": {"name": "REFramework.zip", "downloadCount": 88},
        })]:
            with self.subTest(history=data["history"]):
                root = ElementTree.fromstring(stats.renderSvg(data))
                self.assertEqual(root.attrib["role"], "img")
                self.assertEqual(root.findall(".//svg:path", SVG_NAMESPACE), [])
                circles = root.findall(".//svg:circle", SVG_NAMESPACE)
                self.assertEqual(len(circles), len(data["history"]))
        self.assertIn("首日真实采样", stats.renderSvg(makeHistory()))

    def testSvgUsesRecentCalendarDaysAndRealDateSpacing(self):
        history = [
            {"date": "2026-01-01", "total": 1},
            {"date": "2026-10-01", "total": 7},
            {"date": "2026-10-02", "total": 8},
            {"date": "2026-10-05", "total": 10},
        ]
        data = stats.emptyHistory(REPOSITORY)
        data["history"] = history
        recent = stats.recentHistory(history)
        self.assertEqual(len(recent), 3)
        points = stats.chartPoints(recent, stats.chartScale(recent))
        actualOffset = points[1][0] - points[0][0]
        fullWidth = points[-1][0] - points[0][0]
        self.assertEqual(actualOffset / fullWidth, 0.25)
        root = ElementTree.fromstring(stats.renderSvg(data))
        self.assertEqual(len(root.findall(".//svg:path", SVG_NAMESPACE)), 1)
        self.assertEqual(len(data["history"]), 4)

    def testApiFailureOnLaterPageDoesNotOverwriteExistingFiles(self):
        pages = {
            FIRST_URL: ([{"draft": False, "assets": [makeAsset(101, 12)]}], SECOND_URL),
            SECOND_URL: (HTTPError(SECOND_URL, SERVICE_UNAVAILABLE, "暂时不可用", {}, None), None),
        }
        with tempfile.TemporaryDirectory() as directory:
            historyPath = Path(directory) / "history.json"
            svgPath = Path(directory) / "downloads.svg"
            stats.writeStats(makeHistory(), historyPath, svgPath)
            before = (historyPath.read_bytes(), svgPath.read_bytes())
            with self.assertRaises(HTTPError):
                stats.collectStats(REPOSITORY, "", (historyPath, svgPath), makeOpener(pages))
            self.assertEqual((historyPath.read_bytes(), svgPath.read_bytes()), before)

    def testCorruptOrForeignHistoryIsRejectedWithoutOverwriting(self):
        corrupt = makeHistory({"101": {"name": "REFramework.zip", "downloadCount": 7}})
        corrupt["history"][-1]["total"] = 3
        with self.assertRaises(ValueError):
            stats.validateHistory(corrupt, REPOSITORY)
        with tempfile.TemporaryDirectory() as directory:
            historyPath = Path(directory) / "history.json"
            svgPath = Path(directory) / "downloads.svg"
            historyPath.write_text("{broken", encoding="utf-8")
            svgPath.write_text("原有图表", encoding="utf-8")
            with self.assertRaises(ValueError):
                stats.collectStats(REPOSITORY, "", (historyPath, svgPath))
            self.assertEqual(historyPath.read_text(encoding="utf-8"), "{broken")
            self.assertEqual(svgPath.read_text(encoding="utf-8"), "原有图表")
        with self.assertRaises(ValueError):
            stats.validateHistory(makeHistory(), "other/repository")

    def testRepeatedPaginationLinkAndInvalidCounterFail(self):
        pages = {FIRST_URL: ([], FIRST_URL)}
        with self.assertRaises(ValueError):
            stats.fetchAssetCounts(REPOSITORY, "", makeOpener(pages))
        with self.assertRaises(ValueError):
            stats.readAssetCounts([{"assets": [makeAsset(101, -1)]}])
        with self.assertRaises(ValueError):
            stats.readAssetCounts([{"assets": [makeAsset(101, True)]}])

    def testSuccessfulCollectionPersistsJsonAndSvg(self):
        pages = {FIRST_URL: ([{"assets": [makeAsset(101, 12)]}], None)}
        with tempfile.TemporaryDirectory() as directory:
            historyPath = Path(directory) / "history.json"
            svgPath = Path(directory) / "downloads.svg"
            result = stats.collectStats(REPOSITORY, "", (historyPath, svgPath), makeOpener(pages))
            stored = json.loads(historyPath.read_text(encoding="utf-8"))
            self.assertEqual(stored, result)
            self.assertEqual(stored["history"][-1]["total"], 12)
            self.assertIsNotNone(ElementTree.fromstring(svgPath.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
