#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MongoDB Compass 一键汉化 / 还原工具
=====================================

功能:
  1. 自动检测已安装的 MongoDB Compass 版本（支持 Squirrel 多版本 app-* 并存）；
  2. 检查官方稳定通道是否有新版本，并调用官方 Update.exe 升级；
  3. 一键汉化：备份原始 app.asar -> 注入中文语言包 -> 校验；
  4. 一键还原英文：用备份完整覆盖，SHA256 校验一致；
  5. 备份管理（可回滚到任意历史备份）、操作日志、错误提示。

用法:
  python CompassZhCn.py                     # 打开图形界面
  python CompassZhCn.py --status            # 查看状态
  python CompassZhCn.py --apply             # 命令行一键汉化
  python CompassZhCn.py --restore           # 命令行一键还原英文
  python CompassZhCn.py --check-update      # 仅检查更新
  python CompassZhCn.py --update            # 升级到最新版（如已汉化会自动重新汉化）
  python CompassZhCn.py --backups           # 列出备份
  python CompassZhCn.py --restore-id ID     # 回滚到指定备份

仅支持 Windows 10/11 x64 + 官方 Squirrel 安装版 MongoDB Compass。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

try:
    import winreg  # type: ignore
except ImportError:  # 非 Windows 环境
    winreg = None

TOOL_NAME = "MongoDB Compass 汉化工具"
TOOL_VERSION = "2.0.0"
FEED_BASE = "https://compass.mongodb.com/api/v2/update/compass/stable/win32-x64"
INJECT_REL = "build/compass-zh-cn/zh-CN.js"
INJECT_DIR = "build/compass-zh-cn"
INJECT_TAG = '<script src="compass-zh-cn/zh-CN.js"></script>'
MAIN_HOOK_REL = "build/compass-zh-cn/main-hook.js"
MENU_JSON_REL = "build/compass-zh-cn/menu-zh-CN.json"
MENU_HOOK_MARKER = "__COMPASS_ZH_MENU__"
BLOCK_SIZE = 4 * 1024 * 1024

IS_FROZEN = bool(getattr(sys, "frozen", False))
if IS_FROZEN:
    EXE_DIR = Path(sys.executable).resolve().parent
    BASE_DIR = Path(getattr(sys, "_MEIPASS", EXE_DIR))
else:
    EXE_DIR = Path(__file__).resolve().parent
    BASE_DIR = EXE_DIR


def resource_path(rel: str) -> Path:
    """安装目录下存在同名资源时优先使用（便于用户改词表/图标），否则用打包内置资源。"""
    external = EXE_DIR / rel
    if external.exists():
        return external
    return BASE_DIR / rel


LANG_FILE = resource_path("lang/zh-CN.json")
TEMPLATE_FILE = resource_path("lang/inject.js")
MAIN_HOOK_TEMPLATE = resource_path("lang/main-hook.js")
ASSETS_DIR = resource_path("assets")
ICON_ICO = ASSETS_DIR / "compass.ico"

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CompassZhCn"
BACKUP_DIR = DATA_DIR / "backup"
LOG_DIR = DATA_DIR / "logs"
STATE_FILE = DATA_DIR / "state.json"
MONGODB_DATA_BUNDLED = resource_path("data/mongodb_versions.json")
MONGODB_DATA_CACHE = DATA_DIR / "mongodb-versions.json"
MONGODB_RELEASE_NOTES = "https://www.mongodb.com/docs/manual/release-notes/"
COMPASS_DOWNLOAD_PAGE = "https://www.mongodb.com/try/download/compass"
MONGODB_SERVER_PAGE = "https://www.mongodb.com/try/download/community"
MONGODB_SERVER_MSI = "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-{version}-signed.msi"
MONGODB_DOWNLOAD_DIR = DATA_DIR / "downloads"

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# --------------------------------------------------------------------------- #
# 日志
# --------------------------------------------------------------------------- #

class Logger:
    def __init__(self) -> None:
        self.sinks: list[Callable[[str, str], None]] = []
        self._lock = threading.Lock()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.path = LOG_DIR / f"tool-{datetime.now():%Y%m%d}.log"

    def add_sink(self, fn: Callable[[str, str], None]) -> None:
        self.sinks.append(fn)

    def log(self, message: str, level: str = "INFO") -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{stamp}] [{level:<5}] {message}"
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass
        for sink in list(self.sinks):
            try:
                sink(line, level)
            except Exception:
                pass

    def info(self, msg: str) -> None:
        self.log(msg, "INFO")

    def ok(self, msg: str) -> None:
        self.log(msg, "OK")

    def warn(self, msg: str) -> None:
        self.log(msg, "WARN")

    def error(self, msg: str) -> None:
        self.log(msg, "ERROR")


LOG = Logger()


class ToolError(Exception):
    """可预期的业务错误，直接展示给用户。"""


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #

def atomic_replace(src: Path, dst: Path, attempts: int = 4) -> None:
    """优先原子替换；若目标被安全软件/索引器占用，退化为原地写入后复验。"""
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            if dst.exists():
                try:
                    os.chmod(dst, 0o666)
                except OSError:
                    pass
            os.replace(src, dst)
            return
        except PermissionError as exc:
            last = exc
            time.sleep(0.4 * (i + 1))

    # 回退方案：直接写入目标文件（调用方会在之后重新校验哈希/结构）
    try:
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            shutil.copyfileobj(fi, fo, 1024 * 1024)
            fo.flush()
            os.fsync(fo.fileno())
        src.unlink(missing_ok=True)
        LOG.warn("目标文件被占用，已改为原地写入（备份仍可用于回滚）。")
        return
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            f"无法写入 {dst.name}（文件被占用）。\n"
            "请确认 Compass 已完全退出，并暂时关闭杀毒软件的实时防护后重试。\n"
            f"原始错误：{last or exc}"
        ) from exc


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def version_key(text: str) -> tuple:
    parts = re.findall(r"\d+", text)
    return tuple(int(p) for p in parts) if parts else (0,)


def human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{num} B"
        num /= 1024.0
    return f"{num:.1f} GB"


def default_install_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "MongoDBCompass"
    return Path.home() / "AppData" / "Local" / "MongoDBCompass"


