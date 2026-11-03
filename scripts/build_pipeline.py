"""串联版本确定、源码准备、汉化、编译和打包，默认只生成本地成品。"""

import argparse
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from scripts import cmake_patches, imgui_patches
from scripts.build_support import BUILD_TIMEOUT_SECONDS, BuildSettings, log, runCommand, writeMessage
from scripts.localization_identity import writeBuildIdentity
from scripts.release_artifacts import createPackage, publishPackage
from scripts.repository_identity import currentRepository
from scripts.source_checkout import checkoutSource, writeCommitIdentity
from scripts.translation_assets import generateTranslation, load_hash_dict, load_translations
from scripts.upstream_release import resolveRelease

CONFIGURE_TIMEOUT_SECONDS = 900


def configureAndBuild(settings, target):
    cmake = shutil.which("cmake")
    if not cmake:
        raise RuntimeError("未找到 CMake，请安装 Visual Studio 2022 的 C++ 桌面开发及 CMake 工具。")
    configure = [cmake, "-S", ".", "-B", "build"]
    if os.name == "nt":
        configure.extend(["-G", "Visual Studio 17 2022", "-A", "x64"])
    elif settings.toolchainFile:
        configure.extend(
            ["-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_TOOLCHAIN_FILE={settings.toolchainFile}"]
        )
    else:
        raise RuntimeError("正式构建需要 Windows；交叉编译请显式配置 REF_TOOLCHAIN_FILE。")
    log("配置编译环境。")
    runCommand(configure, settings.workDirectory, CONFIGURE_TIMEOUT_SECONDS, False)
    command = [cmake, "--build", "build", "--target", target, "--config", "Release"]
    log("编译 dinput8.dll，以下为编译器实际输出。")
    runCommand(command, settings.workDirectory, BUILD_TIMEOUT_SECONDS, False)


def prepareLocalization(settings, release):
    root = settings.repositoryRoot
    texts = load_translations(root / "translations.txt")
    hashes = load_hash_dict(root / "hash_dict.txt")
    log(f"载入词库：{len(texts)} 条原文，{len(hashes)} 条哈希。")
    writeCommitIdentity(settings, release)
    repository = currentRepository(settings.repositoryRoot, required=False)
    projectUrl = f"https://github.com/{repository}" if repository else None
    writeBuildIdentity(settings.workDirectory, release.number, projectUrl=projectUrl)
    generateTranslation(texts, hashes, settings.workDirectory / "src")
    for patch in (
        imgui_patches.patch_imconfig,
        imgui_patches.patch_imgui_cpp,
        imgui_patches.patch_text_rendering,
        imgui_patches.patch_imgui_widgets,
        cmake_patches.patch_cmake_toml,
        imgui_patches.patch_reframework_cpp,
    ):
        patch(settings.workDirectory)


def buildLocalizedPackage(settings, release):
    settings.workDirectory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ref-", dir=settings.workDirectory.parent) as directory:
        session = replace(settings, workDirectory=Path(directory) / "source")
        checkoutSource(session, release)
        target = cmake_patches.resolve_build_target(session.workDirectory)
        prepareLocalization(session, release)
        configureAndBuild(session, target)
        return createPackage(session, release, target)


def argumentParser():
    parser = argparse.ArgumentParser(description="基于固定的官方 Nightly 源码生成 REFramework 汉化包。")
    parser.add_argument("--check-only", action="store_true", help="仅显示官方编号和源码提交，不构建。")
    parser.add_argument("--publish", action="store_true", help="构建完成后明确发布到 GitHub Releases。")
    return parser


def main(arguments=None):
    options = argumentParser().parse_args(arguments)
    try:
        if options.publish and os.environ.get("SKIP_GITHUB_PUBLISH") == "1":
            raise ValueError("--publish 与 SKIP_GITHUB_PUBLISH=1 冲突。")
        release = resolveRelease()
        log(f"官方版本：{release.tag}")
        if options.check_only:
            return 0
        settings = BuildSettings.fromEnvironment()
        artifact = buildLocalizedPackage(settings, release)
        if options.publish:
            publishPackage(artifact, release, settings)
        else:
            log("本地打包完成；发布请显式使用 --publish，或使用 GitHub 工作流。")
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        writeMessage(f"[构建失败] {error}", sys.stderr)
        return 1
    except KeyboardInterrupt:
        writeMessage("[构建停止] 维护者取消了本次任务。", sys.stderr)
        return 1
