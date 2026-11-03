"""以明确、可验证的定位条件注入 ImGui 汉化，不更改格式参数。"""

import re
import textwrap
from pathlib import Path

from scripts.build_support import insertAfter as patch_insert_after
from scripts.build_support import log, replaceUnique
from scripts.build_support import readText as read_text
from scripts.build_support import writeText as write_text
from scripts.localization_identity import patchBuildIdentity

IMGUI_TITLE_PATCH_MATCH_COUNT = 1


def fail(message):
    raise ValueError(message)


def patch_imconfig(build):
    path = build / "src/re2-imgui/re2_imconfig.hpp"
    content = read_text(path)
    marker = "// [REF_TRANSLATE_HOOK]"
    callbacks = (
        "extern const char* (*g_imgui_translate_fn)(const char*, const char*);",
        "extern const char* (*g_imgui_translate_format_fn)(const char*);",
    )
    if marker in content:
        if not all(callback in content for callback in callbacks):
            raise ValueError("翻译回调声明不一致，请使用干净源码重新构建。")
        return
    snippet = textwrap.dedent("""\

        // [REF_TRANSLATE_HOOK] 显示文本与控件标识分别处理，文本片段保留结束位置。
        extern const char* (*g_imgui_translate_fn)(const char*, const char*);
        extern const char* (*g_imgui_translate_format_fn)(const char*);
        static inline const char* ImGui_Translate(const char* text, const char* textEnd = nullptr) {
            return text && g_imgui_translate_fn ? g_imgui_translate_fn(text, textEnd) : text;
        }
        static inline const char* ImGui_TranslateFormat(const char* format) {
            return format && g_imgui_translate_format_fn ? g_imgui_translate_format_fn(format) : format;
        }
        """)
    write_text(path, content + snippet)


def patch_imgui_cpp(build: Path):
    p = build / "dependencies" / "imgui" / "imgui.cpp"
    c = read_text(p)
    marker = "/* REF_TRANSLATE_PATCHED */"
    titleAnchor = (
        "void ImGui::RenderWindowTitleBarContents(ImGuiWindow* window, "
        "const ImRect& title_bar_rect, const char* name, bool* p_open)\n{\n"
    )
    insertion = "    name = ImGui_Translate(name);\n"
    if c.count(titleAnchor) != IMGUI_TITLE_PATCH_MATCH_COUNT:
        fail("imgui.cpp: 标题绘制函数缺失或重复，已停止汉化补丁。")
    if marker in c:
        if (
            c.count(marker) != IMGUI_TITLE_PATCH_MATCH_COUNT
            or c.count(titleAnchor + insertion) != IMGUI_TITLE_PATCH_MATCH_COUNT
        ):
            fail("imgui.cpp: 标题补丁标记与代码不一致，请使用干净上游源码重新构建。")
        return

    anchor_inc = '#ifndef IMGUI_DISABLE\n#include "imgui_internal.h"'
    if c.count(anchor_inc) != IMGUI_TITLE_PATCH_MATCH_COUNT:
        fail("imgui.cpp: imgui_internal.h 包含位置缺失或重复，已停止汉化补丁。")
    c = c.replace(anchor_inc, anchor_inc + "\n" + marker, IMGUI_TITLE_PATCH_MATCH_COUNT)

    # 仅修改绘制函数的局部标题，窗口创建、查找和持久化仍使用原名。
    c = patch_insert_after(c, titleAnchor, insertion, "RenderWindowTitleBarContents")

    write_text(p, c)
    log("已修补 imgui.cpp（标题显示翻译，保留原窗口标识）")


TEXT_RANGE_PATCH = (
    "    { const char* translated = ImGui_Translate(text, text_end); "
    "if (translated != text) { text = translated; text_end = nullptr; } }\n"
)
RENDER_SIGNATURES = (
    (
        "void ImGui::RenderText(ImVec2 pos, const char* text, const char* text_end, bool hide_text_after_hash)",
        TEXT_RANGE_PATCH,
    ),
    (
        "void ImGui::RenderTextWrapped(ImVec2 pos, const char* text, const char* text_end, float wrap_width)",
        TEXT_RANGE_PATCH,
    ),
    (
        "ImVec2 ImGui::CalcTextSize(const char* text, const char* text_end, bool hide_text_after_double_hash, float wrap_width)",
        TEXT_RANGE_PATCH,
    ),
    (
        "void ImGui::RenderTextClipped(const ImVec2& pos_min, const ImVec2& pos_max, const char* text, const char* text_end, const ImVec2* text_size_if_known, const ImVec2& align, const ImRect* clip_rect)",
        TEXT_RANGE_PATCH.replace("text_end = nullptr;", "text_end = nullptr; text_size_if_known = nullptr;"),
    ),
    (
        "void ImGui::RenderTextEllipsis(ImDrawList* draw_list, const ImVec2& pos_min, const ImVec2& pos_max, float ellipsis_max_x, const char* text, const char* text_end_full, const ImVec2* text_size_if_known)",
        TEXT_RANGE_PATCH.replace("text_end", "text_end_full").replace(
            "text_end_full = nullptr;", "text_end_full = nullptr; text_size_if_known = nullptr;"
        ),
    ),
)


