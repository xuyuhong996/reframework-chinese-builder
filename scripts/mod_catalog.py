"""由收录记录生成页面汇总和模组明细，并检查词库引用与页面是否同步。"""

import argparse
import html
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from scripts.translation_assets import load_hash_dict, load_translations

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_HEADING = "## 已收录汉化库的 Mod\n"
NEXT_HEADING = "## 提交未汉化 Mod\n"
INCLUDED_STATUSES = {"included", "partial"}
ARCHIVE_VERSION_KINDS = {"file", "script", "page_only", "unknown"}
LOCAL_PATH = re.compile(r"\b[A-Za-z]:[\\/]|file://|\\\\[^\\/\s]+[\\/]", re.I)


def tableText(value):
    text = html.escape(str(value), quote=False)
    for original in ("\\", "|", "[", "]"):
        text = text.replace(original, "\\" + original)
    return text.replace("\r", " ").replace("\n", " ")


def includedMods(game):
    return [mod for mod in game["mods"] if mod["dictionary_status"] in INCLUDED_STATUSES]


def validateReferences(mod, translations, hashes):
    references = mod.get("dictionary_refs")
    if not references:
        raise ValueError(f"收录条目没有词库引用：{mod['name']}")
    for reference in references:
        if reference["kind"] == "exact" and reference["key"] in translations:
            continue
        if reference["kind"] == "hash" and int(reference["hash"], 16) in hashes:
            continue
        raise ValueError(f"词库引用已失效：{mod['name']} / {reference}")


def validatePublicIdentity(gameId, mod):
    if type(mod["id"]) is not int or mod["id"] <= 0:
        raise ValueError("模组编号必须是正整数。")
    address = urlparse(mod["url"])
    if address.scheme != "https" or address.netloc not in {"nexusmods.com", "www.nexusmods.com"}:
        raise ValueError(f"模组原链接无效：{mod['name']}")
    if address.path.rstrip("/") != f"/{gameId}/mods/{mod['id']}":
        raise ValueError(f"游戏与模组原链接不一致：{mod['name']}")
    if address.query or address.fragment:
        raise ValueError("模组入口应使用稳定原页面，不能使用临时下载地址。")
    if any(key in mod for key in ("path", "archive", "download_path", "local_path")):
        raise ValueError("公开清单不能保存本机下载或解包路径。")
    validatePublicMetadata(mod)


def containsLocalPath(value):
    if isinstance(value, str):
        return bool(LOCAL_PATH.search(value))
    if isinstance(value, dict):
        return any(containsLocalPath(key) or containsLocalPath(item) for key, item in value.items())
    if isinstance(value, list):
        return any(containsLocalPath(item) for item in value)
    return False


def validatePublicMetadata(mod):
    metadata = {key: value for key, value in mod.items() if key != "dictionary_refs"}
    if containsLocalPath(metadata):
        raise ValueError("公开来源信息不能包含本机文件路径。")
    for reference in mod.get("dictionary_refs", []):
        # 英文原文可包含字体路径示例，只有这一处文字值不作为本机来源路径检查。
        if containsLocalPath({key: value for key, value in reference.items() if key != "key"}):
            raise ValueError("公开词库引用的附加信息不能包含本机文件路径。")


def validateSource(mod):
    sourceType = mod.get("source_type")
    versionKind = mod.get("version_kind")
    if sourceType == "nexus_archive":
        if versionKind not in ARCHIVE_VERSION_KINDS:
            raise ValueError(f"原包版本类型缺失或不正确：{mod['name']}")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", mod.get("sha256") or ""):
            raise ValueError(f"原包缺少可追溯校验值：{mod['name']}")
        return
    if sourceType != "author_github_commit" or versionKind != "github_commit":
        raise ValueError(f"来源与版本类型缺失或不一致：{mod['name']}")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", mod.get("source_commit") or ""):
        raise ValueError(f"关联源码必须固定提交：{mod['name']}")
    repository = urlparse(mod.get("source_repository") or "")
    if repository.scheme != "https" or repository.netloc != "github.com":
        raise ValueError(f"关联源码必须提供作者仓库：{mod['name']}")
    if not re.fullmatch(r"/[^/]+/[^/]+/?", repository.path) or repository.query or repository.fragment:
        raise ValueError(f"作者仓库地址不正确：{mod['name']}")
    if mod.get("sha256"):
        raise ValueError(f"关联源码不能冒充 Nexus 原包校验值：{mod['name']}")


