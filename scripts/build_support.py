"""构建路径、命令执行与源码补丁的公共约定。"""

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMMAND_TIMEOUT_SECONDS = 120
BUILD_TIMEOUT_SECONDS = 5400
EXPECTED_MATCH_COUNT = 1


@dataclass(frozen=True)
class BuildSettings:
    repositoryRoot: Path
    sourceDirectory: Path
    workDirectory: Path
    outputDirectory: Path
    toolchainFile: str = ""

    @classmethod
    def fromEnvironment(cls, environment=None):
        environment = os.environ if environment is None else environment
        session = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        defaultWork = Path(r"C:\ref_build_runs") if os.name == "nt" else REPOSITORY_ROOT / ".build"
        return cls(
            repositoryRoot=REPOSITORY_ROOT,
            sourceDirectory=Path(environment.get("REF_SOURCE_DIR", REPOSITORY_ROOT / "REFramework-src")),
            workDirectory=Path(environment.get("REF_BUILD_ROOT", defaultWork)) / session,
            outputDirectory=Path(environment.get("REF_OUTPUT_DIR", REPOSITORY_ROOT / "deliverables")),
            toolchainFile=environment.get("REF_TOOLCHAIN_FILE", ""),
        )


def writeMessage(message, stream=None):
    stream = sys.stdout if stream is None else stream
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="backslashreplace")
    print(message, file=stream, flush=True)


def log(message):
    writeMessage(f"[汉化构建] {message}")


def runCommand(command, cwd=None, timeout=COMMAND_TIMEOUT_SECONDS, capture=True):
    try:
        result = subprocess.run(
            [str(argument) for argument in command],
            cwd=cwd,
            timeout=timeout,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{command[0]} 超过 {timeout} 秒未完成，请检查网络或构建日志。") from None
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"{command[0]} 执行失败（退出码 {result.returncode}）：{detail}")
    return result.stdout.strip() if capture else ""


def readText(path):
    return Path(path).read_text(encoding="utf-8-sig")


def writeText(path, content):
    Path(path).write_text(content, encoding="utf-8", newline="\n")


def replaceUnique(content, anchor, replacement, label):
    matches = content.count(anchor)
    if matches != EXPECTED_MATCH_COUNT:
        raise ValueError(f"上游源码定位失败：{label}，匹配 {matches} 处。")
    return content.replace(anchor, replacement, EXPECTED_MATCH_COUNT)


def insertAfter(content, anchor, insertion, label):
    return replaceUnique(content, anchor, anchor + insertion, label)
