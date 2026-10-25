from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable, Optional

import flet as ft

import CompassZhCn as core


# --------------------------------------------------------------------------- #
# 设计令牌
# --------------------------------------------------------------------------- #

LIGHT = {
    "bg": "#F3F6F4", "surface": "#FFFFFF", "surface2": "#F1F5F3",
    "text": "#001E2B", "secondary": "#5C6C75", "muted": "#66757D",
    "primary": "#00684A", "onPrimary": "#FFFFFF", "accent": "#00ED64",
    "border": "#DDE4E1", "ok": "#00684A", "warn": "#B45C00", "danger": "#C0392B",
    "okSoft": "#E8F5EE", "warnSoft": "#FFF4E5", "dangerSoft": "#FDECEA",
    "primarySoft": "#E6F4EE", "logBg": "#FBFDFC", "mark": "compass-mark-64.png",
}
DARK = {
    "bg": "#00161F", "surface": "#0B1D29", "surface2": "#112733",
    "text": "#E8EDEB", "secondary": "#C1C7C6", "muted": "#889397",
    "primary": "#00ED64", "onPrimary": "#001E2B", "accent": "#00ED64",
    "border": "#243B49", "ok": "#00ED64", "warn": "#FFB74D", "danger": "#FF6960",
    "okSoft": "#0D3328", "warnSoft": "#3A2A12", "dangerSoft": "#3A1D1B",
    "primarySoft": "#0D3328", "logBg": "#081720", "mark": "compass-mark-dark-64.png",
}


def _ui_prefs_path() -> Path:
    return core.DATA_DIR / "ui.json"


