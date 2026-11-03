"""编译并执行真实 C++ 翻译代码；没有编译器时明确跳过，CI 必须执行。"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import imgui_patches
from scripts.translation_assets import generateTranslation, load_translations, unescape_translation

ROOT = Path(__file__).resolve().parents[1]
COMPILE_TIMEOUT_SECONDS = 240
RUN_TIMEOUT_SECONDS = 30

# 用可执行的字体选择分支验证启动位置，不依赖真实游戏或字体资源。
FONT_SOURCE = """#include <REFramework.hpp>
namespace spdlog { void info(const char*, const char*) {} }
struct REFramework {
    bool m_fonts_need_init = true;
    bool custom = false, cached = false, failed = false;
    const char* m_default_font_file = "DEFAULT";
    void init_fonts();
};
void REFramework::init_fonts() {
    if (!m_fonts_need_init) {
        return;
    }

    m_fonts_need_init = false;
    if (!custom && !cached && !failed) {
        spdlog::info("Loaded default font: {}", m_default_font_file);
    }
}
extern const char* (*g_imgui_translate_fn)(const char*, const char*);
extern const char* (*g_imgui_translate_format_fn)(const char*);
void require(bool, const char*);
void checkFontInitialization() {
    for (int scenario = 0; scenario < 4; ++scenario) {
        REFramework framework;
        framework.custom = scenario == 1;
        framework.cached = scenario == 2;
        framework.failed = scenario == 3;
        g_imgui_translate_fn = nullptr;
        g_imgui_translate_format_fn = nullptr;
        framework.init_fonts();
        require(g_imgui_translate_fn && g_imgui_translate_format_fn,
                "translation startup must not depend on the font choice or load result");
    }
}
"""


def prepareFontInitializer(directory):
    source = directory / "src/REFramework.cpp"
    source.parent.mkdir(parents=True)
    source.write_text(FONT_SOURCE, encoding="utf-8")
    (directory / "REFramework.hpp").write_text("#pragma once\n", encoding="utf-8")
    with patch.object(imgui_patches, "patchBuildIdentity"):
        imgui_patches.patch_reframework_cpp(directory)
    return str(source)


def hashText(text):
    value = 0x811C9DC5
    for character in text.encode("utf-8"):
        value = ((value ^ character) * 0x01000193) & 0xFFFFFFFF
    return value


def compilerCommand():
    compiler = os.environ.get("REF_TEST_CXX") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        if os.environ.get("REQUIRE_NATIVE_TESTS") == "1":
            raise RuntimeError("CI 未找到 C++ 编译器，不能跳过核心翻译验证。")
        raise unittest.SkipTest("未找到 C++ 编译器；使用 REF_TEST_CXX 指定，CI 会执行此验证。")
    return [compiler, "c++"] if Path(compiler).stem == "zig" else [compiler]


def prepareImGui(directory):
    configured = os.environ.get("IMGUI_TEST_SOURCE")
    source = Path(configured) if configured else ROOT / "REFramework-src/dependencies/imgui"
    if not (source / "imgui.cpp").is_file():
        if os.environ.get("REQUIRE_IMGUI_TESTS") == "1":
            raise RuntimeError("缺少实际 ImGui 源码，CI 不能省略界面行为验证。")
        return []
    target = directory / "dependencies/imgui"
    target.mkdir(parents=True)
    for path in (*source.glob("*.h"), *source.glob("imgui*.cpp")):
        shutil.copy2(path, target / path.name)
    config = directory / "src/re2-imgui/re2_imconfig.hpp"
    config.parent.mkdir(parents=True)
    config.write_text("#pragma once\n", encoding="utf-8")
    imgui_patches.patch_imconfig(directory)
    imgui_patches.patch_imgui_cpp(directory)
    imgui_patches.patch_text_rendering(directory)
    imgui_patches.patch_imgui_widgets(directory)
    return [
        "-DREF_TEST_IMGUI",
        "-DIMGUI_DISABLE_WIN32_FUNCTIONS",
        "-include",
        str(config),
        "-I",
        str(target),
        *(
            str(target / name)
            for name in ("imgui.cpp", "imgui_draw.cpp", "imgui_tables.cpp", "imgui_widgets.cpp")
        ),
    ]


class TranslationRuntimeTests(unittest.TestCase):
    def testRealNativeTranslationAndImGuiBehavior(self):
        command = compilerCommand()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            generateTranslation(
                {
                    "Enable": "启用",
                    "Enabled": "启用",
                    "Long": "长" * 3000,
                    "Commits: %i": "提交: %i",
                    "Branch: %s": "分支: %s",
                    "Precise: %.2f%%": "精度: %.2f%%",
                    "Broken: %i": "错误: %s",
                    "Missing: %s %i": "缺失: %s",
                },
                {hashText("HashOnly"): "哈希翻译", hashText("HashCount: %i"): "哈希计数: %i"},
                directory,
            )
            executable = directory / ("verify.exe" if os.name == "nt" else "verify")
            command += [
                "-std=c++20",
                "-DREF_TRANSLATION_TEST",
                "-I",
                str(directory),
                str(directory / "Translation.cpp"),
                str(ROOT / "tests/native_translation.cpp"),
                prepareFontInitializer(directory),
                *prepareImGui(directory),
                "-o",
                str(executable),
            ]
            compilation = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=COMPILE_TIMEOUT_SECONDS,
            )
            self.assertEqual(compilation.returncode, 0, compilation.stderr)
            execution = subprocess.run(
                [str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT_SECONDS
            )
            self.assertEqual(execution.returncode, 0, execution.stdout + execution.stderr)
            self.assertIn("Native translation checks passed", execution.stdout)

    def testTranslationEscapesAndExplicitKeysRemainCompatible(self):
        self.assertEqual(unescape_translation(r"line\nnext\\name"), "line\nnext\\name")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "translations.txt"
            path.write_text("Tooltip\\nNext=提示\\n下一行\nEnabled##a=启用##a\n", encoding="utf-8")
            translations = load_translations(path)
        self.assertEqual(translations["Tooltip\nNext"], "提示\n下一行")
        self.assertEqual(translations["Enabled"], "启用")


if __name__ == "__main__":
    unittest.main()
