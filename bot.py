"""bot.py — 挂机机器人引擎（后台线程）。

功能：
1. 空闲检测（InputMonitor 低层钩子，只统计真实物理输入）+
   自动刷功德（支持"点击木鱼"与"键盘输入(note.ms)"两种方式切换）。
2. 功德宝箱自动化：检测橙黄图标 -> 打开开箱页 -> 点红色「开箱」->
   等动画 -> 点「下一个宝箱」-> 点右上角「x」关闭。

所有自动化仅在用户空闲（idle >= 阈值）时执行；程序自己的点击/按键
不会被误判为"用户活跃"，用户一动鼠标/键盘立即挂起。
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


def _lum(rgb):
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


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
        self.actions_sent = 0
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

    def add_actions(self, n):
        with self._lock:
            self.actions_sent += n

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
                "actions_sent": self.actions_sent,
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
        self.monitor = win32.InputMonitor()
        self.box_busy = False
        self._stop = threading.Event()
        self._thread = None
        self._fish_cache_key = None
        self._fish_center = None
        self._notems_opened = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.monitor.start()
        self.state.running = True
        self.state.set_status("运行中")
        method = self.cfg.get("farm_method", "click")
        self.state.log("机器人已启动（%s刷功德）" % ("点击木鱼" if method != "keyboard" else "键盘输入note.ms"))
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.monitor.stop()
        self.state.running = False
        self.state.set_status("已停止")
        self.state.log("机器人已停止")

    # ---------------- 主循环 ----------------
    def _run(self):
        last_box_check = 0.0
        while not self._stop.is_set():
            try:
                idle = self.monitor.idle_seconds()
                self.state.idle_seconds = idle
                threshold = self.cfg.get("idle_threshold_seconds", 30)

                if idle >= threshold and not self.box_busy:
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

    # ---------------- 刷功德（点击木鱼 / 键盘输入 note.ms） ----------------
    def _farm_burst(self):
        method = self.cfg.get("farm_method", "click")
        if method == "keyboard":
            self._keyboard_burst()
        else:
            self._click_burst()

    def _click_burst(self):
        gw = find_game_window(self.cfg)
        if gw is None:
            return
        rect = win32.window_rect(gw["hwnd"])
        if rect is None:
            return
        self.state.set_status("点击木鱼刷功德中")
        # 用户空闲，把游戏带到前台确保点击命中
        win32.set_foreground(gw["hwnd"])
        cx, cy = self._get_fish_center(rect)
        if cx is None:
            return
        n = int(self.cfg.get("clicks_per_burst", 15))
        interval = float(self.cfg.get("click_interval_ms", 60)) / 1000.0
        sent = 0
        for _ in range(n):
            if self._stop.is_set():
                break
            if self.monitor.idle_seconds() < self.cfg.get("idle_threshold_seconds", 30):
                break  # 用户回来了
            # 轻微随机抖动，避免每次点同一像素
            jx = random.randint(-3, 3)
            jy = random.randint(-3, 3)
            win32.click(rect[0] + cx + jx, rect[1] + cy + jy, settle=0.0)
            sent += 1
            time.sleep(interval)
        if sent:
            self.state.add_actions(sent)

    def _keyboard_burst(self):
        self.state.set_status("键盘输入刷功德中(note.ms)")
        self._ensure_notems()
        n = int(self.cfg.get("clicks_per_burst", 15))
        interval = float(self.cfg.get("click_interval_ms", 60)) / 1000.0
        sent = 0
        for _ in range(n):
            if self._stop.is_set():
                break
            if self.monitor.idle_seconds() < self.cfg.get("idle_threshold_seconds", 30):
                break  # 用户回来了
            if win32.type_char(random.choice(CHARS), hold_ms=40):
                sent += 1
            time.sleep(interval)
        if sent:
            self.state.add_actions(sent)

    def _ensure_notems(self):
        """首次调用时打开 note.ms 页面并等待其加载聚焦。"""
        if self._notems_opened:
            return
        url = self.cfg.get("notems_url", "https://note.ms/muyu")
        ok = win32.open_url(url)
        self._notems_opened = True
        if ok:
            self.state.log("已打开 note.ms: %s" % url)
        else:
            self.state.log("打开 note.ms 失败: %s" % url)
        time.sleep(3.0)  # 等浏览器加载并聚焦文本区

    def _get_fish_center(self, rect):
        """返回木鱼中心（相对窗口）。优先用配置值，否则动态检测。"""
        rel = self.cfg.get("fish_center_rel")
        if rel and len(rel) == 2:
            return int(rel[0]), int(rel[1])
        # 动态检测回退：中段深色像素中心
        if self._fish_cache_key == rect and self._fish_center:
            return self._fish_center
        l, t, r, b = rect
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            return None
        ww, hh, buf = win32.capture_region(l, t, w, h)
        y0, y1 = int(h * 0.45), int(h * 0.80)
        pts = []
        for yy in range(y0, y1):
            for xx in range(w):
                i = (yy * w + xx) * 4
                rgb = (buf[i + 2], buf[i + 1], buf[i])
                if _lum(rgb) < 80:
                    pts.append((xx, yy))
        if len(pts) < 100:
            cx, cy = w // 2, int(h * 0.66)
        else:
            cx, cy = _bbox_center(pts)
        self._fish_cache_key = rect
        self._fish_center = (cx, cy)
        return (cx, cy)

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
        win32.set_foreground(gw["hwnd"])
        # 等待"功德+1"点击特效消退（实测约 400ms 消退），避免误判为宝箱图标
        time.sleep(float(self.cfg.get("box_settle_ms", 600)) / 1000.0)
        # 只在图标固定区域（右上角）内扫描，进一步排除木鱼特效/皮肤干扰
        x0, y0, x1, y1 = self._icon_region(w, h)
        ww, hh, buf = win32.capture_region(l, t, w, h)
        pts = [
            (xx, yy)
            for yy in range(y0, y1)
            for xx in range(x0, x1)
            if is_warm(win32.pixel_at(buf, w, xx, yy))
        ]
        if len(pts) < self.cfg.get("icon_min_pixels", 20):
            return
        cx, cy = _bbox_center(pts)
        self.state.log("检测到功德宝箱图标 @(%d,%d)" % (l + cx, t + cy))
        self._open_box_flow(l + cx, t + cy)

    def _icon_region(self, w, h):
        fx = self.cfg.get("box_icon_region", [0.68, 0.38, 0.92, 0.62])
        return int(w * fx[0]), int(h * fx[1]), int(w * fx[2]), int(h * fx[3])

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
