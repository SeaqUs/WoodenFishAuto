"""main.py — 程序入口。"""
import os
import tkinter as tk

import config as config_mod
import gui
from bot import Bot


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(base, "config.json")
    cfg = config_mod.load(cfg_path)

    root = tk.Tk()
    bot = Bot(cfg)
    gui.App(root, cfg, cfg_path, bot)
    root.mainloop()


if __name__ == "__main__":
    main()
