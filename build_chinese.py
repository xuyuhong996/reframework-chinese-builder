#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""

功能:
  1. 从 translations.txt 读取精确翻译字典
  2. 从 hash_dict.txt 读取 FNV1a-32 哈希翻译字典 (老版汉化DLL)
  3. 在 ImGui 源码中插入安全的运行时翻译钩子
  4. 添加 CJK 字体支持
  5. 编译 dinput8.dll
  6. 打包为 zip (仅含 dll)

用法:
  python build_chinese.py
"""

import os, sys, re, shutil, subprocess, zipfile, textwrap, json, locale, ctypes, hashlib
from pathlib import Path
from datetime import datetime
import threading, time, itertools

class TaskProgress:
    def __init__(self, message="正在处理中", zeno_speed=0.03, use_fake_percent=True):
        if len(message) > 20: 
            message = message[:18] + ".."
        self.message = message
        self.running = False
        self.thread = None
        self.frames = ['ᕕ( ᐛ )ᕗ', '(ง ᐛ )ง'] if USE_FANCY_CONSOLE else ['->', '=>']
        self.frame_idx = 0
        self.percent = 0.0
        self.bar_len = 25
        self.has_exact = False
        self.zeno_speed = zeno_speed
        self.use_fake_percent = use_fake_percent
        self.start_ts = None
        
    def spin(self):
        while self.running:
            self.frame_idx = (self.frame_idx + 1) % len(self.frames)
            runner = self.frames[self.frame_idx]
            
            # 仅在没有真实进度时使用假进度，避免把不定进度步骤伪装成 98% 卡住
            if self.use_fake_percent and not self.has_exact and self.percent < 99.0:
                self.percent += (99.0 - self.percent) * self.zeno_speed

            icon = "✨" if USE_FANCY_CONSOLE else "*"

            if self.has_exact or self.use_fake_percent:
                p = min(max(int(self.percent), 0), 100)
                filled = int((p / 100.0) * self.bar_len)

                trail = '=' * filled
                empty = ' ' * (self.bar_len - filled)

                if filled > 0:
                    dust = '≡' if USE_FANCY_CONSOLE and self.frame_idx % 2 == 0 else '='
                    trail = trail[:-1] + dust

                bar_end = "🏁" if USE_FANCY_CONSOLE else ">"
                bar = f"{trail}{runner}{empty}{bar_end}"
                status_text = f"{bar} {p}% "
            else:
                elapsed = time.time() - self.start_ts if self.start_ts else 0.0
                status_text = f"{runner} 进行中 ({elapsed:.0f}s) "

            stream_write(sys.stdout, f"\x1b[2K\r[汉化构建] {icon} {self.message}  {status_text}", flush=True)
            time.sleep(0.15)
            
    def start(self):
        self.running = True
        self.start_ts = time.time()
        self.thread = threading.Thread(target=self.spin)
        self.thread.daemon = True
        self.thread.start()
        
    def set_percent(self, p):
        self.has_exact = True
        self.percent = float(p)
        
    def stop(self, success=True, quiet=False):
        self.running = False
        if self.thread:
            self.thread.join()
        
        stream_write(sys.stdout, "\x1b[2K\r", flush=False)
        if quiet:
            return
        if success:
            bar = '=' * self.bar_len + ('🏁 ⁽⁽٩(๑˃̶͈̀ ᗨ ˂̶͈́)۶⁾⁾ 🎉' if USE_FANCY_CONSOLE else ' [done]')
            stream_write(sys.stdout, f"[汉化构建] ✓ {self.message}  {bar} 100% 完成!\n")
        else:
            bar = '=' * self.bar_len + ('💥 (╯°□°)╯︵ ┻━┻' if USE_FANCY_CONSOLE else ' [failed]')
            stream_write(sys.stdout, f"[汉化构建] ✗ {self.message}  {bar} 失败!\n")

os.system("")  # Enable ANSI in windows terminal (CMD/Powershell)

if os.name == "nt":
    try:
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

PREFERRED_TEXT_ENCODING = locale.getpreferredencoding(False) or "utf-8"
CONSOLE_ENCODING = getattr(sys.stdout, "encoding", None) or PREFERRED_TEXT_ENCODING or "utf-8"

def console_safe_text(text: str, stream=None) -> str:
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or CONSOLE_ENCODING or "utf-8"
    try:
        text.encode(encoding)
        return text
    except Exception:
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")

def stream_write(stream, text: str, flush: bool = True):
    stream.write(console_safe_text(text, stream))
    if flush:
        stream.flush()

def safe_echo(text: str, stream=None):
    stream = stream or sys.stdout
    stream_write(stream, f"{text}\n")

def console_supports(text: str, stream=None) -> bool:
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or CONSOLE_ENCODING or "utf-8"
    try:
        text.encode(encoding)
        return True
    except Exception:
        return False

USE_FANCY_CONSOLE = console_supports("🚀✨💥🏁⚠️ᕕ( ᐛ )ᕗ(ง ᐛ )ง≡⁽⁽٩(๑˃̶͈̀ ᗨ ˂̶͈́)۶⁾⁾╯°□°︵┻━┻")

def decode_cmd_bytes(raw: bytes) -> str:
    if raw is None:
        return ""

    candidates = [PREFERRED_TEXT_ENCODING, "utf-8", "gb18030", "gbk", "cp936"]
    seen = set()
    for enc in candidates:
        key = (enc or "").lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode(PREFERRED_TEXT_ENCODING, errors="replace")

def run_with_progress(args, label, regex=None, cwd=None, zeno_speed=0.03, quiet_failure=False):
    progress = TaskProgress(label, zeno_speed=zeno_speed, use_fake_percent=bool(regex))
    progress.start()

    proc = subprocess.Popen(
        args, cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=False,
        bufsize=0
    )

    lines = []
    prog_re = re.compile(regex) if regex else None
    buf = bytearray()

    while True:
        char = proc.stdout.read(1)
        if not char:
            if buf:
                lines.append(decode_cmd_bytes(bytes(buf)).strip())
            break
        if char in (b'\r', b'\n'):
            line_str = decode_cmd_bytes(bytes(buf)).strip()
            if line_str:
                lines.append(line_str)
                # 针对含有正则 % 的提取
                if prog_re:
                    m = prog_re.search(line_str)
                    if m:
                        try:
                            progress.set_percent(int(m.groups()[-1]))
                        except:
                            pass
            buf = bytearray()
        else:
            buf.extend(char)

    proc.wait()
    progress.stop(proc.returncode == 0, quiet=(proc.returncode != 0 and quiet_failure))

    class DummyRet: pass
    ret = DummyRet()
    ret.returncode = proc.returncode
    ret.stdout = "\n".join(lines[-2000:]).encode('utf-8')
    ret.stderr = b""
    return ret

def run_with_retry_progress(args, label, regex=None, cwd=None, zeno_speed=0.03, max_attempts=3, on_retry=None):
    last_ret = None
    for attempt in range(1, max_attempts + 1):
        attempt_label = f"{label} ({attempt}/{max_attempts})" if max_attempts > 1 else label
        last_ret = run_with_progress(
            args,
            attempt_label,
            regex=regex,
            cwd=cwd,
            zeno_speed=zeno_speed,
            quiet_failure=(attempt < max_attempts),
        )
        if last_ret.returncode == 0:
            return last_ret

        if attempt < max_attempts:
            if on_retry:
                on_retry(attempt)
            stream_write(
                sys.stdout,
                f"\x1b[2K\r[汉化构建] {label} 失败，正在重试 ({attempt + 1}/{max_attempts})...",
                flush=True,
            )
            time.sleep(1.0)

    return last_ret

SILENT_LOG = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ============================================================================
# 配置
# ============================================================================
SCRIPT_DIR   = Path(__file__).resolve().parent
IS_WINDOWS_BUILD = os.name == "nt"
DEFAULT_SRC_DIR = SCRIPT_DIR / "REFramework-src"
DEFAULT_BUILD_ROOT = Path(r"C:\ref_build_runs") if IS_WINDOWS_BUILD else Path("/workspace/build")
SRC_DIR = Path(os.environ.get("REF_SOURCE_DIR", str(DEFAULT_SRC_DIR)))
# Windows 保持短路径，Linux 容器通过环境变量使用独立工作卷。
BUILD_ROOT_BASE = Path(os.environ.get("REF_BUILD_ROOT", str(DEFAULT_BUILD_ROOT)))
BUILD_ROOT   = BUILD_ROOT_BASE / "bootstrap"
BUILD_DIR_NAME = "build"
# 构建目标由复制后的上游源码自动识别，兼容旧版 MHWILDS 与新版统一 REFramework 目标。
BUILD_TARGET = ""
DICT_FILE    = SCRIPT_DIR / "translations.txt"
HASH_DICT    = SCRIPT_DIR / "hash_dict.txt"
REWARD_QR_FILE = SCRIPT_DIR / "assets" / "wechat-reward-qr.jpg"
OUTPUT_DIR = Path(os.environ.get("REF_OUTPUT_DIR", str(SCRIPT_DIR)))
TOOLCHAIN_FILE = os.environ.get("REF_TOOLCHAIN_FILE", "")

GIT_REPO     = "https://github.com/praydog/REFramework.git"
NIGHTLY_API = "https://api.github.com/repos/praydog/REFramework-nightly/releases/latest"
NIGHTLY_GIT_REPO = "https://github.com/praydog/REFramework-nightly.git"
GITHUB_RELEASE_REPOSITORY = "xuyuhong996/reframework-chinese-builder"
GITHUB_RELEASE_REPOSITORY_URL = f"https://github.com/{GITHUB_RELEASE_REPOSITORY}.git"
PUBLISH_CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", str(SCRIPT_DIR))) / "REFrameworkChineseBuilder"

CMAKE_BIN = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Community"
    r"\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
)

# ============================================================================
# 工具函数
# ============================================================================
def get_nightly_number() -> str:
    """获取 REFramework-nightly 发布列表中的最新 Nightly 编号。"""
    try:
        response = requests.get(NIGHTLY_API, headers={"User-Agent": "REF-Chinese-Build"}, timeout=15)
        tag = response.json().get("tag_name", "") if response.status_code == 200 else ""
        matched = re.match(r"nightly-(\d+)", tag)
        if matched:
            return matched.group(1).zfill(5)
    except Exception:
        pass

    result = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", NIGHTLY_GIT_REPO],
        capture_output=True,
        timeout=30,
    )
    numbers = [
        int(match.group(1))
        for match in re.finditer(r"refs/tags/nightly-(\d+)-", decode_cmd_bytes(result.stdout))
    ]
    if numbers:
        return f"{max(numbers):05d}"
    fail("无法获取 REFramework-nightly 发布列表，已停止以避免生成错误包名。")

def log(msg):
    global SILENT_LOG
    if not SILENT_LOG:
        stream_write(sys.stdout, f"\x1b[2K\r[汉化构建] {msg}\n")

def fail(msg):
    stream_write(sys.stderr, f"\n[错误] {msg}\n")
    sys.exit(1)

def run_git(args, cwd=SRC_DIR, timeout=30):
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        timeout=timeout
    )

def git_output(args, cwd=SRC_DIR, timeout=30):
    try:
        ret = run_git(args, cwd=cwd, timeout=timeout)
        if ret.returncode == 0:
            return decode_cmd_bytes(ret.stdout).strip()
    except Exception:
        pass
    return ""

def parse_git_epoch(raw_ts: str):
    raw_ts = (raw_ts or "").strip()
    if not raw_ts:
        return None
    try:
        return datetime.fromtimestamp(int(raw_ts)).astimezone()
    except Exception:
        return None

def format_local_time(dt: datetime) -> str:
    if dt is None:
        return "未知时间"
    if dt.tzinfo is None:
        dt = dt.astimezone()
    offset = dt.strftime("%z")
    if len(offset) == 5:
        offset = f"{offset[:3]}:{offset[3:]}"
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {offset}"

def format_duration_zh(seconds: float) -> str:
    sec = int(max(0, round(seconds)))
    if sec < 60:
        return f"{sec}秒"
    minutes, sec = divmod(sec, 60)
    if minutes < 60:
        return f"{minutes}分{sec:02d}秒"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}小时{minutes}分"
    days, hours = divmod(hours, 24)
    return f"{days}天{hours}小时"

def format_age_from_now(dt: datetime, now: datetime = None) -> str:
    if dt is None:
        return "时间未知"
    now = now or datetime.now().astimezone()
    delta = now - dt
    if delta.total_seconds() >= 0:
        return f"距今 {format_duration_zh(delta.total_seconds())}"
    return f"领先当前 {format_duration_zh(-delta.total_seconds())}"

def to_int_safe(value, default=0):
    try:
        return int(str(value).strip())
    except Exception:
        return default

def translate_commit_body_zh(body: str) -> str:
    s = (body or "").strip()
    if not s:
        return s

    exact_map = {
        "Migration of rendering structures from upscaler branch": "将渲染结构从 upscaler 分支迁移",
    }
    if s in exact_map:
        return exact_map[s]

    # 合并类提交
    m = re.match(r"^Merge pull request #(\d+) from (.+)$", s, flags=re.IGNORECASE)
    if m:
        return f"合并拉取请求 #{m.group(1)}（来源 {m.group(2).strip()}）"

    m = re.match(r"^Merge branch ['\"]?(.+?)['\"]?(?: into ['\"]?(.+?)['\"]?)?$", s, flags=re.IGNORECASE)
    if m:
        src = m.group(1).strip()
        dst = (m.group(2) or "").strip()
        if dst:
            return f"合并分支 {src} 到 {dst}"
        return f"合并分支 {src}"

    # 高优先级句式
    m = re.match(r"^Migration of (.+?) from ([A-Za-z0-9._/-]+) branch$", s, flags=re.IGNORECASE)
    if m:
        thing = translate_commit_body_zh(m.group(1).strip())
        source_branch = m.group(2).strip()
        return f"将{thing}从 {source_branch} 分支迁移"

    m = re.match(r"^Update ([A-Za-z0-9._/-]+)\s*\((.+)\)$", s, flags=re.IGNORECASE)
    if m:
        dep_name = m.group(1).strip()
        reason = translate_commit_body_zh(m.group(2).strip())
        return f"更新 {dep_name}（{reason}）"

    m = re.match(r"^Bump ([A-Za-z0-9._/-]+) from (.+?) to (.+)$", s, flags=re.IGNORECASE)
    if m:
        return f"将 {m.group(1).strip()} 从 {m.group(2).strip()} 升级到 {m.group(3).strip()}"

    m = re.match(r"^Revert ['\"](.+)['\"]$", s, flags=re.IGNORECASE)
    if m:
        reverted = translate_commit_body_zh(m.group(1).strip())
        return f"回滚：{reverted}"

    m = re.match(r"^Add (.+?) to (.+)$", s, flags=re.IGNORECASE)
    if m:
        left = translate_commit_body_zh(m.group(1).strip())
        right = translate_commit_body_zh(m.group(2).strip())
        return f"将{left}添加到{right}"

    m = re.match(r"^Remove (.+?) from (.+)$", s, flags=re.IGNORECASE)
    if m:
        left = translate_commit_body_zh(m.group(1).strip())
        right = translate_commit_body_zh(m.group(2).strip())
        return f"从{right}移除{left}"

    m = re.match(r"^Fix (.+?) in (.+)$", s, flags=re.IGNORECASE)
    if m:
        what = translate_commit_body_zh(m.group(1).strip())
        where = translate_commit_body_zh(m.group(2).strip())
        return f"修复{where}中的{what}"
    m = re.match(r"^(Add|Fix|Update|Improve|Remove|Refactor|Support)\s+(.+)$", s, flags=re.IGNORECASE)
    if m:
        action_map = {
            "add": "新增",
            "fix": "修复",
            "update": "更新",
            "improve": "改进",
            "remove": "移除",
            "refactor": "重构",
            "support": "支持",
        }
        action = action_map.get(m.group(1).lower(), m.group(1))
        tail = translate_commit_body_zh(m.group(2).strip())
        return f"{action}{tail}"

    phrase_replacements = [
        (r"\brendering structures?\b", "渲染结构"),
        (r"\bupscaler branch\b", "upscaler 分支"),
        (r"\bpipe\s*server\b", "管道服务器"),
        (r"\bzombie spawner\b", "僵尸生成器"),
        (r"\btest script\b", "测试脚本"),
        (r"\bnew games\b", "新游戏"),
        (r"\breadme list\b", "README 列表"),
        (r"\bpull request\b", "拉取请求"),
        (r"\bto the\b", "到"),
        (r"\bfrom the\b", "从"),
        (r"\bof the\b", "的"),
    ]

    out = s
    for pattern, repl in phrase_replacements:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)

    word_map = {
        "wip": "开发中",
        "the": "",
        "a": "",
        "an": "",
        "for": "用于",
        "in": "在",
        "of": "的",
        "from": "从",
        "to": "到",
        "into": "到",
        "with": "包含",
        "without": "不含",
        "and": "与",
        "by": "由",
        "via": "通过",
        "or": "或",
        "on": "在",
        "off": "关闭",
        "update": "更新",
        "updates": "更新",
        "updated": "更新",
        "upgrade": "升级",
        "upgrades": "升级",
        "upgraded": "升级",
        "fix": "修复",
        "fixes": "修复",
        "fixed": "修复",
        "improve": "改进",
        "improves": "改进",
        "improved": "改进",
        "improvement": "改进",
        "add": "新增",
        "adds": "新增",
        "added": "新增",
        "remove": "移除",
        "removes": "移除",
        "removed": "移除",
        "support": "支持",
        "supports": "支持",
        "supported": "支持",
        "optimize": "优化",
        "optimized": "优化",
        "optimization": "优化",
        "refactor": "重构",
        "refactored": "重构",
        "refactoring": "重构",
        "crash": "崩溃",
        "crashes": "崩溃",
        "failure": "失败",
        "failures": "失败",
        "error": "错误",
        "errors": "错误",
        "issue": "问题",
        "issues": "问题",
        "memory": "内存",
        "renderer": "渲染器",
        "resource": "资源",
        "plugin": "插件",
        "loader": "加载器",
        "script": "脚本",
        "test": "测试",
        "server": "服务器",
        "branch": "分支",
        "migration": "迁移",
        "migrate": "迁移",
        "migrated": "迁移",
        "structure": "结构",
        "structures": "结构",
    }

    def _word_repl(match):
        raw = match.group(0)
        key = raw.lower()
        return word_map.get(key, raw)

    out = re.sub(r"[A-Za-z]+(?:'[A-Za-z]+)?", _word_repl, out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = out.replace(" ,", ",").replace(" .", ".")
    return out

def translate_commit_message_zh(message: str) -> str:
    s = (message or "").strip()
    if not s:
        return "（无提交说明）"

    prefix_map = {
        "deps": "依赖更新",
        "dep": "依赖更新",
        "fix": "修复",
        "feat": "新功能",
        "feature": "新功能",
        "build": "构建",
        "ci": "持续集成",
        "refactor": "重构",
        "docs": "文档",
        "doc": "文档",
        "test": "测试",
        "chore": "杂项",
        "perf": "性能优化",
        "revert": "回滚",
        "sdk": "SDK",
        ".net": ".NET",
        "net": ".NET",
        "ui": "界面",
        "lua": "Lua",
    }

    m = re.match(r"^([A-Za-z.][A-Za-z0-9._/-]{0,24})\s*:\s*(.+)$", s)
    if m:
        raw_prefix = m.group(1).strip()
        body = m.group(2).strip()
        prefix = prefix_map.get(raw_prefix.lower(), raw_prefix)
        body_zh = translate_commit_body_zh(body)
        return f"{prefix}：{body_zh}"

    return translate_commit_body_zh(s)

def collect_commit_list(cwd: Path, rev_spec: str, limit=10):
    pretty = "%h%x1f%an%x1f%ct%x1f%s"
    output = git_output(
        ["log", f"--max-count={limit}", f"--pretty=format:{pretty}", rev_spec],
        cwd=cwd,
        timeout=20
    )
    commits = []
    if not output:
        return commits
    for line in output.splitlines():
        parts = line.split("\x1f", 3)
        if len(parts) != 4:
            continue
        short_hash, author, commit_ts, subject = parts
        commits.append({
            "short": short_hash.strip(),
            "author": author.strip(),
            "timestamp": to_int_safe(commit_ts, 0),
            "subject": subject.strip(),
        })
    return commits

def collect_diff_name_status(cwd: Path, base_ref: str, target_ref: str):
    out = git_output(["diff", "--name-status", f"{base_ref}..{target_ref}"], cwd=cwd, timeout=45)
    added, modified, deleted = 0, 0, 0
    if not out:
        return added, modified, deleted

    for line in out.splitlines():
        if not line:
            continue
        status = line.split("\t", 1)[0].strip().upper()
        head = status[:1]
        if head == "A":
            added += 1
        elif head == "D":
            deleted += 1
        else:
            modified += 1
    return added, modified, deleted

def collect_commit_file_summary(cwd: Path, commit_hash: str):
    out = git_output(["show", "--name-only", "--pretty=format:", commit_hash], cwd=cwd, timeout=30)
    files = [line.strip() for line in out.splitlines() if line.strip()]
    if not files:
        return ""

    groups = {}
    for f in files:
        root = f.split("/", 1)[0]
        groups[root] = groups.get(root, 0) + 1

    sorted_groups = sorted(groups.items(), key=lambda x: (-x[1], x[0]))
    top_labels = [name for name, _ in sorted_groups[:3]]
    group_text = "、".join(top_labels)
    if len(sorted_groups) > 3:
        group_text += " 等"
    return f"涉及 {len(files)} 个文件（{group_text}）"

def log_update_changelog(sync_info: dict):
    commits = sync_info.get("commits") or []
    total = sync_info.get("update_total", 0)
    mode = sync_info.get("mode", "update")
    added = sync_info.get("files_added", 0)
    modified = sync_info.get("files_modified", 0)
    deleted = sync_info.get("files_deleted", 0)

    log("=" * 60)
    if mode == "clone":
        log(f"更新日志（中文）: 首次克隆，展示最近 {len(commits)} 条上游提交")
    elif total <= 0:
        log("更新日志（中文）: 未检测到上游新提交，本地已与远程一致")
    else:
        log(f"更新日志（中文）: 共 {total} 条")

    for idx, c in enumerate(commits, 1):
        zh_subject = translate_commit_message_zh(c["subject"])
        log(f"{idx}) {zh_subject}")
        log(f"   提交: {c['short']} | 作者: {c['author']}")
        file_summary = collect_commit_file_summary(SRC_DIR, c["short"])
        if file_summary:
            log(f"   变更: {file_summary}")

    if total > len(commits):
        log(f"……其余 {total - len(commits)} 条提交已省略")

    if mode != "clone" and total > 0:
        log(f"变更统计：新增 {added}，修改 {modified}，删除 {deleted}")
    log("=" * 60)

def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")

def write_text(p: Path, s: str):
    p.write_text(s, encoding="utf-8", newline="\n")

def patch_insert_after(content: str, anchor: str, insertion: str, label: str = "") -> str:
    idx = content.find(anchor)
    if idx == -1:
        fail(f"找不到锚点 [{label}]: {anchor!r:.120}")
    end = idx + len(anchor)
    return content[:end] + insertion + content[end:]

# ============================================================================
# 步骤 1: 读取翻译字典
# ============================================================================
def unescape_translation(s: str) -> str:
    """将翻译文本中的字面转义序列 (\\n, \\r, \\t, \\\\) 转换为真实字符。
    
    Lua/C++ 字符串中 \\n 是真实换行 (0x0A)，但翻译文件中是字面量两字符。
    如果不做此转换，含换行的 Tooltip 等文本将永远匹配不到翻译。
    """
    result = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == 'n':
                result.append('\n')
                i += 2
            elif nxt == 'r':
                result.append('\r')
                i += 2
            elif nxt == 't':
                result.append('\t')
                i += 2
            elif nxt == '\\':
                result.append('\\')
                i += 2
            else:
                result.append(s[i])
                i += 1
        else:
            result.append(s[i])
            i += 1
    return ''.join(result)


def load_translations() -> dict:
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
            en, zh = line[:eq], line[eq+1:]

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

def load_hash_dict() -> dict:
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
        cn = parts[1].replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t").replace("\\\\", "\\")
        if cn:
            d[h] = cn
    return d

# ============================================================================
# 步骤 2: 生成 Translation.hpp (仅声明，不含数据)
# ============================================================================
def generate_translation_hpp(dst: Path):
    code = textwrap.dedent('''\
    #pragma once
    // =====================================================================
    // REFramework Translation Library - 自动生成，请勿手动编辑
    // =====================================================================
    #ifndef REF_TRANSLATION_HPP
    #define REF_TRANSLATION_HPP

    namespace reframework {
    namespace translation {
        void startup();
        const char* translate(const char* text);
    } // namespace translation
    } // namespace reframework

    // 全局快捷翻译 (供 ImGui 源码调用)
    inline const char* REF_ImGui_TranslateCB(const char* t) {
        return reframework::translation::translate(t);
    }

    #endif // REF_TRANSLATION_HPP
    ''')
    write_text(dst, code)
    log("已生成 Translation.hpp (仅声明)")

# ============================================================================
# 步骤 3: 生成 Translation.cpp (所有实现和数据)
# ============================================================================
def generate_translation_cpp(translations: dict, hash_translations: dict, dst: Path):
    def c_escape(s):
        return (s.replace("\\", "\\\\")
                 .replace('"', '\\"')
                 .replace("\n", "\\n")
                 .replace("\r", "\\r")
                 .replace("\t", "\\t"))

    # 字符串翻译表
    str_pairs = []
    for en, zh in translations.items():
        str_pairs.append(f'        {{"{c_escape(en)}", "{c_escape(zh)}"}}')
    str_pairs_str = ",\n".join(str_pairs)

    # 哈希翻译表
    hash_pairs = []
    for h, cn in sorted(hash_translations.items()):
        hash_pairs.append(f'        {{0x{h:08X}U, "{c_escape(cn)}"}}')
    hash_pairs_str = ",\n".join(hash_pairs)

    code = textwrap.dedent(f'''\
    // =====================================================================
    // REFramework Translation Library - 实现
    // 字符串词条: {len(translations)}  |  哈希词条: {len(hash_translations)}
    // =====================================================================
    #include <windows.h>
    #include <unordered_map>
    #include <string>
    #include <fstream>
    #include <filesystem>
    #include <cstring>
    #include <spdlog/spdlog.h>
    #include "Translation.hpp"

    // 函数指针 (在 re2_imconfig.hpp 中声明为 extern)
    const char* (*g_imgui_translate_fn)(const char* text) = nullptr;

    namespace reframework {{
    namespace translation {{

    // ---- FNV-1a 32-bit (与老版汉化DLL相同算法) ----
    static uint32_t fnv1a_32(const char* s, size_t len) {{
        uint32_t h = 0x811c9dc5U;
        for (size_t i = 0; i < len; i++)
            h = (h ^ (uint8_t)s[i]) * 0x01000193U;
        return h;
    }}
    static uint32_t fnv1a_32(const char* s) {{
        uint32_t h = 0x811c9dc5U;
        for (; *s; s++)
            h = (h ^ (uint8_t)*s) * 0x01000193U;
        return h;
    }}

    // ---- 翻译缓冲区 (纯 POD，避免析构问题) ----
    static constexpr int BUF_COUNT = 32;
    static constexpr int BUF_SIZE  = 2048;
    static thread_local char   tl_bufs[BUF_COUNT][BUF_SIZE];
    static thread_local int    tl_idx = 0;

    static char* next_buf() {{
        return tl_bufs[tl_idx++ & (BUF_COUNT - 1)];
    }}

    // ---- 数据 ----
    static std::unordered_map<std::string, std::string> s_dict;
    static std::unordered_map<uint32_t, std::string>    s_hash_dict;
    static bool s_initialized = false;

    // ---- 内置字符串翻译表 ----
    static void load_builtin() {{
        static const std::pair<const char*, const char*> data[] = {{
    {str_pairs_str}
        }};
        for (auto& [k, v] : data)
            s_dict[k] = v;
    }}

    // ---- 内置哈希翻译表 (从老版汉化DLL提取) ----
    static void load_hash_builtin() {{
        static const std::pair<uint32_t, const char*> data[] = {{
    {hash_pairs_str}
        }};
        for (auto& [k, v] : data)
            s_hash_dict[k] = v;
    }}

    // ---- 从外部文件追加覆盖 ----
    static void load_file(const std::filesystem::path& p) {{
        std::ifstream f(p, std::ios::binary);
        if (!f.is_open()) return;
        std::string line;
        int count = 0;
        char bom[3];
        f.read(bom, 3);
        if (!(bom[0] == (char)0xEF && bom[1] == (char)0xBB && bom[2] == (char)0xBF))
            f.seekg(0);
        while (std::getline(f, line)) {{
            if (!line.empty() && line.back() == '\\r') line.pop_back();
            if (line.empty() || line[0] == '#') continue;
            auto eq = line.find('=');
            if (eq == std::string::npos || eq == 0) continue;
            std::string en = line.substr(0, eq);
            std::string zh = line.substr(eq + 1);
            if (!en.empty() && !zh.empty()) {{
                s_dict[en] = zh;
                count++;
            }}
        }}
        if (count > 0)
            spdlog::info("[Translation] Loaded {{}} from external file: {{}}", count, p.string());
    }}

    // ---- 初始化 ----
    static void init() {{
        if (s_initialized) return;
        try {{
            load_builtin();
            load_hash_builtin();
            wchar_t mod_path[MAX_PATH] = {{}};
            HMODULE hm = nullptr;
            GetModuleHandleExW(
                GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                (LPCWSTR)&init, &hm);
            if (hm && GetModuleFileNameW(hm, mod_path, MAX_PATH)) {{
                auto dll_dir = std::filesystem::path(mod_path).parent_path();
                auto ext1 = dll_dir / "reframework" / "translations.txt";
                auto ext2 = dll_dir / "translations.txt";
                if (std::filesystem::exists(ext1)) load_file(ext1);
                else if (std::filesystem::exists(ext2)) load_file(ext2);
            }}
        }} catch (const std::exception& e) {{
            spdlog::error("[Translation] Init exception: {{}}", e.what());
        }} catch (...) {{
            spdlog::error("[Translation] Init unknown exception");
        }}
        s_initialized = true;
        spdlog::info("[Translation] Ready: {{}} string + {{}} hash entries",
                     s_dict.size(), s_hash_dict.size());
    }}

    // ---- 核心翻译函数 ----
    const char* translate(const char* text) {{
        if (!text || !*text || !s_initialized)
            return text;

        try {{
            // 跳过前导空白后查找
            const char* trimmed = text;
            while (*trimmed == ' ' || *trimmed == '\\t') trimmed++;
            size_t leading_spaces = (size_t)(trimmed - text);

            // 计算去尾空白的长度
            size_t trimmed_len = strlen(trimmed);
            while (trimmed_len > 0 && (trimmed[trimmed_len-1] == ' ' || trimmed[trimmed_len-1] == '\\t'))
                trimmed_len--;

            const char* hash_mark = strstr(trimmed, "##");

            if (!hash_mark) {{
                // 无 ## : 先精确匹配原始文本
                auto it = s_dict.find(text);
                if (it != s_dict.end())
                    return it->second.c_str();

                // 若有前导/尾随空格，尝试去空格后匹配
                if (leading_spaces > 0 || trimmed_len != strlen(text)) {{
                    std::string clean(trimmed, trimmed_len);
                    auto it2 = s_dict.find(clean);
                    if (it2 != s_dict.end()) {{
                        char* buf = next_buf();
                        int n = snprintf(buf, BUF_SIZE, "%.*s%s",
                                         (int)leading_spaces, text,
                                         it2->second.c_str());
                        if (n > 0 && n < BUF_SIZE) return buf;
                    }}
                }}

                // 哈希匹配
                uint32_t h = fnv1a_32(text);
                auto hit = s_hash_dict.find(h);
                if (hit != s_hash_dict.end())
                    return hit->second.c_str();

                return text;
            }}

            // 有 ## : 先尝试完整字符串精确匹配(含##)
            {{
                auto it_full = s_dict.find(text);
                if (it_full != s_dict.end())
                    return it_full->second.c_str();
                // 去前导空格后重试
                if (leading_spaces > 0) {{
                    auto it_full2 = s_dict.find(trimmed);
                    if (it_full2 != s_dict.end())
                        return it_full2->second.c_str();
                }}
            }}

            // 再尝试只翻译显示部分, 保留 ##id
            size_t disp_len = (size_t)(hash_mark - trimmed);
            if (disp_len == 0)
                return text;

            // 1) 精确匹配显示部分(去掉前导空格)
            std::string disp_str(trimmed, disp_len);
            auto it = s_dict.find(disp_str);
            if (it != s_dict.end()) {{
                char* buf = next_buf();
                int n = snprintf(buf, BUF_SIZE, "%s%s", it->second.c_str(), hash_mark);
                if (n > 0 && n < BUF_SIZE) return buf;
                return text;
            }}

            // 2) 哈希匹配完整字符串
            uint32_t h_full = fnv1a_32(text);
            auto hit = s_hash_dict.find(h_full);
            if (hit != s_hash_dict.end()) {{
                if (hit->second.find("##") != std::string::npos)
                    return hit->second.c_str();
                char* buf = next_buf();
                int n = snprintf(buf, BUF_SIZE, "%s%s", hit->second.c_str(), hash_mark);
                if (n > 0 && n < BUF_SIZE) return buf;
                return text;
            }}

            // 3) 哈希匹配仅显示部分
            uint32_t h_disp = fnv1a_32(text, disp_len);
            hit = s_hash_dict.find(h_disp);
            if (hit != s_hash_dict.end()) {{
                char* buf = next_buf();
                int n = snprintf(buf, BUF_SIZE, "%s%s", hit->second.c_str(), hash_mark);
                if (n > 0 && n < BUF_SIZE) return buf;
            }}
        }} catch (...) {{
            // 绝不因翻译异常导致应用崩溃
        }}

        return text;
    }}

    // ---- startup ----
    void startup() {{
        init();
        g_imgui_translate_fn = &REF_ImGui_TranslateCB;
        spdlog::info("[Translation] ImGui translate callback installed");
    }}

    }} // namespace translation
    }} // namespace reframework
    ''')
    write_text(dst, code)
    log(f"已生成 Translation.cpp ({len(translations)} 字符串 + {len(hash_translations)} 哈希)")

# ============================================================================
# 步骤 4: Patch re2_imconfig.hpp
# ============================================================================
def patch_imconfig(build: Path):
    p = build / "src" / "re2-imgui" / "re2_imconfig.hpp"
    c = read_text(p)
    marker = "// [REF_TRANSLATE_HOOK]"
    if marker in c:
        return
    snippet = textwrap.dedent(f'''\

    // [REF_TRANSLATE_HOOK] 运行时翻译回调
    extern const char* (*g_imgui_translate_fn)(const char* text);
    static inline const char* ImGui_Translate(const char* text) {{
        return (text && g_imgui_translate_fn) ? g_imgui_translate_fn(text) : text;
    }}
    ''')
    c += snippet
    write_text(p, c)
    log("已 patch re2_imconfig.hpp")

# ============================================================================
# 步骤 5: Patch imgui.cpp (仅 Begin 窗口标题)
#   不再 hook SetTooltipV — 它是 printf-like 函数，翻译fmt会破坏格式说明符
# ============================================================================
def patch_imgui_cpp(build: Path):
    p = build / "dependencies" / "imgui" / "imgui.cpp"
    c = read_text(p)
    marker = "/* REF_TRANSLATE_PATCHED */"
    if marker in c:
        return

    anchor_inc = '#ifndef IMGUI_DISABLE\n#include "imgui_internal.h"'
    first_inc = c.find(anchor_inc)
    if first_inc == -1:
        fail("imgui.cpp: 找不到 #ifndef IMGUI_DISABLE / #include \"imgui_internal.h\"")
    target = '#include "imgui_internal.h"'
    inc_pos = c.index(target, first_inc)
    eol = c.index("\n", inc_pos)
    c = c[:eol+1] + "\n" + marker + "\n" + c[eol+1:]

    # Begin — 翻译窗口标题
    anchor_begin = (
        'bool ImGui::Begin(const char* name, bool* p_open, ImGuiWindowFlags flags)\n'
        '{\n'
        '    ImGuiContext& g = *GImGui;'
    )
    c = patch_insert_after(c, anchor_begin.split('\n')[1] + '\n',
        '    name = ImGui_Translate(name);\n',
        'Begin')

    write_text(p, c)
    log("已 patch imgui.cpp (仅 Begin)")

# ============================================================================
# 步骤 6: Patch imgui_widgets.cpp
#   安全规则:
#     ✗ Text/TextColored/TextDisabled/TextWrapped — printf-like, 会破坏格式说明符
#     ✗ CollapsingHeader — TreeNodeBehavior 已覆盖
#     ✓ 其余 widget 的 label 参数安全翻译
# ============================================================================
def patch_imgui_widgets(build: Path):
    p = build / "dependencies" / "imgui" / "imgui_widgets.cpp"
    c = read_text(p)
    marker = "/* REF_TRANSLATE_WIDGETS */"
    if marker in c:
        return

    first_include = c.find('#include "imgui.h"')
    if first_include == -1:
        fail("imgui_widgets.cpp: 找不到 #include \"imgui.h\"")
    eol = c.index("\n", first_include)
    c = c[:eol+1] + marker + "\n" + c[eol+1:]

    # TextEx: 特殊处理 text_end
    anchor = 'void ImGui::TextEx(const char* text, const char* text_end, ImGuiTextFlags flags)\n{\n'
    idx = c.find(anchor)
    if idx != -1:
        insert_pos = idx + len(anchor)
        snippet = (
            '    { const char* _t = ImGui_Translate(text); '
            'if (_t != text) { text = _t; text_end = NULL; } }\n'
        )
        c = c[:insert_pos] + snippet + c[insert_pos:]
        log("  TextEx ✓")

    # ButtonEx
    anchor = 'bool ImGui::ButtonEx(const char* label, const ImVec2& size_arg, ImGuiButtonFlags flags)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'ButtonEx')
    log("  ButtonEx ✓")

    # Checkbox
    anchor = 'bool ImGui::Checkbox(const char* label, bool* v)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'Checkbox')
    log("  Checkbox ✓")

    # RadioButton
    anchor = 'bool ImGui::RadioButton(const char* label, bool active)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'RadioButton')
    log("  RadioButton ✓")

    # BeginCombo
    anchor = 'bool ImGui::BeginCombo(const char* label, const char* preview_value, ImGuiComboFlags flags)\n{\n'
    c = patch_insert_after(c, anchor,
        '    label = ImGui_Translate(label);\n'
        '    preview_value = ImGui_Translate(preview_value);\n',
        'BeginCombo')
    log("  BeginCombo ✓")

    # DragScalar (仅label, 不动format)
    anchor = 'bool ImGui::DragScalar(const char* label, ImGuiDataType data_type, void* p_data, float v_speed, const void* p_min, const void* p_max, const char* format, ImGuiSliderFlags flags)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'DragScalar')
    log("  DragScalar ✓")

    # DragScalarN
    anchor = 'bool ImGui::DragScalarN(const char* label, ImGuiDataType data_type, void* p_data, int components, float v_speed, const void* p_min, const void* p_max, const char* format, ImGuiSliderFlags flags)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'DragScalarN')
    log("  DragScalarN ✓")

    # SliderScalar
    anchor = 'bool ImGui::SliderScalar(const char* label, ImGuiDataType data_type, void* p_data, const void* p_min, const void* p_max, const char* format, ImGuiSliderFlags flags)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'SliderScalar')
    log("  SliderScalar ✓")

    # SliderScalarN
    anchor = 'bool ImGui::SliderScalarN(const char* label, ImGuiDataType data_type, void* v, int components, const void* v_min, const void* v_max, const char* format, ImGuiSliderFlags flags)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'SliderScalarN')
    log("  SliderScalarN ✓")

    # InputScalar
    anchor = 'bool ImGui::InputScalar(const char* label, ImGuiDataType data_type, void* p_data, const void* p_step, const void* p_step_fast, const char* format, ImGuiInputTextFlags flags)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'InputScalar')
    log("  InputScalar ✓")

    # InputScalarN
    anchor = 'bool ImGui::InputScalarN(const char* label, ImGuiDataType data_type, void* p_data, int components, const void* p_step, const void* p_step_fast, const char* format, ImGuiInputTextFlags flags)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'InputScalarN')
    log("  InputScalarN ✓")

    # InputText
    anchor = 'bool ImGui::InputText(const char* label, char* buf, size_t buf_size, ImGuiInputTextFlags flags, ImGuiInputTextCallback callback, void* user_data)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'InputText')
    log("  InputText ✓")

    # InputTextMultiline
    anchor = 'bool ImGui::InputTextMultiline(const char* label, char* buf, size_t buf_size, const ImVec2& size, ImGuiInputTextFlags flags, ImGuiInputTextCallback callback, void* user_data)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'InputTextMultiline')
    log("  InputTextMultiline ✓")

    # InputTextWithHint
    anchor = 'bool ImGui::InputTextWithHint(const char* label, const char* hint, char* buf, size_t buf_size, ImGuiInputTextFlags flags, ImGuiInputTextCallback callback, void* user_data)\n{\n'
    c = patch_insert_after(c, anchor,
        '    label = ImGui_Translate(label);\n'
        '    hint = ImGui_Translate(hint);\n',
        'InputTextWithHint')
    log("  InputTextWithHint ✓")

    # TreeNodeBehavior (CollapsingHeader/TreeNode 最终都经过这里)
    anchor = 'bool ImGui::TreeNodeBehavior(ImGuiID id, ImGuiTreeNodeFlags flags, const char* label, const char* label_end)\n{\n'
    c = patch_insert_after(c, anchor,
        '    { const char* _t = ImGui_Translate(label); '
        'if (_t != label) { label = _t; label_end = NULL; } }\n',
        'TreeNodeBehavior')
    log("  TreeNodeBehavior ✓")

    # Selectable #1
    anchor = 'bool ImGui::Selectable(const char* label, bool selected, ImGuiSelectableFlags flags, const ImVec2& size_arg)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'Selectable#1')
    log("  Selectable#1 ✓")

    # Selectable #2
    anchor = 'bool ImGui::Selectable(const char* label, bool* p_selected, ImGuiSelectableFlags flags, const ImVec2& size_arg)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'Selectable#2')
    log("  Selectable#2 ✓")

    # BeginMenuEx
    anchor = 'bool ImGui::BeginMenuEx(const char* label, const char* icon, bool enabled)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'BeginMenuEx')
    log("  BeginMenuEx ✓")

    # MenuItemEx (仅label, shortcut不翻译)
    anchor = 'bool ImGui::MenuItemEx(const char* label, const char* icon, const char* shortcut, bool selected, bool enabled)\n{\n'
    c = patch_insert_after(c, anchor,
        '    label = ImGui_Translate(label);\n',
        'MenuItemEx')
    log("  MenuItemEx ✓")

    # BeginTabItem
    anchor = 'bool    ImGui::BeginTabItem(const char* label, bool* p_open, ImGuiTabItemFlags flags)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'BeginTabItem')
    log("  BeginTabItem ✓")

    # TabItemButton
    anchor = 'bool    ImGui::TabItemButton(const char* label, ImGuiTabItemFlags flags)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'TabItemButton')
    log("  TabItemButton ✓")

    # SeparatorText
    anchor = 'void ImGui::SeparatorText(const char* label)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'SeparatorText')
    log("  SeparatorText ✓")

    # LabelTextV (仅翻译 label, 不翻译 fmt — fmt 是 printf 格式字符串)
    anchor = 'void ImGui::LabelTextV(const char* label, const char* fmt, va_list args)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'LabelTextV')
    log("  LabelTextV ✓")

    # PlotEx (内部函数，PlotLines/PlotHistogram 都走这里; 仅翻译 label)
    anchor = 'int ImGui::PlotEx(ImGuiPlotType plot_type, const char* label, float (*values_getter)(void* data, int idx), void* data, int values_count, int values_offset, const char* overlay_text, float scale_min, float scale_max, const ImVec2& size_arg)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'PlotEx')
    log("  PlotEx ✓")

    write_text(p, c)
    log("已 patch imgui_widgets.cpp (24 个安全 hook)")

# ============================================================================
# 步骤 6b: Patch imgui_tables.cpp (表格列标题翻译)
# ============================================================================
def patch_imgui_tables(build: Path):
    p = build / "dependencies" / "imgui" / "imgui_tables.cpp"
    c = read_text(p)
    marker = "/* REF_TRANSLATE_TABLES */"
    if marker in c:
        return

    first_include = c.find('#include "imgui.h"')
    if first_include == -1:
        fail("imgui_tables.cpp: 找不到 #include \"imgui.h\"")
    eol = c.index("\n", first_include)
    c = c[:eol+1] + marker + "\n" + c[eol+1:]

    # TableSetupColumn
    anchor = 'void ImGui::TableSetupColumn(const char* label, ImGuiTableColumnFlags flags, float init_width_or_weight, ImGuiID user_id)\n{\n'
    c = patch_insert_after(c, anchor, '    label = ImGui_Translate(label);\n', 'TableSetupColumn')
    log("  TableSetupColumn ✓")

    write_text(p, c)
    log("已 patch imgui_tables.cpp (1 个安全 hook)")

# ============================================================================
# 步骤 7: Patch cmake.toml
# ============================================================================
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


def patch_linux_cmake(build: Path):
    """仅修改构建副本，移除当前上游目标所需的 MSVC 专属配置。"""
    cmake_lists = build / "CMakeLists.txt"
    content = read_text(cmake_lists)
    marker = "# [REF_LINUX_CROSS_COMPILE_PATCHED]"
    if marker in content:
        return

    build_target = resolve_build_target(build)
    sdk_target = "REFrameworkSDK" if build_target == "REFramework" else "MHWILDSSDK"

    cmkr_bootstrap_pattern = (
        r'^([ \t]*)# Bootstrap cmkr and automatically regenerate CMakeLists\.txt\n'
        r'\1include\(cmkr\.cmake OPTIONAL RESULT_VARIABLE CMKR_INCLUDE_RESULT\)\n'
        r'\1if\(CMKR_INCLUDE_RESULT\)\n'
        r'\1\tcmkr\(\)\n'
        r'\1endif\(\)\n'
    )
    content = replace_cmake_regex_once(
        content,
        cmkr_bootstrap_pattern,
        '# Bootstrap cmkr is disabled for the localized Linux cross-build\n',
        "cmkr 自动重生成",
    )
    content = replace_cmake_once(content, "\t\tCSharp\n", "", "CSharp 语言")
    content = replace_cmake_once(content, "include(CSharpUtilities)\n\n", "", "CSharp 工具")
    windows_flags = '''set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} /MP")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /MP")
'''
    content = replace_cmake_once(content, windows_flags, "", "MSVC 并行参数")
    release_pattern = r'if \("\$\{CMAKE_BUILD_TYPE\}" MATCHES "Release"\).*?set\(CMAKE_MSVC_RUNTIME_LIBRARY ".*?"\)\n'
    content = replace_cmake_regex_once(content, release_pattern, 'message(NOTICE "Building Linux cross-compiled Release mode")\n', "MSVC 运行库参数")
    content = replace_cmake_once(content, 'if(CMAKE_CXX_COMPILER_VERSION VERSION_GREATER_EQUAL 19.35)\n\t    target_compile_options(DirectXTK PRIVATE /Zc:templateScope-)\n\t    target_compile_options(DirectXTK12 PRIVATE /Zc:templateScope-)\n\tendif()\n', '', "DirectXTK MSVC 参数")
    content = replace_cmake_once(content, 'target_compile_options(utility PUBLIC\n\t"/EHa"\n)\n\n', '', "utility MSVC 参数")
    content = replace_cmake_once(content, f'target_compile_options({sdk_target} PUBLIC\n\t\t"/EHa"\n\t)\n\n', '', f"{sdk_target} MSVC 参数")
    content = replace_cmake_once(content, f'target_compile_options({build_target} PUBLIC\n\t\t"/GS-"\n\t\t"/bigobj"\n\t\t"/EHa"\n\t)\n\n', '', f"{build_target} MSVC 参数")
    if build_target == "REFramework":
        cimgui_block_start = content.find(
            '\tset_source_files_properties(\n\t    "src/cimgui/cimgui.cpp"\n'
        )
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
        definitions = re.sub(r'\s+', '', content[cimgui_definitions_start:cimgui_definitions_end])
        content = (
            content[:cimgui_definitions_start]
            + definitions
            + content[cimgui_definitions_end:]
        )
    target_pattern = rf'(^# Target: {re.escape(build_target)}\n.*?)(?=^# Target:|\Z)'
    match = re.search(target_pattern, content, flags=re.DOTALL | re.MULTILINE)
    if not match:
        fail(f"Linux CMake 适配锚点异常: {build_target} 目标块不存在")
    target_block = match.group(1)
    target_block = replace_cmake_once(target_block, '\t\tLINK_FLAGS\n\t\t\t"/DELAYLOAD:openvr_api.dll /DELAYLOAD:openxr_loader.dll /DELAYLOAD:d3d11.dll /DELAYLOAD:d3d12.dll /DELAYLOAD:D3DCOMPILER_47.dll"\n', '', f"{build_target} 延迟加载参数")
    target_block = replace_cmake_regex_once(target_block, r'\tadd_custom_command\(\n\t    TARGET [^\n]+ PRE_BUILD\n\t    COMMAND \$\{CMAKE_COMMAND\} -E echo "Generating commit hash\.\.\."\n\t    COMMAND \$\{CMAKE_COMMAND\} -E chdir \$\{CMAKE_SOURCE_DIR\} \$\{CMAKE_SOURCE_DIR\}/MakeCommitHash\.bat\n\t\)\n\n', '', f"{build_target} Windows 构建钩子")
    target_block = replace_cmake_once(target_block, '\t\t"src/REFramework.hpp"\n', '\t\t"src/REFramework.hpp"\n\t\t"src/Translation.cpp"\n\t\t"src/Translation.hpp"\n', f"{build_target} 翻译源文件")
    content = content[:match.start()] + target_block + content[match.end():]
    write_text(cmake_lists, content + f"\n{marker}\n")
    log("已 patch CMakeLists.txt (Linux 交叉编译适配)")


def patch_cmake_toml(build: Path):
    if not IS_WINDOWS_BUILD:
        patch_linux_cmake(build)
        return

    p = build / "cmake.toml"
    c = read_text(p)
    marker = "# [REF_TRANSLATE_PATCHED]"
    cmake_lists = build / "CMakeLists.txt"
    cmake_lists_marker = "# [REF_TRANSLATE_CMAKELISTS_PATCHED]"

    if marker not in c:
        c = c.replace(
            'set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} /MP")',
            'set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} /MP /utf-8")'
        )
        c = c.replace(
            'set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /MP")',
            'set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /MP /utf-8")'
        )
        c = c.replace(
            'compile-options = ["/GS-", "/bigobj", "/EHa"]',
            'compile-options = ["/GS-", "/bigobj", "/EHa", "/utf-8"]'
        )
        # 新版源码需要 CSharp 但我们只编译 C++ 目标，移除避免报错
        c = c.replace(
            'languages = ["CXX", "C", "CSharp"]',
            'languages = ["CXX", "C"]'
        )
        c += f"\n{marker}\n"
        write_text(p, c)
        log("已 patch cmake.toml (/utf-8)")

    cmake_lists_text = read_text(cmake_lists)
    if cmake_lists_marker not in cmake_lists_text:
        cmake_lists_text = re.sub(
            r'(?ms)^([ \t]*)# Bootstrap cmkr and automatically regenerate CMakeLists\.txt\n'
            r'\1include\(cmkr\.cmake OPTIONAL RESULT_VARIABLE CMKR_INCLUDE_RESULT\)\n'
            r'\1if\(CMKR_INCLUDE_RESULT\)\n'
            r'\1\tcmkr\(\)\n'
            r'\1endif\(\)\n',
            r'\1# Bootstrap cmkr and automatically regenerate CMakeLists.txt\n'
            r'\1message(STATUS "Skipping cmkr regeneration for localized build")\n',
            cmake_lists_text,
            count=1,
        )
        cmake_lists_text = re.sub(
            r'(?m)^[ \t]*CSharp\s*\n',
            '',
            cmake_lists_text,
            count=1,
        )
        cmake_lists_text = re.sub(
            r'(?m)^include\(CSharpUtilities\)\s*\n',
            '',
            cmake_lists_text,
            count=1,
        )
        cmake_lists_text = cmake_lists_text.replace(
            'set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} /MP")',
            'set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} /MP /utf-8")'
        )
        cmake_lists_text = cmake_lists_text.replace(
            'set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /MP")',
            'set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /MP /utf-8")'
        )
        # 注入 Translation.cpp/hpp 到所有 game target 的源文件列表
        # 禁用 cmkr 后 CMakeLists.txt 不再自动从 glob 拾取新文件，需手动添加
        cmake_lists_text = cmake_lists_text.replace(
            '"src/REFramework.hpp"\n',
            '"src/REFramework.hpp"\n\t\t"src/Translation.cpp"\n\t\t"src/Translation.hpp"\n'
        )
        cmake_lists_text += f"\n{cmake_lists_marker}\n"
        write_text(cmake_lists, cmake_lists_text)
        log("已 patch CMakeLists.txt (跳过 cmkr + 注入翻译源文件)")

# ============================================================================
# 步骤 8: Patch REFramework.cpp
# ============================================================================
def patch_reframework_cpp(build: Path):
    p = build / "src" / "REFramework.cpp"
    c = read_text(p)
    marker = "/* REF_TRANSLATE_INIT */"
    if marker in c:
        return

    inc_anchor = '#include <REFramework.hpp>'
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
            'cfg.GlyphRanges = fonts->GetGlyphRangesChineseFull();\n'
            '            ' + full_font_line
        )

    # 调用 startup()
    startup_anchor = 'spdlog::info("Loaded default font: {}", m_default_font_file);'
    if startup_anchor in c:
        c = c.replace(
            startup_anchor,
            startup_anchor + '\n                reframework::translation::startup();'
        )
    else:
        alt_anchor = 'm_default_font = loaded_fonts["DEFAULT"];'
        if alt_anchor in c:
            idx = c.rfind(alt_anchor)
            end = idx + len(alt_anchor)
            c = c[:end] + '\n        reframework::translation::startup();' + c[end:]

    write_text(p, c)
    log("已 patch REFramework.cpp (CJK 字体 + 翻译初始化)")

# ============================================================================
# 步骤 8.5: 清理旧产物
# ============================================================================
def clean_outputs():
    """删除当前输出目录下已有的 dinput8.dll。"""
    dll = OUTPUT_DIR / "dinput8.dll"
    if dll.exists():
        dll.unlink()
        log(f"已删除旧 DLL: {dll}")

def clear_windows_attributes(path: Path):
    """清除 Windows 下目录及其子项的只读/隐藏/系统属性，提高删除成功率。"""
    if os.name != "nt" or not path.exists():
        return

    try:
        subprocess.run(
            ["cmd", "/c", "attrib", "-R", "-H", "-S", str(path)],
            capture_output=True,
            timeout=60,
        )
    except Exception:
        pass

    try:
        wildcard = str(path / "*")
        subprocess.run(
            ["cmd", "/c", "attrib", "-R", "-H", "-S", "/S", "/D", wildcard],
            capture_output=True,
            timeout=180,
        )
    except Exception:
        pass

def force_remove_tree(path: Path, label: str = "目录", retries: int = 4, delay: float = 1.0):
    """在 Windows 下尽量稳妥地删除目录，处理隐藏/只读属性与 rd 兜底。"""
    if not path.exists():
        return

    last_err = None
    for attempt in range(1, retries + 1):
        clear_windows_attributes(path)

        try:
            shutil.rmtree(str(path))
        except Exception as e:
            last_err = e

        if not path.exists():
            return

        # PowerShell 的 Remove-Item 对隐藏目录更稳一些
        if os.name == "nt":
            try:
                escaped_path = str(path).replace("'", "''")
                subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        (
                            f"$p = '{escaped_path}'; "
                            "if(Test-Path -LiteralPath $p){ "
                            "Get-ChildItem -LiteralPath $p -Force -Recurse -ErrorAction SilentlyContinue | "
                            "ForEach-Object { try { $_.Attributes = 'Normal' } catch {} }; "
                            "Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue }"
                        ),
                    ],
                    capture_output=True,
                    timeout=180,
                )
            except Exception as e:
                last_err = e

        if not path.exists():
            return

        try:
            subprocess.run(
                ["cmd", "/c", "rd", "/s", "/q", str(path)],
                capture_output=True,
                timeout=120,
            )
        except Exception as e:
            last_err = e

        if not path.exists():
            return

        if attempt < retries:
            log(f"{label} 清理未完成，正在重试 ({attempt}/{retries})：{path}")
            time.sleep(delay * attempt)

    detail = f"{last_err}" if last_err else "未知原因"
    fail(f"{label} 清理失败: {path} ({detail})")

def mirror_tree(src: Path, dst: Path, exclude_dirs=None):
    exclude_dirs = exclude_dirs or []
    if not IS_WINDOWS_BUILD:
        ignored = shutil.ignore_patterns(*exclude_dirs)
        shutil.copytree(src, dst, ignore=ignored)
        return

    args = [
        "robocopy", str(src), str(dst), "/MIR", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
    ]
    if exclude_dirs:
        args.extend(["/XD", *exclude_dirs])
    ret = subprocess.run(args, capture_output=True, timeout=300)
    if ret.returncode >= 8:
        stdout = decode_cmd_bytes(ret.stdout or b"").strip()
        stderr = decode_cmd_bytes(ret.stderr or b"").strip()
        detail = stdout or stderr or f"代码 {ret.returncode}"
        fail(f"robocopy 失败: {detail[:200]}")

# ============================================================================
# 步骤 9: 克隆/拉取最新代码 + 复制源码
# ============================================================================
def copy_source():
    max_attempts = 3

    if SRC_DIR.exists() and (SRC_DIR / ".git").exists():
        log("发现本地源码，正在同步到最新 origin/master...")

        local_branch = git_output(["rev-parse", "--abbrev-ref", "HEAD"], cwd=SRC_DIR)
        local_head = git_output(["rev-parse", "--short", "HEAD"], cwd=SRC_DIR)
        local_full_head = git_output(["rev-parse", "HEAD"], cwd=SRC_DIR)
        expected_head = os.environ.get("UPSTREAM_SHA", "").strip()
        if local_branch:
            log(f"本地分支: {local_branch}")
        if local_head:
            log(f"本地HEAD: {local_head}")

        if expected_head and local_full_head == expected_head:
            log("本地源码已与本次检测到的上游提交一致，跳过重复网络拉取。")
        else:
            ret = run_with_retry_progress(
                ["git", "fetch", "--depth", "1", "--progress", "origin", "master"],
                "更新本地仓库",
                r'(\d+)%',
                cwd=SRC_DIR,
                max_attempts=max_attempts,
            )
            if ret.returncode != 0:
                fail("git fetch 失败，请检查 GitHub 连接。")

            remote_head = git_output(["rev-parse", "--short", "origin/master"], cwd=SRC_DIR)
            if remote_head:
                log(f"远程HEAD: {remote_head}")

            ret = subprocess.run(
                ["git", "reset", "--hard", "origin/master"],
                cwd=str(SRC_DIR),
                capture_output=True,
                timeout=300
            )
            if ret.returncode != 0:
                fail("git reset --hard origin/master 失败")

            subprocess.run(["git", "clean", "-fd"], cwd=str(SRC_DIR), capture_output=True, timeout=120)

            ret = run_with_retry_progress(
                ["git", "submodule", "update", "--init", "--recursive", "--depth", "1", "--progress"],
                "拉取最新子模块",
                r'(\d+)%',
                cwd=SRC_DIR,
                max_attempts=max_attempts,
            )
            if ret.returncode != 0:
                fail("git submodule update 失败")

            log("源码及子模块已更新到最新版！")
    else:
        if SRC_DIR.exists():
            log(f"检测到现有目录但不是有效 Git 仓库，先清理: {SRC_DIR}")
            force_remove_tree(SRC_DIR, "源码目录")

        log("未发现本地源码，正在从 GitHub 克隆最新源码...")
        def cleanup_clone_retry(_attempt):
            if SRC_DIR.exists():
                force_remove_tree(SRC_DIR, "源码目录")

        ret = run_with_retry_progress(
            ["git", "clone", "--progress", "--recurse-submodules", "--depth", "1", GIT_REPO, str(SRC_DIR)],
            "克隆源码及依赖 (耗时较长，请耐心等待)",
            regex=r'(\d+)%',
            max_attempts=max_attempts,
            on_retry=cleanup_clone_retry,
        )
        if ret.returncode != 0:
            stderr = decode_cmd_bytes(ret.stdout).strip() if ret.stdout else ""
            fail(f"克隆失败: {stderr[:200]}")

        log("源码克隆成功！")

    # 拉取所有 tag 引用 (浅克隆不包含 tag，导致版本号显示为 no_tag)
    log("正在拉取版本 tag 信息...")
    try:
        subprocess.run(["git", "fetch", "--tags", "--force"],
                       cwd=str(SRC_DIR), capture_output=True, timeout=60)
        # 深化历史以便 git describe 能找到 tag
        subprocess.run(["git", "fetch", "--deepen", "200"],
                       cwd=str(SRC_DIR), capture_output=True, timeout=60)
        log("tag 信息拉取完成")
    except Exception as e:
        log(f"tag 拉取失败 (非严重): {e}")

    # 获取当前 commit 信息
    try:
        ret = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=str(SRC_DIR), capture_output=True, timeout=10
        )
        if ret.returncode == 0:
            commit_info = decode_cmd_bytes(ret.stdout).strip()
            log(f"当前版本: {commit_info}")
    except Exception:
        pass

    log(f"正在复制源码到 {BUILD_ROOT}...")
    # 全量重建: 清空构建目录确保产出全新 DLL
    if BUILD_ROOT.exists():
        log(f"正在清空旧构建目录: {BUILD_ROOT}...")
        force_remove_tree(BUILD_ROOT, "构建根目录")

    mirror_tree(SRC_DIR, BUILD_ROOT, exclude_dirs=[".git", "build"])
    log("源码复制完成")

    return {"mode": "latest"}
# ============================================================================
# 步骤 9.5: 生成版本信息 (CommitHash.autogenerated)
# ============================================================================
def generate_commit_hash():
    """在 BUILD_ROOT 生成 CommitHash.autogenerated，避免浅克隆导致 git describe 失败"""
    def git_output(args):
        try:
            r = subprocess.run(["git"] + args, cwd=str(SRC_DIR),
                               capture_output=True, timeout=10)
            return decode_cmd_bytes(r.stdout).strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    commit_hash = git_output(["rev-parse", "HEAD"])
    tag = git_output(["describe", "--tags", "--abbrev=0"])
    if not tag:
        # 备用: 取最新 tag 名
        tag = git_output(["tag", "--sort=-version:refname"]).split("\n")[0].strip()
    if not tag:
        tag = "unknown"

    tag_long = git_output(["describe", "--tags", "--long"])
    commits_past_tag = "0"
    if tag_long:
        # 格式: v1.722-15-gabcdef
        m = re.match(r".+-(\d+)-g[0-9a-f]+$", tag_long)
        if m:
            commits_past_tag = m.group(1)

    branch = git_output(["rev-parse", "--abbrev-ref", "HEAD"]) or "master"
    total_commits = git_output(["rev-list", "--count", "HEAD"]) or "0"

    now = datetime.now()
    build_date = now.strftime("%d.%m.%Y")
    build_time = now.strftime("%H:%M")

    content = (
        f'#pragma once\n'
        f'#define REF_COMMIT_HASH "{commit_hash}"\n'
        f'#define REF_TAG "{tag}"\n'
        f'#define REF_TAG_LONG "{tag_long}"\n'
        f'#define REF_COMMITS_PAST_TAG {commits_past_tag}\n'
        f'#define REF_BRANCH "{branch}"\n'
        f'#define REF_TOTAL_COMMITS {total_commits}\n'
        f'#define REF_BUILD_DATE "{build_date}"\n'
        f'#define REF_BUILD_TIME "{build_time}"\n'
    )

    out_path = BUILD_ROOT / "src" / "CommitHash.autogenerated"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    log(f"版本信息: tag={tag}, commits_past_tag={commits_past_tag}, branch={branch}")
    log(f"已生成 {out_path}")

# ============================================================================
# 步骤 10: CMake + 编译
# ============================================================================
def build():
    global BUILD_DIR_NAME
    cmake = CMAKE_BIN if os.path.isfile(CMAKE_BIN) else "cmake"

    def run_cmd(args, label, regex=None, zeno_speed=0.03, fatal=True):
        ret = run_with_progress(args, label, regex=regex, cwd=BUILD_ROOT, zeno_speed=zeno_speed)
        if ret.returncode != 0:
            stdout = decode_cmd_bytes(ret.stdout)
            lines = stdout.split("\n")
            error_lines = [l for l in lines if "error" in l.lower()]
            if error_lines:
                for l in error_lines[-30:]:
                    safe_echo(l)
            else:
                for l in lines[-30:]:
                    safe_echo(l)
            if fatal:
                fail(f"{label} 失败 (代码 {ret.returncode})")
        return ret.returncode, ret.stdout

    max_cfg_retries = 3
    for attempt in range(1, max_cfg_retries + 1):
        build_dir_name = "build" if attempt == 1 else f"build_retry_{attempt}"
        if IS_WINDOWS_BUILD:
            cmake_config_args = [cmake, "-B", build_dir_name, "-G", "Visual Studio 17 2022", "-A", "x64"]
        else:
            if not TOOLCHAIN_FILE:
                fail("Linux 构建缺少 REF_TOOLCHAIN_FILE")
            cmake_config_args = [
                cmake, "-S", ".", "-B", build_dir_name, "-G", "Ninja",
                "-DCMAKE_BUILD_TYPE=Release",
                f"-DCMAKE_TOOLCHAIN_FILE={TOOLCHAIN_FILE}",
                "-DFETCHCONTENT_BASE_DIR=/runtime/fetch-content",
            ]
        code, _ = run_cmd(cmake_config_args, "CMake 配置生成", regex=None, zeno_speed=0.05, fatal=False)
        if code == 0:
            BUILD_DIR_NAME = build_dir_name
            break

        if attempt < max_cfg_retries:
            log(f"CMake 配置失败，准备重试 ({attempt}/{max_cfg_retries})，下次将切换到新的构建目录...")
            build_dir = BUILD_ROOT / build_dir_name
            if build_dir.exists():
                force_remove_tree(build_dir, "CMake 构建目录")
                log(f"已清理构建目录: {build_dir}")
            time.sleep(2)
        else:
            fail(f"CMake 配置生成 失败 (代码 {code})")

    build_args = [cmake, "--build", BUILD_DIR_NAME, "--target", BUILD_TARGET]
    if IS_WINDOWS_BUILD:
        build_args.extend(["--config", "Release"])
    run_cmd(build_args,
            "编译核心 DLL 二进制", regex=r'\[\s*(\d+)%\]', zeno_speed=0.005, fatal=True)

# ============================================================================
# 步骤 11: 打包
# ============================================================================
def package(zip_label: str):
    dll_path = BUILD_ROOT / BUILD_DIR_NAME / "bin" / BUILD_TARGET / "dinput8.dll"
    if not dll_path.exists():
        fail(f"找不到编译产物: {dll_path}")
    if not REWARD_QR_FILE.exists():
        fail(f"找不到打赏二维码: {REWARD_QR_FILE}")

    dll_size = dll_path.stat().st_size
    log(f"DLL 大小: {dll_size:,} 字节")

    zip_name = f"{zip_label}.zip"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUTPUT_DIR / zip_name
    with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(str(dll_path), "dinput8.dll")
        zf.write(str(REWARD_QR_FILE), "赏口饭吃.jpg")

    zip_size = zip_path.stat().st_size
    log(f"已打包: {zip_path}")
    log("已包含打赏二维码: 赏口饭吃.jpg")
    log(f"ZIP 大小: {zip_size:,} 字节")
    return zip_path


# ============================================================================
# 步骤 12: 发布 GitHub 历史版本
# ============================================================================
def run_publish_command(args, cwd=None, allow_failure=False):
    """运行发布命令，失败时保留命令自身的清晰提示。"""
    try:
        result = subprocess.run(args, cwd=str(cwd) if cwd else None)
    except FileNotFoundError:
        if allow_failure:
            return None
        fail(f"未找到发布工具: {args[0]}")

    if result.returncode != 0 and not allow_failure:
        fail(f"发布步骤失败: {' '.join(args[:3])}")
    return result


def ensure_github_release_access():
    """确认 GitHub CLI 已安装并完成首次浏览器登录。"""
    if shutil.which("gh") is None:
        fail("未安装 GitHub CLI，请先安装后再运行构建脚本。")

    status = run_publish_command(
        ["gh", "auth", "status", "--hostname", "github.com"],
        allow_failure=True,
    )
    if status is not None and status.returncode == 0:
        return

    log("首次发布需要登录 GitHub，浏览器即将打开，请完成授权后返回此窗口。")
    run_publish_command([
        "gh", "auth", "login", "--hostname", "github.com",
        "--git-protocol", "https", "--web",
    ])


def initialize_publish_repository():
    """初始化仅存放最新 ZIP 的本地发布缓存仓库。"""
    git_dir = PUBLISH_CACHE_DIR / ".git"
    if not git_dir.exists():
        if PUBLISH_CACHE_DIR.exists():
            fail(f"发布缓存目录不是 Git 仓库: {PUBLISH_CACHE_DIR}")
        run_publish_command(["git", "clone", GITHUB_RELEASE_REPOSITORY_URL, str(PUBLISH_CACHE_DIR)])

    has_head = run_publish_command(
        ["git", "-C", str(PUBLISH_CACHE_DIR), "rev-parse", "--verify", "HEAD"],
        allow_failure=True,
    )
    if has_head is not None and has_head.returncode == 0:
        run_publish_command([
            "git", "-C", str(PUBLISH_CACHE_DIR), "pull", "--ff-only",
            "origin", "main",
        ])
        return

    run_publish_command(["git", "-C", str(PUBLISH_CACHE_DIR), "switch", "-c", "main"])


def stage_current_package(package_path: Path) -> tuple[Path, str]:
    """用新 ZIP 替换仓库首页的旧成品，并生成校验文件。"""
    for old_package in PUBLISH_CACHE_DIR.glob("REF Nightly *.zip"):
        old_package.unlink()
    for old_checksum in PUBLISH_CACHE_DIR.glob("REF Nightly *.zip.sha256"):
        old_checksum.unlink()

    published_package = PUBLISH_CACHE_DIR / package_path.name
    shutil.copy2(package_path, published_package)
    package_hash = hashlib.sha256(package_path.read_bytes()).hexdigest()
    checksum_path = PUBLISH_CACHE_DIR / f"{package_path.name}.sha256"
    checksum_path.write_text(f"{package_hash}  {package_path.name}\n", encoding="ascii")

    run_publish_command([
        "git", "-C", str(PUBLISH_CACHE_DIR), "add", "--all", "--",
        "REF Nightly *.zip", "REF Nightly *.zip.sha256",
    ])
    return checksum_path, package_hash


def push_current_package(package_name: str):
    """提交并推送仓库主页展示的最新 ZIP。"""
    diff = run_publish_command(
        ["git", "-C", str(PUBLISH_CACHE_DIR), "diff", "--cached", "--quiet"],
        allow_failure=True,
    )
    if diff is not None and diff.returncode == 0:
        log("ZIP 内容未变化，仓库主页无需重复更新。")
        return

    run_publish_command(["git", "-C", str(PUBLISH_CACHE_DIR), "config", "user.name", "REFramework Chinese Builder"])
    run_publish_command(["git", "-C", str(PUBLISH_CACHE_DIR), "config", "user.email", "reframework-chinese-builder@users.noreply.github.com"])
    message = f"Publish {package_name} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    run_publish_command(["git", "-C", str(PUBLISH_CACHE_DIR), "commit", "-m", message])
    run_publish_command(["git", "-C", str(PUBLISH_CACHE_DIR), "push", "origin", "HEAD:main"])


def create_github_release(package_path: Path, checksum_path: Path, package_hash: str):
    """为不同内容的 ZIP 创建可长期下载的 GitHub Releases 历史版本。"""
    release_tag = f"build-{package_hash[:12]}"
    existing_release = run_publish_command(
        ["gh", "release", "view", release_tag, "--repo", GITHUB_RELEASE_REPOSITORY],
        allow_failure=True,
    )
    if existing_release is not None and existing_release.returncode == 0:
        log("这个 ZIP 已存在对应的 GitHub 历史发布版本。")
        return

    nightly_match = re.match(r"REF Nightly (\d+)", package_path.stem)
    if nightly_match is None:
        fail(f"无法从包名识别 Nightly 编号: {package_path.name}")

    release_asset_name = f"REF-Nightly-{nightly_match.group(1)}-Chinese-Edition.zip"
    release_package_path = package_path.with_name(release_asset_name)
    release_checksum_path = release_package_path.with_name(f"{release_asset_name}.sha256")
    shutil.copy2(package_path, release_package_path)
    release_checksum_path.write_text(
        f"{package_hash}  {release_asset_name}\n", encoding="ascii"
    )

    run_publish_command([
        "gh", "release", "create", release_tag,
        str(release_package_path),
        str(release_checksum_path),
        "--repo", GITHUB_RELEASE_REPOSITORY,
        "--title", package_path.stem,
        "--notes", "由本机 Visual Studio 构建并自动发布。",
    ])
    log(f"已创建 GitHub 历史版本: https://github.com/{GITHUB_RELEASE_REPOSITORY}/releases")


def publish_package(package_path: Path):
    """发布最新 ZIP，并为每个不同成品保留独立历史版本。"""
    log("正在发布 ZIP 到 GitHub 成品仓库...")
    ensure_github_release_access()
    initialize_publish_repository()
    checksum_path, package_hash = stage_current_package(package_path)
    push_current_package(package_path.name)
    create_github_release(package_path, checksum_path, package_hash)

# ============================================================================
# 主流程
# ============================================================================
def main():
    global BUILD_ROOT, BUILD_DIR_NAME, BUILD_TARGET
    build_started = datetime.now().astimezone()
    session_id = build_started.strftime("%Y%m%d-%H%M%S")
    BUILD_ROOT = BUILD_ROOT_BASE / session_id
    BUILD_DIR_NAME = "build"

    log("=" * 60)
    log(f"{'🚀' if USE_FANCY_CONSOLE else '[START]'} REFramework 一键汉化构建")
    log(f"会话ID: {session_id}")
    log(f"构建目录: {BUILD_ROOT}")
    log("=" * 60)

    # 清理旧产物
    clean_outputs()

    # 智能更新拉取或克隆最新代码
    copy_source()
    BUILD_TARGET = resolve_build_target(BUILD_ROOT)
    log(f"已识别上游构建目标: {BUILD_TARGET}")

    # 包名严格使用 REFramework-nightly 发布列表的 Nightly 编号。
    nightly_num = get_nightly_number()
    zip_label = f"REF Nightly {nightly_num} -前置汉化版"

    translations = load_translations()
    hash_translations = load_hash_dict()

    log("=" * 60)
    log(f"{'✨' if USE_FANCY_CONSOLE else '*'} 汉化资源加载完毕: 共同汇集入 {len(translations) + len(hash_translations)} 条翻译记录")
    log(f"   - 精确匹配词条项: {len(translations)}")
    log(f"   - 哈希兜底匹配项: {len(hash_translations)}")
    log("=" * 60)

    generate_commit_hash()

    generate_translation_hpp(BUILD_ROOT / "src" / "Translation.hpp")
    generate_translation_cpp(translations, hash_translations, BUILD_ROOT / "src" / "Translation.cpp")

    global SILENT_LOG
    SILENT_LOG = True
    ptr = TaskProgress("向 C++ 核心源码安全注入汉化钩子")
    ptr.start()

    ptr.set_percent(10); patch_imconfig(BUILD_ROOT)
    ptr.set_percent(30); patch_imgui_cpp(BUILD_ROOT)
    ptr.set_percent(50); patch_imgui_widgets(BUILD_ROOT)
    ptr.set_percent(70); patch_imgui_tables(BUILD_ROOT)
    ptr.set_percent(90); patch_cmake_toml(BUILD_ROOT)
    ptr.set_percent(95); patch_reframework_cpp(BUILD_ROOT)

    ptr.set_percent(100)
    ptr.stop(True)
    SILENT_LOG = False

    build()
    zip_path = package(zip_label)
    if os.environ.get("SKIP_GITHUB_PUBLISH") == "1":
        log("当前由 GitHub Actions 发布 ZIP，跳过本地发布步骤。")
    else:
        publish_package(zip_path)

    log("=" * 60)
    log(f"{'🎉' if USE_FANCY_CONSOLE else '[OK]'} 汉化打包大功告成！")
    log(f"{'🎁' if USE_FANCY_CONSOLE else '[ZIP]'} 输出包名: {zip_label}.zip")
    log(f"{'📦' if USE_FANCY_CONSOLE else '[OUT]'} 文件位置: {OUTPUT_DIR / (zip_label + '.zip')}")
    log("=" * 60)
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stream_write(sys.stdout, f"\n\x1b[2K\r[汉化构建] {'⚠️' if USE_FANCY_CONSOLE else '[WARN]'} 用户手动终止了构建过程 (Ctrl+C)\n")
        sys.exit(1)