def _decode_console(data: bytes) -> str:
    """Windows 控制台输出使用系统 ANSI 代码页（中文系统为 GBK）。"""
    if not data:
        return ""
    for enc in ("mbcs", "utf-8", "gbk"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def compass_running() -> list[str]:
    if os.name != "nt":
        return []
    try:
        res = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq MongoDBCompass.exe", "/NH"],
            capture_output=True, timeout=15,
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:
        return []
    out = _decode_console(res.stdout or b"")
    return [ln.strip() for ln in out.splitlines() if "MongoDBCompass.exe" in ln]


def kill_compass() -> None:
    subprocess.run(
        ["taskkill", "/IM", "MongoDBCompass.exe", "/T", "/F"],
        capture_output=True, timeout=30,
        creationflags=_CREATE_NO_WINDOW,
    )


# --------------------------------------------------------------------------- #
# asar 读写
# --------------------------------------------------------------------------- #

@dataclass
class AsarEntry:
    data: Optional[bytes]          # unpacked 条目为 None，内容在 app.asar.unpacked 目录
    meta: dict = field(default_factory=dict)


class AsarArchive:
    """最小实现的 Electron asar 读写器，保留 unpacked / executable / integrity 等字段。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.raw = self.path.read_bytes()
        if len(self.raw) < 16:
            raise ToolError(f"app.asar 文件过小，可能已损坏：{path}")
        self.header_json_len = struct.unpack("<I", self.raw[12:16])[0]
        try:
            self.header = json.loads(self.raw[16:16 + self.header_json_len].decode("utf-8"))
        except Exception as exc:
            raise ToolError(f"无法解析 app.asar 头部：{exc}") from exc
        self.base = 16 + ((self.header_json_len + 3) // 4) * 4
        self.entries: dict[str, AsarEntry] = {}
        self._walk(self.header)

    def _walk(self, node: dict, prefix: str = "") -> None:
        for name, child in node.get("files", {}).items():
            path = f"{prefix}/{name}" if prefix else name
            if "files" in child:
                self._walk(child, path)
                continue
            meta = {k: v for k, v in child.items() if k not in ("offset", "size")}
            if child.get("unpacked") and "offset" not in child:
                self.entries[path] = AsarEntry(None, meta)
            else:
                off = int(child.get("offset", 0))
                size = int(child.get("size", 0))
                self.entries[path] = AsarEntry(self.raw[self.base + off:self.base + off + size], meta)

    # -- 查询 ------------------------------------------------------------- #
    def exists(self, path: str) -> bool:
        return path in self.entries

    def read(self, path: str) -> bytes:
        entry = self.entries.get(path)
        if entry is None or entry.data is None:
            raise ToolError(f"asar 中不存在文件：{path}")
        return entry.data

    def read_text(self, path: str) -> str:
        return self.read(path).decode("utf-8")

    @property
    def package(self) -> dict:
        try:
            return json.loads(self.read_text("package.json"))
        except Exception:
            return {}

    # -- 修改 ------------------------------------------------------------- #
    def write_file(self, path: str, data: bytes) -> None:
        self.entries[path] = AsarEntry(data, {})
        entry = self.entries[path]
        entry.meta["_modified"] = True

    # -- 保存 ------------------------------------------------------------- #
    @staticmethod
    def _integrity(data: bytes) -> dict:
        blocks = []
        for i in range(0, len(data), BLOCK_SIZE):
            blocks.append(hashlib.sha256(data[i:i + BLOCK_SIZE]).hexdigest())
        return {
            "algorithm": "SHA256",
            "hash": hashlib.sha256(data).hexdigest(),
            "blockSize": BLOCK_SIZE,
            "blocks": blocks,
        }

    def save(self, dest: Optional[Path] = None) -> Path:
        """增量写入：仅追加被修改/新增的文件，其余条目的 offset 原样保留。

        这样可以把改动面压到最小，避免因整体重排导致原生模块或资源读取异常。
        """
        dest = Path(dest or self.path)
        blob = bytearray(self.raw[self.base:])
        changed = 0
        for path, entry in self.entries.items():
            if entry.data is None or not entry.meta.get("_modified"):
                continue
            while len(blob) % 4:
                blob.append(0)
            offset = len(blob)
            blob += entry.data
            node = self._ensure_node(path)
            node.pop("unpacked", None)
            node["size"] = len(entry.data)
            node["offset"] = str(offset)
            node["integrity"] = self._integrity(entry.data)
            changed += 1
        if changed == 0:
            raise ToolError("没有需要写入的改动。")

        header_bytes = json.dumps(self.header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        json_len = len(header_bytes)
        payload = 4 + json_len
        payload += (4 - payload % 4) % 4
        prefix = struct.pack("<I", 4)
        prefix += struct.pack("<I", 4 + payload)
        prefix += struct.pack("<I", payload)
        prefix += struct.pack("<I", json_len)
        prefix += header_bytes
        prefix += b"\x00" * (payload - 4 - json_len)

        tmp = dest.with_suffix(dest.suffix + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(prefix)
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        AsarArchive.verify(tmp)
        atomic_replace(tmp, dest)
        self.raw = b""
        return dest

    def _ensure_node(self, path: str) -> dict:
        node = self.header
        parts = path.split("/")
        for part in parts[:-1]:
            child = node["files"].get(part)
            if child is None or "files" not in child:
                child = {"files": {}}
                node["files"][part] = child
            node = child
        leaf = node["files"].get(parts[-1])
        if leaf is None or "files" in leaf:
            leaf = {}
            node["files"][parts[-1]] = leaf
        return leaf

    @staticmethod
    def verify(path: Path) -> None:
        try:
            arc = AsarArchive(path)
        except Exception as exc:
            raise ToolError(f"生成的 app.asar 无法解析：{exc}") from exc
        if not arc.exists("build/index.html"):
            raise ToolError("生成的 app.asar 缺少 build/index.html，已中止写入。")


# --------------------------------------------------------------------------- #
# 安装检测
# --------------------------------------------------------------------------- #

@dataclass
class Install:
    root: Path
    app_dir: Path
    version: str
    resources: Path
    asar: Optional[Path]
    app_folder: Optional[Path]   # 未打包（resources/app）形式

    @property
    def kind(self) -> str:
        return "asar" if self.asar else "folder"


def find_install(root: Path, only_dir: Optional[Path] = None) -> Install:
    if not root.exists():
        raise ToolError(
            f"未找到 Compass 安装目录：{root}\n"
            "请确认已通过官方安装包安装 MongoDB Compass，或使用 --root 指定目录。"
        )
    if only_dir:
        candidates = [only_dir]
    else:
        candidates = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("app-")]
    if not candidates:
        raise ToolError(f"在 {root} 下未找到 app-* 版本目录，安装可能不完整。")
    candidates.sort(key=lambda p: version_key(p.name), reverse=True)
    for app_dir in candidates:
        res = app_dir / "resources"
        asar = res / "app.asar"
        folder = res / "app"
        if asar.exists():
            version = app_dir.name.split("-", 1)[1] if "-" in app_dir.name else app_dir.name
            try:
                ver = AsarArchive(asar).package.get("version") or version
            except Exception:
                ver = version
            return Install(root, app_dir, ver, res, asar, None)
        if folder.exists():
            version = app_dir.name.split("-", 1)[1] if "-" in app_dir.name else app_dir.name
            return Install(root, app_dir, version, res, None, folder)
    raise ToolError("未找到 resources/app.asar 或 resources/app，安装可能不完整。")


def is_patched(install: Install) -> tuple[bool, str]:
    try:
        if install.asar:
            arc = AsarArchive(install.asar)
            if not arc.exists(INJECT_REL):
                return False, ""
            html = arc.read_text("build/index.html")
            if "compass-zh-cn/zh-CN.js" not in html:
                return False, ""
            js = arc.read_text(INJECT_REL)
            m = re.search(r"[\"']version[\"']\s*:\s*[\"']([^\"']+)[\"']", js)
            return True, m.group(1) if m else ""
        else:
            assert install.app_folder
            js = install.app_folder / INJECT_REL
            html = (install.app_folder / "build" / "index.html").read_text(encoding="utf-8")
            if js.exists() and "compass-zh-cn/zh-CN.js" in html:
                return True, ""
            return False, ""
    except Exception:
        return False, ""


# --------------------------------------------------------------------------- #
# 备份
# --------------------------------------------------------------------------- #

def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    ensure_dirs()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class Backup:
    backup_id: str
    app_dir: Path
    version: str
    created: str
    sha256: str
    size: int
    asar_path: Path
    note: str = ""

    @property
    def human_time(self) -> str:
        try:
            return datetime.fromisoformat(self.created).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return self.created


def list_backups() -> list[Backup]:
    ensure_dirs()
    result: list[Backup] = []
    for meta_file in BACKUP_DIR.glob("*/meta.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            asar = meta_file.parent / "app.asar"
            if not asar.exists():
                continue
            result.append(Backup(
                backup_id=meta.get("id", meta_file.parent.name),
                app_dir=Path(meta["appDir"]),
                version=meta.get("version", "?"),
                created=meta.get("created", ""),
                sha256=meta.get("sha256", ""),
                size=meta.get("size", asar.stat().st_size),
                asar_path=asar,
                note=meta.get("note", ""),
            ))
        except Exception:
            continue
    result.sort(key=lambda b: b.created, reverse=True)
    return result


def create_backup(install: Install, note: str = "") -> Backup:
    assert install.asar
    ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_id = f"{install.version}_{stamp}"
    folder = BACKUP_DIR / backup_id
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / "app.asar"

    LOG.info(f"正在备份原始 app.asar（{human_size(install.asar.stat().st_size)}）…")
    shutil.copy2(install.asar, dst)
    digest = sha256_file(dst)
    src_digest = sha256_file(install.asar)
    if digest != src_digest:
        raise ToolError("备份校验失败：备份文件与原始文件 SHA256 不一致。")

    meta = {
        "id": backup_id,
        "appDir": str(install.app_dir),
        "version": install.version,
        "created": datetime.now().isoformat(timespec="seconds"),
        "sha256": digest,
        "size": dst.stat().st_size,
        "note": note,
        "tool": TOOL_VERSION,
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    LOG.ok(f"备份完成：{backup_id}（SHA256 {digest[:12]}…）")
    prune_backups(install.app_dir)
    return Backup(backup_id, install.app_dir, install.version, meta["created"], digest,
                  meta["size"], dst, note)


def prune_backups(app_dir: Path, keep: int = 5) -> None:
    items = [b for b in list_backups() if b.app_dir == app_dir]
    for old in items[keep:]:
        try:
            shutil.rmtree(old.asar_path.parent, ignore_errors=True)
            LOG.info(f"已清理旧备份：{old.backup_id}")
        except Exception:
            pass


def find_backup_for(install: Install) -> Optional[Backup]:
    state = load_state()
    entry = state.get(str(install.app_dir)) or {}
    backup_id = entry.get("backupId")
    items = list_backups()
    if backup_id:
        for b in items:
            if b.backup_id == backup_id:
                return b
    same = [b for b in items if b.app_dir.resolve() == install.app_dir.resolve()]
    return same[0] if same else None


# --------------------------------------------------------------------------- #
# 语言包载荷
# --------------------------------------------------------------------------- #

def load_language_pack() -> tuple[dict, list]:
    if not LANG_FILE.exists():
        raise ToolError(f"缺少语言包文件：{LANG_FILE}")
    if not TEMPLATE_FILE.exists():
        raise ToolError(f"缺少注入脚本模板：{TEMPLATE_FILE}")
    try:
        data = json.loads(LANG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError(f"语言包 JSON 格式错误：第 {exc.lineno} 行 {exc.msg}") from exc
    mapping = data.get("dict") or {}
    patterns = data.get("patterns") or []
    if not isinstance(mapping, dict) or not mapping:
        raise ToolError("语言包中没有有效词条。")
    for item in patterns:
        if not (isinstance(item, list) and len(item) == 2):
            raise ToolError("语言包 patterns 格式应为 [[正则, 替换文本], ...]。")
        try:
            re.compile(item[0])
        except re.error as exc:
            raise ToolError(f"语言包正则表达式无效：{item[0]}（{exc}）") from exc
    menu = data.get("menu")
    if menu is not None and not isinstance(menu, dict):
        raise ToolError("语言包 menu 字段应为对象。")
    return data, patterns


def build_payload(lang: dict, version: str) -> bytes:
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    mapping = lang["dict"]
    patterns = lang.get("patterns", [])
    meta = {
        "version": version,
        "entries": len(mapping),
        "builtAt": datetime.now().isoformat(timespec="seconds"),
        "tool": TOOL_VERSION,
    }
    js = template.replace("__META__", json.dumps(meta, ensure_ascii=False))
    js = js.replace("__DICT__", json.dumps(mapping, ensure_ascii=False, separators=(",", ":")))
    js = js.replace("__RULES__", json.dumps(patterns, ensure_ascii=False, separators=(",", ":")))
    return js.encode("utf-8")


def patch_html(html: str) -> str:
    if "compass-zh-cn/zh-CN.js" in html:
        return html
    if "</body>" not in html:
        raise ToolError("build/index.html 结构异常：缺少 </body>，无法注入语言包。")
    return html.replace("</body>", INJECT_TAG + "</body>")


def find_menu_chunk(arc: "AsarArchive") -> Optional[str]:
    """定位构建原生菜单的主进程 chunk（体积较小且同时出现两个 Menu API）。"""
    for path, entry in arc.entries.items():
        if not path.startswith("build/") or not path.endswith(".js"):
            continue
        if path.endswith(".renderer.js") or entry.data is None:
            continue
        if len(entry.data) > 400_000:
            continue
        if b"setApplicationMenu" in entry.data and b"buildFromTemplate" in entry.data:
            return path
    return None


def patch_main_chunk(text: str) -> str:
    if MENU_HOOK_MARKER in text:
        return text
    return (
        f"/*{MENU_HOOK_MARKER}*/"
        'try{require("./compass-zh-cn/main-hook.js")}catch(e){}\n'
    ) + text


# --------------------------------------------------------------------------- #
# 汉化 / 还原
# --------------------------------------------------------------------------- #

def apply_patch(install: Install, backup_note: str = "") -> None:
    if not install.asar:
        raise ToolError("当前安装为未打包目录形式，暂不支持自动汉化，请使用官方安装版。")
    ensure_dirs()
    lang, _ = load_language_pack()
    lang_version = str(lang.get("meta", {}).get("version", "1.0.0"))
    payload = build_payload(lang, lang_version)

    arc = AsarArchive(install.asar)
    html_before = arc.read_text("build/index.html")
    html_after = patch_html(html_before)
    if html_after != html_before:
        arc.write_file("build/index.html", html_after.encode("utf-8"))
    arc.write_file(INJECT_REL, payload)

    # 原生菜单（主进程）：字典存在且能找到菜单 chunk 时注入
    menu = lang.get("menu") or {}
    if menu:
        menu_chunk = find_menu_chunk(arc)
        if menu_chunk and MAIN_HOOK_TEMPLATE.exists():
            hook = MAIN_HOOK_TEMPLATE.read_text(encoding="utf-8")
            arc.write_file(MAIN_HOOK_REL, hook.encode("utf-8"))
            arc.write_file(MENU_JSON_REL, json.dumps(menu, ensure_ascii=False, indent=2).encode("utf-8"))
            chunk_text = arc.read_text(menu_chunk)
            patched_text = patch_main_chunk(chunk_text)
            if patched_text != chunk_text:
                arc.write_file(menu_chunk, patched_text.encode("utf-8"))
            LOG.info(f"已注入原生菜单汉化：{menu_chunk}（{len(menu)} 项）")
        else:
            LOG.warn("未找到可注入的原生菜单 chunk，本次跳过菜单汉化（界面文案不受影响）。")

    backup = find_backup_for(install)
    if backup is None:
        # 若当前 app.asar 已被旧工具改过，先接管其原始备份，避免把“已汉化文件”当成原版备份
        backup = adopt_legacy_backup(install)
    if backup is None:
        if is_patched(install)[0]:
            raise ToolError(
                "检测到当前 app.asar 已被汉化，但找不到对应的原始备份。\n"
                "为避免把已修改的文件当作原版备份，已中止操作。\n"
                "请先用 Compass 官方安装包覆盖安装，再重新汉化。"
            )
        backup = create_backup(install, note=backup_note or "首次汉化前自动备份")
    else:
        LOG.info(f"复用已有备份：{backup.backup_id}")

    LOG.info("正在写入语言包到 app.asar …")
    arc.save()
    digest = sha256_file(install.asar)

    # 回读校验
    check = AsarArchive(install.asar)
    if not check.exists(INJECT_REL) or "compass-zh-cn/zh-CN.js" not in check.read_text("build/index.html"):
        raise ToolError("写入后校验失败：语言包未正确注入。")

    state = load_state()
    state[str(install.app_dir)] = {
        "version": install.version,
        "langVersion": lang_version,
        "entitlements": len(lang["dict"]),
        "menuEntries": len(lang.get("menu") or {}),
        "patchedAt": datetime.now().isoformat(timespec="seconds"),
        "patchedAsarSha256": digest,
        "backupId": backup.backup_id,
        "originalSha256": backup.sha256,
    }
    save_state(state)
    LOG.ok(f"汉化完成：Compass {install.version}，语言包 v{lang_version}，词条 {len(lang['dict'])} 条。")
    LOG.info("请完全退出并重新启动 Compass 使中文界面生效。")


def restore_english(install: Install, backup_id: Optional[str] = None) -> None:
    if not install.asar:
        raise ToolError("当前安装为未打包目录形式，无需还原。")
    backup = None
    if backup_id:
        backup = next((b for b in list_backups() if b.backup_id == backup_id), None)
        if backup is None:
            raise ToolError(f"未找到备份：{backup_id}")
    else:
        backup = find_backup_for(install)
        if backup is None:
            backup = adopt_legacy_backup(install)
    if backup is None:
        raise ToolError(
            "未找到可用的原始 app.asar 备份，无法还原。\n"
            "如果这是首次运行本工具，请改用 Compass 官方安装包覆盖安装以恢复英文。"
        )

    LOG.info(f"使用备份 {backup.backup_id}（{backup.human_time}）还原…")
    if not backup.asar_path.exists():
        raise ToolError(f"备份文件已丢失：{backup.asar_path}")
    digest = sha256_file(backup.asar_path)
    if backup.sha256 and digest != backup.sha256:
        raise ToolError("备份文件 SHA256 校验失败，备份可能已损坏，已中止还原。")

    tmp = install.asar.with_suffix(".asar.restore.tmp")
    shutil.copy2(backup.asar_path, tmp)
    if sha256_file(tmp) != digest:
        tmp.unlink(missing_ok=True)
        raise ToolError("写入临时文件时校验失败，已中止还原。")
    AsarArchive.verify(tmp)
    atomic_replace(tmp, install.asar)

    state = load_state()
    entry = state.get(str(install.app_dir)) or {}
    entry.pop("patchedAsarSha256", None)
    entry.pop("patchedAt", None)
    entry["restoredAt"] = datetime.now().isoformat(timespec="seconds")
    state[str(install.app_dir)] = entry
    save_state(state)
    LOG.ok(f"已还原为英文原版（SHA256 {digest[:12]}…）。")
    LOG.info("请完全退出并重新启动 Compass。")


def adopt_legacy_backup(install: Install) -> Optional[Backup]:
    """接管旧版工具留下的 resources/compass-zh-cn/app.asar.orig。"""
    assert install.asar
    legacy = install.resources / "compass-zh-cn" / "app.asar.orig"
    if not legacy.exists():
        return None
    try:
        if AsarArchive(legacy).exists(INJECT_REL):
            return None
    except Exception:
        return None
    ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_id = f"{install.version}_{stamp}_legacy"
    folder = BACKUP_DIR / backup_id
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / "app.asar"
    shutil.copy2(legacy, dst)
    digest = sha256_file(dst)
    meta = {
        "id": backup_id,
        "appDir": str(install.app_dir),
        "version": install.version,
        "created": datetime.now().isoformat(timespec="seconds"),
        "sha256": digest,
        "size": dst.stat().st_size,
        "note": "接管旧版汉化工具的原始备份",
        "tool": TOOL_VERSION,
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    LOG.warn(f"检测到旧版汉化工具留下的原始备份，已接管为 {backup_id}。")
    return Backup(backup_id, install.app_dir, install.version, meta["created"], digest, meta["size"], dst, meta["note"])


# --------------------------------------------------------------------------- #
# 版本检测 / 升级
# --------------------------------------------------------------------------- #

def check_latest(current: str) -> tuple[bool, Optional[str]]:
    url = f"{FEED_BASE}/{current}/RELEASES?id=MongoDBCompass&localVersion={current}&arch=amd64"
    req = urllib.request.Request(url, headers={"User-Agent": "CompassZhCn/" + TOOL_VERSION})
    LOG.info(f"正在查询官方更新源…（当前 {current}）")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8-sig", errors="ignore")
            status = resp.status
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ToolError("官方更新接口返回 404，可能是通道/架构参数不匹配。") from exc
        raise ToolError(f"查询更新失败：HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ToolError(f"无法连接官方更新源，请检查网络或代理：{exc.reason}") from exc

    if status == 204 or not body.strip():
        return False, None
    latest = None
    for line in body.strip().splitlines():
        m = re.search(r"MongoDBCompass-(\d+(?:\.\d+)+)-full\.nupkg", line)
        if m:
            latest = m.group(1)
    if not latest:
        return False, None
    return version_key(latest) > version_key(current), latest


def _fetch_text(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CompassZhCn/" + TOOL_VERSION,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def load_mongodb_versions() -> dict:
    """优先读取用户缓存，其次读取随软件分发的官方快照。"""
    for path, origin in ((MONGODB_DATA_CACHE, "cache"), (MONGODB_DATA_BUNDLED, "bundled")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema") == 1 and data.get("versions"):
                data["_origin"] = origin
                data["_path"] = str(path)
                return data
        except Exception:
            continue
    raise ToolError("未找到 MongoDB 版本数据文件，请重新安装或检查 data 目录。")


def refresh_mongodb_versions() -> dict:
    """从官方 Release Notes 刷新当前稳定版与各系列最新补丁号，并写入缓存。"""
    data = load_mongodb_versions()
    index = _fetch_text(MONGODB_RELEASE_NOTES)
    m = re.search(r"Current Stable Release.*?release-notes/(\d+\.\d+)(?:/|#|&quot;|\")", index, re.S | re.I)
    if not m:
        raise ToolError("无法从官方 Release Notes 解析当前稳定版，页面结构可能已调整。")
    current = m.group(1)

    previous: list[str] = []
    block = re.search(r"Previous Stable Releases(.*?)(?:EOL Releases|Additional Information)",
                      index, re.S | re.I)
    if block:
        for v in re.findall(r"release-notes/(\d+\.\d+)(?:/|#|&quot;|\")", block.group(1)):
            if v != current and v not in previous:
                previous.append(v)
    previous = previous[:3]

    def fetch_patch(series: str):
        try:
            html = _fetch_text(f"{MONGODB_RELEASE_NOTES}{series}/", timeout=20)
            nums = [int(x) for x in re.findall(rf"\b{re.escape(series)}\.(\d+)\b", html)]
            return series, (f"{series}.{max(nums)}" if nums else None)
        except Exception:
            return series, None

    patch_map: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for series, patch in pool.map(fetch_patch, [current] + previous):
            if patch:
                patch_map[series] = patch

    data["current"] = current
    if previous:
        data["previous"] = previous[0]
    if current in patch_map:
        if patch_map[current] != data.get("latest_patch"):
            data["latest_patch_date"] = "官方页面"
        data["latest_patch"] = patch_map[current]
    data["fetched_at"] = datetime.now().strftime("%Y-%m-%d")
    for item in data.get("versions", []):
        series = item.get("series")
        if series in patch_map:
            item["latest"] = patch_map[series]
        if series == current:
            item["status"] = "当前稳定版"
            item["status_key"] = "current"
        elif series in previous and item.get("status_key") == "current":
            item["status"] = "前序稳定版"
            item["status_key"] = "previous"
    data["refresh_note"] = (
        "版本号已从官方 Release Notes 刷新；特性摘要与支持周期为内置快照。"
        if current in {v.get("series") for v in data.get("versions", [])}
        else f"官方当前稳定版为 {current}，内置对比表尚未覆盖该系列，请更新软件。"
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MONGODB_DATA_CACHE.with_suffix(".tmp")
    payload = {k: v for k, v in data.items() if not k.startswith("_")}
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(MONGODB_DATA_CACHE)
    data["_origin"] = "cache"
    return data


def run_upgrade(install: Install, latest: str) -> Optional[Install]:
    update_exe = install.root / "Update.exe"
    if not update_exe.exists():
        update_exe = install.app_dir / "Update.exe"
    if not update_exe.exists():
        raise ToolError("未找到 Update.exe，无法调用官方更新程序，请手动下载安装最新版。")
    if compass_running():
        raise ToolError("升级前请先完全退出 Compass。")

    feed = f"{FEED_BASE}/{install.version}"
    LOG.info(f"正在调用官方更新程序升级到 {latest}（约 180 MB，请耐心等待）…")
    proc = subprocess.run(
        [str(update_exe), "--update", feed],
        capture_output=True, timeout=1800,
        creationflags=_CREATE_NO_WINDOW,
    )
    if proc.returncode not in (0, 1):
        detail = _decode_console(proc.stderr or proc.stdout or b"").strip()[:300]
        LOG.warn(f"Update.exe 返回码 {proc.returncode}：{detail}")

    LOG.info("等待新版本目录写入完成…")
    deadline = time.time() + 600
    while time.time() < deadline:
        try:
            new_install = find_install(install.root)
            if version_key(new_install.version) >= version_key(latest) and new_install.app_dir != install.app_dir:
                LOG.ok(f"升级完成：{install.version} → {new_install.version}")
                return new_install
        except Exception:
            pass
        time.sleep(5)
    LOG.warn("未在预期时间内检测到新版本目录，请查看 Compass 的 Squirrel-Update.log。")
    return None


# --------------------------------------------------------------------------- #
# 状态
# --------------------------------------------------------------------------- #

def _iter_uninstall_entries():
    """遍历 32/64 位卸载注册表项，返回 (DisplayName, InstallLocation)。"""
    if winreg is None:
        return
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
                     winreg.KEY_READ | winreg.KEY_WOW64_32KEY):
            try:
                base = winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", 0, view)
            except OSError:
                continue
            with base:
                for index in range(winreg.QueryInfoKey(base)[0]):
                    try:
                        name = winreg.EnumKey(base, index)
                        with winreg.OpenKey(base, name) as key:
                            display = str(winreg.QueryValueEx(key, "DisplayName")[0])
                            try:
                                location = str(winreg.QueryValueEx(key, "InstallLocation")[0] or "")
                            except OSError:
                                location = ""
                        yield display, location
                    except OSError:
                        continue


def _compass_install_roots() -> list:
    """默认安装目录 + 注册表安装位置，兼容非默认盘符/目录。"""
    roots = [default_install_root()]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "Programs" / "MongoDBCompass")
    for display, location in _iter_uninstall_entries():
        if display.strip().lower() != "mongodb compass" or not location:
            continue
        path = Path(location)
        if path.name.lower().startswith("app-"):
            path = path.parent
        roots.append(path)
    result, seen = [], set()
    for path in roots:
        try:
            key = str(path.resolve()).lower()
        except Exception:
            key = str(path).lower()
        if key in seen or not path.exists():
            continue
        seen.add(key)
        result.append(path)
    return result


def find_any_install() -> Optional[Install]:
    best = None
    for root in _compass_install_roots():
        try:
            install = find_install(root)
        except Exception:
            continue
        if best is None or version_key(install.version) > version_key(best.version):
            best = install
    return best


@dataclass
class MongoServer:
    version: str
    exe: Path
    source: str


def _mongod_version(exe: Path) -> Optional[str]:
    try:
        proc = subprocess.run(
            [str(exe), "--version"], capture_output=True, timeout=10,
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:
        return None
    text = _decode_console((proc.stdout or b"") + (proc.stderr or b""))
    match = re.search(r"db version v?([0-9]+(?:\.[0-9]+)+)", text)
    return match.group(1) if match else None


def detect_mongodb_server(force: bool = False) -> Optional[MongoServer]:
    """检测本机 MongoDB Server（mongod）版本，优先 PATH/Program Files，再查注册表。"""
    if not force and _SERVER_CACHE[0] and time.time() - _SERVER_CACHE[0] < 20:
        return _SERVER_CACHE[1]

    candidates: dict = {}

    def add(exe: Path, hint: str, source: str) -> None:
        try:
            if not exe.is_file():
                return
            key = exe.resolve()
        except Exception:
            return
        if key not in candidates:
            candidates[key] = (hint, source)

    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = Path(os.environ.get(env, "")) / "MongoDB" / "Server"
        if not base.is_dir():
            continue
        try:
            children = list(base.iterdir())
        except OSError:
            continue
        for child in children:
            add(child / "bin" / "mongod.exe", child.name, "Program Files")

    which = shutil.which("mongod")
    if which:
        add(Path(which), "", "PATH")

    for display, location in _iter_uninstall_entries():
        match = re.match(r"MongoDB\s+([0-9]+(?:\.[0-9]+)+)", display)
        if not match:
            continue
        low = display.lower()
        if any(word in low for word in ("compass", "shell", "tools", "bi connector")):
            continue
        hint = match.group(1)
        if location:
            path = Path(location)
            add(path / "mongod.exe", hint, "注册表")
            add(path / "bin" / "mongod.exe", hint, "注册表")

    best: Optional[MongoServer] = None
    for exe, (hint, source) in candidates.items():
        version = _mongod_version(exe) or hint
        if not version:
            continue
        if best is None or version_key(version) > version_key(best.version):
            best = MongoServer(version, exe, source)
    _SERVER_CACHE[0] = time.time()
    _SERVER_CACHE[1] = best
    return best


_SERVER_CACHE: list = [0.0, None]


def server_msi_url(version: str) -> str:
    return MONGODB_SERVER_MSI.format(version=version)


def server_msi_path(version: str) -> Path:
    return MONGODB_DOWNLOAD_DIR / f"mongodb-windows-x86_64-{version}-signed.msi"


def server_msi_size(version: str) -> int:
    req = urllib.request.Request(server_msi_url(version), method="HEAD",
                                 headers={"User-Agent": "Mozilla/5.0 CompassZhCn/" + TOOL_VERSION})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return int(resp.headers.get("Content-Length") or 0)


def server_msi_sha256(version: str) -> str:
    try:
        text = _fetch_text(server_msi_url(version) + ".sha256", timeout=20)
    except Exception:
        return ""
    match = re.search(r"\b([0-9a-fA-F]{64})\b", text)
    return match.group(1).lower() if match else ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_server_msi(version: str, progress=None, cancelled=None) -> Path:
    """下载官方签名的 Windows x64 MSI，校验大小与 SHA256。"""
    url = server_msi_url(version)
    target = server_msi_path(version)
    MONGODB_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    expected_hash = server_msi_sha256(version)
    if target.exists():
        try:
            valid = target.stat().st_size > 10 * 1024 * 1024
            with target.open("rb") as fh:
                valid = valid and fh.read(8) == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
            if valid and (not expected_hash or _sha256_file(target) == expected_hash):
                return target
        except Exception:
            pass

    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 CompassZhCn/" + TOOL_VERSION,
        "Accept": "application/octet-stream",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        free = shutil.disk_usage(str(MONGODB_DOWNLOAD_DIR)).free
        if total and free < total + 300 * 1024 * 1024:
            raise ToolError(
                f"磁盘空间不足：需要约 {human_size(total)}，当前仅剩 {human_size(free)}。"
            )
        tmp = target.with_suffix(target.suffix + ".part")
        done = 0
        with tmp.open("wb") as fh:
            while True:
                if cancelled and cancelled():
                    fh.close()
                    tmp.unlink(missing_ok=True)
                    raise ToolError("下载已取消。")
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    try:
                        progress(done, total)
                    except Exception:
                        pass

    if total and done != total:
        tmp.unlink(missing_ok=True)
        raise ToolError(f"下载不完整：{human_size(done)} / {human_size(total)}。")

    with tmp.open("rb") as fh:
        if fh.read(8) != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            tmp.unlink(missing_ok=True)
            raise ToolError("下载的文件不是有效的 MSI 安装包，请检查网络或代理。")

    if expected_hash:
        actual = _sha256_file(tmp)
        if actual != expected_hash:
            tmp.unlink(missing_ok=True)
            raise ToolError("安装包 SHA256 校验失败，文件可能不完整，请重试。")

    tmp.replace(target)
    return target


@dataclass
class Status:
    root: Path
    install: Optional[Install]
    patched: bool = False
    patch_version: str = ""
    running: bool = False
    backups: list[Backup] = field(default_factory=list)
    mongodb: Optional[MongoServer] = None
    error: str = ""


def get_status(root: Optional[Path] = None) -> Status:
    mongodb = detect_mongodb_server()
    if root is None:
        install = find_any_install()
        root = install.root if install else default_install_root()
        if install is None:
            return Status(root, None,
                          error="未检测到 MongoDB Compass，请先安装官方客户端。",
                          mongodb=mongodb)
    else:
        root = Path(root)
        try:
            install = find_install(root)
        except ToolError as exc:
            return Status(root, None, error=str(exc), mongodb=mongodb)
    patched, ver = is_patched(install)
    return Status(
        root=root,
        install=install,
        patched=patched,
        patch_version=ver,
        running=bool(compass_running()),
        backups=[b for b in list_backups() if b.app_dir.resolve() == install.app_dir.resolve()],
        mongodb=mongodb,
    )


# --------------------------------------------------------------------------- #
# GUI —— 视觉与交互层（MongoDB Compass / LeafyGreen 风格）
# --------------------------------------------------------------------------- #

def run_gui() -> int:
    import base64
    import ctypes
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import ttk

    # 让 Tk 直接使用物理像素，避免 Windows 位图缩放导致的模糊
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # LeafyGreen 设计令牌：浅色/深色两套，与 Compass 主题对应
    THEMES = {
        "light": {
            "bg": "#FFFFFF", "surface": "#F9FBFA", "surface2": "#F1F5F3",
            "border": "#E8EDEB", "borderStrong": "#C1C7C6",
            "text": "#001E2B", "secondary": "#5C6C75", "muted": "#66757D",
            "primary": "#00684A", "primaryHover": "#00593F", "onPrimary": "#FFFFFF",
            "accent": "#00ED64", "accentDark": "#00684A",
            "danger": "#DB3030", "dangerHover": "#B92B2B",
            "warn": "#946300", "ok": "#00684A",
            "focus": "#0498EC", "logBg": "#FFFFFF", "track": "#E8EDEB",
            "disabledBg": "#E8EDEB", "disabledFg": "#889397",
        },
        "dark": {
            "bg": "#001E2B", "surface": "#0B1D29", "surface2": "#112733",
            "border": "#1C2D38", "borderStrong": "#3D4F58",
            "text": "#E8EDEB", "secondary": "#C1C7C6", "muted": "#889397",
            "primary": "#00ED64", "primaryHover": "#33F27F", "onPrimary": "#001E2B",
            "accent": "#00ED64", "accentDark": "#00ED64",
            "danger": "#FF6960", "dangerHover": "#FF8A82",
            "warn": "#FFC010", "ok": "#00ED64",
            "focus": "#0498EC", "logBg": "#001E2B", "track": "#1C2D38",
            "disabledBg": "#1C2D38", "disabledFg": "#5C6C75",
        },
    }

    UI_PREFS = DATA_DIR / "ui.json"

    def load_ui_prefs() -> dict:
        try:
            return json.loads(UI_PREFS.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_ui_prefs(prefs: dict) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            UI_PREFS.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def compass_pref_theme() -> str:
        """首次运行时跟随 Compass 自身的主题设置。"""
        try:
            pref = Path(os.environ["APPDATA"]) / "MongoDB Compass" / "AppPreferences" / "General.json"
            theme = str(json.loads(pref.read_text(encoding="utf-8")).get("theme", "LIGHT")).upper()
            return "dark" if theme == "DARK" else "light"
        except Exception:
            return "light"

    def pick_font(root, candidates, fallback: str) -> str:
        try:
            families = set(tkfont.families(root))
        except Exception:
            return fallback
        for name in candidates:
            if name in families:
                return name
        return fallback

    def set_titlebar_theme(window, dark: bool) -> None:
        """让 Windows 原生标题栏跟随明暗主题。"""
        try:
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            value = ctypes.c_int(1 if dark else 0)
            for attr in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
        except Exception:
            pass

    def ellipsize(font: "tkfont.Font", text: str, max_width: int, middle: bool = False) -> str:
        if max_width <= 0 or font.measure(text) <= max_width:
            return text
        if middle and len(text) > 12:
            head, tail = text[: len(text) // 2], text[len(text) // 2:]
            while head and font.measure(head + "…" + tail) > max_width:
                if len(head) > len(tail):
                    head = head[:-1]
                else:
                    tail = tail[1:]
            return head + "…" + tail
        out = text
        while out and font.measure(out + "…") > max_width:
            out = out[:-1]
        return (out + "…") if out else ""

    def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kwargs):
        r = max(1, int(r))
        points = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    # ------------------------------------------------------------------ #
    # 控件
    # ------------------------------------------------------------------ #
    class LGButton(tk.Canvas):
        """LeafyGreen 风格圆角按钮，支持 hover / press / focus / disabled。"""

        def __init__(self, master, text, command, theme, fonts, variant="primary",
                     height=40, min_width=0, background=None):
            self.theme = theme
            self.fonts = fonts
            self.variant = variant
            self.text = text
            self.command = command
            self._enabled = True
            self._hover = False
            self._pressed = False
            self._focus = False
            self.scale = max(1.0, master.winfo_fpixels("1i") / 96.0)
            self.S = lambda n: int(round(n * self.scale))
            self.r = self.S(6)
            self.pad = self.S(18)
            self.h = self.S(height)
            self._font = tkfont.Font(root=master, family=fonts["ui"], size=10,
                                     weight="bold" if variant == "primary" else "normal")
            self._btn_w = max(self.S(min_width), self._font.measure(text) + 2 * self.pad)
            self._bg = background or theme["bg"]
            super().__init__(master, width=self._btn_w, height=self.h, bg=self._bg,
                             highlightthickness=0, bd=0, takefocus=1, cursor="hand2")
            self.bind("<Enter>", self._on_enter)
            self.bind("<Leave>", self._on_leave)
            self.bind("<ButtonPress-1>", self._on_press)
            self.bind("<ButtonRelease-1>", self._on_release)
            self.bind("<FocusIn>", self._on_focus_in)
            self.bind("<FocusOut>", self._on_focus_out)
            self.bind("<Return>", self._on_key)
            self.bind("<space>", self._on_key)
            self._draw()

        def _palette(self):
            t = self.theme
            if not self._enabled:
                if self.variant == "primary":
                    return t["disabledBg"], t["disabledFg"], None
                return self._bg, t["disabledFg"], t["border"]
            if self.variant == "primary":
                return (t["primaryHover"] if self._hover else t["primary"]), t["onPrimary"], None
            if self.variant == "danger":
                return (t["surface2"] if self._hover else self._bg), (
                    t["dangerHover"] if self._hover else t["danger"]), t["danger"]
            if self.variant == "secondary":
                return (t["surface2"] if self._hover else self._bg), t["text"], t["borderStrong"]
            return (t["surface2"] if self._hover else self._bg), (
                t["text"] if self._hover else t["secondary"]), None

        def _draw(self):
            self.delete("all")
            fill, fg, border = self._palette()
            w, h = self._btn_w, self.h
            round_rect(self, 0.5, 0.5, w - 1, h - 1, self.r, fill=fill, outline=border or fill, width=1)
            self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self._font)
            if self._focus and self._enabled:
                round_rect(self, 2.5, 2.5, w - 3.5, h - 3.5, self.r - 1,
                           fill="", outline=self.theme["focus"], width=2)

        def _on_enter(self, _e):
            self._hover = True
            self._draw()

        def _on_leave(self, _e):
            self._hover = False
            self._pressed = False
            self._draw()

        def _on_press(self, _e):
            if self._enabled:
                self._pressed = True
                self.focus_set()

        def _on_release(self, _e):
            if self._enabled and self._pressed and self._hover:
                self._pressed = False
                self.after(10, self.command)
            self._pressed = False

        def _on_focus_in(self, _e):
            self._focus = True
            self._draw()

        def _on_focus_out(self, _e):
            self._focus = False
            self._draw()

        def _on_key(self, _e):
            if self._enabled:
                self.after(10, self.command)
            return "break"

        def set_enabled(self, enabled: bool) -> None:
            self._enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
            self._draw()

        def set_theme(self, theme, background=None) -> None:
            self.theme = theme
            self._bg = background or theme["bg"]
            self.configure(bg=self._bg)
            self._draw()

        def set_text(self, text: str) -> None:
            self.text = text
            self._btn_w = max(self._btn_w, self._font.measure(text) + 2 * self.pad)
            self.configure(width=self._btn_w)
            self._draw()

    class StatusCard(tk.Canvas):
        """状态卡：标签 / 主值 / 辅助说明，随窗口宽度自适应。"""

        def __init__(self, master, theme, fonts, label, value="—", sub="", value_color=None):
            self.scale = max(1.0, master.winfo_fpixels("1i") / 96.0)
            self.S = lambda n: int(round(n * self.scale))
            super().__init__(master, width=1, height=self.S(104), bg=theme["bg"],
                             highlightthickness=0, bd=0)
            self.theme = theme
            self.fonts = fonts
            self._label = label
            self._value = value
            self._sub = sub
            self._value_color = value_color
            self._font_label = tkfont.Font(root=master, family=fonts["ui"], size=9)
            self._font_value = tkfont.Font(root=master, family=fonts["ui"], size=17, weight="bold")
            self._font_sub = tkfont.Font(root=master, family=fonts["ui"], size=9)
            self.bind("<Configure>", lambda _e: self._draw())

        def set_values(self, value=None, sub=None, value_color=None) -> None:
            if value is not None:
                self._value = value
            if sub is not None:
                self._sub = sub
            self._value_color = value_color
            self._draw()

        def set_theme(self, theme) -> None:
            self.theme = theme
            self.configure(bg=theme["bg"])
            self._draw()

        def _draw(self) -> None:
            w, h = self.winfo_width(), self.winfo_height()
            if w < 10 or h < 10:
                return
            t = self.theme
            self.delete("all")
            round_rect(self, 0.5, 0.5, w - 1, h - 1, self.S(8), fill=t["surface"], outline=t["border"], width=1)
            pad = self.S(18)
            self.create_text(pad, self.S(15), text=self._label, anchor="nw", fill=t["muted"], font=self._font_label)
            self.create_text(pad, self.S(38), text=self._value, anchor="nw",
                             fill=self._value_color or t["text"], font=self._font_value)
            sub = ellipsize(self._font_sub, self._sub, w - pad * 2)
            self.create_text(pad, self.S(76), text=sub, anchor="nw", fill=t["secondary"], font=self._font_sub)

    class LogoMark(tk.Canvas):
        def __init__(self, master, theme, size=40):
            self.scale = max(1.0, master.winfo_fpixels("1i") / 96.0)
            self.size = int(round(size * self.scale))
            super().__init__(master, width=self.size, height=self.size, bg=theme["bg"],
                             highlightthickness=0, bd=0)
            self.theme = theme
            self._draw()

        def set_theme(self, theme) -> None:
            self.theme = theme
            self.configure(bg=theme["bg"])
            self._draw()

        def _draw(self) -> None:
            self.delete("all")
            s = self.size
            pts = [(s * .50, s * .06), (s * .86, s * .33), (s * .75, s * .72),
                   (s * .50, s * .94), (s * .25, s * .72), (s * .14, s * .33)]
            self.create_polygon(pts, smooth=True, splinesteps=30, fill=self.theme["accent"], outline="")
            self.create_line(s * .50, s * .20, s * .50, s * .84,
                             fill=self.theme["accentDark"], width=max(1, int(s * .045)))

    class ProgressLine(tk.Canvas):
        def __init__(self, master, theme):
            self.scale = max(1.0, master.winfo_fpixels("1i") / 96.0)
            super().__init__(master, height=max(3, int(round(4 * self.scale))),
                             bg=theme["bg"], highlightthickness=0, bd=0)
            self.theme = theme
            self._running = False
            self._pos = 0
            self.bind("<Configure>", lambda _e: self._draw_idle())

        def set_theme(self, theme) -> None:
            self.theme = theme
            self.configure(bg=theme["bg"])
            if not self._running:
                self._draw_idle()

        def _draw_idle(self) -> None:
            self.delete("all")
            w = self.winfo_width()
            if w > 2:
                round_rect(self, 0, 1, w, 3, 1.5, fill=self.theme["track"], outline=self.theme["track"])

        def start(self) -> None:
            if self._running:
                return
            self._running = True
            self._pos = 0
            self._tick()

        def stop(self) -> None:
            self._running = False
            self._draw_idle()

        def _tick(self) -> None:
            if not self._running:
                return
            w = max(1, self.winfo_width())
            seg = max(40, int(w * 0.26))
            self.delete("all")
            round_rect(self, 0, 1, w, 3, 1.5, fill=self.theme["track"], outline=self.theme["track"])
            x = -seg + (self._pos % (w + seg))
            round_rect(self, max(0, x), 1, min(w, x + seg), 3, 1.5,
                       fill=self.theme["primary"], outline=self.theme["primary"])
            self._pos += max(6, int(w * 0.012))
            self.after(33, self._tick)

    class ThemeSwitch(tk.Frame):
        def __init__(self, master, app, theme, fonts):
            self.scale = max(1.0, master.winfo_fpixels("1i") / 96.0)
            super().__init__(master, bg=theme["bg"], highlightbackground=theme["border"], highlightthickness=1)
            self.app = app
            self.fonts = fonts
            self.labels = {}
            for name, text in (("light", "浅色"), ("dark", "深色")):
                lb = tk.Label(self, text=text, font=(fonts["ui"], 9), padx=int(10 * self.scale),
                              pady=int(3 * self.scale), cursor="hand2", bd=0)
                lb.pack(side="left")
                lb.bind("<Button-1>", lambda _e, n=name: self.app.set_theme(n))
                self.labels[name] = lb
            self.set_theme(theme, app.theme_name)

        def set_theme(self, theme, active) -> None:
            self.configure(bg=theme["bg"], highlightbackground=theme["border"])
            for name, lb in self.labels.items():
                if name == active:
                    lb.configure(bg=theme["surface2"], fg=theme["text"],
                                 font=(self.fonts["ui"], 9, "bold"))
                else:
                    lb.configure(bg=theme["bg"], fg=theme["muted"], font=(self.fonts["ui"], 9))

    class Modal(tk.Toplevel):
        """无边框模态框，替代系统 messagebox，保持视觉一致。"""

        def __init__(self, parent, theme, fonts, kind, title, message,
                     confirm_text="确认", cancel_text="取消"):
            super().__init__(parent)
            self.result = False
            self.parent = parent
            self.theme = theme
            self.fonts = fonts
            self.scale = max(1.0, parent.winfo_fpixels("1i") / 96.0)
            self.S = lambda n: int(round(n * self.scale))
            self.overrideredirect(True)
            self.configure(bg=theme["borderStrong"])
            self.transient(parent)
            try:
                self.attributes("-topmost", True)
            except tk.TclError:
                pass

            outer = tk.Frame(self, bg=theme["bg"])
            outer.pack(fill="both", expand=True, padx=1, pady=1)
            body = tk.Frame(outer, bg=theme["bg"])
            body.pack(fill="both", expand=True, padx=self.S(24), pady=(self.S(20), self.S(16)))

            head = tk.Frame(body, bg=theme["bg"])
            head.pack(fill="x")
            tk.Label(head, text=title, bg=theme["bg"], fg=theme["text"],
                     font=(fonts["ui"], 13, "bold"), anchor="w").pack(side="left")
            close = tk.Label(head, text="✕", bg=theme["bg"], fg=theme["muted"],
                             font=(fonts["ui"], 11), cursor="hand2", padx=self.S(4))
            close.pack(side="right")
            close.bind("<Button-1>", lambda _e: self._close(False))
            tk.Frame(body, bg=theme["border"], height=1).pack(fill="x", pady=(self.S(10), 0))

            msg = tk.Label(body, text=message, bg=theme["bg"], fg=theme["secondary"],
                           font=(fonts["ui"], 10), justify="left", anchor="w",
                           wraplength=self.S(440))
            msg.pack(fill="x", pady=(self.S(12), self.S(18)))

            btns = tk.Frame(body, bg=theme["bg"])
            btns.pack(fill="x")
            primary = LGButton(btns, confirm_text, lambda: self._close(True), theme, fonts,
                               "primary" if kind != "error" else "primary",
                               height=36, background=theme["bg"])
            primary.pack(side="right")
            if kind == "askyesno":
                cancel = LGButton(btns, cancel_text, lambda: self._close(False), theme, fonts,
                                  "secondary", height=36, background=theme["bg"])
                cancel.pack(side="right", padx=(0, self.S(8)))

            self.bind("<Escape>", lambda _e: self._close(False))
            self.bind("<Return>", lambda _e: self._close(True))

            # 拖动
            for widget in (head, msg):
                widget.bind("<ButtonPress-1>", self._drag_start)
                widget.bind("<B1-Motion>", self._drag_move)

            self.update_idletasks()
            w = max(self.S(520), self.winfo_reqwidth())
            h = self.winfo_reqheight()
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            self.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + max(0, (ph - h) // 3)}")
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.update_idletasks()
            self.grab_set()
            self.after(20, self.lift)
            self.after(40, self.focus_force)
            self.after(40, primary.focus_set)

        def _drag_start(self, e):
            self._dx, self._dy = e.x, e.y

        def _drag_move(self, e):
            self.geometry(f"+{self.winfo_x() + e.x - self._dx}+{self.winfo_y() + e.y - self._dy}")

        def _close(self, result: bool) -> None:
            self.result = result
            try:
                self.grab_release()
            except tk.TclError:
                pass
            self.destroy()

        def show(self) -> bool:
            self.wait_window()
            return self.result

    class BackupDialog(tk.Toplevel):
        def __init__(self, app):
            super().__init__(app)
            self.app = app
            t, fonts, S = app.T, app.fonts, app.S
            self.title("备份与撤销 · Compass 汉化工具")
            self.configure(bg=t["bg"])
            self.minsize(S(680), S(420))
            self.transient(app)
            ensure_dirs()
            self.grab_set()
            self.after(350, lambda: set_titlebar_theme(self, t is THEMES["dark"]))

            head = tk.Frame(self, bg=t["bg"])
            head.pack(fill="x", padx=S(24), pady=(S(20), S(4)))
            tk.Label(head, text="备份与撤销", bg=t["bg"], fg=t["text"],
                     font=(fonts["ui"], 15, "bold")).pack(anchor="w")
            tk.Label(head, text="每次汉化前都会自动备份原始 app.asar，可选择任意历史版本回滚。",
                     bg=t["bg"], fg=t["secondary"], font=(fonts["ui"], 9)).pack(anchor="w", pady=(S(4), 0))

            card = tk.Frame(self, bg=t["surface"], highlightbackground=t["border"], highlightthickness=1)
            card.pack(fill="both", expand=True, padx=S(24), pady=(S(12), S(12)))
            card.grid_columnconfigure(0, weight=1)
            card.grid_rowconfigure(0, weight=1)

            cols = ("创建时间", "Compass 版本", "大小", "备份 ID")
            self.tree = ttk.Treeview(card, columns=cols, show="headings", style="LG.Treeview", height=6)
            for col, width, anchor in zip(cols, (160, 120, 100, 340), ("w", "w", "e", "w")):
                self.tree.heading(col, text=col, anchor="w")
                self.tree.column(col, width=S(width), anchor=anchor, stretch=(col == "备份 ID"))
            scroll = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview,
                                   style="LG.Vertical.TScrollbar")
            self.tree.configure(yscrollcommand=scroll.set)
            self.tree.grid(row=0, column=0, sticky="nsew", padx=(S(8), 0), pady=S(8))
            scroll.grid(row=0, column=1, sticky="ns", pady=S(8), padx=(0, S(8)))

            self.items = list_backups()
            if self.items:
                for b in self.items:
                    self.tree.insert("", "end", iid=b.backup_id,
                                     values=(b.human_time, b.version, human_size(b.size), b.backup_id))
                first = self.items[0].backup_id
                self.tree.selection_set(first)
                self.tree.focus(first)
            else:
                tk.Label(card, text="暂无可用备份\n首次汉化时会自动创建", bg=t["surface"],
                         fg=t["muted"], font=(fonts["ui"], 10), justify="center").grid(
                    row=0, column=0, sticky="nsew")
            self.tree.bind("<Double-1>", lambda _e: self.rollback())

            foot = tk.Frame(self, bg=t["bg"])
            foot.pack(fill="x", padx=S(24), pady=(0, S(20)))
            self.btn_rollback = LGButton(foot, "回滚到此备份", self.rollback, t, fonts, "primary", height=38)
            self.btn_rollback.pack(side="left")
            if not self.items:
                self.btn_rollback.set_enabled(False)
            LGButton(foot, "打开备份目录", lambda: os.startfile(str(BACKUP_DIR)), t, fonts,
                     "secondary", height=38).pack(side="left", padx=(S(10), 0))
            LGButton(foot, "关闭", self.destroy, t, fonts, "ghost", height=38).pack(side="right")

            self.bind("<Escape>", lambda _e: self.destroy())

            self.update_idletasks()
            w = max(S(820), self.winfo_reqwidth())
            h = self.winfo_reqheight()
            px, py = app.winfo_rootx(), app.winfo_rooty()
            pw, ph = app.winfo_width(), app.winfo_height()
            self.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + max(0, (ph - h) // 2)}")

        def rollback(self) -> None:
            sel = self.tree.selection()
            if not sel:
                self.app._modal("info", "未选择备份", "请先在列表中选择一条备份。")
                self.grab_set()
                return
            backup_id = sel[0]
            if not self.app._modal("askyesno", "确认回滚",
                                   f"将使用备份 {backup_id} 覆盖当前 app.asar，是否继续？",
                                   confirm_text="回滚"):
                self.grab_set()
                return
            install = self.app.status.install if self.app.status else None
            if install is None:
                self.app._modal("error", "无法回滚", "未检测到有效的 Compass 安装。")
                return
            if compass_running():
                if not self.app._modal("askyesno", "Compass 正在运行",
                                       "需要先关闭 Compass。是否由工具关闭？",
                                       confirm_text="关闭 Compass"):
                    self.grab_set()
                    return
                kill_compass()
                time.sleep(2)

            def task():
                restore_english(install, backup_id=backup_id)
                self.app._sync_dialog("info", "回滚完成", "已回滚到所选备份，请重新启动 Compass。")

            self.destroy()
            self.app._run(task, "正在回滚…")

    # ------------------------------------------------------------------ #
    # 主窗口
    # ------------------------------------------------------------------ #
    class MongoVersionDialog(tk.Toplevel):
        """MongoDB 官方版本信息与主流版本对比。"""

        def __init__(self, app):
            super().__init__(app)
            self.app = app
            self.theme = app.T
            self.fonts = app.fonts
            self.S = app.S
            self.title("MongoDB 版本信息 · Compass 汉化工具")
            self.configure(bg=self.theme["bg"])
            self.geometry(f"{self.S(1120)}x{self.S(800)}")
            self.minsize(self.S(940), self.S(680))
            self.transient(app)
            self.grab_set()
            self.data = load_mongodb_versions()
            self.server_data = detect_mongodb_server()
            self._server_choices: dict = {}
            self._downloading = False
            self._download_cancel = False
            self._dl_queue: queue.Queue = queue.Queue()
            self._queue: queue.Queue = queue.Queue()
            self._refreshing = False
            self._build()
            self.update_idletasks()
            px, py = app.winfo_rootx(), app.winfo_rooty()
            pw, ph = app.winfo_width(), app.winfo_height()
            w, h = self.winfo_width(), self.winfo_height()
            self.geometry(f"+{px + max(0, (pw - w) // 2)}+{py + max(0, (ph - h) // 2)}")
            self.after(60, lambda: set_titlebar_theme(self, app.theme_name == "dark"))
            self.bind("<Escape>", lambda _e: self.destroy())

        # ------------------------------------------------------------------ #
        def _card(self, parent, label):
            card = StatusCard(parent, self.theme, self.fonts, label)
            card.pack(side="left", fill="both", expand=True, padx=(0, self.S(10)))
            return card

        def _build(self) -> None:
            t, S, fonts = self.theme, self.S, self.fonts
            margin = S(24)

            head = tk.Frame(self, bg=t["bg"])
            head.pack(fill="x", padx=margin, pady=(S(16), S(6)))
            titles = tk.Frame(head, bg=t["bg"])
            titles.pack(side="left")
            tk.Label(titles, text="MongoDB 版本信息", bg=t["bg"], fg=t["text"],
                     font=(fonts["ui"], 16, "bold")).pack(anchor="w")
            tk.Label(titles, text="官方稳定版与主流版本核心差异 · 数据来自 MongoDB 官方文档",
                     bg=t["bg"], fg=t["secondary"], font=(fonts["ui"], 9)).pack(anchor="w", pady=(S(2), 0))
            close = tk.Label(head, text="✕", bg=t["bg"], fg=t["muted"], font=(fonts["ui"], 12),
                             cursor="hand2", padx=S(6))
            close.pack(side="right", anchor="n")
            close.bind("<Button-1>", lambda _e: self.destroy())

            cards = tk.Frame(self, bg=t["bg"])
            cards.pack(fill="x", padx=margin, pady=(S(6), S(10)))
            self.card_current = self._card(cards, "当前稳定版")
            self.card_previous = self._card(cards, "前序稳定版")
            self.card_support = self._card(cards, "支持至")
            self.card_updated = self._card(cards, "数据更新")
            self.card_current.pack_configure(padx=(0, S(10)))

            style = ttk.Style(self)
            style.configure("Mongo.TNotebook", background=t["bg"], borderwidth=0,
                            tabmargins=(0, 0, 0, 0))
            style.configure("Mongo.TNotebook.Tab", background=t["surface"], foreground=t["secondary"],
                            padding=(S(16), S(8)), font=(fonts["ui"], 9))
            style.map("Mongo.TNotebook.Tab",
                      background=[("selected", t["bg"])],
                      foreground=[("selected", t["text"])])
            style.configure("Mongo.TCombobox", fieldbackground=t["surface"], background=t["surface"],
                            foreground=t["text"], arrowcolor=t["secondary"], bordercolor=t["border"],
                            lightcolor=t["border"], darkcolor=t["border"], padding=S(4),
                            font=(fonts["ui"], 9))
            style.map("Mongo.TCombobox",
                      fieldbackground=[("readonly", t["surface"])],
                      foreground=[("readonly", t["text"])])
            style.configure("Mongo.Horizontal.TProgressbar", troughcolor=t["border"],
                            background=t["primary"], bordercolor=t["surface"],
                            lightcolor=t["primary"], darkcolor=t["primary"], thickness=S(8))
            style.configure("Mongo.Treeview", background=t["surface"], fieldbackground=t["surface"],
                            foreground=t["text"], borderwidth=0, rowheight=S(44),
                            font=(fonts["ui"], 9))
            style.configure("Mongo.Treeview.Heading", background=t["bg"], foreground=t["secondary"],
                            borderwidth=0, relief="flat", font=(fonts["ui"], 9, "bold"),
                            padding=(S(8), S(7)))
            style.map("Mongo.Treeview", background=[("selected", t["primary"])],
                      foreground=[("selected", t["onPrimary"])])

            self.notebook = ttk.Notebook(self, style="Mongo.TNotebook")
            self.notebook.pack(fill="both", expand=True, padx=margin, pady=(0, S(8)))

            # Tab 1: 更新亮点
            tab1 = tk.Frame(self.notebook, bg=t["surface"])
            self.notebook.add(tab1, text="更新亮点")
            text_wrap = tk.Frame(tab1, bg=t["surface"])
            text_wrap.pack(fill="both", expand=True, padx=S(12), pady=S(12))
            text_wrap.grid_columnconfigure(0, weight=1)
            text_wrap.grid_rowconfigure(0, weight=1)
            self.highlight_text = tk.Text(text_wrap, bg=t["surface"], fg=t["text"], bd=0,
                                          relief="flat", highlightthickness=0, wrap="word",
                                          width=1, height=8, font=(fonts["ui"], 9),
                                          padx=S(10), pady=S(8), spacing1=1, spacing3=2)
            self.highlight_text.grid(row=0, column=0, sticky="nsew")
            scroll1 = ttk.Scrollbar(text_wrap, orient="vertical", command=self.highlight_text.yview,
                                    style="LG.Vertical.TScrollbar")
            self.highlight_text.configure(yscrollcommand=scroll1.set)
            scroll1.grid(row=0, column=1, sticky="ns")

            # Tab 2: 版本对比
            tab2 = tk.Frame(self.notebook, bg=t["surface"])
            self.notebook.add(tab2, text="版本对比")
            table_wrap = tk.Frame(tab2, bg=t["surface"])
            table_wrap.pack(fill="both", expand=True, padx=S(12), pady=S(12))
            table_wrap.grid_columnconfigure(0, weight=1)
            table_wrap.grid_rowconfigure(0, weight=1)
            self.tree = ttk.Treeview(table_wrap, show="headings", style="Mongo.Treeview", height=9)
            self.tree.grid(row=0, column=0, sticky="nsew")
            scroll2 = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview,
                                    style="LG.Vertical.TScrollbar")
            self.tree.configure(yscrollcommand=scroll2.set)
            scroll2.grid(row=0, column=1, sticky="ns")

            # Tab 3: 下载并安装 MongoDB Server
            tab3 = tk.Frame(self.notebook, bg=t["surface"])
            self.notebook.add(tab3, text="下载安装")
            box = tk.Frame(tab3, bg=t["surface"])
            box.pack(fill="both", expand=True, padx=S(20), pady=S(18))

            tk.Label(box, text="本机 MongoDB Server", bg=t["surface"], fg=t["muted"],
                     font=(fonts["ui"], 8)).grid(row=0, column=0, columnspan=2, sticky="w")
            self.server_value = tk.Label(box, text="检测中…", bg=t["surface"], fg=t["text"],
                                         font=(fonts["ui"], 18, "bold"))
            self.server_value.grid(row=1, column=0, sticky="w", pady=(S(2), 0))
            self.server_source = tk.Label(box, text="", bg=t["surface"], fg=t["secondary"],
                                          font=(fonts["ui"], 9), anchor="w")
            self.server_source.grid(row=1, column=1, sticky="w", padx=(S(14), 0))
            self.server_path = tk.Label(box, text="", bg=t["surface"], fg=t["muted"],
                                        font=(fonts["mono"], 8), anchor="w", justify="left",
                                        wraplength=S(780))
            self.server_path.grid(row=2, column=0, columnspan=2, sticky="w", pady=(S(2), S(10)))
            tk.Frame(box, bg=t["border"], height=1).grid(row=3, column=0, columnspan=2,
                                                         sticky="ew", pady=(0, S(12)))

            tk.Label(box, text="选择要安装的 MongoDB 版本", bg=t["surface"], fg=t["text"],
                     font=(fonts["ui"], 10, "bold")).grid(row=4, column=0, columnspan=2, sticky="w")
            self.server_combo = ttk.Combobox(box, state="readonly", style="Mongo.TCombobox",
                                             width=34, font=(fonts["ui"], 9))
            self.server_combo.grid(row=5, column=0, sticky="w", pady=(S(6), S(12)))
            self.server_combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_server_button())

            server_actions = tk.Frame(box, bg=t["surface"])
            server_actions.grid(row=6, column=0, columnspan=2, sticky="w")
            self.btn_install_server = LGButton(server_actions, "下载并安装", self._start_download,
                                              t, self.fonts, "primary", height=36)
            self.btn_install_server.pack(side="left", padx=(0, S(8)))
            self.btn_server_page = LGButton(server_actions, "官方下载页", self._open_server_page,
                                            t, self.fonts, "secondary", height=36)
            self.btn_server_page.pack(side="left", padx=(0, S(8)))
            self.btn_server_recheck = LGButton(server_actions, "重新检测", self._recheck_server,
                                               t, self.fonts, "ghost", height=36)
            self.btn_server_recheck.pack(side="left")
            self.btn_cancel_download = LGButton(server_actions, "取消下载", self._cancel_download,
                                                t, self.fonts, "danger", height=36)
            self.btn_cancel_download.pack(side="left", padx=(S(8), 0))
            self.btn_cancel_download.pack_forget()

            self.download_box = tk.Frame(box, bg=t["surface"])
            self.download_box.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(S(14), 0))
            self.download_box.grid_columnconfigure(0, weight=1)
            self.download_bar = ttk.Progressbar(self.download_box, style="Mongo.Horizontal.TProgressbar",
                                                orient="horizontal", mode="determinate", maximum=100)
            self.download_bar.grid(row=0, column=0, sticky="ew")
            self.download_status = tk.Label(self.download_box, text="", bg=t["surface"], fg=t["secondary"],
                                            font=(fonts["ui"], 8), anchor="w")
            self.download_status.grid(row=1, column=0, sticky="w", pady=(S(4), 0))
            self.download_box.grid_remove()

            notes = tk.Label(
                box,
                text="安装包来源：fastdl.mongodb.org（MongoDB 官方签名 MSI），下载后自动校验 SHA256。"
                     "安装程序会请求管理员权限，本工具只负责下载并启动官方安装程序，"
                     "不会修改系统服务、数据目录或现有数据库。升级前请备份数据并阅读官方升级说明。",
                bg=t["surface"], fg=t["muted"], font=(fonts["ui"], 8),
                justify="left", anchor="w", wraplength=S(940),
            )
            notes.grid(row=8, column=0, columnspan=2, sticky="w", pady=(S(16), 0))

            # 底部：来源、覆盖范围、更新方式
            foot = tk.Frame(self, bg=t["bg"])
            foot.pack(fill="x", padx=margin, pady=(0, S(14)))
            left = tk.Frame(foot, bg=t["bg"])
            left.pack(side="left", fill="x", expand=True)
            links = tk.Frame(left, bg=t["bg"])
            links.pack(anchor="w")
            tk.Label(links, text="数据来源：", bg=t["bg"], fg=t["muted"],
                     font=(fonts["ui"], 8)).pack(side="left")
            for label, url in (
                ("Release Notes", self.data["source"]["release_notes"]),
                ("生命周期", self.data["source"]["lifecycle"]),
                ("升级路径", self.data["source"]["versions"]),
            ):
                lb = tk.Label(links, text=label, bg=t["bg"], fg=t["primary"],
                              font=(fonts["ui"], 8, "underline"), cursor="hand2")
                lb.pack(side="left", padx=(0, S(10)))
                lb.bind("<Button-1>", lambda _e, u=url: self._open_url(u))
            self.coverage_label = tk.Label(left, text="", bg=t["bg"], fg=t["secondary"],
                                           font=(fonts["ui"], 8), justify="left", anchor="w",
                                           wraplength=S(700))
            self.coverage_label.pack(anchor="w", pady=(S(4), 0))
            self.update_label = tk.Label(left, text="", bg=t["bg"], fg=t["muted"],
                                         font=(fonts["ui"], 8), justify="left", anchor="w",
                                         wraplength=S(700))
            self.update_label.pack(anchor="w", pady=(S(2), 0))

            right = tk.Frame(foot, bg=t["bg"])
            right.pack(side="right", anchor="se")
            self.btn_refresh = LGButton(right, "刷新数据", self._refresh, self.theme, self.fonts,
                                        "secondary", height=36)
            self.btn_refresh.pack(anchor="e")
            self.status_label = tk.Label(right, text="", bg=t["bg"], fg=t["muted"],
                                         font=(fonts["ui"], 8), anchor="e", justify="right",
                                         wraplength=S(250))
            self.status_label.pack(anchor="e", pady=(S(4), 0))

            self._configure_text_tags()
            self._populate()

        def _configure_text_tags(self) -> None:
            t, S, fonts = self.theme, self.S, self.fonts
            self.highlight_text.tag_configure("h1", font=(fonts["ui"], 14, "bold"), foreground=t["text"],
                                              spacing3=S(2))
            self.highlight_text.tag_configure("meta", font=(fonts["ui"], 9), foreground=t["secondary"],
                                              spacing3=S(8))
            self.highlight_text.tag_configure("h2", font=(fonts["ui"], 10, "bold"), foreground=t["text"],
                                              spacing1=S(10), spacing3=S(4))
            self.highlight_text.tag_configure("bt", font=(fonts["ui"], 9, "bold"), foreground=t["text"],
                                              lmargin1=S(12), lmargin2=S(12))
            self.highlight_text.tag_configure("body", font=(fonts["ui"], 9), foreground=t["secondary"],
                                              lmargin1=S(12), lmargin2=S(12))
            self.highlight_text.tag_configure("note", font=(fonts["ui"], 8), foreground=t["muted"],
                                              lmargin1=S(12), lmargin2=S(12))

        def _populate(self) -> None:
            data = self.data
            versions = {v["series"]: v for v in data.get("versions", [])}
            current = data.get("current", "")
            previous = data.get("previous", "")
            cur = versions.get(current, {})
            prev = versions.get(previous, {})

            self.card_current.set_values(
                current or "—",
                f"{data.get('latest_patch', '—')} · {data.get('latest_patch_date', '')}",
                self.theme["ok"],
            )
            self.card_previous.set_values(previous or "—", prev.get("latest", "—"))
            eol = cur.get("eol", "—")
            self.card_support.set_values(eol[:7] if eol != "—" else "—", f"{current} 官方生命周期")
            self.card_updated.set_values(data.get("fetched_at", "—"), "官方 Release Notes 快照")

            self.notebook.tab(0, text=f"{current} 更新亮点" if current else "更新亮点")
            self._fill_highlights()
            self._fill_table()
            if not self._downloading:
                self._populate_server()

            self.coverage_label.configure(
                text="覆盖范围：" + data.get("coverage", "") +
                     "  更新方式：" + data.get("update_method", "")
            )
            origin = "本地缓存" if data.get("_origin") == "cache" else "内置快照"
            self.status_label.configure(text=f"{origin} · 更新于 {data.get('fetched_at', '—')}")

        def _fill_highlights(self) -> None:
            data, cur, prev = self.data, self.data.get("current", ""), self.data.get("previous", "")
            self.highlight_text.configure(state="normal")
            self.highlight_text.delete("1.0", "end")
            self.highlight_text.insert("end", f"MongoDB {cur} · 当前稳定版\n", "h1")
            meta = f"最新补丁 {data.get('latest_patch', '—')}"
            if data.get("latest_patch_date"):
                meta += f"（{data['latest_patch_date']}）"
            meta += f"    对比基线 {prev}"
            self.highlight_text.insert("end", meta + "\n", "meta")
            self.highlight_text.insert("end", f"相较 {prev} 的核心更新\n", "h2")
            for item in data.get("latest_changes", []):
                self.highlight_text.insert("end", f"• {item.get('title', '')}\n", "bt")
                self.highlight_text.insert("end", f"   {item.get('detail', '')}\n", "body")
            self.highlight_text.insert("end", "升级建议\n", "h2")
            self.highlight_text.insert("end", data.get("upgrade_advice", "") + "\n", "body")
            self.highlight_text.insert("end", "说明\n", "h2")
            for note in data.get("notes", []):
                self.highlight_text.insert("end", f"• {note}\n", "note")
            if data.get("refresh_note"):
                self.highlight_text.insert("end", "\n" + data["refresh_note"] + "\n", "note")
            self.highlight_text.configure(state="disabled")

        def _fill_table(self) -> None:
            comp = self.data.get("comparison", {})
            columns = comp.get("columns", [])
            cols = ["feature"] + [c["series"] for c in columns]
            self.tree.configure(columns=cols)
            self.tree.heading("feature", text="维度")
            self.tree.column("feature", width=self.S(112), anchor="w", stretch=False)
            for c in columns:
                series = c["series"]
                self.tree.heading(series, text=c["label"])
                self.tree.column(series, width=self.S(236), anchor="w", stretch=True)
            for item in self.tree.get_children():
                self.tree.delete(item)
            for row in comp.get("rows", []):
                values = [row.get("feature", "")] + [row.get("values", {}).get(c["series"], "") for c in columns]
                self.tree.insert("", "end", values=values)

        def _populate_server(self) -> None:
            srv = self.server_data
            if srv:
                self.server_value.configure(text=srv.version, fg=self.theme["ok"])
                self.server_source.configure(text=f"来源：{srv.source}")
                self.server_path.configure(text=f"mongod 路径：{srv.exe}")
            else:
                self.server_value.configure(text="未检测到", fg=self.theme["muted"])
                self.server_source.configure(text="可安装官方 MongoDB Community Server")
                self.server_path.configure(text="未在 PATH、Program Files\\MongoDB\\Server 或卸载注册表中找到 mongod。")

            choices = {}
            for index, item in enumerate(self.data.get("versions", [])):
                label = f"{item['latest']}（{'最新' if index == 0 else item['series'] + ' 系列'}）"
                choices[label] = item["latest"]
            self._server_choices = choices
            current = self.server_combo.get()
            self.server_combo.configure(values=list(choices))
            if current not in choices:
                self.server_combo.set(next(iter(choices), ""))
            self._sync_server_button()

        def _sync_server_button(self) -> None:
            version = self._server_choices.get(self.server_combo.get(), "")
            if not version:
                self.btn_install_server.set_text("下载并安装")
                return
            srv = self.server_data
            if srv and version_key(srv.version) < version_key(version):
                text = f"更新到 {version}"
            elif srv and version_key(srv.version) >= version_key(version):
                text = f"重新安装 {version}"
            else:
                text = f"下载并安装 {version}"
            self.btn_install_server.set_text(text)

        def _ask(self, kind: str, title: str, message: str, confirm_text: Optional[str] = None) -> bool:
            result = self.app._modal(kind, title, message, confirm_text=confirm_text)
            try:
                self.grab_set()
            except tk.TclError:
                pass
            return result

        def _open_server_page(self) -> None:
            import webbrowser
            webbrowser.open(MONGODB_SERVER_PAGE)

        def _recheck_server(self) -> None:
            self.server_data = detect_mongodb_server(force=True)
            self._populate_server()
            self.app.refresh_status()
            if self.server_data:
                self._set_status(f"已检测到 MongoDB Server {self.server_data.version}")
            else:
                self._set_status("仍未检测到本机 MongoDB Server")

        def _start_download(self) -> None:
            if self._downloading:
                return
            version = self._server_choices.get(self.server_combo.get(), "")
            if not version:
                return
            message = (
                f"将下载 MongoDB {version} Windows x64 官方 MSI 到：\n"
                f"{MONGODB_DOWNLOAD_DIR}\n\n"
                "安装包体积较大（约 0.6–1.0 GB，具体以实际下载为准）。"
                "下载完成后可选择立即运行官方安装程序。是否继续？"
            )
            if not self._ask("askyesno", "下载 MongoDB", message, confirm_text="开始下载"):
                try:
                    if self.winfo_exists():
                        self._set_status("已取消下载")
                except tk.TclError:
                    pass
                return
            self._begin_download(version)

        def _begin_download(self, version: str) -> None:
            self._downloading = True
            self._download_cancel = False
            self.btn_install_server.set_enabled(False)
            self.btn_server_recheck.set_enabled(False)
            self.server_combo.configure(state="disabled")
            self.btn_cancel_download.pack(side="left", padx=(self.S(8), 0))
            self.btn_cancel_download.set_enabled(True)
            self.download_box.grid()
            self.download_bar["value"] = 0
            self.download_status.configure(text="正在连接官方下载服务器…")
            self._dl_queue = queue.Queue()

            def worker():
                try:
                    path = download_server_msi(
                        version,
                        progress=lambda done, total: self._dl_queue.put(("progress", done, total)),
                        cancelled=lambda: self._download_cancel,
                    )
                    self._dl_queue.put(("done", str(path)))
                except Exception as exc:  # noqa: BLE001
                    self._dl_queue.put(("error", str(exc)))

            threading.Thread(target=worker, daemon=True).start()
            self.after(120, self._poll_download)

        def _poll_download(self) -> None:
            try:
                if not self.winfo_exists():
                    return
            except tk.TclError:
                return
            while True:
                try:
                    item = self._dl_queue.get_nowait()
                except queue.Empty:
                    break
                kind = item[0]
                if kind == "progress":
                    done, total = item[1], item[2]
                    if total:
                        percent = min(100, int(done * 100 / total))
                        self.download_bar["value"] = percent
                        self.download_status.configure(
                            text=f"正在下载：{human_size(done)} / {human_size(total)}（{percent}%）"
                        )
                    else:
                        self.download_status.configure(text=f"正在下载：{human_size(done)}")
                elif kind == "done":
                    self._complete_download(item[1])
                    return
                elif kind == "error":
                    self._download_failed(item[1])
                    return
            if self._downloading:
                self.after(120, self._poll_download)

        def _reset_download_ui(self) -> None:
            self._downloading = False
            self.btn_install_server.set_enabled(True)
            self.btn_server_recheck.set_enabled(True)
            self.server_combo.configure(state="readonly")
            self.btn_cancel_download.pack_forget()

        def _complete_download(self, path: str) -> None:
            self._reset_download_ui()
            self.download_bar["value"] = 100
            self.download_status.configure(text=f"下载完成：{path}")
            self._set_status("安装包下载完成")
            if self._ask(
                "askyesno", "下载完成",
                f"安装包已保存到：\n{path}\n\n是否立即运行官方安装程序？",
                confirm_text="运行安装程序",
            ):
                try:
                    os.startfile(path)  # type: ignore[attr-defined]
                except Exception as exc:
                    self._ask("error", "无法启动安装程序",
                              f"请手动双击安装包：\n{path}\n\n{exc}")
                else:
                    self.download_status.configure(text="安装程序已启动；完成后点击「重新检测」。")
            else:
                self.download_status.configure(text="已保存安装包，可稍后手动运行。")

        def _download_failed(self, error: str) -> None:
            self._reset_download_ui()
            self.download_box.grid_remove()
            if "取消" in error:
                self._set_status("已取消下载")
                return
            self._set_status("下载失败")
            if self._ask("askyesno", "下载失败",
                         error + "\n\n是否打开 MongoDB 官方下载页？",
                         confirm_text="打开下载页"):
                self._open_server_page()

        def _cancel_download(self) -> None:
            if not self._downloading:
                return
            self._download_cancel = True
            self.btn_cancel_download.set_enabled(False)
            self.download_status.configure(text="正在取消下载…")

        def destroy(self) -> None:
            self._download_cancel = True
            super().destroy()

        def _open_url(self, url: str) -> None:
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass

        def _set_status(self, text: str) -> None:
            self.status_label.configure(text=text)

        def _refresh(self) -> None:
            if self._refreshing:
                return
            self._refreshing = True
            self.btn_refresh.set_enabled(False)
            self._set_status("正在从官方 Release Notes 刷新…")

            def worker():
                try:
                    self._queue.put(("ok", refresh_mongodb_versions()))
                except Exception as exc:  # noqa: BLE001
                    self._queue.put(("err", str(exc)))

            threading.Thread(target=worker, daemon=True).start()
            self.after(120, self._poll)

        def _poll(self) -> None:
            try:
                if not self.winfo_exists():
                    return
            except tk.TclError:
                return
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                if self._refreshing:
                    self.after(120, self._poll)
                return
            self._refreshing = False
            self.btn_refresh.set_enabled(True)
            if kind == "ok":
                self.data = payload
                self._populate()
                self._set_status(f"已刷新：{payload.get('current')} · {payload.get('latest_patch')}"
                                 f"（{payload.get('fetched_at')}）")
            else:
                self._set_status("刷新失败，继续使用本地快照")
                self.app._modal("error", "刷新失败",
                                "无法从 MongoDB 官方文档获取版本信息：\n\n" + str(payload))


    class CompassApp(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.withdraw()
            self.title(f"{TOOL_NAME} v{TOOL_VERSION}")
            self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
            self.fonts = {
                "ui": pick_font(self, ["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"], "Segoe UI"),
                "mono": pick_font(self, ["Cascadia Mono", "Consolas", "Courier New"], "Consolas"),
            }
            try:
                if ICON_ICO.exists():
                    self.iconbitmap(default=str(ICON_ICO))
            except tk.TclError:
                pass
            prefs = load_ui_prefs()
            self.theme_name = prefs.get("theme") or compass_pref_theme()
            if self.theme_name not in THEMES:
                self.theme_name = "light"
            self.T = THEMES[self.theme_name]
            self._logo_light = self._load_logo_photo(False)
            self._logo_dark = self._load_logo_photo(True)
            self._logo_photo = self._logo_dark if self.theme_name == "dark" else self._logo_light
            self._queue: queue.Queue = queue.Queue()
            self._busy = False
            self.status: Optional[Status] = None
            self.root_override: Optional[Path] = None
            self._full_path = ""
            self._card_refs = []
            self._themed_frames = []
            self._themed_labels = []
            self._buttons = []

            self._init_ttk()
            self._build_ui()
            self._apply_theme()
            self._restore_geometry(prefs)
            self.deiconify()
            self.after(500, lambda: set_titlebar_theme(self, self.theme_name == "dark"))
            self.bind("<Map>", lambda _e: self.after(120, lambda: set_titlebar_theme(self, self.theme_name == "dark")))

            self._latest_state = None
            LOG.add_sink(self._enqueue_log)
            self.after(120, self._drain)
            self.refresh_status()
            self.after(250, self._startup_log)
            self.after(1500, self._auto_check_update)
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.bind("<F5>", lambda _e: self.refresh_status())
            self.bind("<Control-l>", lambda _e: self.open_logs())
            self.bind("<Control-L>", lambda _e: self.open_logs())

        # -- 尺寸与主题 ---------------------------------------------------- #
        def S(self, n) -> int:
            return int(round(n * self.scale))

        def _load_logo_photo(self, dark: bool = False):
            """按当前 DPI 选择最合适的 Compass 官方叶形图标。"""
            try:
                target = int(round(44 * self.scale))
                sizes = (32, 36, 40, 44, 48, 52, 56, 64, 80, 96, 128)
                pick = min(sizes, key=lambda s: abs(s - target))
                prefix = "compass-mark-dark-" if dark else "compass-mark-"
                for name in (f"{prefix}{pick}.png", f"compass-{pick}.png"):
                    path = ASSETS_DIR / name
                    if path.exists():
                        # 经 base64 传入，避免 Tk 无法读取中文路径
                        data = base64.b64encode(path.read_bytes()).decode("ascii")
                        return tk.PhotoImage(master=self, data=data, format="png")
            except Exception:
                pass
            return None

        def _init_ttk(self) -> None:
            self._ttk = ttk.Style(self)
            try:
                self._ttk.theme_use("clam")
            except tk.TclError:
                pass
            self._style_tree()

        def _style_tree(self) -> None:
            t, f, s = self.T, self.fonts, self._ttk
            s.configure("LG.Treeview", background=t["surface"], fieldbackground=t["surface"],
                        foreground=t["text"], borderwidth=0, rowheight=self.S(32),
                        font=(f["ui"], 9))
            s.configure("LG.Treeview.Heading", background=t["bg"], foreground=t["secondary"],
                        borderwidth=0, relief="flat", font=(f["ui"], 9, "bold"),
                        padding=(self.S(8), self.S(6)))
            s.map("LG.Treeview", background=[("selected", t["primary"])],
                  foreground=[("selected", t["onPrimary"])])
            s.configure("LG.Vertical.TScrollbar", background=t["borderStrong"],
                        troughcolor=t["surface"], bordercolor=t["surface"],
                        arrowcolor=t["secondary"], width=self.S(8),
                        arrowsize=0, relief="flat", borderwidth=0)

        def _restore_geometry(self, prefs: dict) -> None:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            default_w = min(self.S(1080), int(sw * 0.92))
            default_h = min(self.S(750), int(sh * 0.88))
            geo = prefs.get("geometry")
            if geo:
                try:
                    self.geometry(geo)
                except tk.TclError:
                    geo = None
            if not geo:
                x = (sw - default_w) // 2
                y = max(0, (sh - default_h) // 2 - self.S(20))
                self.geometry(f"{default_w}x{default_h}+{x}+{y}")
            self.minsize(self.S(980), self.S(690))

        def set_theme(self, name: str) -> None:
            if name not in THEMES:
                return
            self.theme_name = name
            self.T = THEMES[name]
            self._apply_theme()
            self.after(150, lambda: set_titlebar_theme(self, self.theme_name == "dark"))
            self._save_prefs()

        def _apply_theme(self) -> None:
            t = self.T
            self.configure(bg=t["bg"])
            for frame in self._themed_frames:
                try:
                    frame.configure(bg=t["bg"])
                except tk.TclError:
                    pass
            for label, key in self._themed_labels:
                try:
                    label.configure(bg=t["bg"], fg=t[key])
                except tk.TclError:
                    pass
            for widget in getattr(self, "_surface_widgets", []):
                try:
                    widget.configure(bg=t["surface"])
                except tk.TclError:
                    pass
            for widget, key in getattr(self, "_banner_fg", []):
                try:
                    widget.configure(fg=t[key])
                except tk.TclError:
                    pass
            if hasattr(self, "install_banner"):
                self.install_banner.configure(highlightbackground=t["warn"])
            if getattr(self, "_logo_is_image", False):
                self._logo_photo = self._logo_dark if self.theme_name == "dark" else self._logo_light
                self.logo.configure(image=self._logo_photo, bg=t["bg"])
            else:
                self.logo.set_theme(t)
            self.theme_switch.set_theme(t, self.theme_name)
            self.version_pill.configure(bg=t["surface"], fg=t["secondary"], highlightbackground=t["border"])
            for btn in self._buttons:
                btn.set_theme(t, background=t["bg"])
            for card in self._card_refs:
                card.set_theme(t)
            self.progress.set_theme(t)

            self.log_card.configure(bg=t["surface"], highlightbackground=t["border"])
            self.text_wrap.configure(bg=t["surface"])
            self.log_header.configure(bg=t["surface"])
            self.log_title.configure(bg=t["surface"], fg=t["text"])
            self.log_link.configure(bg=t["surface"], fg=t["primary"])
            self.chip.configure(bg=t["surface"], fg=t["ok"] if not self._busy else t["warn"])
            self.log_text.configure(bg=t["logBg"], fg=t["text"], insertbackground=t["text"],
                                    selectbackground=t["primary"], selectforeground=t["onPrimary"])
            self._configure_log_tags()
            self.path_label.configure(bg=t["bg"], fg=t["text"])
            self.copy_link.configure(bg=t["bg"], fg=t["primary"])
            self.footer_right.configure(bg=t["bg"], fg=t["muted"])
            self.hint_label.configure(bg=t["bg"], fg=t["muted"])
            self._style_tree()
            self._fit_path()
            set_titlebar_theme(self, self.theme_name == "dark")
            if self.status is not None:
                self._apply_status(self.status)

        def _configure_log_tags(self) -> None:
            t = self.T
            self.log_text.tag_configure("time", foreground=t["muted"])
            self.log_text.tag_configure("INFO", foreground=t["text"])
            self.log_text.tag_configure("OK", foreground=t["ok"])
            self.log_text.tag_configure("WARN", foreground=t["warn"])
            self.log_text.tag_configure("ERROR", foreground=t["danger"])

        # -- 构建界面 ------------------------------------------------------ #
        def _label(self, parent, text, key="secondary", size=9, weight="normal",
                   font_key="ui", **kwargs):
            lbl = tk.Label(parent, text=text, bg=self.T["bg"], fg=self.T[key],
                           font=(self.fonts[font_key], size, weight), **kwargs)
            self._themed_labels.append((lbl, key))
            return lbl

        def _frame(self, parent, **kwargs):
            frame = tk.Frame(parent, bg=self.T["bg"], **kwargs)
            self._themed_frames.append(frame)
            return frame

        def _build_ui(self) -> None:
            t, S = self.T, self.S
            margin = S(28)
            self.grid_columnconfigure(0, weight=1)
            self.grid_rowconfigure(6, weight=1)

            # 顶部：品牌 + 主题切换
            header = self._frame(self)
            header.grid(row=0, column=0, sticky="ew", padx=margin, pady=(S(18), S(10)))
            if self._logo_photo is not None:
                self.logo = tk.Label(header, image=self._logo_photo, bg=t["bg"], bd=0, highlightthickness=0)
                self._logo_is_image = True
            else:
                self.logo = LogoMark(header, t, 42)
                self._logo_is_image = False
            self.logo.pack(side="left", padx=(0, S(12)))
            titles = self._frame(header)
            titles.pack(side="left", anchor="w")
            self._label(titles, "Compass 汉化工具", "text", 17, "bold").pack(anchor="w")
            self._label(titles, "MongoDB Compass · 简体中文语言包", "secondary", 9).pack(anchor="w", pady=(S(2), 0))

            right = self._frame(header)
            right.pack(side="right", anchor="e")
            self.version_pill = tk.Label(right, text=f"v{TOOL_VERSION}", bg=t["surface"], fg=t["secondary"],
                                         font=(self.fonts["mono"], 9), padx=S(10), pady=S(4),
                                         highlightbackground=t["border"], highlightthickness=1)
            self.version_pill.pack(side="right", padx=(S(10), 0))
            self.theme_switch = ThemeSwitch(right, self, t, self.fonts)
            self.theme_switch.pack(side="right")

            # 状态卡
            cards = self._frame(self)
            cards.grid(row=1, column=0, sticky="ew", padx=margin)
            for i in range(4):
                cards.grid_columnconfigure(i, weight=1, uniform="cards")
            self.card_version = StatusCard(cards, t, self.fonts, "Compass 版本")
            self.card_patch = StatusCard(cards, t, self.fonts, "汉化状态")
            self.card_backup = StatusCard(cards, t, self.fonts, "可用备份")
            self.card_mongo = StatusCard(cards, t, self.fonts, "MongoDB 数据库")
            self._card_refs = [self.card_version, self.card_patch, self.card_backup, self.card_mongo]
            for i, card in enumerate(self._card_refs):
                card.grid(row=0, column=i, sticky="nsew", padx=(0, S(12) if i < 3 else 0))

            # 未安装 Compass 时的引导条（默认隐藏）
            self.install_banner = tk.Frame(self, bg=t["surface"],
                                           highlightbackground=t["warn"], highlightthickness=1)
            self.install_banner.grid(row=2, column=0, sticky="ew", padx=margin, pady=(S(10), 0))
            self.install_banner.grid_columnconfigure(1, weight=1)
            self.banner_icon = tk.Label(self.install_banner, text="!", bg=t["surface"], fg=t["warn"],
                                        font=(self.fonts["ui"], 15, "bold"))
            self.banner_icon.grid(row=0, column=0, padx=(S(14), S(10)), pady=S(12))
            banner_text = tk.Frame(self.install_banner, bg=t["surface"])
            banner_text.grid(row=0, column=1, sticky="w", pady=S(10))
            self.banner_title = tk.Label(banner_text, text="未检测到 MongoDB Compass", bg=t["surface"], fg=t["text"],
                                         font=(self.fonts["ui"], 10, "bold"))
            self.banner_title.pack(anchor="w")
            self.banner_body = tk.Label(banner_text,
                                        text="本工具需要本机已安装官方 Compass 才能汉化。请先下载安装，完成后点击「刷新状态」。",
                                        bg=t["surface"], fg=t["secondary"], font=(self.fonts["ui"], 9),
                                        wraplength=S(610), justify="left")
            self.banner_body.pack(anchor="w", pady=(S(2), 0))
            banner_actions = tk.Frame(self.install_banner, bg=t["surface"])
            banner_actions.grid(row=0, column=2, sticky="e", padx=S(14))
            self.btn_compass_guide = LGButton(banner_actions, "安装指引", self.on_compass_guide,
                                              t, self.fonts, "secondary", height=34)
            self.btn_compass_guide.pack(side="left", padx=(0, S(6)))
            self.btn_compass_download = LGButton(banner_actions, "下载 Compass", self.on_compass_download,
                                                 t, self.fonts, "primary", height=34)
            self.btn_compass_download.pack(side="left")
            self.install_banner.grid_remove()
            self._surface_widgets = [self.install_banner, self.banner_icon, self.banner_title,
                                     self.banner_body, banner_text, banner_actions]
            self._banner_fg = [(self.banner_icon, "warn"), (self.banner_title, "text"),
                               (self.banner_body, "secondary")]

            # 安装路径
            path_row = self._frame(self)
            path_row.grid(row=3, column=0, sticky="ew", padx=margin, pady=(S(10), S(12)))
            self._label(path_row, "安装位置", "muted", 9).pack(side="left")
            self.path_label = tk.Label(path_row, text="检测中…", bg=t["bg"], fg=t["text"],
                                       font=(self.fonts["mono"], 9), anchor="w")
            self.path_label.pack(side="left", fill="x", expand=True, padx=(S(10), S(10)))
            self.path_label.bind("<Configure>", lambda _e: self._fit_path())
            self.copy_link = tk.Label(path_row, text="复制路径", bg=t["bg"], fg=t["primary"],
                                      font=(self.fonts["ui"], 9), cursor="hand2")
            self.copy_link.pack(side="right")
            self.copy_link.bind("<Button-1>", lambda _e: self._copy_path())

            # 操作按钮
            actions = self._frame(self)
            actions.grid(row=4, column=0, sticky="ew", padx=margin)
            self.btn_apply = LGButton(actions, "一键汉化", self.on_apply, t, self.fonts, "primary", height=42)
            self.btn_restore = LGButton(actions, "一键还原英文", self.on_restore, t, self.fonts, "danger", height=42)
            self.btn_check = LGButton(actions, "检查更新", self.on_check, t, self.fonts, "secondary", height=42)
            self.btn_backups = LGButton(actions, "备份与撤销", self.on_backups, t, self.fonts, "secondary", height=42)
            for btn in (self.btn_apply, self.btn_restore, self.btn_check, self.btn_backups):
                btn.pack(side="left", padx=(0, S(10)))
            self._buttons = [self.btn_apply, self.btn_restore, self.btn_check, self.btn_backups]
            self.btn_help = LGButton(actions, "使用说明", self.open_readme, t, self.fonts, "ghost", height=42)
            self.btn_help.pack(side="right")
            self.btn_refresh = LGButton(actions, "刷新状态", self.refresh_status, t, self.fonts, "ghost", height=42)
            self.btn_refresh.pack(side="right", padx=(0, S(6)))
            self.btn_mongo = LGButton(actions, "MongoDB 版本", self.on_mongodb_versions, t, self.fonts, "ghost", height=42)
            self.btn_mongo.pack(side="right", padx=(0, S(6)))
            self._buttons += [self.btn_mongo, self.btn_help, self.btn_refresh,
                              self.btn_compass_guide, self.btn_compass_download]

            # 进度线
            self.progress = ProgressLine(self, t)
            self.progress.grid(row=5, column=0, sticky="ew", padx=margin, pady=(S(10), 0))

            # 日志面板（占满剩余高度）
            self.log_card = tk.Frame(self, bg=t["surface"], highlightbackground=t["border"], highlightthickness=1)
            self.log_card.grid(row=6, column=0, sticky="nsew", padx=margin, pady=(S(6), S(8)))
            self.log_card.grid_columnconfigure(0, weight=1)
            self.log_card.grid_rowconfigure(1, weight=1)

            self.log_header = tk.Frame(self.log_card, bg=t["surface"])
            self.log_header.grid(row=0, column=0, sticky="ew", padx=S(14), pady=(S(10), S(4)))
            self.log_title = tk.Label(self.log_header, text="操作日志", bg=t["surface"], fg=t["text"],
                                      font=(self.fonts["ui"], 10, "bold"))
            self.log_title.pack(side="left")
            self.chip = tk.Label(self.log_header, text="● 就绪", bg=t["surface"], fg=t["ok"],
                                 font=(self.fonts["ui"], 9))
            self.chip.pack(side="left", padx=(S(10), 0))
            self.log_link = tk.Label(self.log_header, text="打开日志目录", bg=t["surface"], fg=t["primary"],
                                     font=(self.fonts["ui"], 9), cursor="hand2")
            self.log_link.pack(side="right")
            self.log_link.bind("<Button-1>", lambda _e: self.open_logs())

            text_wrap = tk.Frame(self.log_card, bg=t["surface"])
            self.text_wrap = text_wrap
            text_wrap.grid(row=1, column=0, sticky="nsew", padx=S(12), pady=(0, S(12)))
            text_wrap.grid_columnconfigure(0, weight=1)
            text_wrap.grid_rowconfigure(0, weight=1)
            self.log_text = tk.Text(text_wrap, bg=t["logBg"], fg=t["text"], bd=0, relief="flat",
                                    highlightthickness=0, wrap="word", width=1, height=6,
                                    font=(self.fonts["mono"], 10), padx=S(10), pady=S(8),
                                    spacing1=1, spacing3=2)
            self.log_text.grid(row=0, column=0, sticky="nsew")
            self.log_scroll = ttk.Scrollbar(text_wrap, orient="vertical", command=self.log_text.yview,
                                            style="LG.Vertical.TScrollbar")
            self.log_text.configure(yscrollcommand=self.log_scroll.set)
            self.log_scroll.grid(row=0, column=1, sticky="ns")

            # 底部
            footer = self._frame(self)
            footer.grid(row=6, column=0, sticky="ew", padx=margin, pady=(0, S(12)))
            self.hint_label = tk.Label(footer, text="提示：操作前请完全退出 Compass，所有修改都会自动备份。",
                                       bg=t["bg"], fg=t["muted"], font=(self.fonts["ui"], 9))
            self.hint_label.pack(side="left")
            self.footer_right = tk.Label(footer, text=f"数据目录 {DATA_DIR}",
                                         bg=t["bg"], fg=t["muted"], font=(self.fonts["mono"], 8))
            self.footer_right.pack(side="right")

        # -- 主题/尺寸持久化 ----------------------------------------------- #
        def _save_prefs(self) -> None:
            try:
                geo = self.geometry()
            except tk.TclError:
                geo = ""
            save_ui_prefs({"theme": self.theme_name, "geometry": geo})

        def _on_close(self) -> None:
            if self._busy:
                self._modal("warning", "操作正在进行",
                            "请等待当前任务完成后再退出，避免 app.asar 写入中断。")
                return
            self._save_prefs()
            self.destroy()

        # -- 日志 ---------------------------------------------------------- #
        def _enqueue_log(self, line: str, level: str) -> None:
            self._queue.put(("log", line, level))

        def _drain(self) -> None:
            try:
                while True:
                    item = self._queue.get_nowait()
                    if item[0] == "log":
                        _, line, level = item
                        self._append_log(line, level)
                    elif item[0] == "done":
                        self._finish()
                    elif item[0] == "error":
                        self._modal("error", "操作失败", item[1])
                    elif item[0] == "update_info":
                        self._apply_update_info(item[1], item[2], item[3])
                    elif item[0] == "dialog":
                        req = item[1]
                        try:
                            req["box"]["result"] = self._modal(req["kind"], req["title"], req["message"])
                        finally:
                            req["event"].set()
            except queue.Empty:
                pass
            self.after(120, self._drain)

        def _append_log(self, line: str, level: str) -> None:
            at_bottom = self.log_text.yview()[1] >= 0.999
            m = re.match(r"^\[([^\]]+)\]\s*\[([A-Z]+)\s*\]\s*(.*)$", line)
            if m:
                stamp, lvl, msg = m.group(1), m.group(2), m.group(3)
                self.log_text.insert("end", f"{stamp}  ", ("time",))
                self.log_text.insert("end", f"{lvl:<5}", (lvl if lvl in ("INFO", "OK", "WARN", "ERROR") else "INFO",))
                self.log_text.insert("end", f"  {msg}\n", (lvl if lvl in ("INFO", "OK", "WARN", "ERROR") else "INFO",))
            else:
                self.log_text.insert("end", line + "\n", (level if level in ("INFO", "OK", "WARN", "ERROR") else "INFO",))
            if at_bottom:
                self.log_text.see("end")

        def _startup_log(self) -> None:
            self.log(f"{TOOL_NAME} v{TOOL_VERSION} 已启动", "OK")
            st = self.status
            if st and st.install:
                self.log(f"检测到 Compass {st.install.version}：{st.install.app_dir}")
                self.log(f"当前状态：{'已汉化' if st.patched else '英文原版'}；可用备份 {len(st.backups)} 份")
            elif st:
                self.log(st.error or "未检测到 Compass 安装", "ERROR")
            self.log("提示：操作前请完全退出 Compass；修改前会自动备份原始 app.asar。")

        def log(self, msg: str, level: str = "INFO") -> None:
            LOG.log(msg, level)

        def _auto_check_update(self) -> None:
            install = self.status.install if self.status else None
            if install is None or self._busy:
                return

            def worker():
                try:
                    newer, latest = check_latest(install.version)
                    self._queue.put(("update_info", newer, latest or "", install.version))
                except Exception as exc:  # 网络失败不打扰用户
                    self._queue.put(("update_info", None, str(exc), install.version))

            threading.Thread(target=worker, daemon=True).start()

        def _apply_update_info(self, newer, latest: str, current: str) -> None:
            if self.status is None or self.status.install is None:
                return
            self._latest_state = (newer, latest)
            if newer is None:
                self.log(f"自动检查更新未完成：{latest}", "INFO")
            elif newer:
                self.log(f"发现新版本 {latest}（当前 {current}），建议更新。", "WARN")
            else:
                self.log(f"已是最新稳定版：{current}", "OK")
            self._apply_status(self.status)

        def _finish(self) -> None:
            self._busy = False
            self.progress.stop()
            self.chip.configure(text="● 就绪", fg=self.T["ok"])
            self.hint_label.configure(text="提示：操作前请完全退出 Compass，所有修改都会自动备份。")
            self.config(cursor="")
            self.refresh_status()

        def _sync_actions(self) -> None:
            ready = bool(self.status and self.status.install)
            for btn in (self.btn_apply, self.btn_restore, self.btn_check, self.btn_backups):
                btn.set_enabled(ready and not self._busy)
            self.btn_refresh.set_enabled(not self._busy)

        def _set_busy(self, hint: str) -> None:
            self._busy = True
            for btn in (self.btn_apply, self.btn_restore, self.btn_check, self.btn_backups, self.btn_refresh):
                btn.set_enabled(False)
            self.progress.start()
            self._sync_actions()
            self.chip.configure(text="● 执行中", fg=self.T["warn"])
            self.hint_label.configure(text=hint)
            self.config(cursor="watch")

        # -- 对话框 -------------------------------------------------------- #
        def _modal(self, kind: str, title: str, message: str,
                   confirm_text: Optional[str] = None) -> bool:
            if confirm_text is None:
                confirm_text = {"info": "知道了", "error": "关闭", "warning": "知道了"}.get(kind, "确认")
            return Modal(self, self.T, self.fonts, kind, title, message, confirm_text=confirm_text).show()

        def _sync_dialog(self, kind: str, title: str, message: str) -> bool:
            box: dict = {"result": False}
            event = threading.Event()
            self._queue.put(("dialog", {"kind": kind, "title": title, "message": message,
                                        "event": event, "box": box}))
            event.wait()
            return bool(box["result"])

        def _sync_confirm_close(self) -> bool:
            procs = compass_running()
            if not procs:
                return True
            ok = self._sync_dialog("askyesno", "Compass 正在运行",
                                   f"检测到 {len(procs)} 个 MongoDBCompass.exe 进程。\n\n"
                                   "升级/写入前需要完全退出 Compass。是否由本工具关闭？")
            if not ok:
                return False
            kill_compass()
            time.sleep(2)
            if compass_running():
                self._sync_dialog("warning", "无法关闭", "Compass 仍在运行，请手动退出后重试。")
                return False
            self.log("已关闭 Compass 进程。", "WARN")
            return True

        # -- 状态 ---------------------------------------------------------- #
        def refresh_status(self) -> None:
            if self._busy:
                return
            self.status = get_status(self.root_override)
            self._apply_status(self.status)

        def _apply_status(self, st: Status) -> None:
            t = self.T
            if st.install is None:
                self.card_version.set_values("未检测到", "请确认安装路径", t["danger"])
                self.card_patch.set_values("—", "无法读取安装信息")
                self.card_backup.set_values(f"{len(st.backups)} 份", "备份仍可手动回滚")
                self.install_banner.grid()
                self._full_path = str(st.root)
                self.chip.configure(text="● 未就绪", fg=t["danger"])
            else:
                kind = "Squirrel · asar" if st.install.asar else "未打包目录"
                sub, vcolor = kind, None
                if self._latest_state is not None:
                    newer, latest = self._latest_state
                    if newer is True and latest:
                        sub, vcolor = f"建议更新至 {latest}", t["warn"]
                    elif newer is False:
                        sub = f"{kind} · 已是最新"
                self.card_version.set_values(st.install.version, sub, vcolor)
                if st.patched:
                    self.card_patch.set_values("已汉化", f"语言包 v{st.patch_version or '?'}", t["ok"])
                else:
                    self.card_patch.set_values("英文原版", "可直接一键汉化", t["text"])
                self.card_backup.set_values(
                    f"{len(st.backups)} 份",
                    "可回滚至官方原版" if st.backups else "首次汉化会自动创建",
                )
                self.install_banner.grid_remove()
                self._full_path = str(st.install.app_dir)
                if not self._busy:
                    self.chip.configure(text="● 就绪", fg=t["ok"])
            if st.mongodb:
                self.card_mongo.set_values(st.mongodb.version, f"Server · {st.mongodb.source}", t["ok"])
            else:
                self.card_mongo.set_values("未安装", "可在「MongoDB 版本」下载", t["muted"])
            self._sync_actions()
            self._fit_path()

        def _fit_path(self) -> None:
            if not hasattr(self, "path_label"):
                return
            width = max(60, self.path_label.winfo_width())
            font = tkfont.Font(root=self, family=self.fonts["mono"], size=9)
            text = ellipsize(font, self._full_path or "—", width, middle=True)
            if self.path_label.cget("text") != text:
                self.path_label.configure(text=text)

        def _copy_path(self) -> None:
            if not self._full_path:
                return
            self.clipboard_clear()
            self.clipboard_append(self._full_path)
            self.copy_link.configure(text="已复制")
            self.after(1200, lambda: self.copy_link.configure(text="复制路径"))

        # -- 任务 ---------------------------------------------------------- #
        def _run(self, fn, hint: str) -> None:
            if self._busy:
                return
            self._set_busy(hint)

            def worker():
                try:
                    fn()
                except ToolError as exc:
                    self.log(str(exc), "ERROR")
                    self._queue.put(("error", str(exc)))
                except Exception as exc:  # noqa: BLE001
                    detail = traceback.format_exc()
                    self.log(f"未预期的错误：{exc}", "ERROR")
                    self.log(detail, "ERROR")
                    self._queue.put(("error", f"未预期的错误：{exc}"))
                finally:
                    self._queue.put(("done",))

            threading.Thread(target=worker, daemon=True).start()

        def _confirm_close(self) -> bool:
            procs = compass_running()
            if not procs:
                return True
            if not self._modal("askyesno", "Compass 正在运行",
                               f"检测到 {len(procs)} 个 MongoDBCompass.exe 进程。\n\n"
                               "修改 app.asar 前需要完全退出 Compass，否则新界面不会生效。\n"
                               "是否由本工具关闭 Compass？",
                               confirm_text="关闭 Compass"):
                return False
            kill_compass()
            time.sleep(2)
            if compass_running():
                self._modal("warning", "无法关闭", "Compass 仍在运行，请手动退出后重试。")
                return False
            self.log("已关闭 Compass 进程。", "WARN")
            return True

        def on_apply(self) -> None:
            if not self._confirm_close():
                return
            install = self.status.install if self.status else None
            if install is None:
                self._modal("error", "无法汉化", "未检测到有效的 Compass 安装。")
                return
            if self.status and self.status.patched:
                if not self._modal("askyesno", "已是汉化状态",
                                   "检测到当前已安装中文语言包，是否重新写入（覆盖更新）？",
                                   confirm_text="重新写入"):
                    return

            def task():
                self.log("=" * 56)
                self.log(f"开始汉化 Compass {install.version} …")
                apply_patch(install)
                self._sync_dialog("info", "汉化完成", "中文语言包已写入。\n\n请重新启动 Compass 查看效果。")

            self._run(task, "正在汉化，请稍候…")

        def on_restore(self) -> None:
            if not self._confirm_close():
                return
            install = self.status.install if self.status else None
            if install is None:
                self._modal("error", "无法还原", "未检测到有效的 Compass 安装。")
                return
            if self.status and not self.status.patched:
                if not self._modal("askyesno", "当前为英文",
                                   "当前未检测到汉化，是否仍用备份覆盖一次以恢复原版？",
                                   confirm_text="继续"):
                    return
            if not self._modal("askyesno", "确认还原",
                               "将使用原始备份覆盖 app.asar，恢复为英文界面。\n是否继续？",
                               confirm_text="还原"):
                return

            def task():
                self.log("=" * 56)
                self.log("开始还原英文原版 …")
                restore_english(install)
                self._sync_dialog("info", "还原完成", "已恢复为英文原版。\n\n请重新启动 Compass。")

            self._run(task, "正在还原，请稍候…")

        def on_check(self) -> None:
            install = self.status.install if self.status else None
            if install is None:
                self._modal("error", "无法检查", "未检测到有效的 Compass 安装。")
                return

            def task():
                self.log("=" * 56)
                newer, latest = check_latest(install.version)
                if newer and latest:
                    self.log(f"发现新版本：{install.version} → {latest}", "WARN")
                    if not self._sync_dialog("askyesno", "发现新版本",
                                             f"当前版本 {install.version}，最新稳定版 {latest}。\n\n"
                                             "是否立即调用官方更新程序升级？\n"
                                             "升级会下载约 180 MB 数据，期间 Compass 会自动关闭。"):
                        return
                    was_patched = self.status.patched if self.status else False
                    if not self._sync_confirm_close():
                        return
                    new_install = run_upgrade(install, latest)
                    if new_install and was_patched:
                        self.log("检测到升级前已汉化，正在为新版本重新注入语言包…")
                        apply_patch(new_install)
                        self._sync_dialog("info", "升级并汉化完成",
                                          f"已升级到 {new_install.version} 并重新汉化。")
                    elif new_install:
                        self._sync_dialog("info", "升级完成", f"已升级到 {new_install.version}。")
                else:
                    self.log(f"当前已是最新稳定版：{install.version}", "OK")
                    self._sync_dialog("info", "已是最新", f"当前版本 {install.version} 已是最新稳定版。")

            self._run(task, "正在检查更新…")

        def on_backups(self) -> None:
            BackupDialog(self)

        def open_logs(self) -> None:
            ensure_dirs()
            os.startfile(str(LOG_DIR))  # type: ignore[attr-defined]

        def on_compass_download(self) -> None:
            import webbrowser
            webbrowser.open(COMPASS_DOWNLOAD_PAGE)
            self.log("已打开 MongoDB Compass 官方下载页。", "INFO")

        def on_compass_guide(self) -> None:
            import webbrowser
            ok = self._modal(
                "askyesno", "安装 MongoDB Compass",
                "1. 点击「打开下载页」，选择 Windows x64 安装包；\n"
                "2. 下载后运行安装程序，按向导完成安装；\n"
                "3. 启动一次 Compass，确认能正常打开；\n"
                "4. 回到本工具，点击「刷新状态」重新检测。\n\n"
                "Compass 默认安装到 %LOCALAPPDATA%\\MongoDBCompass。",
                confirm_text="打开下载页",
            )
            if ok:
                webbrowser.open(COMPASS_DOWNLOAD_PAGE)

        def on_mongodb_versions(self) -> None:
            try:
                MongoVersionDialog(self)
            except ToolError as exc:
                self._modal("error", "无法读取版本信息", str(exc))

        def open_readme(self) -> None:
            path = resource_path("README.md")
            if path.exists():
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                self._modal("info", "使用说明", f"未找到说明文档：{path}")

    app = CompassApp()
    app.mainloop()
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def print_status(st: Status) -> None:
    print(f"{TOOL_NAME} v{TOOL_VERSION}")
    print("-" * 58)
    print(f"安装根目录 : {st.root}")
    if st.install:
        print(f"版本目录   : {st.install.app_dir}")
        print(f"Compass 版本: {st.install.version}")
        if st.mongodb:
            print(f"MongoDB 数据库: {st.mongodb.version}（{st.mongodb.source}）")
        else:
            print("MongoDB 数据库: 未检测到本机 Server")
        print(f"资源形式   : {st.install.kind}")
        print(f"汉化状态   : {'已汉化（语言包 v' + (st.patch_version or '?') + '）' if st.patched else '英文原版'}")
        print(f"进程状态   : {'运行中' if st.running else '未运行'}")
        print(f"可用备份   : {len(st.backups)} 份")
        for b in st.backups[:5]:
            print(f"   - {b.backup_id}  {b.human_time}  {human_size(b.size)}")
    else:
        print(f"错误       : {st.error}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=f"{TOOL_NAME} v{TOOL_VERSION}")
    parser.add_argument("--root", type=str, help="Compass 安装根目录（默认 %%LOCALAPPDATA%%\\MongoDBCompass）")
    parser.add_argument("--status", action="store_true", help="查看安装与汉化状态")
    parser.add_argument("--apply", action="store_true", help="一键汉化")
    parser.add_argument("--restore", action="store_true", help="一键还原英文")
    parser.add_argument("--restore-id", type=str, help="回滚到指定备份")
    parser.add_argument("--check-update", action="store_true", help="检查官方最新版本")
    parser.add_argument("--update", action="store_true", help="调用官方更新程序升级")
    parser.add_argument("--backups", action="store_true", help="列出所有备份")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认（用于脚本）")
    parser.add_argument("--kill", action="store_true", help="操作前自动关闭 Compass")
    parser.add_argument("--gui", action="store_true", help="强制打开图形界面")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser() if args.root else default_install_root()
    cli_mode = any([args.status, args.apply, args.restore, args.restore_id,
                    args.check_update, args.update, args.backups])
    if not cli_mode or args.gui:
        try:
            return run_gui()
        except Exception as exc:  # noqa: BLE001
            print(f"图形界面启动失败：{exc}", file=sys.stderr)
            print("可改用命令行：--status / --apply / --restore", file=sys.stderr)
            return 2

    LOG.add_sink(lambda line, level: print(line))

    if args.status:
        print_status(get_status(root))
        return 0

    if args.backups:
        for b in list_backups():
            print(f"{b.backup_id}  {b.human_time}  {b.version}  {human_size(b.size)}  {b.note}")
        return 0

    try:
        install = find_install(root)
    except ToolError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    if args.check_update:
        try:
            newer, latest = check_latest(install.version)
        except ToolError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1
        if newer:
            print(f"发现新版本：{install.version} → {latest}")
        else:
            print(f"当前已是最新稳定版：{install.version}")
        return 0

    if args.apply or args.restore or args.restore_id or args.update:
        if compass_running():
            if args.kill:
                kill_compass()
                time.sleep(2)
            else:
                print("错误：Compass 正在运行，请先完全退出（或加 --kill 自动关闭）。", file=sys.stderr)
                return 1

    if args.update:
        try:
            newer, latest = check_latest(install.version)
            if not newer or not latest:
                print(f"当前已是最新稳定版：{install.version}")
                return 0
            was = is_patched(install)[0]
            new_install = run_upgrade(install, latest)
            if new_install and was:
                apply_patch(new_install)
            return 0 if new_install else 1
        except ToolError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1

    if args.apply:
        if not args.yes:
            print(f"即将汉化 Compass {install.version}（{install.app_dir}），按 Enter 继续，Ctrl+C 取消…")
            try:
                input()
            except KeyboardInterrupt:
                print("已取消。")
                return 130
        try:
            apply_patch(install)
            return 0
        except ToolError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1

    if args.restore or args.restore_id:
        try:
            restore_english(install, backup_id=args.restore_id)
            return 0
        except ToolError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
