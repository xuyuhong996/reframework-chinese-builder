"""集中适配上游 CMake，Windows 为正式发布环境，交叉编译保留原有支持。"""

import os
import re
from pathlib import Path

from scripts.build_support import log
from scripts.build_support import readText as read_text
from scripts.build_support import writeText as write_text

IS_WINDOWS_BUILD = os.name == "nt"
MSVC_PARALLEL_FLAGS = (
    'set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} /MP")\nset(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /MP")\n'
)


def fail(message):
    raise ValueError(message)


def replace_cmake_once(content: str, old: str, new: str, label: str) -> str:
    matches = content.count(old)
    if matches != 1:
        fail(f"Linux CMake 适配锚点异常: {label}，命中 {matches} 次")
    return content.replace(old, new, 1)


def replace_cmake_regex_once(content: str, pattern: str, new: str, label: str) -> str:
    patched, matches = re.subn(pattern, new, content, count=1, flags=re.DOTALL | re.MULTILINE)
    if matches != 1:
        fail(f"Linux CMake 适配锚点异常: {label}，命中 {matches} 次")
    return patched


def resolve_build_target(build: Path) -> str:
    """按上游 CMake 的目标声明选择实际需要输出 dinput8.dll 的目标。"""
    cmake_lists = build / "CMakeLists.txt"
    content = read_text(cmake_lists)
    if "# Target: REFramework\n" in content:
        return "REFramework"
    if "# Target: MHWILDS\n" in content:
        return "MHWILDS"
    fail("未识别到可构建的 REFramework 目标；上游 CMake 结构已变化，已停止以避免生成错误 DLL")


def patchLinuxCompiler(content, build_target, sdk_target):
    cmkr_bootstrap_pattern = (
        r"^([ \t]*)# Bootstrap cmkr and automatically regenerate CMakeLists\.txt\n"
        r"\1include\(cmkr\.cmake OPTIONAL RESULT_VARIABLE CMKR_INCLUDE_RESULT\)\n"
        r"\1if\(CMKR_INCLUDE_RESULT\)\n"
        r"\1\tcmkr\(\)\n"
        r"\1endif\(\)\n"
    )
    content = replace_cmake_regex_once(
        content,
        cmkr_bootstrap_pattern,
        "# Bootstrap cmkr is disabled for the localized Linux cross-build\n",
        "cmkr 自动重生成",
    )
    content = replace_cmake_once(content, "\t\tCSharp\n", "", "CSharp 语言")
    content = replace_cmake_once(content, "include(CSharpUtilities)\n\n", "", "CSharp 工具")
    content = replace_cmake_once(content, MSVC_PARALLEL_FLAGS, "", "MSVC 并行参数")
    release_pattern = (
        r'if \("\$\{CMAKE_BUILD_TYPE\}" MATCHES "Release"\).*?set\(CMAKE_MSVC_RUNTIME_LIBRARY ".*?"\)\n'
    )
    content = replace_cmake_regex_once(
        content,
        release_pattern,
        'message(NOTICE "Building Linux cross-compiled Release mode")\n',
        "MSVC 运行库参数",
    )
    content = replace_cmake_once(
        content,
        "if(CMAKE_CXX_COMPILER_VERSION VERSION_GREATER_EQUAL 19.35)\n\t    target_compile_options(DirectXTK PRIVATE /Zc:templateScope-)\n\t    target_compile_options(DirectXTK12 PRIVATE /Zc:templateScope-)\n\tendif()\n",
        "",
        "DirectXTK MSVC 参数",
    )
    content = replace_cmake_once(
        content, 'target_compile_options(utility PUBLIC\n\t"/EHa"\n)\n\n', "", "utility MSVC 参数"
    )
    content = replace_cmake_once(
        content,
        f'target_compile_options({sdk_target} PUBLIC\n\t\t"/EHa"\n\t)\n\n',
        "",
        f"{sdk_target} MSVC 参数",
    )
    content = replace_cmake_once(
        content,
        f'target_compile_options({build_target} PUBLIC\n\t\t"/GS-"\n\t\t"/bigobj"\n\t\t"/EHa"\n\t)\n\n',
        "",
        f"{build_target} MSVC 参数",
    )
    return content


def flattenCimguiDefinitions(content):
    cimgui_block_start = content.find('\tset_source_files_properties(\n\t    "src/cimgui/cimgui.cpp"\n')
    cimgui_property_start = content.find("COMPILE_DEFINITIONS\n", cimgui_block_start)
    cimgui_definitions_start = content.find('"', cimgui_property_start) + 1
    cimgui_definitions_end = content.find('"\n\t)', cimgui_definitions_start)
    if (
        cimgui_block_start == -1
        or cimgui_property_start == -1
        or cimgui_definitions_start == 0
        or cimgui_definitions_end == -1
    ):
        fail("Linux CMake 适配锚点异常: cimgui 多行兼容宏，命中 0 次")
    definitions = re.sub(r"\s+", "", content[cimgui_definitions_start:cimgui_definitions_end])
    content = content[:cimgui_definitions_start] + definitions + content[cimgui_definitions_end:]
    return content