def validateMod(gameId, mod, dictionaries):
    validatePublicIdentity(gameId, mod)
    if mod.get("dictionary_status") not in INCLUDED_STATUSES:
        raise ValueError(f"未收录条目应单列核对结论：{mod['name']}")
    if mod.get("requires_reframework") is not True or mod.get("translation_path_verified") is not True:
        raise ValueError(f"未证实依赖前置及翻译入口，不得收录：{mod['name']}")
    if not mod.get("hook_evidence"):
        raise ValueError(f"缺少翻译调用路径证据：{mod['name']}")
    if not mod.get("scope") or not mod.get("source_checked"):
        raise ValueError(f"缺少已核对的界面范围或来源：{mod['name']}")
    validateSource(mod)
    validateReferences(mod, *dictionaries)


def validateExclusions(gameId, records, includedIds):
    seen = set(includedIds)
    for record in records:
        validatePublicIdentity(gameId, record)
        if record["id"] in seen:
            raise ValueError(f"收录与排除记录重复：{gameId}/{record['id']}")
        seen.add(record["id"])
        if not record.get("reason") or not record.get("eligibility_checked"):
            raise ValueError(f"未收录条目缺少已核对原因：{record['name']}")


def loadCatalog(root):
    catalog = json.loads((root / "mod-support.json").read_text("utf-8"))
    dictionaries = (load_translations(root / "translations.txt"), load_hash_dict(root / "hash_dict.txt"))
    seenGames = set()
    for game in catalog["games"]:
        gameId = game["id"]
        if gameId in seenGames or not re.fullmatch(r"[a-z0-9]+", gameId):
            raise ValueError("游戏编号重复或格式无效。")
        seenGames.add(gameId)
        seenMods = set()
        for mod in game["mods"]:
            if mod["id"] in seenMods:
                raise ValueError(f"同一游戏重复记录模组：{gameId}/{mod['id']}")
            seenMods.add(mod["id"])
            validateMod(gameId, mod, dictionaries)
        validateExclusions(gameId, game.get("reviewed_exclusions", []), seenMods)
    return catalog


def versionText(mod):
    value = tableText(mod.get("version") or "未标明")
    kind = mod["version_kind"]
    if kind == "github_commit":
        commit = mod["source_commit"][:8]
        return f"关联源码 `{commit}`（不等同于附件版本）"
    if kind == "page_only":
        return f"页面标记 {value}；附件版本未核实"
    if kind == "script":
        return f"脚本标记 {value}"
    if kind == "unknown":
        return "附件版本未标明（来源校验值已记录）"
    return f"附件 {value}"


def statusText(mod):
    state = "部分词条已收录"
    if mod.get("built_in_chinese"):
        state += "；含 Mod 内置中文"
    if mod.get("game_verified"):
        state += "；游戏内已验证"
    else:
        state += "；游戏内待验证"
    return state


def renderSummary(catalog):
    total = sum(len(includedMods(game)) for game in catalog["games"])
    rows = [
        f"当前记录 **{total} 个**依赖 REFramework、且已有界面英文能由本前置词库匹配的设置模组。清单逐项维护名称、N 网原链接、核对来源／版本和词库范围。",
        "",
        "**[查看模组名称、N 网链接、版本与汉化范围](docs/mod-support.md)** · [查看结构化记录](mod-support.json)",
        "",
        "| 游戏 | 已记录的设置模组 | 词库状态 | 游戏内验证 |",
        "| --- | --- | --- | --- |",
    ]
    for game in catalog["games"]:
        mods = includedMods(game)
        name = f"[{tableText(game['name'])}](docs/mod-support.md#{game['id']})"
        verified = "已验证" if mods and all(mod.get("game_verified") for mod in mods) else "待验证"
        if not mods:
            verified = "—"
        state = "菜单与提示部分收录" if mods else "待补充"
        rows.append(f"| {name} | {len(mods)} 个 | {state} | {verified} |")
    rows.extend(
        [
            "",
            "“词库已收录”表示源码词库包含对应的部分界面文字或可复用的通用词条，**不表示整个 Mod 已完整汉化，也不表示当前发布包已包含本轮新增内容**。动态文字、作者自定义内容与绕过前置翻译的绘制内容可能保留原文；详细范围与来源见清单。",
        ]
    )
    return "\n".join(rows) + "\n"


