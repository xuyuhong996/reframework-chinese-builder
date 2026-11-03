"""根据公开页面配置，为当前上游源码生成游戏专属的界面链接。"""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

NEXUS_PAGES_PATH = Path(__file__).resolve().parent.parent / "nexus-pages.json"
GAME_IDENTITY_HEADER = Path("shared/sdk/GameIdentity.hpp")
GAME_KEY_PATTERN = r"[A-Z][A-Z0-9_]*"
NEXUS_PATH_PATTERN = r"/[a-z0-9][a-z0-9_-]*/mods/[1-9][0-9]*"
GAME_ENUM_PATTERN = r"enum\s+class\s+GameID\s*(?::[^{}]+)?\{([^}]+)\}"
DRAW_NEXUS_LINK = """
    inline void drawNexusProjectLink() {
        if (const auto* url = getNexusProjectUrl(); url != nullptr) {
            drawProjectLink("Nexus Mods", url);
        }
    }
"""


def rejectDuplicateKeys(pairs):
    """重复键不能被解析器静默覆盖，否则游戏与页面的对应关系不明确。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"N网页面配置存在重复键：{key}")
        result[key] = value
    return result


def validateNexusUrl(url):
    """仅允许不含参数的公开页面地址，禁止凭据或其他站点进入生成头文件。"""
    if not isinstance(url, str):
        raise ValueError("N网页面地址必须是字符串。")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.netloc != "www.nexusmods.com"
        or not re.fullmatch(NEXUS_PATH_PATTERN, parts.path)
        or parts.query
        or parts.fragment
        or url != parts.geturl()
    ):
        raise ValueError("N网页面地址必须是无凭据、无参数的公开N网模组页面。")


def loadNexusPages(configPath=NEXUS_PAGES_PATH):
    config = json.loads(Path(configPath).read_text("utf-8"), object_pairs_hook=rejectDuplicateKeys)
    if not isinstance(config, dict) or set(config) != {"pages"}:
        raise ValueError("N网页面配置必须仅包含 pages 对象。")
    pages = config["pages"]
    if not isinstance(pages, dict):
        raise ValueError("N网页面配置 pages 必须是对象。")
    usedUrls = set()
    for game, url in pages.items():
        if not re.fullmatch(GAME_KEY_PATTERN, game):
            raise ValueError(f"N网页面的游戏标识格式不正确：{game}")
        validateNexusUrl(url)
        if url in usedUrls:
            raise ValueError("不同游戏不能配置同一个N网页面。")
        usedUrls.add(url)
    return pages


def readAvailableGames(buildDirectory):
    """读取本次固定源码的枚举，避免旧源码引用尚不存在的新游戏成员。"""
    headerPath = Path(buildDirectory) / GAME_IDENTITY_HEADER
    if not headerPath.is_file():
        return None
    header = headerPath.read_text("utf-8")
    header = re.sub(r"/\*.*?\*/|//[^\n]*", "", header, flags=re.DOTALL)
    match = re.search(GAME_ENUM_PATTERN, header)
    if not match:
        raise ValueError("上游游戏识别枚举结构已变化，请检查 GameIdentity.hpp。")
    return set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:=[^,]+)?(?:,|$)", match[1]))


def buildRuntimeSelector(pages, availableGames):
    lines = ["    inline const char* nexusUrlForGame(sdk::GameID game) {", "        switch (game) {"]
    lines.extend(
        f"        case sdk::GameID::{game}: return {json.dumps(url)};"
        for game, url in pages.items()
        if game in availableGames
    )
    lines.extend(
        [
            "        default: return nullptr;",
            "        }",
            "    }",
            "",
            "    inline const char* getNexusProjectUrl() {",
            "        return nexusUrlForGame(sdk::GameIdentity::get().game());",
            "    }",
        ]
    )
    return "\n".join(lines)


def buildLegacySelector(pages):
    """旧上游以游戏编译宏区分目标，只为已有页面的当前目标提供链接。"""
    lines = ["    inline const char* getNexusProjectUrl() {"]
    directive = "#if"
    for game, url in pages.items():
        lines.extend([f"{directive} defined({game})", f"        return {json.dumps(url)};"])
        directive = "#elif"
    if pages:
        lines.append("#else")
    lines.append("        return nullptr;")
    if pages:
        lines.append("#endif")
    lines.append("    }")
    return "\n".join(lines)


def buildNexusLinkCode(buildDirectory, pages):
    availableGames = readAvailableGames(buildDirectory)
    include = "#include <sdk/GameIdentity.hpp>\n" if availableGames is not None else ""
    selector = (
        buildRuntimeSelector(pages, availableGames)
        if availableGames is not None
        else buildLegacySelector(pages)
    )
    return f"{include}\nnamespace reframework::localization {{\n{selector}\n{DRAW_NEXUS_LINK}}}\n"