def patch_linux_cmake(build: Path):
    """仅修改构建副本，移除当前上游目标所需的 MSVC 专属配置。"""
    cmake_lists = build / "CMakeLists.txt"
    content = read_text(cmake_lists)
    marker = "# [REF_LINUX_CROSS_COMPILE_PATCHED]"
    if marker in content:
        return

    build_target = resolve_build_target(build)
    sdk_target = "REFrameworkSDK" if build_target == "REFramework" else "MHWILDSSDK"

    content = patchLinuxCompiler(content, build_target, sdk_target)
    if build_target == "REFramework":
        content = flattenCimguiDefinitions(content)
    target_pattern = rf"(^# Target: {re.escape(build_target)}\n.*?)(?=^# Target:|\Z)"
    match = re.search(target_pattern, content, flags=re.DOTALL | re.MULTILINE)
    if not match:
        fail(f"Linux CMake 适配锚点异常: {build_target} 目标块不存在")
    target_block = match.group(1)
    target_block = replace_cmake_once(
        target_block,
        '\t\tLINK_FLAGS\n\t\t\t"/DELAYLOAD:openvr_api.dll /DELAYLOAD:openxr_loader.dll /DELAYLOAD:d3d11.dll /DELAYLOAD:d3d12.dll /DELAYLOAD:D3DCOMPILER_47.dll"\n',
        "",
        f"{build_target} 延迟加载参数",
    )
    target_block = replace_cmake_regex_once(
        target_block,
        r'\tadd_custom_command\(\n\t    TARGET [^\n]+ PRE_BUILD\n\t    COMMAND \$\{CMAKE_COMMAND\} -E echo "Generating commit hash\.\.\."\n\t    COMMAND \$\{CMAKE_COMMAND\} -E chdir \$\{CMAKE_SOURCE_DIR\} \$\{CMAKE_SOURCE_DIR\}/MakeCommitHash\.bat\n\t\)\n\n',
        "",
        f"{build_target} Windows 构建钩子",
    )
    target_block = replace_cmake_once(
        target_block,
        '\t\t"src/REFramework.hpp"\n',
        '\t\t"src/REFramework.hpp"\n\t\t"src/Translation.cpp"\n\t\t"src/Translation.hpp"\n',
        f"{build_target} 翻译源文件",
    )
    content = content[: match.start()] + target_block + content[match.end() :]
    write_text(cmake_lists, content + f"\n{marker}\n")
    log("已 patch CMakeLists.txt (Linux 交叉编译适配)")


def prepareWindowsLanguages(cmake_lists_text):
    cmake_lists_text = re.sub(
        r"(?ms)^([ \t]*)# Bootstrap cmkr and automatically regenerate CMakeLists\.txt\n"
        r"\1include\(cmkr\.cmake OPTIONAL RESULT_VARIABLE CMKR_INCLUDE_RESULT\)\n"
        r"\1if\(CMKR_INCLUDE_RESULT\)\n"
        r"\1\tcmkr\(\)\n"
        r"\1endif\(\)\n",
        r"\1# Bootstrap cmkr and automatically regenerate CMakeLists.txt\n"
        r'\1message(STATUS "Skipping cmkr regeneration for localized build")\n',
        cmake_lists_text,
        count=1,
    )
    cmake_lists_text = re.sub(
        r"(?m)^[ \t]*CSharp\s*\n",
        "",
        cmake_lists_text,
        count=1,
    )
    cmake_lists_text = re.sub(
        r"(?m)^include\(CSharpUtilities\)\s*\n",
        "",
        cmake_lists_text,
        count=1,
    )
    return cmake_lists_text


def patchWindowsLists(cmake_lists):
    cmake_lists_marker = "# [REF_TRANSLATE_CMAKELISTS_PATCHED]"
    cmake_lists_text = read_text(cmake_lists)
    if cmake_lists_marker not in cmake_lists_text:
        cmake_lists_text = prepareWindowsLanguages(cmake_lists_text)
        cmake_lists_text = cmake_lists_text.replace(
            'set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} /MP")', 'set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} /MP /utf-8")'
        )
        cmake_lists_text = cmake_lists_text.replace(
            'set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /MP")',
            'set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /MP /utf-8")',
        )
        # 注入 Translation.cpp/hpp 到所有 game target 的源文件列表
        # 禁用 cmkr 后 CMakeLists.txt 不再自动从 glob 拾取新文件，需手动添加
        cmake_lists_text = cmake_lists_text.replace(
            '"src/REFramework.hpp"\n',
            '"src/REFramework.hpp"\n\t\t"src/Translation.cpp"\n\t\t"src/Translation.hpp"\n',
        )
        cmake_lists_text += f"\n{cmake_lists_marker}\n"
        write_text(cmake_lists, cmake_lists_text)
        log("已 patch CMakeLists.txt (跳过 cmkr + 注入翻译源文件)")


def patch_cmake_toml(build: Path):
    if not IS_WINDOWS_BUILD:
        patch_linux_cmake(build)
        return

    p = build / "cmake.toml"
    c = read_text(p)
    marker = "# [REF_TRANSLATE_PATCHED]"

    if marker not in c:
        c = c.replace(
            'set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} /MP")', 'set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} /MP /utf-8")'
        )
        c = c.replace(
            'set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /MP")',
            'set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /MP /utf-8")',
        )
        c = c.replace(
            'compile-options = ["/GS-", "/bigobj", "/EHa"]',
            'compile-options = ["/GS-", "/bigobj", "/EHa", "/utf-8"]',
        )
        # 新版源码需要 CSharp 但我们只编译 C++ 目标，移除避免报错
        c = c.replace('languages = ["CXX", "C", "CSharp"]', 'languages = ["CXX", "C"]')
        c += f"\n{marker}\n"
        write_text(p, c)
        log("已 patch cmake.toml (/utf-8)")

    patchWindowsLists(build / "CMakeLists.txt")