def renderGameDetails(game):
    rows = [f'<a id="{game["id"]}"></a>', "", f"## {game['name']}", ""]
    mods = includedMods(game)
    if not mods:
        rows.append(game.get("note") or "当前尚无已完成词库匹配核对的收录条目，后续继续补充。")
        return rows + [""] + renderExclusions(game)
    rows.extend(
        [
            f"当前收录 **{len(mods)} 个**。以下记录为本次核对的来源快照，排名与版本可能变化。",
            "",
            "| 模组（点击前往 N 网） | 核对来源／版本 | 本次核对的词库范围 | 状态 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for mod in mods:
        name = f"[{tableText(mod['name'])}]({mod['url']})"
        rows.append(f"| {name} | {versionText(mod)} | {tableText(mod['scope'])} | {statusText(mod)} |")
    return rows + [""] + renderExclusions(game)


def renderExclusions(game):
    records = game.get("reviewed_exclusions", [])
    if not records:
        return []
    rows = [
        "<details>",
        f"<summary>已核对但未纳入词库（{len(records)} 个，不计入收录数）</summary>",
        "",
        "| 模组（点击前往 N 网） | 未收录原因 |",
        "| --- | --- |",
    ]
    for record in records:
        name = f"[{tableText(record['name'])}]({record['url']})"
        rows.append(f"| {name} | {tableText(record['reason'])} |")
    return rows + ["", "</details>", ""]


def renderDetails(catalog):
    rows = [
        "# 模组汉化库收录清单",
        "",
        "此清单只记录依赖 REFramework 运行、且界面英文经过本前置翻译入口的 Mod。工作内容是补充本项目的源码词库；原作者 Mod 只用于核对英文与调用路径，不修改原 Mod。**已收录不等于整套 Mod 已完整汉化，也不等于已经打包或游戏内实测。**",
        "",
        f"核对日期：{catalog['updated_at']}。{catalog['criteria']}",
        "",
        "附件版本、脚本自身版本、页面显示版本与关联 GitHub 源码提交分别标记；关联源码不冒充 Nexus 原包。原包校验值、词库引用和来源提交见[结构化记录](../mod-support.json)。",
        "",
        "仅纳入当前前置可处理的菜单、设置与提示。独立程序、游戏原生界面、未经过翻译入口的 Direct2D 等绘制内容不计入；Lua 预先拼接或格式化的动态文字及未收录内容可能保留原文。内置中文由原 Mod 或其依赖提供。",
        "",
    ]
    for game in catalog["games"]:
        rows.extend(renderGameDetails(game))
    return "\n".join(rows).rstrip() + "\n"


def expectedDocuments(root, catalog):
    readme = (root / "README.md").read_text("utf-8")
    before, heading, remainder = readme.partition(SUMMARY_HEADING)
    _, nextHeading, after = remainder.partition(NEXT_HEADING)
    if not heading or not nextHeading:
        raise ValueError("README 缺少收录清单区段，停止覆盖。")
    updated = before + heading + "\n" + renderSummary(catalog) + "\n" + nextHeading + after
    return {"README.md": updated, "docs/mod-support.md": renderDetails(catalog)}


def synchronize(root, checkOnly=False):
    catalog = loadCatalog(root)
    changed = []
    for name, expected in expectedDocuments(root, catalog).items():
        path = root / name
        if path.exists() and path.read_text("utf-8") == expected:
            continue
        changed.append(name)
        if not checkOnly:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8", newline="\n")
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="仅检查清单、词库引用和页面是否同步")
    arguments = parser.parse_args()
    changed = synchronize(ROOT, arguments.check)
    if arguments.check and changed:
        raise SystemExit("清单页面尚未同步：" + "、".join(changed))
    print("清单页面已同步。" if not arguments.check else "清单与词库引用检查通过。")


if __name__ == "__main__":
    main()
