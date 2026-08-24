"""main.py — 程序入口。"""
import os
import sys
import tkinter as tk

import config as config_mod
import gui
from bot import Bot


def _resource_path(rel):
    """返回打包资源的路径（兼容 PyInstaller 冻结环境）。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def main():
    # 冻结成 exe 后，config.json 放在 exe 同目录；源码运行时放在脚本目录
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(base, "config.json")
    cfg = config_mod.load(cfg_path)

    root = tk.Tk()
    # 设置窗口图标（标题栏 + 任务栏）
    icon_path = _resource_path("icon.ico")
    if os.path.exists(icon_path):
        try:
            root.iconbitmap(icon_path)
        except Exception:
            pass

    bot = Bot(cfg)
    gui.App(root, cfg, cfg_path, bot)
    root.mainloop()


if __name__ == "__main__":
    main()
