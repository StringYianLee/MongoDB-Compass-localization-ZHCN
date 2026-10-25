"""从本机系统字体提取 Web 版所需的中文字体。

仓库不包含微软雅黑字体（版权归 Microsoft）。这份脚本只在本机运行，
把 C://Windows//Fonts//msyh.ttc 中名为 "Microsoft YaHei UI" 的子字体
导出为 assets/fonts/MicrosoftYaHeiUI.ttf，供 Flet Web（CanvasKit）使用。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "fonts" / "MicrosoftYaHeiUI.ttf"
SYSTEM_FONTS = [
    Path(r"C:/Windows/Fonts/msyh.ttc"),
    Path(r"C:/Windows/Fonts/msyh.ttf"),
    Path(r"C:/Windows/Fonts/simhei.ttf"),
]
TARGET_FAMILY = "Microsoft YaHei UI"


def main() -> int:
    try:
        from fontTools.ttLib import TTCollection
    except ImportError:
        print("[ERROR] 缺少 fontTools：pip install fonttools")
        return 1

    source = next((p for p in SYSTEM_FONTS if p.exists()), None)
    if source is None:
        print("[ERROR] 未找到系统字体（msyh.ttc / msyh.ttf / simhei.ttf）。")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".ttc":
        collection = TTCollection(str(source))
        chosen = None
        for font in collection.fonts:
            if font["name"].getDebugName(1) == TARGET_FAMILY:
                chosen = font
                break
        if chosen is None:
            chosen = collection.fonts[0]
        chosen.save(str(OUT))
    else:
        OUT.write_bytes(source.read_bytes())

    print(f"[OK] 已生成 {OUT.relative_to(ROOT)}（来源：{source}）")
    print("该字体仅用于本机 Web 版渲染，请勿提交到 Git 仓库。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
