"""打包、摘要与显式发布；二进制附件不再写进源码提交历史。"""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.build_support import log, runCommand, writeMessage
from scripts.repository_identity import currentRepository
from scripts.upstream_release import UpstreamRelease

HASH_PREFIX_LENGTH = 12
PE_HEADER_OFFSET = 0x3C
PE_COFF_HEADER_SIZE = 24
AMD64_MACHINE = 0x8664
PE32_PLUS_MAGIC = 0x20B
DLL_CHARACTERISTIC = 0x2000


def buildSourceIdentity(repositoryRoot):
    repository = currentRepository(repositoryRoot, required=False)
    return {
        "builderRepository": repository,
        "builderCommit": runCommand(["git", "rev-parse", "HEAD"], repositoryRoot) if repository else None,
        "translationSha256": hashlib.sha256((repositoryRoot / "translations.txt").read_bytes()).hexdigest(),
        "hashDictionarySha256": hashlib.sha256((repositoryRoot / "hash_dict.txt").read_bytes()).hexdigest(),
    }


def createPackage(settings, release, target):
    dll = settings.workDirectory / "build/bin" / target / "dinput8.dll"
    reward = settings.repositoryRoot / "assets/wechat-reward-qr.jpg"
    licensePath = settings.sourceDirectory / "LICENSE"
    for path in (dll, reward, licensePath):
        if not path.is_file():
            raise FileNotFoundError(f"缺少打包文件：{path}")
    settings.outputDirectory.mkdir(parents=True, exist_ok=True)
    package = settings.outputDirectory / f"REFramework-Nightly-{release.number}.zip"
    temporary = package.with_suffix(".zip.tmp")
    manifest = {
        "upstreamTag": release.tag,
        "upstreamSha": release.sourceSha,
        "dllSha256": hashlib.sha256(dll.read_bytes()).hexdigest(),
        **buildSourceIdentity(settings.repositoryRoot),
    }
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            archive.write(dll, "dinput8.dll")
            archive.write(reward, "赏口饭吃.jpg")
            archive.write(licensePath, "LICENSE-REFramework.txt")
            archive.writestr("build-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        retainPackage(temporary, package, settings.repositoryRoot)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    checksum = Path(f"{package}.sha256")
    checksum.write_text(f"{digest}  {package.name}\n", encoding="ascii")
    delivery = (
        f"# 当前交付说明\n\n成品：{package.name}\n\n官方版本：{release.tag}\n\n"
        f"SHA256：{digest}\n\n构建工作区：{settings.workDirectory}\n\n"
        "状态：已打包并生成摘要；尚未安装或进行游戏内验证。\n"
    )
    (settings.outputDirectory / "CURRENT.md").write_text(delivery, encoding="utf-8")
    log(f"已生成 {package}")
    return package, checksum, digest


def retainPackage(temporary, package, repositoryRoot):
    if not package.exists():
        temporary.replace(package)
        return
    content = temporary.read_bytes()
    if package.read_bytes() == content:
        return
    digest = hashlib.sha256(content).hexdigest()
    candidates = repositoryRoot / "outputs/build-candidates"
    candidates.mkdir(parents=True, exist_ok=True)
    candidate = candidates / f"{package.stem}-{digest[:HASH_PREFIX_LENGTH]}.zip"
    if not candidate.exists():
        candidate.write_bytes(content)
    raise ValueError(f"同编号成品内容不同，已保留原件；候选文件留在 {candidate}，请先核对来源。")


def publishPackage(artifact, release, settings):
    package, checksum, digest = artifact
    tag = f"build-{digest[:HASH_PREFIX_LENGTH]}"
    repository = currentRepository(settings.repositoryRoot)
    if runCommand(["git", "status", "--porcelain"], settings.repositoryRoot):
        raise ValueError("发布前请提交当前仓库的源码修改；普通本地构建不受此限制。")
    builderSha = runCommand(["git", "rev-parse", "HEAD"], settings.repositoryRoot)
    # 发布由维护者显式选择；复用 GitHub CLI 已有登录，不自动登录或推送源码。
    runCommand(["gh", "auth", "status", "--hostname", "github.com"])
    notes = f"本地构建。\n\nNightly 发布: {release.tag}"
    runCommand(
        [
            "gh",
            "release",
            "create",
            tag,
            package,
            checksum,
            "--repo",
            repository,
            "--target",
            builderSha,
            "--title",
            f"REFramework-Nightly-汉化-{release.number}",
            "--notes",
            notes,
        ]
    )


def verifyDllImage(content):
    offset = int.from_bytes(content[PE_HEADER_OFFSET : PE_HEADER_OFFSET + 4], "little")
    if content[:2] != b"MZ" or len(content) < offset + PE_COFF_HEADER_SIZE + 2:
        raise ValueError("压缩包中的 dinput8.dll 不是完整的 Windows 二进制文件。")
    machine = int.from_bytes(content[offset + 4 : offset + 6], "little")
    characteristic = int.from_bytes(content[offset + 22 : offset + PE_COFF_HEADER_SIZE], "little")
    magic = int.from_bytes(content[offset + PE_COFF_HEADER_SIZE : offset + PE_COFF_HEADER_SIZE + 2], "little")
    if (
        content[offset : offset + 4] != b"PE\0\0"
        or machine != AMD64_MACHINE
        or magic != PE32_PLUS_MAGIC
        or not characteristic & DLL_CHARACTERISTIC
    ):
        raise ValueError("发布文件必须是 x64 PE32+ DLL。")


def verifyPackage(package, expectedIdentity):
    with ZipFile(package) as archive:
        if archive.testzip() is not None:
            raise ValueError("压缩包完整性校验失败。")
        manifest = json.loads(archive.read("build-manifest.json"))
        dll = archive.read("dinput8.dll")
        if not archive.read("LICENSE-REFramework.txt"):
            raise ValueError("压缩包缺少上游许可证。")
    verifyDllImage(dll)
    release = UpstreamRelease.fromTag(manifest["upstreamTag"])
    if manifest["upstreamSha"] != release.sourceSha:
        raise ValueError("包内官方版本与源码提交不一致。")
    if manifest["dllSha256"] != hashlib.sha256(dll).hexdigest():
        raise ValueError("包内 DLL 摘要与来源清单不一致。")
    for field, value in expectedIdentity.items():
        if manifest.get(field) != value:
            raise ValueError(f"包内来源与本次构建不一致：{field}。")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="核对发布包的 DLL、源码提交及词库来源。")
    parser.add_argument("package", type=Path)
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument("--builder-sha", required=True)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    expected = buildSourceIdentity(root)
    expected.update({"builderCommit": arguments.builder_sha, "upstreamTag": arguments.upstream_tag})
    verifyPackage(arguments.package, expected)
    writeMessage("压缩包、x64 DLL、构建提交和词库摘要验证通过。")


if __name__ == "__main__":
    main()
