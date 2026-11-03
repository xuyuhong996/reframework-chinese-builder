"""读取词库并生成 C++ 资源，运行时算法保存在 templates 中。"""

from pathlib import Path

from scripts.build_support import writeText

TEMPLATE_DIRECTORY = Path(__file__).resolve().parents[1] / "templates"
HASH_MAXIMUM = 0xFFFFFFFF


def fail(message):
    raise ValueError(message)


def unescape_translation(s: str) -> str:
    """将翻译文本中的字面转义序列 (\\n, \\r, \\t, \\\\) 转换为真实字符。

    Lua/C++ 字符串中 \\n 是真实换行 (0x0A)，但翻译文件中是字面量两字符。
    如果不做此转换，含换行的 Tooltip 等文本将永远匹配不到翻译。
    """
    result = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n":
                result.append("\n")
                i += 2
            elif nxt == "r":
                result.append("\r")
                i += 2
            elif nxt == "t":
                result.append("\t")
                i += 2
            elif nxt == "\\":
                result.append("\\")
                i += 2
            else:
                result.append(s[i])
                i += 1
        else:
            result.append(s[i])
            i += 1
    return "".join(result)


def load_translations(path) -> dict:
    DICT_FILE = Path(path)
    if not DICT_FILE.exists():
        fail(f"翻译字典文件不存在: {DICT_FILE}")
    d = {}
    for line in DICT_FILE.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 支持 tab 分隔符 (用于 key 中含 '=' 的条目)
        if "\t" in line:
            parts = line.split("\t", 1)
            if len(parts) == 2:
                en, zh = parts[0].strip(), parts[1].strip()
            else:
                continue
        else:
            eq = line.find("=")
            if eq <= 0:
                continue
            en, zh = line[:eq], line[eq + 1 :]

        # 关键修复: 将字面转义序列转换为真实字符，使 Tooltip 等含 \n 的文本能正确匹配
        en = unescape_translation(en)
        zh = unescape_translation(zh)

        if en and zh:
            d[en] = zh
            # 如果 key 含 ## , 同时添加不含 ## 的显示部分作为备用匹配
            # 例: "Enabled in Multiplayer##ID" -> 额外添加 "Enabled in Multiplayer"
            hh = en.find("##")
            if hh > 0:
                disp_en = en[:hh]
                hh_zh = zh.find("##")
                disp_zh = zh[:hh_zh] if hh_zh > 0 else zh
                if disp_en not in d:  # 不覆盖已有的精确条目
                    d[disp_en] = disp_zh
    return d


def load_hash_dict(path) -> dict:
    HASH_DICT = Path(path)
    if not HASH_DICT.exists():
        return {}
    d = {}
    for line in HASH_DICT.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            h = int(parts[0], 16)
        except ValueError:
            continue
        cn = unescape_translation(parts[1])
        if not 0 <= h <= HASH_MAXIMUM:
            raise ValueError("哈希词条必须是 32 位无符号数。")
        if cn:
            d[h] = cn
    return d


def cppString(text):
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def generateTranslation(translations, hashes, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    header = (TEMPLATE_DIRECTORY / "Translation.hpp").read_text("utf-8")
    source = (TEMPLATE_DIRECTORY / "Translation.cpp").read_text("utf-8")
    textEntries = "\n".join(
        f'        {{"{cppString(key)}", "{cppString(value)}"}},' for key, value in translations.items()
    )
    hashEntries = "\n".join(
        f'        {{0x{key:08X}U, "{cppString(value)}"}},' for key, value in sorted(hashes.items())
    )
    source = source.replace("@@TEXT_ENTRIES@@", textEntries).replace("@@HASH_ENTRIES@@", hashEntries)
    writeText(destination / "Translation.hpp", header)
    writeText(destination / "Translation.cpp", source)
