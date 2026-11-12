#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preview.py — 把渲染好的 HTML 截成图，用于「所见即所得」确认排版

为什么要它:
    公众号排版最容易翻车的地方是「粘贴完才发现不对」。先在本地截图确认，
    比反复粘贴省事得多。

依赖: 本机 Chrome / Chromium / Edge 任一（自动查找），无需额外安装。

用法:
    python3 preview.py article.html -o preview.png
    python3 preview.py article.html -o preview.png --width 760 --height 4200
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
]


def find_chrome():
    for p in CHROME_CANDIDATES:
        if os.path.isfile(p):
            return p
    for name in ("google-chrome", "chromium", "chrome", "microsoft-edge"):
        p = shutil.which(name)
        if p:
            return p
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="把公众号 HTML 渲染成图片，用于排版确认",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("html", help="md2wx.py 生成的 HTML")
    ap.add_argument("-o", "--out", default="preview.png", help="输出 PNG")
    ap.add_argument("--width", type=int, default=760, help="视口宽度，默认 760（模拟手机阅读列宽）")
    ap.add_argument("--height", type=int, default=3200, help="视口高度，长文请调大，默认 3200")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.html):
        raise SystemExit("找不到 HTML: %s" % args.html)

    chrome = find_chrome()
    if not chrome:
        raise SystemExit(
            "未找到 Chrome/Chromium/Edge。请装一个，或手动打开 HTML 截图：\n  %s"
            % os.path.abspath(args.html)
        )

    html_path = "file://" + os.path.abspath(args.html)
    out_path = os.path.abspath(args.out)

    with tempfile.TemporaryDirectory(prefix="wx-preview-") as profile:
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            "--user-data-dir=" + profile,
            "--window-size=%d,%d" % (args.width, args.height),
            "--screenshot=" + out_path,
            html_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if not os.path.isfile(out_path):
            raise SystemExit(
                "截图失败：\n%s\n%s"
                % (proc.stdout[-800:], proc.stderr[-800:])
            )

    print("✓ %s (%dx%d @2x)" % (out_path, args.width, args.height))
    return 0


if __name__ == "__main__":
    sys.exit(main())
