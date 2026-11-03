"""验证同一动态库的页面归属、未知游戏隐藏行为及旧上游兼容。"""

import json
import tempfile
import unittest
from pathlib import Path

from scripts import nexus_links as links
from scripts.localization_identity import writeBuildIdentity

PAGES = {
    "MHWILDS": "https://www.nexusmods.com/monsterhunterwilds/mods/5269",
    "MHRISE": "https://www.nexusmods.com/monsterhunterrise/mods/4057",
    "RE2": "https://www.nexusmods.com/residentevil22019/mods/3122",
}
GAME_HEADER = """#pragma once
namespace sdk {
// 测试保留已发布源码的枚举结构与行尾注释形式。
enum class GameID : uint8_t {
    Unknown = 0,
    RE2,
    MHRISE, // 崛起
    MHWILDS, /* 荒野 */
    SF6,
    Count
};
}
"""
NIGHTLY_NUMBER = "01436"


def writeGameHeader(directory, content=GAME_HEADER):
    path = Path(directory) / links.GAME_IDENTITY_HEADER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def writeConfig(directory, config):
    path = Path(directory) / "nexus-pages.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class NexusLinkTests(unittest.TestCase):
    def testPublicPagesContainOnlyCanonicalPublicUrls(self):
        pages = links.loadNexusPages()
        for game, url in PAGES.items():
            self.assertEqual(pages[game], url)
        self.assertEqual(len(pages.values()), len(set(pages.values())))

    def testEachRuntimeGameUsesItsOwnPageInOneSelector(self):
        with tempfile.TemporaryDirectory() as directory:
            writeGameHeader(directory)
            code = links.buildNexusLinkCode(directory, PAGES)
        self.assertIn("#include <sdk/GameIdentity.hpp>", code)
        self.assertIn("nexusUrlForGame(sdk::GameIdentity::get().game())", code)
        for game, url in PAGES.items():
            self.assertIn(f'case sdk::GameID::{game}: return "{url}";', code)
        self.assertIn("default: return nullptr;", code)
        self.assertIn("if (const auto* url = getNexusProjectUrl(); url != nullptr)", code)
        self.assertNotIn("#if defined(", code)

    def testUnconfiguredGamesCannotFallBackToTheWildsPage(self):
        with tempfile.TemporaryDirectory() as directory:
            writeGameHeader(directory)
            code = links.buildNexusLinkCode(directory, {"MHRISE": PAGES["MHRISE"]})
        self.assertNotIn("case sdk::GameID::MHWILDS:", code)
        self.assertNotIn("case sdk::GameID::SF6:", code)
        self.assertNotIn(PAGES["MHWILDS"], code)
        self.assertIn("default: return nullptr;", code)

    def testOlderRuntimeEnumsDoNotReferenceUnavailableGameMembers(self):
        olderHeader = "enum class GameID { Unknown = 0, RE2, Count };"
        with tempfile.TemporaryDirectory() as directory:
            writeGameHeader(directory, olderHeader)
            code = links.buildNexusLinkCode(directory, PAGES)
        self.assertIn("case sdk::GameID::RE2:", code)
        self.assertNotIn("sdk::GameID::MHWILDS", code)
        self.assertNotIn("sdk::GameID::MHRISE", code)
        self.assertIn("default: return nullptr;", code)

    def testLegacySourcesUseOnlyTheMatchingCompileTimeGameMacro(self):
        with tempfile.TemporaryDirectory() as directory:
            code = links.buildNexusLinkCode(directory, PAGES)
        for game, url in PAGES.items():
            self.assertIn(f'defined({game})\n        return "{url}";', code)
        self.assertIn("#else\n        return nullptr;\n#endif", code)
        self.assertNotIn("sdk::", code)
        self.assertNotIn("#include <sdk/GameIdentity.hpp>", code)

    def testEmptyConfigurationHidesTheLinkForBothSourceLayouts(self):
        with tempfile.TemporaryDirectory() as directory:
            legacyCode = links.buildNexusLinkCode(directory, {})
            writeGameHeader(directory)
            runtimeCode = links.buildNexusLinkCode(directory, {})
        for code in (legacyCode, runtimeCode):
            self.assertIn("return nullptr;", code)
            self.assertNotIn("nexusmods.com", code)

    def testGameHeaderParserIgnoresCommentsAndPreservesMembers(self):
        with tempfile.TemporaryDirectory() as directory:
            writeGameHeader(directory)
            games = links.readAvailableGames(directory)
        self.assertEqual(games, {"Unknown", "RE2", "MHRISE", "MHWILDS", "SF6", "Count"})

    def testMalformedUpstreamGameHeaderDoesNotPartiallyWriteIdentity(self):
        with tempfile.TemporaryDirectory() as directory:
            writeGameHeader(directory, "namespace sdk { class GameIdentity {}; }")
            configPath = writeConfig(directory, {"pages": PAGES})
            with self.assertRaises(ValueError):
                writeBuildIdentity(directory, NIGHTLY_NUMBER, configPath)
            self.assertFalse((Path(directory) / "src").exists())

    def testInvalidConfigsAreRejectedBeforeCreatingTheHeader(self):
        configs = (
            {"pages": []},
            {"pages": PAGES, "extra": "unexpected"},
            [],
            {"pages": {"badGame": PAGES["RE2"]}},
            {"pages": {"RE2": PAGES["RE2"], "MHRISE": PAGES["RE2"]}},
        )
        for config in configs:
            with self.subTest(config=config), tempfile.TemporaryDirectory() as directory:
                configPath = writeConfig(directory, config)
                with self.assertRaises(ValueError):
                    writeBuildIdentity(directory, NIGHTLY_NUMBER, configPath)
                self.assertFalse((Path(directory) / "src").exists())

    def testExternalOrNonCanonicalAddressesAreRejected(self):
        invalidUrls = (
            "http://www.nexusmods.com/monsterhunterrise/mods/4057",
            "https://example.com/monsterhunterrise/mods/4057",
            "https://user@www.nexusmods.com/monsterhunterrise/mods/4057",
            PAGES["MHRISE"] + "?tab=description",
            PAGES["MHRISE"] + "#anchor",
            PAGES["MHRISE"] + "\n",
            PAGES["MHRISE"] + "/",
            "not a URL",
            "https://www.nexusmods.com/monsterhunterrise/mods/0",
            None,
        )
        for url in invalidUrls:
            with self.subTest(url=url), tempfile.TemporaryDirectory() as directory:
                configPath = writeConfig(directory, {"pages": {"MHRISE": url}})
                with self.assertRaises(ValueError):
                    links.loadNexusPages(configPath)

    def testDuplicateJsonKeysCannotSilentlyReplaceGameOwnership(self):
        with tempfile.TemporaryDirectory() as directory:
            configPath = Path(directory) / "nexus-pages.json"
            configPath.write_text('{"pages":{"RE2":null,"RE2":null}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                links.loadNexusPages(configPath)


if __name__ == "__main__":
    unittest.main()