def load_prefs() -> dict:
    try:
        return json.loads(_ui_prefs_path().read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def save_prefs(data: dict) -> None:
    try:
        core.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _ui_prefs_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def initial_theme() -> str:
    prefs = load_prefs()
    if prefs.get("theme") in ("light", "dark"):
        return prefs["theme"]
    try:
        path = Path(os.environ["APPDATA"]) / "MongoDB Compass" / "AppPreferences" / "General.json"
        pref = json.loads(path.read_text(encoding="utf-8")).get("theme", "LIGHT")
        return "dark" if str(pref).upper() == "DARK" else "light"
    except Exception:
        return "light"


def _fmt_time() -> str:
    return time.strftime("%H:%M:%S")


def _parse_log(line: str) -> tuple[str, str, str]:
    m = re.match(r"\[([^\]]+)\]\s+\[([A-Z]+)\]\s+(.*)", line)
    if m:
        return m.group(1)[-8:], m.group(2), m.group(3)
    return _fmt_time(), "INFO", line


# --------------------------------------------------------------------------- #
# 版本信息窗口
# --------------------------------------------------------------------------- #

class VersionDialog:
    def __init__(self, app: "FletCompassApp", tab_index: int = 0):
        self.app = app
        self.page = app.page
        self.palette = app.palette
        self.data = core.load_mongodb_versions()
        self.server = core.detect_mongodb_server()
        self.tab_index = tab_index
        self.dialog: Optional[ft.AlertDialog] = None
        self.choices: dict[str, str] = {}
        self.downloading = False
        self.cancel_flag = False
        self.closed = False
        self.queue: queue.Queue = queue.Queue()
        self.tabs: Optional[ft.Tabs] = None
        self.overview: Optional[ft.ListView] = None
        self.table_host: Optional[ft.Container] = None
        self.server_value: Optional[ft.Text] = None
        self.server_source: Optional[ft.Text] = None
        self.server_path: Optional[ft.Text] = None
        self.version_dd: Optional[ft.Dropdown] = None
        self.install_btn: Optional[ft.FilledButton] = None
        self.recheck_btn: Optional[ft.TextButton] = None
        self.progress: Optional[ft.ProgressBar] = None
        self.dl_status: Optional[ft.Text] = None
        self.open()

    # ------------------------------------------------------------------ #
    def open(self) -> None:
        p = self.palette
        self.overview = ft.ListView(expand=True, spacing=4, padding=ft.Padding.only(right=8))
        self.table_host = ft.Container(expand=True)
        content = ft.Container(
            width=720, height=520,
            content=ft.Column([
                ft.Text("MongoDB 版本信息", size=20, weight=ft.FontWeight.BOLD, color=p["text"]),
                ft.Text("官方稳定版与主流版本对比 · 数据来自 MongoDB 官方文档",
                        size=11, color=p["secondary"]),
                ft.Container(height=8),
                ft.Tabs(
                    selected_index=self.tab_index, length=3, expand=True,
                    content=ft.Column([
                        ft.TabBar(tabs=[
                            ft.Tab(label="更新亮点"),
                            ft.Tab(label="版本对比"),
                            ft.Tab(label="下载安装"),
                        ], divider_color=p["border"], label_color=p["primary"],
                            unselected_label_color=p["secondary"], indicator_color=p["primary"]),
                        ft.TabBarView(controls=[
                            self._tab_overview(),
                            self._tab_compare(),
                            self._tab_install(),
                        ], expand=True),
                    ], spacing=0, expand=True),
                ),
            ], spacing=4, expand=True),
        )
        self.dialog = ft.AlertDialog(
            modal=True, content=content,
            actions=[
                ft.TextButton(content=ft.Text("刷新数据", color=p["primary"]), on_click=self._refresh_data),
                ft.TextButton(content=ft.Text("关闭"), on_click=lambda _e: self.close()),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor=p["surface"],
        )
        self._render_all()
        self.page.show_dialog(self.dialog)

    def close(self) -> None:
        self.closed = True
        self.cancel_flag = True
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def _tab_overview(self) -> ft.Control:
        p = self.palette
        self.overview = ft.ListView(expand=True, spacing=4, padding=ft.Padding.only(right=8))
        return ft.Container(content=self.overview, padding=ft.Padding.only(top=12, right=6, bottom=6))

    def _tab_compare(self) -> ft.Control:
        self.table_host = ft.Container(expand=True)
        return ft.Container(content=self.table_host, padding=ft.Padding.only(top=12, right=6, bottom=6))

    def _tab_install(self) -> ft.Control:
        p = self.palette
        self.server_value = ft.Text("—", size=24, weight=ft.FontWeight.BOLD, color=p["text"])
        self.server_source = ft.Text("", size=11, color=p["secondary"])
        self.server_path = ft.Text("", size=10, color=p["muted"], font_family="Consolas",
                                   max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self.version_dd = ft.Dropdown(
            width=320, value=None,
            bgcolor=p["surface2"], border_color=p["border"], border_radius=8,
            text_size=12, text_style=ft.TextStyle(color=p["text"], size=12),
            on_select=self._sync_install_button,
        )
        self.install_btn = ft.FilledButton(
            content=ft.Text("下载并安装"), icon=ft.Icons.CLOUD_DOWNLOAD,
            on_click=self._start_download,
            style=ft.ButtonStyle(bgcolor=p["primary"], color=p["onPrimary"],
                                 shape=ft.RoundedRectangleBorder(radius=8),
                                 padding=ft.Padding.symmetric(horizontal=18, vertical=14)),
        )
        self.recheck_btn = ft.TextButton(
            content=ft.Text("重新检测"), icon=ft.Icons.REFRESH,
            on_click=self._recheck_server,
        )
        self.progress = ft.ProgressBar(value=0, visible=False, bar_height=6,
                                       color=p["primary"], bgcolor=p["surface2"])
        self.dl_status = ft.Text("", size=10, color=p["secondary"], max_lines=2)
        info = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Column([
                        ft.Text("本机 MongoDB Server", size=10, color=p["muted"]),
                        self.server_value,
                        self.server_source,
                        self.server_path,
                    ], spacing=2, expand=True),
                    self.recheck_btn,
                ], vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Divider(height=1, color=p["border"]),
                ft.Text("选择要安装的 MongoDB 版本", size=12, weight=ft.FontWeight.BOLD, color=p["text"]),
                ft.Row([self.version_dd, self.install_btn], spacing=12, wrap=True),
                self.progress,
                self.dl_status,
                ft.Container(
                    content=ft.Text(
                        "安装包来源：fastdl.mongodb.org（MongoDB 官方签名 MSI），下载后自动校验 SHA256。"
                        "安装程序会请求管理员权限，本工具只负责下载并启动官方安装程序，"
                        "不会修改系统服务、数据目录或现有数据库。升级前请备份数据并阅读官方升级说明。",
                        size=10, color=p["muted"], max_lines=4,
                    ),
                    padding=ft.Padding.all(12), bgcolor=p["surface2"], border_radius=8,
                ),
            ], spacing=10),
            padding=ft.Padding.only(top=12, right=6),
        )
        return ft.Container(content=info, expand=True)

    # ------------------------------------------------------------------ #
    def _render_all(self) -> None:
        if not self.data:
            return
        self._render_overview()
        self._render_table()
        self._render_install()

    def _render_overview(self) -> None:
        p = self.palette
        if self.overview is None:
            return
        self.overview.controls.clear()
        data = self.data
        cur = data.get("current", "")
        prev = data.get("previous", "")
        self.overview.controls.append(
            ft.Text(f"MongoDB {cur} · 当前稳定版", size=18, weight=ft.FontWeight.BOLD, color=p["text"])
        )
        meta = f"最新补丁 {data.get('latest_patch', '—')}"
        if data.get("latest_patch_date"):
            meta += f"（{data['latest_patch_date']}）"
        meta += f"    对比基线 {prev}"
        self.overview.controls.append(ft.Text(meta, size=11, color=p["secondary"]))
        self.overview.controls.append(ft.Container(height=4))
        self.overview.controls.append(
            ft.Text(f"相较 {prev} 的核心更新", size=13, weight=ft.FontWeight.BOLD, color=p["text"])
        )
        for item in data.get("latest_changes", []):
            self.overview.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text(item.get("title", ""), size=12, weight=ft.FontWeight.BOLD, color=p["text"]),
                        ft.Text(item.get("detail", ""), size=11, color=p["secondary"]),
                    ], spacing=2),
                    padding=ft.Padding.only(left=12, top=6, bottom=6),
                    border=ft.Border.only(left=ft.BorderSide(2, p["primary"])),
                )
            )
        self.overview.controls.append(ft.Text("升级建议", size=13, weight=ft.FontWeight.BOLD, color=p["text"]))
        self.overview.controls.append(ft.Text(data.get("upgrade_advice", ""), size=11, color=p["secondary"]))
        self.overview.controls.append(ft.Text("说明", size=13, weight=ft.FontWeight.BOLD, color=p["text"]))
        for note in data.get("notes", []):
            self.overview.controls.append(ft.Text("• " + note, size=10, color=p["muted"]))
        if data.get("refresh_note"):
            self.overview.controls.append(ft.Text(data["refresh_note"], size=10, color=p["warn"]))
        self.page.update()

    def _render_table(self) -> None:
        p = self.palette
        comp = self.data.get("comparison", {})
        columns = comp.get("columns", [])
        headers = [ft.DataColumn(ft.Text("维度", size=11, weight=ft.FontWeight.BOLD, color=p["secondary"]))]
        for c in columns:
            headers.append(ft.DataColumn(ft.Text(c["label"], size=11, weight=ft.FontWeight.BOLD, color=p["secondary"])))
        rows = []
        for row in comp.get("rows", []):
            cells = [ft.DataCell(ft.Container(
                content=ft.Text(row.get("feature", ""), size=10, weight=ft.FontWeight.BOLD, color=p["text"]),
                width=78,
            ))]
            for c in columns:
                cells.append(ft.DataCell(ft.Container(
                    content=ft.Text(row.get("values", {}).get(c["series"], ""), size=9.5, color=p["secondary"]),
                    width=146,
                )))
            rows.append(ft.DataRow(cells=cells))
        table = ft.DataTable(
            columns=headers, rows=rows,
            bgcolor=p["surface"], border=ft.Border.all(1, p["border"]),
            border_radius=8, heading_row_color=p["surface2"],
            heading_row_height=40, data_row_min_height=44, data_row_max_height=64,
            column_spacing=6, horizontal_margin=6,
            divider_thickness=1,
        )
        self.table_host.content = ft.Column(
            [ft.Row([table], scroll=ft.ScrollMode.AUTO,
                    vertical_alignment=ft.CrossAxisAlignment.START)],
            scroll=ft.ScrollMode.AUTO, expand=True,
        )
        self.page.update()

    def _render_install(self) -> None:
        p = self.palette
        if self.server_value is None:
            return
        srv = self.server
        if srv:
            self.server_value.value = srv.version
            self.server_value.color = p["ok"]
            self.server_source.value = f"来源：{srv.source}"
            self.server_path.value = f"mongod 路径：{srv.exe}"
        else:
            self.server_value.value = "未检测到"
            self.server_value.color = p["muted"]
            self.server_source.value = "可安装官方 MongoDB Community Server"
            self.server_path.value = "未在 PATH、Program Files\\MongoDB\\Server 或卸载注册表中找到 mongod。"
        self.choices = {}
        for index, item in enumerate(self.data.get("versions", [])):
            label = f"{item['latest']}（{'最新' if index == 0 else item['series'] + ' 系列'}）"
            self.choices[label] = item["latest"]
        self.version_dd.options = [ft.DropdownOption(key=label, text=label) for label in self.choices]
        if self.version_dd.value not in self.choices:
            self.version_dd.value = next(iter(self.choices), None)
        self._sync_install_button()
        self.page.update()

    def _sync_install_button(self, _e=None) -> None:
        if not self.version_dd or not self.install_btn:
            return
        version = self.choices.get(self.version_dd.value or "", "")
        if not version:
            return
        srv = self.server
        if srv and core.version_key(srv.version) < core.version_key(version):
            text = f"更新到 {version}"
        elif srv and core.version_key(srv.version) >= core.version_key(version):
            text = f"重新安装 {version}"
        else:
            text = f"下载并安装 {version}"
        self.install_btn.content.value = text
        self.page.update()

    # ------------------------------------------------------------------ #
    def _refresh_data(self, _e=None) -> None:
        if getattr(self, "_refreshing", False):
            return
        self._refreshing = True
        self.app.snack("正在从官方 Release Notes 刷新…", p=self.palette)
        q = queue.Queue()

        def worker():
            try:
                q.put(core.refresh_mongodb_versions())
            except Exception as exc:  # noqa: BLE001
                q.put(exc)

        threading.Thread(target=worker, daemon=True).start()

        async def poll():
            while True:
                if self.closed:
                    return
                try:
                    result = q.get_nowait()
                    break
                except queue.Empty:
                    await asyncio.sleep(0.15)
            self._refreshing = False
            if isinstance(result, Exception):
                self.app.snack(f"刷新失败：{result}", error=True)
                return
            self.data = result
            self._render_overview()
            self._render_table()
            self._render_install()
            self.app.snack(f"已刷新：{result.get('current')} · {result.get('latest_patch')}")

        self.page.run_task(poll)

    def _recheck_server(self, _e=None) -> None:
        self.server = core.detect_mongodb_server(force=True)
        self._render_install()
        self.app.refresh_status()
        self.app.snack(f"已检测到 MongoDB Server {self.server.version}" if self.server else "仍未检测到本机 MongoDB Server")

    # ------------------------------------------------------------------ #
    def _start_download(self, _e=None) -> None:
        if self.downloading:
            return
        version = self.choices.get(self.version_dd.value or "", "")
        if not version:
            return
        message = (
            f"将下载 MongoDB {version} Windows x64 官方 MSI 到：\n{core.MONGODB_DOWNLOAD_DIR}\n\n"
            "安装包体积较大（约 0.6–1.0 GB，具体以实际下载为准）。"
            "下载完成后可选择立即运行官方安装程序。是否继续？"
        )
        self.app.confirm("下载 MongoDB", message, lambda: self._begin_download(version), "开始下载")

    def _begin_download(self, version: str) -> None:
        p = self.palette
        self.downloading = True
        self.cancel_flag = False
        self.install_btn.disabled = True
        self.version_dd.disabled = True
        self.recheck_btn.disabled = True
        self.progress.visible = True
        self.progress.value = 0
        self.dl_status.value = "正在连接官方下载服务器…"
        self.page.update()
        q = self.queue = queue.Queue()

        def worker():
            try:
                path = core.download_server_msi(
                    version,
                    progress=lambda done, total: q.put(("progress", done, total)),
                    cancelled=lambda: self.cancel_flag,
                )
                q.put(("done", str(path)))
            except Exception as exc:  # noqa: BLE001
                q.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

        async def poll():
            while True:
                if self.closed:
                    return
                try:
                    event = q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.15)
                    continue
                kind = event[0]
                if kind == "progress":
                    done, total = event[1], event[2]
                    if total:
                        pct = min(100, int(done * 100 / total))
                        self.progress.value = pct / 100
                        self.dl_status.value = f"正在下载：{core.human_size(done)} / {core.human_size(total)}（{pct}%）"
                    else:
                        self.dl_status.value = f"正在下载：{core.human_size(done)}"
                    self.page.update()
                elif kind == "done":
                    self._download_done(event[1])
                    return
                else:
                    self._download_failed(event[1])
                    return

        self.page.run_task(poll)

    def _reset_download(self) -> None:
        self.downloading = False
        self.install_btn.disabled = False
        self.version_dd.disabled = False
        self.recheck_btn.disabled = False
        self.progress.visible = False
        self.page.update()

    def _download_done(self, path: str) -> None:
        self._reset_download()
        self.dl_status.value = f"下载完成：{path}"
        self.page.update()
        if self.app.confirm("下载完成", f"安装包已保存到：\n{path}\n\n是否立即运行官方安装程序？",
                            lambda: self._launch_installer(path), "运行安装程序"):
            pass

    def _launch_installer(self, path: str) -> None:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            self.dl_status.value = "安装程序已启动；完成后点击「重新检测」。"
        except Exception as exc:  # noqa: BLE001
            self.app.info("无法启动安装程序", f"请手动双击安装包：\n{path}\n\n{exc}")
        self.page.update()

    def _download_failed(self, error: str) -> None:
        self._reset_download()
        self.dl_status.value = "已取消下载" if "取消" in error else "下载失败"
        self.page.update()
        if "取消" not in error:
            self.app.info("下载失败", error + "\n\n可点击「官方下载页」手动下载。")


