"""直接验证窗口标题补丁的实际落点、窗口标识和重复执行。"""

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from scripts import imgui_patches as buildScript

DOCUMENTATION = """/*
绘制循环示例中的左花括号不能作为标题补丁的定位条件。
while (true)
{
    drawFrame();
}
*/
"""
INCLUDES = '#ifndef IMGUI_DISABLE\n#include "imgui_internal.h"\n'
TITLE_FUNCTION = """void ImGui::RenderWindowTitleBarContents(ImGuiWindow* window, const ImRect& title_bar_rect, const char* name, bool* p_open)
{
    ImGuiContext& g = *GImGui;
    const ImVec2 text_size = CalcTextSize(name, NULL, true);
    RenderTextClipped(layout_r.Min, layout_r.Max, name, NULL, &text_size);
}
"""
BEGIN_FUNCTION = """bool ImGui::Begin(const char* name, bool* p_open, ImGuiWindowFlags flags)
{
    ImGuiContext& g = *GImGui;
    ImGuiWindow* window = FindWindowByName(name);
    RenderWindowTitleBarContents(window, title_bar_rect, name, p_open);
    return true;
}
"""
UNRELATED_FUNCTION = "void drawFrame()\n{\n    updateFrame();\n}\n"
SOURCE = DOCUMENTATION + INCLUDES + UNRELATED_FUNCTION + TITLE_FUNCTION + BEGIN_FUNCTION
TRANSLATION_CALL = "    name = ImGui_Translate(name);\n"
PATCH_MARKER = "/* REF_TRANSLATE_PATCHED */"
EXPECTED_MATCH_COUNT = 1


def writeSource(directory, source):
    sourcePath = Path(directory) / "dependencies/imgui/imgui.cpp"
    sourcePath.parent.mkdir(parents=True)
    sourcePath.write_text(source, encoding="utf-8", newline="\n")
    return sourcePath


class ImGuiTitleTests(unittest.TestCase):
    def patchSource(self, source):
        with tempfile.TemporaryDirectory() as directory:
            sourcePath = writeSource(directory, source)
            with patch.object(buildScript, "log"):
                buildScript.patch_imgui_cpp(Path(directory))
            return sourcePath.read_text("utf-8")

    def assertPatchRejected(self, source):
        with tempfile.TemporaryDirectory() as directory:
            sourcePath = writeSource(directory, source)
            originalBytes = sourcePath.read_bytes()
            with redirect_stderr(io.StringIO()), self.assertRaises(ValueError):
                buildScript.patch_imgui_cpp(Path(directory))
            self.assertEqual(sourcePath.read_bytes(), originalBytes)

    def testTranslationOnlyChangesTitleDrawingBeforeTextMeasurement(self):
        patchedSource = self.patchSource(SOURCE)
        titleBody = patchedSource.split(TITLE_FUNCTION.split("\n")[0], EXPECTED_MATCH_COUNT)[-1]
        titleBody = titleBody.split(BEGIN_FUNCTION.split("\n")[0], EXPECTED_MATCH_COUNT)[0]
        self.assertIn(TRANSLATION_CALL, titleBody)
        self.assertLess(titleBody.index(TRANSLATION_CALL), titleBody.index("CalcTextSize(name"))
        self.assertTrue(patchedSource.startswith(DOCUMENTATION))
        self.assertIn(UNRELATED_FUNCTION, patchedSource)
        self.assertIn(BEGIN_FUNCTION, patchedSource)
        self.assertEqual(patchedSource.count(TRANSLATION_CALL), EXPECTED_MATCH_COUNT)

    def testRepeatedApplicationDoesNotDuplicateThePatch(self):
        patchedSource = self.patchSource(SOURCE)
        self.assertEqual(self.patchSource(patchedSource), patchedSource)

    def testMissingOrAmbiguousTitleFunctionDoesNotChangeTheFile(self):
        for source in (SOURCE.replace(TITLE_FUNCTION, ""), SOURCE + TITLE_FUNCTION):
            with self.subTest(source=source):
                self.assertPatchRejected(source)

    def testMissingOrAmbiguousIncludesDoNotChangeTheFile(self):
        for source in (SOURCE.replace(INCLUDES, ""), SOURCE + INCLUDES):
            with self.subTest(source=source):
                self.assertPatchRejected(source)

    def testIncompleteOldPatchMarkerCannotReportSuccess(self):
        oldSource = SOURCE.replace(INCLUDES, INCLUDES + PATCH_MARKER + "\n")
        oldSource = oldSource.replace("{\n", "{\n" + TRANSLATION_CALL, EXPECTED_MATCH_COUNT)
        self.assertPatchRejected(oldSource)


if __name__ == "__main__":
    unittest.main()
