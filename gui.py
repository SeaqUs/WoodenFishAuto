"""gui.py — 简洁操作面板（tkinter）。"""
import tkinter as tk
from tkinter import ttk, scrolledtext

import config as config_mod


class App:
    def __init__(self, root, cfg, cfg_path, bot):
        self.root = root
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.bot = bot
        root.title("电子木鱼自动挂机")
        root.geometry("420x560")
        root.resizable(False, False)
        self._build()
        self._refresh()

    def _build(self):
        # 状态区
        status = ttk.LabelFrame(self.root, text="状态", padding=10)
        status.pack(fill="x", padx=10, pady=(10, 4))
        self.var_status = tk.StringVar(value="已停止")
        self.var_idle = tk.StringVar(value="空闲: -")
        self.var_clicks = tk.StringVar(value="已点击木鱼: 0")
        self.var_boxes = tk.StringVar(value="已开宝箱: 0")
        self.var_countdown = tk.StringVar(value="距下个宝箱: 待定")
        ttk.Label(status, textvariable=self.var_status, font=("", 12, "bold")).pack(anchor="w")
        ttk.Label(status, textvariable=self.var_idle).pack(anchor="w", pady=(4, 0))
        ttk.Label(status, textvariable=self.var_clicks).pack(anchor="w")
        ttk.Label(status, textvariable=self.var_boxes).pack(anchor="w")
        ttk.Label(status, textvariable=self.var_countdown).pack(anchor="w")

        # 控制区
        ctrl = ttk.LabelFrame(self.root, text="控制", padding=10)
        ctrl.pack(fill="x", padx=10, pady=4)
        self.btn_start = ttk.Button(ctrl, text="启动", command=self._toggle)
        self.btn_start.pack(fill="x")
        self.var_farm = tk.BooleanVar(value=bool(self.cfg.get("farm_enabled")))
        self.var_box = tk.BooleanVar(value=bool(self.cfg.get("box_enabled")))
        ttk.Checkbutton(ctrl, text="挂机刷功德", variable=self.var_farm, command=self._save_cfg).pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(ctrl, text="功德宝箱自动化", variable=self.var_box, command=self._save_cfg).pack(anchor="w")

        # 参数区
        param = ttk.LabelFrame(self.root, text="参数", padding=10)
        param.pack(fill="x", padx=10, pady=4)
        row1 = ttk.Frame(param)
        row1.pack(fill="x")
        ttk.Label(row1, text="空闲阈值(秒):").pack(side="left")
        self.var_idle_th = tk.IntVar(value=int(self.cfg.get("idle_threshold_seconds", 30)))
        ttk.Spinbox(row1, from_=5, to=600, textvariable=self.var_idle_th, width=8).pack(side="left", padx=6)
        row2 = ttk.Frame(param)
        row2.pack(fill="x", pady=(4, 0))
        ttk.Label(row2, text="点击间隔(毫秒):").pack(side="left")
        self.var_delay = tk.IntVar(value=int(self.cfg.get("click_interval_ms", 60)))
        ttk.Spinbox(row2, from_=10, to=1000, textvariable=self.var_delay, width=8).pack(side="left", padx=6)

        # 变量变化即保存
        self.var_idle_th.trace_add("write", lambda *_: self._save_cfg())
        self.var_delay.trace_add("write", lambda *_: self._save_cfg())

        # 日志区
        log = ttk.LabelFrame(self.root, text="日志", padding=6)
        log.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.txt_log = scrolledtext.ScrolledText(log, height=14, state="disabled", font=("Consolas", 9))
        self.txt_log.pack(fill="both", expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _toggle(self):
        if self.bot.state.running:
            self.bot.stop()
            self.btn_start.config(text="启动")
        else:
            self.bot.start()
            self.btn_start.config(text="停止")

    def _save_cfg(self):
        try:
            self.cfg["farm_enabled"] = bool(self.var_farm.get())
            self.cfg["box_enabled"] = bool(self.var_box.get())
            self.cfg["idle_threshold_seconds"] = int(self.var_idle_th.get())
            self.cfg["click_interval_ms"] = int(self.var_delay.get())
            config_mod.save(self.cfg_path, self.cfg)
        except Exception:
            pass

    def _refresh(self):
        snap = self.bot.state.snapshot()
        self.var_status.set("状态: " + snap["status"])
        self.var_idle.set("空闲: %.1f 秒" % snap["idle_seconds"])
        self.var_clicks.set("已点击木鱼: %d" % snap["clicks_sent"])
        self.var_boxes.set("已开宝箱: %d" % snap["boxes_opened"])
        cd = snap["next_box_countdown"]
        if cd is not None:
            self.var_countdown.set("距下个宝箱: %02d:%02d" % (int(cd // 60), int(cd % 60)))
        else:
            self.var_countdown.set("距下个宝箱: 待定（开箱后开始计时）")

        logs = snap["logs"]
        if logs:
            self.txt_log.config(state="normal")
            self.txt_log.delete("1.0", "end")
            self.txt_log.insert("end", "\n".join(logs[-14:]))
            self.txt_log.config(state="disabled")
        self.root.after(300, self._refresh)

    def _on_close(self):
        self._save_cfg()
        self.bot.stop()
        self.root.destroy()