# --------------------------------------------------------------------------- #
# 主应用
# --------------------------------------------------------------------------- #

class FletCompassApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.is_web = bool(getattr(page, "web", False))
        self.prefs = load_prefs()
        self.dark = initial_theme() == "dark"
        self.palette = DARK if self.dark else LIGHT
        self.status: Optional[core.Status] = None
        self.busy = False
        self.logs: list[tuple[str, str, str]] = []
        self.queue: queue.Queue = queue.Queue()
        self._done_cb: Optional[Callable] = None
        self._task_name = ""
        self._latest_state = None
        self._root: Optional[ft.Column] = None
        self._log_list: Optional[ft.ListView] = None
        self._cards: dict[str, tuple[ft.Text, ft.Text]] = {}
        self._banner: Optional[ft.Container] = None
        self._path_text: Optional[ft.Text] = None
        self._chip: Optional[ft.Container] = None
        self._progress: Optional[ft.ProgressBar] = None
        self._action_buttons: list = []
        self._refresh_btn = None
        self._resize_seq = 0

        self._setup_page()
        core.LOG.add_sink(self._log_sink)
        self._root = ft.Column(expand=True, spacing=0,
                               horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        self.page.add(self._root)
        self.rebuild()
        self.page.run_task(self._poll_events)
        self.refresh_status()
        self.page.run_task(self._auto_check_update)

    # ------------------------------------------------------------------ #
    def _build_theme(self) -> ft.Theme:
        p = self.palette
        return ft.Theme(
            color_scheme=ft.ColorScheme(
                primary=p["primary"], on_primary=p["onPrimary"],
                surface=p["surface"], on_surface=p["text"],
                on_surface_variant=p["secondary"], outline=p["border"],
                error=p["danger"],
            ),
            font_family="Microsoft YaHei UI", use_material3=True,
            scaffold_bgcolor=p["bg"],
        )

    def _apply_page_theme(self) -> None:
        theme = self._build_theme()
        self.page.theme = theme
        self.page.dark_theme = theme

    def _setup_page(self) -> None:
        p = self.palette
        self.page.title = f"{core.TOOL_NAME} v{core.TOOL_VERSION}"
        self.page.padding = 0
        self.page.spacing = 0
        self.page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.page.bgcolor = p["bg"]
        self.page.theme_mode = ft.ThemeMode.DARK if self.dark else ft.ThemeMode.LIGHT
        self._apply_page_theme()
        if not self.is_web:
            self.page.window.width = max(1040, int(self.prefs.get("width", 1280)))
            self.page.window.height = max(720, int(self.prefs.get("height", 840)))
            self.page.window.min_width = 1000
            self.page.window.min_height = 700
        try:
            self.clipboard = ft.Clipboard()
            self.page.services.append(self.clipboard)
        except Exception:
            self.clipboard = None
        try:
            # CanvasKit/Web 渲染器不带系统字体，注册中文字体资源（桌面忽略）。
            self.page.fonts = {"Microsoft YaHei UI": "fonts/MicrosoftYaHeiUI.ttf"}
        except Exception:
            pass
        self.page.on_resize = self._on_resize
        if not self.is_web:
            try:
                self.page.window.icon = "compass.ico"
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    def rebuild(self) -> None:
        p = self.palette
        self.page.bgcolor = p["bg"]
        self.page.theme_mode = ft.ThemeMode.DARK if self.dark else ft.ThemeMode.LIGHT
        self._apply_page_theme()
        assert self._root is not None
        full_width, inner_width = self._layout_widths()
        self._root.controls.clear()
        self._root.width = full_width
        header = self._header()
        header.width = full_width
        self._root.controls.append(header)
        self._root.controls.append(
            ft.Container(
                expand=True, bgcolor=p["bg"], width=full_width,
                padding=ft.Padding.symmetric(
                    horizontal=16 if inner_width < 780 else 28, vertical=16),
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    width=inner_width,
                    controls=[
                        self._cards_row(inner_width),
                        self._install_banner(),
                        self._path_row(),
                        self._actions(inner_width),
                        self._status_row(),
                        self._log_panel(),
                        self._footer(),
                    ],
                    spacing=12, expand=True,
                ),
            )
        )
        self._apply_status()
        self.page.update()

    def _layout_widths(self) -> tuple[int, int]:
        def num(value) -> int:
            try:
                return int(value or 0)
            except Exception:
                return 0
        page_w = num(self.page.width)
        win_w = num(self.page.window.width)
        candidates = [v for v in (page_w, win_w) if v > 0]
        available = min(candidates) if candidates else 1280
        if self.is_web:
            # 浏览器：逻辑宽即 CSS 像素，宽屏铺满留白、窄屏自适应。
            full = max(340, min(1120, int(available) - 48))
            inner = full - (32 if full < 780 else 56)
            return full, inner
        # 桌面：Flet 的排版宽度会按 Windows 缩放比例放大；用 72% 预留 DPI 余量，
        # 使 100%–150% 缩放下都能完整显示并居中留白。
        full = max(700, min(1100, int(available * 0.66) - 60))
        inner = full - 56
        return full, inner

    def _on_resize(self, _e=None) -> None:
        self._resize_seq += 1
        seq = self._resize_seq

        async def later():
            await asyncio.sleep(0.25)
            if seq == self._resize_seq:
                self.rebuild()

        self.page.run_task(later)

    def _header(self) -> ft.Control:
        p = self.palette
        brand = ft.Row([
            ft.Image(src=p["mark"], width=42, height=42, fit=ft.BoxFit.CONTAIN),
            ft.Column([
                ft.Text(core.TOOL_NAME, size=18, weight=ft.FontWeight.BOLD, color=p["text"]),
                ft.Text("MongoDB Compass · 简体中文语言包 · MongoDB Server 工具",
                        size=10, color=p["secondary"]),
            ], spacing=1),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        refresh_btn = ft.IconButton(
            icon=ft.Icons.REFRESH, tooltip="刷新状态",
            icon_color=p["secondary"], on_click=lambda _e: self.refresh_status(),
        )
        self._refresh_btn = refresh_btn
        tools = ft.Row([
            ft.IconButton(icon=ft.Icons.DNS_OUTLINED, tooltip="MongoDB 版本",
                          icon_color=p["secondary"], on_click=self.open_versions),
            ft.IconButton(icon=ft.Icons.MENU_BOOK_OUTLINED, tooltip="使用说明",
                          icon_color=p["secondary"], on_click=self.open_readme),
            refresh_btn,
            ft.Container(
                content=ft.Text(f"v{core.TOOL_VERSION}", size=10, color=p["secondary"]),
                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                border=ft.Border.all(1, p["border"]), border_radius=20,
            ),
            ft.IconButton(
                icon=ft.Icons.LIGHT_MODE_OUTLINED if self.dark else ft.Icons.DARK_MODE_OUTLINED,
                tooltip="切换浅色/深色主题",
                icon_color=p["secondary"],
                on_click=self.toggle_theme,
            ),
        ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        return ft.Container(
            bgcolor=p["surface"],
            padding=ft.Padding.symmetric(horizontal=28, vertical=14),
            content=ft.Row([brand, tools], alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER,
                           wrap=True, run_spacing=8),
        )

    def _status_card(self, key: str, label: str, width: float) -> ft.Container:
        p = self.palette
        value = ft.Text("—", size=24, weight=ft.FontWeight.BOLD, color=p["text"],
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        sub = ft.Text("", size=10, color=p["secondary"], max_lines=2,
                      overflow=ft.TextOverflow.ELLIPSIS)
        self._cards[key] = (value, sub)
        inner = ft.Container(
            padding=ft.Padding.all(16),
            bgcolor=p["surface"],
            border=ft.Border.all(1, p["border"]),
            border_radius=12,
            content=ft.Column([
                ft.Text(label, size=10, color=p["muted"]),
                value, sub,
            ], spacing=2, tight=True),
        )
        return ft.Container(width=width, padding=ft.Padding.all(6), content=inner)

    def _cards_row(self, width: int) -> ft.Control:
        # 宽布局四卡一行；窄布局（Web 窄视口）由 wrap 自动降为 2/1 列。
        card_width = (width - 24) / 4 if width >= 640 else width - 24
        return ft.Row([
            self._status_card("version", "COMPASS 版本", card_width),
            self._status_card("patch", "汉化状态", card_width),
            self._status_card("backup", "可用备份", card_width),
            self._status_card("mongo", "MONGODB 数据库", card_width),
        ], spacing=8, width=width, wrap=True, run_spacing=8)

    def _install_banner(self) -> ft.Control:
        p = self.palette
        self._banner = ft.Container(
            visible=False,
            bgcolor=p["warnSoft"],
            border=ft.Border.all(1, p["warn"]),
            border_radius=10,
            padding=ft.Padding.symmetric(horizontal=16, vertical=12),
            content=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=p["warn"], size=22),
                ft.Column([
                    ft.Text("未检测到 MongoDB Compass", size=12, weight=ft.FontWeight.BOLD, color=p["text"]),
                    ft.Text("本工具需要本机已安装官方 Compass 才能汉化。请先下载安装，完成后点击「刷新状态」。",
                            size=10, color=p["secondary"]),
                ], spacing=2, expand=True),
                ft.TextButton(content=ft.Text("安装指引"), on_click=self.show_compass_guide),
                ft.FilledButton(
                    content=ft.Text("下载 Compass"), icon=ft.Icons.DOWNLOAD,
                    url=core.COMPASS_DOWNLOAD_PAGE,
                    style=ft.ButtonStyle(bgcolor=p["warn"], color="#FFFFFF",
                                         shape=ft.RoundedRectangleBorder(radius=8)),
                ),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
        )
        return self._banner

    def _path_row(self) -> ft.Control:
        p = self.palette
        self._path_text = ft.Text("检测中…", size=11, color=p["text"], font_family="Consolas",
                                  no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        return ft.Container(
            bgcolor=p["surface"], border=ft.Border.all(1, p["border"]), border_radius=10,
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            content=ft.Row([
                ft.Text("安装位置", size=10, color=p["muted"]),
                self._path_text,
                ft.TextButton(content=ft.Text("复制路径"), icon=ft.Icons.COPY,
                              on_click=self.copy_path),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def _button_style(self, kind: str, danger: bool = False) -> ft.ButtonStyle:
        p = self.palette
        radius = ft.RoundedRectangleBorder(radius=8)
        if kind == "primary":
            return ft.ButtonStyle(bgcolor=p["primary"], color=p["onPrimary"], shape=radius,
                                  padding=ft.Padding.symmetric(horizontal=18, vertical=14))
        if danger:
            return ft.ButtonStyle(bgcolor=p["surface"], color=p["danger"], shape=radius,
                                  side=ft.BorderSide(1, p["danger"]),
                                  padding=ft.Padding.symmetric(horizontal=16, vertical=14))
        return ft.ButtonStyle(bgcolor=p["surface"], color=p["text"], shape=radius,
                              side=ft.BorderSide(1, p["border"]),
                              padding=ft.Padding.symmetric(horizontal=16, vertical=14))

    def _actions(self, width: int) -> ft.Control:
        p = self.palette
        self._action_buttons = []
        apply_btn = ft.FilledButton(
            content=ft.Text("一键汉化"), icon=ft.Icons.PLAY_ARROW_ROUNDED,
            on_click=self.on_apply, style=self._button_style("primary"),
        )
        restore_btn = ft.OutlinedButton(
            content=ft.Text("一键还原英文"), icon=ft.Icons.RESTORE,
            on_click=self.on_restore, style=self._button_style("outline", danger=True),
        )
        check_btn = ft.OutlinedButton(
            content=ft.Text("检查更新"), icon=ft.Icons.SYSTEM_UPDATE_ALT,
            on_click=self.on_check_update, style=self._button_style("outline"),
        )
        backups_btn = ft.OutlinedButton(
            content=ft.Text("备份与撤销"), icon=ft.Icons.HISTORY,
            on_click=self.show_backups, style=self._button_style("outline"),
        )
        self._action_buttons = [apply_btn, restore_btn, check_btn, backups_btn]
        return ft.Row(self._action_buttons, spacing=8, wrap=True, width=width)

    def _status_row(self) -> ft.Control:
        p = self.palette
        self._ring = ft.ProgressRing(width=16, height=16, stroke_width=2.5,
                                     visible=False, color=p["primary"])
        self._chip = ft.Container(
            content=ft.Text("● 就绪", size=10, color=p["ok"]),
            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
            bgcolor=p["okSoft"], border_radius=12,
        )
        return ft.Row([self._ring, self._chip], alignment=ft.MainAxisAlignment.END, spacing=8)

    def _log_panel(self) -> ft.Control:
        p = self.palette
        try:
            win_h = int(self.page.height or self.page.window.height or 840)
        except Exception:
            win_h = 840
        # Flet 1.0 下 expand 嵌套滚动列渲染异常，这里按窗口高度精确计算日志高度，
        # 使内容恰好填满窗口（overhead 为其余区域的实测固定开销，含页脚）。
        overhead = 432 if self.is_web else 527
        log_h = max(150, min(480, win_h - overhead))
        self._log_list = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=2)
        for entry in self.logs[-400:]:
            self._log_list.controls.append(self._log_row(*entry))
        return ft.Container(
            height=log_h, bgcolor=p["surface"], border=ft.Border.all(1, p["border"]), border_radius=12,
            content=ft.Column([
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=14, vertical=8),
                    content=ft.Row([
                        ft.Text("操作日志", size=12, weight=ft.FontWeight.BOLD, color=p["text"]),
                        ft.Container(expand=True),
                        ft.TextButton(content=ft.Text("打开日志目录"), icon=ft.Icons.FOLDER_OPEN,
                                      on_click=lambda _e: self.open_logs()),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ),
                ft.Divider(height=1, color=p["border"]),
                ft.Container(
                    content=self._log_list,
                    padding=ft.Padding.only(left=12, right=8, top=6, bottom=8),
                ),
            ], spacing=0),
        )

    def _log_row(self, ts: str, level: str, message: str) -> ft.Control:
        p = self.palette
        colors = {"OK": (p["ok"], p["okSoft"]), "WARN": (p["warn"], p["warnSoft"]),
                  "ERROR": (p["danger"], p["dangerSoft"]), "INFO": (p["secondary"], p["surface2"])}
        fg, bg = colors.get(level, colors["INFO"])
        return ft.Row([
            ft.Text(ts, size=9, color=p["muted"], font_family="Consolas", width=70),
            ft.Container(content=ft.Text(level, size=8, color=fg, weight=ft.FontWeight.BOLD),
                         bgcolor=bg, border_radius=4, padding=ft.Padding.symmetric(horizontal=5, vertical=2)),
            ft.Text(message, size=10.5, color=p["text"], selectable=True, expand=True),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)

    def _footer(self) -> ft.Control:
        p = self.palette
        return ft.Row([
            ft.Text("提示：操作前请完全退出 Compass，所有修改都会自动备份。", size=9, color=p["muted"]),
            ft.Container(expand=True),
            ft.Text(f"数据目录 {core.DATA_DIR}", size=9, color=p["muted"]),
        ], wrap=True, run_spacing=4)

    # ------------------------------------------------------------------ #
    def _log_sink(self, line: str, level: str) -> None:
        self.queue.put(("log", line, level))

    async def _poll_events(self) -> None:
        while True:
            try:
                while True:
                    event = self.queue.get_nowait()
                    self._handle_event(event)
            except queue.Empty:
                pass
            await asyncio.sleep(0.12)

    def _handle_event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "log":
            ts, level, message = _parse_log(event[1])
            self.add_log(ts, level, message)
        elif kind == "done":
            _, name, result = event
            self._finish_task()
            if self._done_cb:
                cb, self._done_cb = self._done_cb, None
                cb(result)
        elif kind == "error":
            _, name, message = event
            self._finish_task()
            self._done_cb = None
            self.info("操作失败", message)
        elif kind == "auto_update":
            newer, latest, current = event[1], event[2], event[3]
            self._apply_update_info(newer, latest, current)

    def add_log(self, ts: str, level: str, message: str) -> None:
        self.logs.append((ts, level, message))
        if len(self.logs) > 400:
            self.logs = self.logs[-400:]
        if self._log_list is not None:
            self._log_list.controls.append(self._log_row(ts, level, message))
            while len(self._log_list.controls) > 400:
                self._log_list.controls.pop(0)
            self.page.update()

    def run_background(self, name: str, fn: Callable, on_done: Optional[Callable],
                       busy_text: str) -> None:
        if self.busy:
            return
        self.busy = True
        self._done_cb = on_done
        self._task_name = name
        self._set_busy_ui(True, busy_text)

        def worker():
            try:
                result = fn()
                self.queue.put(("done", name, result))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", name, str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _set_busy_ui(self, busy: bool, text: str = "") -> None:
        p = self.palette
        if self._ring:
            self._ring.visible = busy
        if self._chip:
            self._chip.content.value = "● 执行中" if busy else "● 就绪"
            self._chip.content.color = p["warn"] if busy else p["ok"]
            self._chip.bgcolor = p["warnSoft"] if busy else p["okSoft"]
        for btn in self._action_buttons:
            btn.disabled = busy
        if self._refresh_btn:
            self._refresh_btn.disabled = busy
        self.page.update()

    def _finish_task(self) -> None:
        self.busy = False
        self._set_busy_ui(False)
        self.refresh_status()

    # ------------------------------------------------------------------ #
    def refresh_status(self) -> None:
        if self.busy:
            return
        try:
            self.status = core.get_status(None)
        except Exception as exc:  # noqa: BLE001
            self.status = core.Status(core.default_install_root(), None, error=str(exc))
        self._apply_status()
        self.page.update()

    def _apply_status(self) -> None:
        if not self.status or "version" not in self._cards:
            return
        p = self.palette
        st = self.status
        version_val, version_sub = self._cards["version"]
        patch_val, patch_sub = self._cards["patch"]
        backup_val, backup_sub = self._cards["backup"]
        mongo_val, mongo_sub = self._cards["mongo"]
        if st.install is None:
            version_val.value = "未检测到"
            version_val.color = p["danger"]
            version_sub.value = "请先安装 MongoDB Compass"
            patch_val.value = "—"
            patch_sub.value = "无法读取安装信息"
            backup_val.value = f"{len(st.backups)} 份"
            backup_sub.value = "备份仍可手动回滚"
            if self._banner:
                self._banner.visible = True
            if self._path_text:
                self._path_text.value = str(st.root)
        else:
            version_val.value = st.install.version
            version_val.color = p["text"]
            sub = "Squirrel · asar" if st.install.asar else "未打包目录"
            if self._latest_state is not None:
                newer, latest = self._latest_state
                if newer is True and latest:
                    sub, version_val.color = f"建议更新至 {latest}", p["warn"]
                elif newer is False:
                    sub = f"{sub} · 已是最新"
            version_sub.value = sub
            patch_val.value = "已汉化" if st.patched else "英文原版"
            patch_val.color = p["ok"] if st.patched else p["text"]
            patch_sub.value = f"语言包 v{st.patch_version or '?'}" if st.patched else "可直接一键汉化"
            backup_val.value = f"{len(st.backups)} 份"
            backup_sub.value = "可回滚至官方原版" if st.backups else "首次汉化会自动创建"
            if self._banner:
                self._banner.visible = False
            if self._path_text:
                self._path_text.value = str(st.install.app_dir)
        if st.mongodb:
            mongo_val.value = st.mongodb.version
            mongo_val.color = p["ok"]
            mongo_sub.value = f"Server · {st.mongodb.source}"
        else:
            mongo_val.value = "未安装"
            mongo_val.color = p["muted"]
            mongo_sub.value = "可在「MongoDB 版本」下载"
        ready = st.install is not None and not self.busy
        for btn in self._action_buttons:
            btn.disabled = not ready
        if self._refresh_btn:
            self._refresh_btn.disabled = self.busy

    def _apply_update_info(self, newer, latest: str, current: str) -> None:
        self._latest_state = (newer, latest)
        if newer is None:
            self.add_log(_fmt_time(), "INFO", f"自动检查更新未完成：{latest}")
        elif newer:
            self.add_log(_fmt_time(), "WARN", f"发现新版本 {latest}（当前 {current}），建议更新。")
        else:
            self.add_log(_fmt_time(), "OK", f"已是最新稳定版：{current}")
        self._apply_status()
        self.page.update()

    async def _auto_check_update(self) -> None:
        await asyncio.sleep(1.5)
        st = self.status
        if not st or not st.install:
            return

        def worker():
            try:
                newer, latest = core.check_latest(st.install.version)
                self.queue.put(("auto_update", newer, latest or "", st.install.version))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("auto_update", None, str(exc), st.install.version))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ #
    def toggle_theme(self, _e=None) -> None:
        self.dark = not self.dark
        self.palette = DARK if self.dark else LIGHT
        if not self.is_web:
            self.page.window.bgcolor = self.palette["bg"]
        self.page.theme_mode = ft.ThemeMode.DARK if self.dark else ft.ThemeMode.LIGHT
        prefs = load_prefs()
        prefs["theme"] = "dark" if self.dark else "light"
        save_prefs(prefs)
        self.rebuild()

    def snack(self, message: str, error: bool = False, p=None) -> None:
        palette = p or self.palette
        self.page.show_dialog(ft.SnackBar(
            content=ft.Text(message, size=11, color="#FFFFFF"),
            bgcolor=palette["danger"] if error else palette["text"],
            duration=3200,
        ))

    def confirm(self, title: str, message: str, on_yes: Callable,
                confirm_text: str = "确认", danger: bool = False) -> bool:
        p = self.palette
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=p["text"]),
            content=ft.Container(width=470, content=ft.Text(message, size=12, color=p["secondary"])),
            actions=[
                ft.TextButton(content=ft.Text("取消"), on_click=lambda _e: self.page.pop_dialog()),
                ft.FilledButton(
                    content=ft.Text(confirm_text),
                    on_click=lambda _e: (self.page.pop_dialog(), on_yes()),
                    style=ft.ButtonStyle(
                        bgcolor=p["danger"] if danger else p["primary"],
                        color=p["onPrimary"] if not danger else "#FFFFFF",
                        shape=ft.RoundedRectangleBorder(radius=8),
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor=p["surface"],
        )
        self.page.show_dialog(dlg)
        return True

    def info(self, title: str, message: str) -> None:
        p = self.palette
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=p["text"]),
            content=ft.Container(width=460, content=ft.Text(message, size=12, color=p["secondary"])),
            actions=[ft.FilledButton(content=ft.Text("知道了"), on_click=lambda _e: self.page.pop_dialog())],
            bgcolor=p["surface"],
        )
        self.page.show_dialog(dlg)

    # ------------------------------------------------------------------ #
    def copy_path(self, _e=None) -> None:
        path = self.status.install.app_dir if self.status and self.status.install else (
            str(self.status.root) if self.status else "")
        if not path:
            return
        try:
            if self.clipboard is None:
                raise RuntimeError("clipboard service unavailable")
            self.clipboard.set(str(path))
            self.snack("安装路径已复制到剪贴板")
        except Exception:
            self.snack("复制失败，请手动选择路径", error=True)

    def open_logs(self) -> None:
        try:
            core.ensure_dirs()
            os.startfile(str(core.LOG_DIR))
        except Exception as exc:  # noqa: BLE001
            self.snack(f"无法打开日志目录：{exc}", error=True)

    def open_readme(self, _e=None) -> None:
        path = core.resource_path("README.md")
        try:
            os.startfile(str(path))
        except Exception as exc:  # noqa: BLE001
            self.snack(f"无法打开说明文档：{exc}", error=True)

    def show_compass_guide(self, _e=None) -> None:
        p = self.palette
        text = (
            "1. 点击「打开下载页」，选择 Windows x64 安装包；\n"
            "2. 下载后运行安装程序，按向导完成安装；\n"
            "3. 启动一次 Compass，确认能正常打开；\n"
            "4. 回到本工具，点击「刷新状态」重新检测。\n\n"
            "Compass 默认安装到 %LOCALAPPDATA%\\MongoDBCompass。"
        )
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("安装 MongoDB Compass", size=16, weight=ft.FontWeight.BOLD, color=p["text"]),
            content=ft.Container(width=500, content=ft.Text(text, size=12, color=p["secondary"])),
            actions=[
                ft.TextButton(content=ft.Text("关闭"), on_click=lambda _e: self.page.pop_dialog()),
                ft.FilledButton(content=ft.Text("打开下载页"), icon=ft.Icons.OPEN_IN_NEW,
                                url=core.COMPASS_DOWNLOAD_PAGE,
                                on_click=lambda _e: self.page.pop_dialog()),
            ],
            bgcolor=p["surface"],
        )
        self.page.show_dialog(dlg)

    # ------------------------------------------------------------------ #
    def on_apply(self, _e=None) -> None:
        if not self.status or not self.status.install:
            return
        if core.compass_running():
            self.confirm("Compass 正在运行", "汉化前需要完全退出 Compass，是否由本工具关闭？",
                         lambda: self._do_apply(True))
        else:
            self._do_apply(False)

    def _do_apply(self, close_first: bool) -> None:
        install = self.status.install

        def task():
            if close_first:
                core.kill_compass()
                time.sleep(1.5)
            core.apply_patch(install)
            return True

        self.run_background("apply", task, lambda _r: self._after_patch("汉化完成"), "正在汉化…")

    def on_restore(self, _e=None) -> None:
        if not self.status or not self.status.install:
            return
        if core.compass_running():
            self.confirm("Compass 正在运行", "还原前需要完全退出 Compass，是否由本工具关闭？",
                         lambda: self._do_restore(True))
        else:
            self._do_restore(False)

    def _do_restore(self, close_first: bool) -> None:
        install = self.status.install

        def task():
            if close_first:
                core.kill_compass()
                time.sleep(1.5)
            core.restore_english(install)
            return True

        self.run_background("restore", task, lambda _r: self._after_patch("已还原英文"), "正在还原…")

    def _after_patch(self, message: str) -> None:
        self.refresh_status()
        self.snack(message)

    def on_check_update(self, _e=None) -> None:
        if not self.status or not self.status.install:
            return
        current = self.status.install.version
        self.run_background("check", lambda: core.check_latest(current), self._after_check, "正在检查更新…")

    def _after_check(self, result) -> None:
        newer, latest = result
        if not newer or not latest:
            self.snack(f"已是最新稳定版：{self.status.install.version if self.status.install else ''}")
            return
        self.confirm("发现新版本", f"Compass {latest} 已发布，当前版本 {self.status.install.version}。\n是否立即升级？",
                     lambda: self._do_upgrade(latest), "升级")

    def _do_upgrade(self, latest: str) -> None:
        install = self.status.install

        def task():
            if core.compass_running():
                core.kill_compass()
                time.sleep(1.5)
            return core.run_upgrade(install, latest)

        self.run_background("upgrade", task, lambda _r: self._after_upgrade(), f"正在升级到 {latest}…")

    def _after_upgrade(self) -> None:
        self.refresh_status()
        self.snack("升级流程已结束，请查看日志确认结果")

    # ------------------------------------------------------------------ #
    def show_backups(self, _e=None) -> None:
        p = self.palette
        backups = core.list_backups()
        install = self.status.install if self.status else None
        if install:
            backups = [b for b in backups if b.app_dir.resolve() == install.app_dir.resolve()]
        rows = []
        for backup in backups:
            rows.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                border=ft.Border.only(bottom=ft.BorderSide(1, p["border"])),
                content=ft.Row([
                    ft.Text(backup.human_time, size=10, color=p["secondary"], width=140),
                    ft.Text(backup.version, size=10, color=p["text"], width=90),
                    ft.Text(core.human_size(backup.size), size=10, color=p["secondary"], width=80),
                    ft.Text(backup.backup_id, size=9, color=p["muted"], expand=True),
                    ft.TextButton(content=ft.Text("回滚"),
                                  on_click=lambda _e, b=backup: self._confirm_rollback(b)),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))
        body = ft.Container(
            width=780, height=380,
            content=ft.Column([
                ft.Text("备份列表", size=13, weight=ft.FontWeight.BOLD, color=p["text"]),
                ft.Text("回滚会使用选中的备份覆盖 app.asar，并自动校验 SHA256。", size=10, color=p["secondary"]),
                ft.Divider(height=1, color=p["border"]),
                ft.ListView(rows if rows else [ft.Text("暂无备份", size=11, color=p["muted"])],
                            expand=True, spacing=0),
            ], spacing=8, expand=True),
        )
        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("备份与撤销", size=16, weight=ft.FontWeight.BOLD, color=p["text"]),
            content=body,
            actions=[ft.TextButton(content=ft.Text("关闭"), on_click=lambda _e: self.page.pop_dialog())],
            bgcolor=p["surface"],
        )
        self.page.show_dialog(dlg)

    def _confirm_rollback(self, backup: core.Backup) -> None:
        self.page.pop_dialog()
        self.confirm("回滚备份", f"将回滚到 {backup.human_time} 的备份（{backup.backup_id}）。\n是否继续？",
                     lambda: self._do_rollback(backup), "回滚", danger=True)

    def _do_rollback(self, backup: core.Backup) -> None:
        install = self.status.install

        def task():
            if core.compass_running():
                core.kill_compass()
                time.sleep(1.5)
            core.restore_english(install, backup.backup_id)
            return True

        self.run_background("rollback", task, lambda _r: self._after_patch("已回滚到所选备份"), "正在回滚…")

    def open_versions(self, _e=None) -> None:
        try:
            VersionDialog(self)
        except Exception as exc:  # noqa: BLE001
            self.info("无法打开版本信息", str(exc))


def main(page: ft.Page) -> None:
    FletCompassApp(page)


if __name__ == "__main__":
    ft.run(main, assets_dir=str(core.ASSETS_DIR))
