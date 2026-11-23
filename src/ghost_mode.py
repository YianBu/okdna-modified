"""幽灵模式：把云游戏浏览器窗口移到所有显示器之外。

为什么不是 SW_HIDE 或最小化：Windows Graphics Capture 抓的是 DWM 合成后的
窗口内容。窗口被隐藏或最小化后 DWM 停止合成，帧会冻结（甚至变黑），脚本随后
就会卡在等待画面上。把窗口移到虚拟桌面之外、同时保持 WS_VISIBLE，合成仍然
继续；配合 Chromium 启动参数 --disable-backgrounding-occluded-windows 和
--disable-features=CalculateNativeWinOcclusion，页面也会继续渲染和联网。

输入不受影响：项目使用 PostMessage 交互，按键/鼠标按窗口内坐标投递，与窗口在
屏幕上的位置无关。
"""

import win32api
import win32con
import win32gui


_runtime_enabled = None


def set_ghost_enabled(value):
    """界面开关的实时状态；与 config 字典是否共享无关。"""
    global _runtime_enabled
    _runtime_enabled = bool(value)


def ghost_enabled(config=None):
    if _runtime_enabled is not None:
        return _runtime_enabled
    return bool((config or {}).get('ghost_mode'))


class GhostWindowKeeper:
    """把窗口固定在屏幕外，并在退出时还原位置与任务栏样式。"""

    def __init__(self, gap=200):
        self.gap = gap
        self._hwnd = 0
        self._orig_rect = None
        self._orig_exstyle = None

    def _offscreen_pos(self, hwnd):
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        vx = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        vy = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        return vx - width - self.gap, vy + 60

    def _adopt(self, hwnd):
        self._orig_rect = win32gui.GetWindowRect(hwnd)
        exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        self._orig_exstyle = exstyle
        # WS_EX_TOOLWINDOW 让窗口从任务栏和 Alt+Tab 里消失，避免误切进去。
        wanted = (exstyle | win32con.WS_EX_TOOLWINDOW) & ~win32con.WS_EX_APPWINDOW
        if wanted != exstyle:
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, wanted)
        self._hwnd = hwnd

    def keep(self, hwnd):
        """确保窗口在屏幕外；返回 True 表示当前已经处于目标位置。"""
        if not hwnd or not win32gui.IsWindow(hwnd):
            return False
        if win32gui.IsIconic(hwnd):
            # 最小化会被用户或系统还原，交给下一轮 tick 处理。
            return False
        if self._hwnd != hwnd:
            self._adopt(hwnd)
        x, y = self._offscreen_pos(hwnd)
        left, top, _, _ = win32gui.GetWindowRect(hwnd)
        if abs(left - x) <= 2 and abs(top - y) <= 2:
            return True
        win32gui.SetWindowPos(
            hwnd, 0, x, y, 0, 0,
            win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
            | win32con.SWP_FRAMECHANGED)
        return False

    def release(self):
        """还原任务栏样式和原来的位置。"""
        hwnd = self._hwnd
        self._hwnd = 0
        if not hwnd or not win32gui.IsWindow(hwnd):
            return
        if self._orig_exstyle is not None:
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, self._orig_exstyle)
        if self._orig_rect:
            left, top, right, bottom = self._orig_rect
            win32gui.SetWindowPos(
                hwnd, 0, left, top, right - left, bottom - top,
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED)
        self._orig_rect = None
        self._orig_exstyle = None
