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
import os
import subprocess
import threading
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
    """返回系统级"最后一次输入"距今秒数（GetLastInputInfo）。

    注意：GetLastInputInfo 也会被 SendInput 注入的输入刷新，因此它
    无法区分"真实用户输入"与"程序模拟输入"。精确空闲检测请使用
    InputMonitor（低层钩子 + 注入标志位过滤）。
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


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    # 必须包含全部三种结构，联合体大小由最大的 MOUSEINPUT 决定（64位下 32 字节）
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


user32.SendInput.restype = wintypes.UINT
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]


def _key_input(vk, flags):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    inp.union.ki.wScan = user32.MapVirtualKeyW(vk, 0)
    inp.union.ki.dwFlags = flags
    # dwExtraInfo 置空（ctypes 指针字段默认 NULL）
    return inp


def key_down(vk):
    return user32.SendInput(1, ctypes.byref(_key_input(vk, 0)), ctypes.sizeof(INPUT))


def key_up(vk):
    return user32.SendInput(
        1, ctypes.byref(_key_input(vk, KEYEVENTF_KEYUP)), ctypes.sizeof(INPUT)
    )


def tap_key(vk):
    """按下并释放一个虚拟键。"""
    key_down(vk)
    key_up(vk)


def type_char(ch: str, hold_ms: float = 40) -> bool:
    """输入单个可打印字符（基于虚拟键，等价于真实敲键）。

    通过 VkKeyScan 把字符映射为虚拟键，需要 Shift 时自动按/放。
    hold_ms 为按键保持时间（毫秒），真实敲键会按住几十毫秒，
    若游戏按 GetAsyncKeyState 轮询，保持时间过短会被漏掉。
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
    if hold_ms:
        time.sleep(hold_ms / 1000.0)
    key_up(vk)
    if need_shift:
        key_up(VK_SHIFT)
    return True


def type_text(text: str, delay_ms: float = 0.0, hold_ms: float = 40):
    """输入一串文本，字符间可插入延迟（毫秒）。"""
    for ch in text:
        type_char(ch, hold_ms=hold_ms)
        if delay_ms:
            time.sleep(delay_ms / 1000.0)


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


def open_url(url):
    """用默认浏览器打开 url。返回是否成功。"""
    try:
        os.startfile(url)  # noqa
        return True
    except Exception:
        try:
            import webbrowser

            return bool(webbrowser.open(url))
        except Exception:
            return False


# ============================================================
# 物理输入监听（低层钩子，区分注入输入）
# ============================================================

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
LLKHF_INJECTED = 0x00000010
LLMHF_INJECTED = 0x00000001
PM_REMOVE = 0x0001


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


_LowLevelHookProc = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

# 关键：正确设置返回/参数类型，避免 64 位下句柄与坐标被截断
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    ctypes.c_void_p,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
]
user32.PeekMessageW.restype = wintypes.BOOL
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
kernel32.GetModuleHandleW.argtypes = [ctypes.c_void_p]


class InputMonitor:
    """监听"真实物理输入"，用于精确空闲检测。

    通过 WH_MOUSE_LL / WH_KEYBOARD_LL 低层钩子，依据 LLMHF_INJECTED /
    LLKHF_INJECTED 标志位，只记录物理键盘/鼠标输入的时间戳，过滤掉
    SendInput/mouse_event 等注入输入。这样程序自己刷的功德不会误判成
    "用户已回来"。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._last = time.monotonic()
        self._running = False
        self._thread = None
        self._cb_refs = []

    def idle_seconds(self):
        with self._lock:
            return time.monotonic() - self._last

    def _touch(self):
        with self._lock:
            self._last = time.monotonic()

    def start(self):
        if self._running:
            return
        self._running = True
        self._last = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        hmod = kernel32.GetModuleHandleW(None)
        mouse_cb = _LowLevelHookProc(self._mouse_proc)
        key_cb = _LowLevelHookProc(self._key_proc)
        self._cb_refs = [mouse_cb, key_cb]  # 防止回调被回收
        h_mouse = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_cb, hmod, 0)
        h_key = user32.SetWindowsHookExW(WH_KEYBOARD_LL, key_cb, hmod, 0)
        msg = wintypes.MSG()
        try:
            while self._running:
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.005)
        finally:
            if h_mouse:
                user32.UnhookWindowsHookEx(h_mouse)
            if h_key:
                user32.UnhookWindowsHookEx(h_key)

    def _mouse_proc(self, nCode, wParam, lParam):
        if nCode >= 0:
            data = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not (data.flags & LLMHF_INJECTED):
                self._touch()
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _key_proc(self, nCode, wParam, lParam):
        if nCode >= 0:
            data = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if not (data.flags & LLKHF_INJECTED):
                self._touch()
        return user32.CallNextHookEx(None, nCode, wParam, lParam)
