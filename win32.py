"""win32.py — Windows API 的 ctypes 封装（纯标准库，无第三方依赖）。

提供挂机机器人所需的全部底层能力：
- idle_seconds(): 系统级"最后真实输入"距今秒数（GetLastInputInfo）
- 键盘模拟（SendInput，按虚拟键+扫描码，等价于真实按键）
- 鼠标点击（SetCursorPos + mouse_event）
- 窗口查找（EnumWindows 按标题/进程名）
- 屏幕取色（GetPixel）
- 记事本/前台窗口辅助
"""
import ctypes
import subprocess
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

# ============================================================
# 结构体
# ============================================================


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


# ============================================================
# 空闲检测
# ============================================================


def idle_seconds() -> float:
    """返回自最后一次真实用户输入（键盘/鼠标）以来的秒数。

    关键特性：GetLastInputInfo 只统计物理 HID 输入，SendInput 注入的
    模拟输入不会刷新它，因此程序自己刷按键不会误判为"用户已回来"。
    """
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    tick = kernel32.GetTickCount()
    return ((tick - lii.dwTime) & 0xFFFFFFFF) / 1000.0


# ============================================================
# 键盘模拟（SendInput）
# ============================================================

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
VK_SHIFT = 0x10


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


def _key_input(vk, flags):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    inp.union.ki.wScan = user32.MapVirtualKeyW(vk, 0)
    inp.union.ki.dwFlags = flags
    # dwExtraInfo 置空（ctypes 指针字段默认 NULL）
    return inp


def key_down(vk):
    user32.SendInput(1, ctypes.byref(_key_input(vk, 0)), ctypes.sizeof(INPUT))


def key_up(vk):
    user32.SendInput(
        1, ctypes.byref(_key_input(vk, KEYEVENTF_KEYUP)), ctypes.sizeof(INPUT)
    )


def tap_key(vk):
    """按下并释放一个虚拟键。"""
    key_down(vk)
    key_up(vk)


def type_char(ch: str) -> bool:
    """输入单个可打印字符（基于虚拟键，等价于真实敲键）。

    通过 VkKeyScan 把字符映射为虚拟键，需要 Shift 时自动按/放。
    返回是否成功（字符无对应虚拟键时返回 False）。
    """
    if not ch or len(ch) != 1:
        return False
    res = user32.VkKeyScanW(ord(ch))
    if res == -1:
        return False
    vk = res & 0xFF
    modifier = (res >> 8) & 0xFF
    need_shift = bool(modifier & 1)
    if need_shift:
        key_down(VK_SHIFT)
    key_down(vk)
    key_up(vk)
    if need_shift:
        key_up(VK_SHIFT)
    return True


def type_text(text: str, delay_ms: float = 0.0):
    """输入一串文本，字符间可插入延迟（秒）。"""
    for ch in text:
        type_char(ch)
        if delay_ms:
            time.sleep(delay_ms)


# ============================================================
# 鼠标模拟
# ============================================================

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010


def cursor_pos():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move_to(x, y):
    user32.SetCursorPos(int(x), int(y))


def click(x, y, button="left", settle=0.03):
    """把鼠标移到 (x, y) 并单击。button: left/right。"""
    move_to(x, y)
    time.sleep(settle)
    if button == "right":
        user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        time.sleep(0.01)
        user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    else:
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.01)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(settle)


# ============================================================
# 屏幕捕获与取色
# ============================================================

SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


def capture_region(x, y, w, h):
    """捕获屏幕 (x, y) 起 w×h 区域，返回 (w, h, bytes)。

    bytes 为 32 位 BGRA、自上而下、行主序。像素索引: (row*w+col)*4，
    依次为 B, G, R, A。
    """
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, int(x), int(y), SRCCOPY)
        buf = (ctypes.c_ubyte * (w * h * 4))()
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # 负值 => 自上而下
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bmi.bmiHeader.biSizeImage = w * h * 4
        gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
        return w, h, bytes(buf)
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)


def pixel_at(buf, w, x, y):
    """从 capture_region 的 buf 读取 (x, y) 处的 RGB 元组。"""
    i = (y * w + x) * 4
    return (buf[i + 2], buf[i + 1], buf[i])  # B,G,R -> R,G,B


def pixel_color(x, y):
    """读取屏幕绝对坐标 (x, y) 处的颜色，返回 (r, g, b)。"""
    hdc = user32.GetDC(0)
    try:
        c = gdi32.GetPixel(hdc, int(x), int(y))
        # GetPixel 返回 0x00BBGGRR
        return (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)
    finally:
        user32.ReleaseDC(0, hdc)


def is_color(rgb, target, tol=40):
    """判断颜色是否接近目标色（每通道容差 tol）。"""
    return all(abs(rgb[i] - target[i]) <= tol for i in range(3))


# ============================================================
# 窗口查找
# ============================================================

_windows = []


def _enum_cb(hwnd, lparam):
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    length = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title, length + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    _windows.append(
        {
            "hwnd": hwnd,
            "class": cls.value,
            "title": title.value,
            "pid": pid.value,
            "visible": bool(user32.IsWindowVisible(hwnd)),
        }
    )
    return True


_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def enum_windows():
    global _windows
    _windows = []
    user32.EnumWindows(_EnumWindowsProc(_enum_cb), 0)
    return _windows


def process_name(pid) -> str:
    """通过 pid 解析进程可执行文件名（用于定位游戏）。"""
    import os

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(h)
    return ""


def find_window(title=None, proc=None, visible_only=True):
    """按标题子串或进程名查找顶层窗口，返回 dict 或 None。"""
    for w in enum_windows():
        if visible_only and not w["visible"]:
            continue
        if title and title in w["title"]:
            return w
        if proc:
            name = process_name(w["pid"])
            if name and name.lower() == proc.lower():
                # 优先返回有标题的可见窗口
                if w["title"]:
                    return w
    return None


def window_rect(hwnd):
    r = RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return r.left, r.top, r.right, r.bottom
    return None


GA_ROOT = 2


def top_level_hwnd(child_hwnd):
    """把子窗口句柄转换为顶层窗口句柄（用于 tkinter 的 winfo_id）。"""
    try:
        return user32.GetAncestor(child_hwnd, GA_ROOT) or child_hwnd
    except Exception:
        return child_hwnd


def set_foreground(hwnd):
    """尽力把窗口带到前台（带回退技巧）。"""
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    ok = user32.SetForegroundWindow(hwnd)
    if not ok:
        # 经典 hack：先按一下 Alt 打破前台锁
        tap_key(0x12)  # VK_MENU (Alt)
        ok = user32.SetForegroundWindow(hwnd)
    return bool(ok)


def launch_notepad():
    """启动一个记事本窗口并返回其 hwnd（用于挂机时接收打字，避免污染用户其它窗口）。"""
    subprocess.Popen(["notepad.exe"])
    deadline = time.time() + 5
    while time.time() < deadline:
        for w in enum_windows():
            if process_name(w["pid"]).lower() == "notepad.exe" and w["title"]:
                return w["hwnd"]
        time.sleep(0.3)
    return None