def patchFile(path, marker, patches):
    content = read_text(path)
    if marker in content:
        if not all(anchor + insertion in content for anchor, insertion, _ in patches):
            raise ValueError(f"{path.name} 的补丁标记与代码不一致，请重新获取干净源码。")
        return
    for anchor, insertion, label in patches:
        content = patch_insert_after(content, anchor, insertion, label)
    header = "imgui_internal.h" if path.name == "imgui.cpp" else "imgui.h"
    include = f'#include "{header}"\n'
    if path.name == "imgui.cpp":
        include = "#ifndef IMGUI_DISABLE\n" + include
    content = replaceUnique(content, include, include + marker + "\n", path.name)
    write_text(path, content)


def patch_text_rendering(build):
    # 绘制与测量同时翻译，控件名称及 GetID/PushID 始终保持上游原文。
    patches = tuple((signature + "\n{\n", insertion, signature) for signature, insertion in RENDER_SIGNATURES)
    patchFile(build / "dependencies/imgui/imgui.cpp", "/* REF_TRANSLATE_RENDERING */", patches)


def patch_imgui_widgets(build):
    signature = "void ImGui::TextEx(const char* text, const char* text_end, ImGuiTextFlags flags)\n{\n"
    formatSignatures = (
        "void ImGui::TextV(const char* fmt, va_list args)",
        "void ImGui::TextAlignedV(float align_x, float size_x, const char* fmt, va_list args)",
        "void ImGui::LabelTextV(const char* label, const char* fmt, va_list args)",
        "void ImGui::BulletTextV(const char* fmt, va_list args)",
        "bool ImGui::TreeNodeExV(const char* str_id, ImGuiTreeNodeFlags flags, const char* fmt, va_list args)",
        "bool ImGui::TreeNodeExV(const void* ptr_id, ImGuiTreeNodeFlags flags, const char* fmt, va_list args)",
    )
    # 仅翻译显示模板，树节点仍使用原始 str_id/ptr_id 计算标识。
    patches = ((signature, TEXT_RANGE_PATCH, "TextEx"),) + tuple(
        (value + "\n{\n", "    fmt = ImGui_TranslateFormat(fmt);\n", value) for value in formatSignatures
    )
    patchFile(build / "dependencies/imgui/imgui_widgets.cpp", "/* REF_TRANSLATE_WIDGETS */", patches)


def patch_reframework_cpp(build: Path):
    patchBuildIdentity(build)
    p = build / "src" / "REFramework.cpp"
    c = read_text(p)
    marker = "/* REF_TRANSLATE_INIT */"
    if marker in c:
        return

    inc_anchor = "#include <REFramework.hpp>"
    if inc_anchor not in c:
        inc_anchor = '#include "REFramework.hpp"'
    if inc_anchor not in c:
        m = re.search(r'#include\s+[<"]REFramework', c)
        if m:
            inc_anchor = m.group(0)
        else:
            fail("REFramework.cpp: 找不到 #include REFramework")
    c = c.replace(inc_anchor, inc_anchor + '\n#include "Translation.hpp"\n' + marker)

    # CJK glyph ranges
    full_font_line = 'loaded_fonts["DEFAULT"] = fonts->AddFontFromMemoryCompressedTTF(RobotoCJKSC_Medium_compressed_data, RobotoCJKSC_Medium_compressed_size, m_font_size, &cfg);'
    if full_font_line in c:
        c = c.replace(
            full_font_line,
            "cfg.GlyphRanges = fonts->GetGlyphRangesChineseFull();\n            " + full_font_line,
        )

    # 调用 startup()
    startup_anchor = 'spdlog::info("Loaded default font: {}", m_default_font_file);'
    if startup_anchor in c:
        c = c.replace(
            startup_anchor, startup_anchor + "\n                reframework::translation::startup();"
        )
    else:
        alt_anchor = 'm_default_font = loaded_fonts["DEFAULT"];'
        if alt_anchor in c:
            idx = c.rfind(alt_anchor)
            end = idx + len(alt_anchor)
            c = c[:end] + "\n        reframework::translation::startup();" + c[end:]

    if "reframework::translation::startup();" not in c:
        fail("REFramework.cpp: 未定位到翻译初始化位置。")
    write_text(p, c)
    log("已 patch REFramework.cpp (CJK 字体 + 翻译初始化)")
