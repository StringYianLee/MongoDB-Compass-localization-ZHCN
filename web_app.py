from __future__ import annotations

import os

import flet as ft

import CompassZhCn as core
from flet_app import main


def run() -> None:
    port = int(os.environ.get("FLET_WEB_PORT", "8560"))
    ft.run(
        main,
        view=ft.AppView.WEB_BROWSER,
        assets_dir=str(core.ASSETS_DIR),
        port=port,
        no_cdn=True,
    )


if __name__ == "__main__":
    run()
