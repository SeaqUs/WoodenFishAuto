"""bot.py — 挂机机器人引擎（后台线程）。

功能：
1. 空闲检测 + 自动模拟键盘刷功德（GetLastInputInfo 判定真人空闲，
   SendInput 注入的模拟输入不会刷新空闲计时）。
2. 功德宝箱自动化：检测橙黄图标 -> 打开开箱页 -> 点红色「开箱」->
   等动画 -> 点「下一个宝箱」-> 点右上角「x」关闭。

所有自动化仅在用户空闲（idle >= 阈值）时执行，用户一动鼠标/键盘立即挂起。
"""
import random
import threading
import time

import win32

CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"


# ============================================================
# 颜色判定（实测校准）
# ============================================================


def is_warm(rgb):
    """橙黄色 —— 宝箱图标（RGB 约 (213,126,58)/(245,187,62)）。"""
    R, G, B = rgb
    return R > 150 and G > 80 and R > B + 40


def is_red(rgb):
    """红色 —— 开箱按钮/x 按钮/结果按钮（RGB 约 (231,91,67)）。"""
    R, G, B = rgb
    return R > 200 and G < 120 and B < 110 and (R - G) > 100


def _bbox_center(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2


def cluster_by_x(pts, gap=7):
    """按 x 坐标间隙把像素聚类，返回 [(中心, 像素数), ...]，自左向右。"""
    if not pts:
        return []
    xs = sorted(set(p[0] for p in pts))
    groups = []
    cur = [xs[0]]
    for i in range(1, len(xs)):
        if xs[i] - xs[i - 1] > gap:
            groups.append(cur)
            cur = [xs[i]]
        else:
            cur.append(xs[i])
    groups.append(cur)
    out = []
    for g in groups:
        gmin, gmax = min(g), max(g)
        sub = [p for p in pts if gmin <= p[0] <= gmax]
        out.append((_bbox_center(sub), len(sub)))
    return out


# ============================================================
# 窗口定位
# ============================================================


def find_game_window(cfg):
    gw = win32.find_window(title=cfg.get("game_title"))
    if gw is None:
        gw = win32.find_window(proc=cfg.get("game_process"))
    return gw


def find_box_window():
    """定位开箱页窗口：ElectronicWoodfish.exe 的可见窗口，尺寸约 190~320。"""
    for w in win32.enum_windows():
        if not w["visible"]:
            continue
        if win32.process_name(w["pid"]).lower() != "electronicwoodfish.exe":
            continue
        rect = win32.window_rect(w["hwnd"])
        ww = rect[2] - rect[0]
        hh = rect[3] - rect[1]
        if 190 <= ww <= 320 and 180 <= hh <= 320:
            return w, rect
    return None, None


# ============================================================
# 线程安全状态
# ============================================================


class BotState:
    def __init__(self):
        self._lock = threading.Lock()
        self.running = False
        self.status = "已停止"
        self.idle_seconds = 0.0
        self.keys_sent = 0
        self.boxes_opened = 0
        self.last_box_time = None
        self.next_box_countdown = None
        self.logs = []

    def set_status(self, s):
        with self._lock:
            self.status = s

    def log(self, msg):
        with self._lock:
            self.logs.append("[%s] %s" % (time.strftime("%H:%M:%S"), msg))
            self.logs = self.logs[-200:]

    def add_keys(self, n):
        with self._lock:
            self.keys_sent += n

    def mark_box(self):
        with self._lock:
            self.boxes_opened += 1
            self.last_box_time = time.time()

    def update_countdown(self):
        with self._lock:
            if self.last_box_time:
                self.next_box_countdown = max(
                    0.0, 30 * 60 - (time.time() - self.last_box_time)
                )

    def snapshot(self):
        with self._lock:
            return {
                "running": self.running,
                "status": self.status,
                "idle_seconds": self.idle_seconds,
                "keys_sent": self.keys_sent,
                "boxes_opened": self.boxes_opened,
                "next_box_countdown": self.next_box_countdown,
                "logs": list(self.logs),
            }


# ============================================================
# 机器人
# ============================================================


class Bot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = BotState()
        self.panel_hwnd = None
        self.box_busy = False
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.state.running = True
        self.state.set_status("运行中")
        self.state.log("机器人已启动")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.state.running = False
        self.state.set_status("已停止")
        self.state.log("机器人已停止")

    # ---------------- 主循环 ----------------
    def _run(self):
        last_box_check = 0.0
        while not self._stop.is_set():
            try:
                idle = win32.idle_seconds()
                self.state.idle_seconds = idle
                threshold = self.cfg.get("idle_threshold_seconds", 30)

                if idle >= threshold and not self.box_busy:
                    # 用户空闲，执行自动化
                    if self.cfg.get("farm_enabled"):
                        self._farm_burst()

                    now = time.time()
                    if (
                        self.cfg.get("box_enabled")
                        and now - last_box_check >= self.cfg.get("box_check_interval_seconds", 3)
                    ):
                        last_box_check = now
                        self._box_check()
                elif not self.box_busy:
                    self.state.set_status(
                        "用户活跃，挂起（空闲 %.0fs/%ds）" % (idle, threshold)
                    )

                self.state.update_countdown()
            except Exception as e:  # noqa: BLE001
                self.state.log("运行异常: %r" % (e,))
            time.sleep(0.2)

    # ---------------- 挂机刷功德 ----------------
    def _farm_burst(self):
        self.state.set_status("挂机刷功德中")
        if self.panel_hwnd:
            win32.set_foreground(self.panel_hwnd)
        n = int(self.cfg.get("keys_per_burst", 12))
        delay = float(self.cfg.get("type_delay_ms", 25)) / 1000.0
        sent = 0
        for _ in range(n):
            if self._stop.is_set():
                break
            if win32.idle_seconds() < self.cfg.get("idle_threshold_seconds", 30):
                break  # 用户回来了
            if win32.type_char(random.choice(CHARS)):
                sent += 1
            time.sleep(delay)
        if sent:
            self.state.add_keys(sent)

    # ---------------- 宝箱自动化 ----------------
    def _box_check(self):
        gw = find_game_window(self.cfg)
        if gw is None:
            return
        rect = win32.window_rect(gw["hwnd"])
        if rect is None:
            return
        l, t, r, b = rect
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            return
        # 用户空闲，先把游戏带到前台，确保能截到正确画面
        win32.set_foreground(gw["hwnd"])
        time.sleep(0.3)
        ww, hh, buf = win32.capture_region(l, t, w, h)
        pts = [
            (xx, yy)
            for yy in range(h)
            for xx in range(w)
            if is_warm(win32.pixel_at(buf, w, xx, yy))
        ]
        if len(pts) < self.cfg.get("icon_min_pixels", 20):
            return
        cx, cy = _bbox_center(pts)
        self.state.log("检测到功德宝箱图标 @(%d,%d)" % (l + cx, t + cy))
        self._open_box_flow(l + cx, t + cy)

    def _open_box_flow(self, ix, iy):
        self.box_busy = True
        try:
            self.state.set_status("开箱流程中")
            win32.click(ix, iy)
            time.sleep(2.0)

            box, rect = find_box_window()
            if box is None:
                self.state.log("点击图标后未找到开箱页窗口")
                return

            open_btn = self._red_bbox_in(rect, 0.6, self.cfg.get("red_min_pixels", 100))
            if open_btn is None:
                self.state.log("功德不足(<1000)，开箱按钮非红，关闭页面继续挂机")
                self._click_close(rect)
                return

            self.state.log("点击「开箱」")
            win32.click(rect[0] + open_btn[0], rect[1] + open_btn[1])
            time.sleep(float(self.cfg.get("box_wait_after_open_seconds", 6.0)))

            box2, rect2 = find_box_window()
            if box2 is None:
                self.state.log("开箱后未找到结果页窗口")
                return

            btns = self._red_clusters_in(rect2, 0.6)
            if len(btns) < 3:
                self.state.log("未检测到 3 个结果按钮（实际 %d 个）" % len(btns))
                return
            nb = btns[2][0]  # 第 3 个 = 「下一个宝箱」
            self.state.log("点击「下一个宝箱」，开启下个 30 分钟计时")
            win32.click(rect2[0] + nb[0], rect2[1] + nb[1])
            self.state.mark_box()
            time.sleep(2.0)
            self._click_close(rect2)
            self.state.log("开箱完成")
        finally:
            self.box_busy = False
            self.state.set_status("空闲")

    def _red_bbox_in(self, rect, y_frac, min_count=50):
        l, t, r, b = rect
        w, h = r - l, b - t
        y0 = int(h * y_frac)
        ww, hh, buf = win32.capture_region(l, t, w, h)
        pts = [
            (xx, yy)
            for yy in range(y0, h)
            for xx in range(w)
            if is_red(win32.pixel_at(buf, w, xx, yy))
        ]
        if len(pts) < min_count:
            return None
        return _bbox_center(pts)

    def _red_clusters_in(self, rect, y_frac):
        l, t, r, b = rect
        w, h = r - l, b - t
        y0 = int(h * y_frac)
        ww, hh, buf = win32.capture_region(l, t, w, h)
        pts = [
            (xx, yy)
            for yy in range(y0, h)
            for xx in range(w)
            if is_red(win32.pixel_at(buf, w, xx, yy))
        ]
        return cluster_by_x(pts)

    def _click_close(self, rect):
        l, t, r, b = rect
        w, h = r - l, b - t
        ww, hh, buf = win32.capture_region(l, t, w, h)
        pts = [
            (xx, yy)
            for yy in range(0, int(h * 0.35))
            for xx in range(int(w * 0.7), w)
            if is_red(win32.pixel_at(buf, w, xx, yy))
        ]
        if pts:
            cx, cy = _bbox_center(pts)
            win32.click(l + cx, t + cy)
            time.sleep(1.0)
        else:
            self.state.log("未找到右上角关闭按钮 x")
