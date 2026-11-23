"""验证“幽灵模式”在你的机器上是否可用。

用法（在项目根目录）：
    python tools/ghost_check.py
    python tools/ghost_check.py --title 云游戏
    python tools/ghost_check.py --hwnd 123456

脚本会对云游戏浏览器窗口分别做：屏幕内、移出屏幕、SW_HIDE 三种状态下的
WGC 抓帧，比较帧是否仍在更新。移出屏幕这一项通过，就可以在 src/config.py
的 browser 里把 "ghost_mode" 设为 True。脚本结束时会还原窗口位置。
"""

import argparse
import os
import re
import sys
import threading
import time

import numpy as np
import win32api
import win32con
import win32gui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'vendor'))

from ok.device.capture_methods.windows_graphics import WindowsGraphicsCaptureMethod


class StubWindow:
    """只满足 WGC 需要的窗口信息，不依赖 ok 的 HwndWindow 生命周期。"""

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.exists = True
        self.app_exit_event = threading.Event()
        self.capture_target_signature = ('ghost-check', hwnd)
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        self.width = max(1, right - left)
        self.height = max(1, bottom - top)
        self.hwnds = []

    def get_abs_cords(self, x, y):
        return win32gui.ClientToScreen(self.hwnd, (x, y))


def find_window(title_pattern, hwnd=0):
    if hwnd:
        return hwnd
    candidates = []

    def cb(h, _):
        try:
            if not win32gui.IsWindowVisible(h) or win32gui.IsIconic(h):
                return
            if win32gui.GetClassName(h) != 'Chrome_WidgetWin_1':
                return
            title = win32gui.GetWindowText(h)
            if title_pattern and not re.search(title_pattern, title):
                return
            left, top, right, bottom = win32gui.GetWindowRect(h)
            if right - left < 300 or bottom - top < 200:
                return
            candidates.append((h, (right - left) * (bottom - top), title))
        except Exception:
            pass

    win32gui.EnumWindows(cb, None)
    if not candidates:
        return 0
    candidates.sort(key=lambda item: item[1], reverse=True)
    print(f'选中窗口: 0x{candidates[0][0]:x} {candidates[0][2]}')
    return candidates[0][0]


def sample(capture, label, rounds=6):
    frames = []
    for _ in range(rounds):
        try:
            frame = capture.get_frame()
        except Exception as exc:
            print(f'{label}: 异常 {type(exc).__name__} {exc}')
            return None
        if frame is not None:
            frames.append(frame)
        time.sleep(0.25)
    if len(frames) < 2:
        print(f'{label}: 只拿到 {len(frames)} 帧')
        return {'frames': len(frames), 'changed': 0.0, 'mean': 0.0}
    first, last = frames[0], frames[-1]
    changed = float(np.abs(first.astype('int16') - last.astype('int16')).mean())
    mean = float(np.mean([f.mean() for f in frames]))
    result = {'frames': len(frames), 'changed': changed, 'mean': mean}
    print(f'{label}: {len(frames)}/{rounds} 帧, 亮度均值 {mean:.1f}, 首尾差异 {changed:.2f}')
    return result


def offscreen_pos(hwnd):
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width = right - left
    vx = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    vy = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    return vx - width - 200, vy + 60


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--title', default='云游戏', help='窗口标题正则，默认为 云游戏')
    parser.add_argument('--hwnd', type=int, default=0, help='直接指定窗口句柄')
    args = parser.parse_args()

    hwnd = find_window(args.title, args.hwnd)
    if not hwnd:
        print('没有找到匹配的 Edge/Chrome 窗口，先用 --title 或 --hwnd 指定。')
        return 2

    original = win32gui.GetWindowRect(hwnd)
    capture = WindowsGraphicsCaptureMethod(StubWindow(hwnd))
    for _ in range(15):
        if capture.frame_pool is not None:
            break
        try:
            capture.start_or_stop()
        except Exception:
            pass
        time.sleep(0.4)
    if capture.frame_pool is None:
        print('WGC 会话建立失败，检查窗口是否可见、是否被其他程序独占。')
        return 2

    try:
        onscreen = sample(capture, '屏幕内')
        x, y = offscreen_pos(hwnd)
        win32gui.SetWindowPos(hwnd, 0, x, y, 0, 0,
                              win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        time.sleep(1.0)
        print(f'已移到屏幕外: {x},{y}')
        offscreen = sample(capture, '屏幕外')
        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        time.sleep(1.0)
        hidden = sample(capture, '隐藏(SW_HIDE)')
    finally:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.SetWindowPos(hwnd, 0, original[0], original[1],
                              original[2] - original[0], original[3] - original[1],
                              win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        capture.close()

    print()
    if not onscreen or onscreen['frames'] < 2:
        print('结论：屏幕内都抓不到帧，先确认云游戏窗口正在运行、画面在动。')
        return 2
    if not offscreen or offscreen['frames'] < 2:
        print('结论：窗口移出屏幕后抓不到帧，这台机器不适合用幽灵模式。')
        print('      可以改用 Playwright 截图/输入的方案（窗口真正隐藏也能控制）。')
        return 1
    if offscreen['changed'] < 0.5:
        print('结论：屏幕外能出帧，但首尾帧几乎没变化。')
        print('      如果游戏画面本来就在动，说明画面冻结，不建议开启幽灵模式。')
        return 1
    print('结论：通过。屏幕外仍能持续抓帧，可以在 src/config.py 里把')
    print('      browser -> "ghost_mode" 设为 True。')
    if hidden and hidden['frames'] >= 2:
        print('      注：SW_HIDE 也能出帧，说明这台机器的 DWM 行为比较宽松。')
    else:
        print('      注：SW_HIDE 抓不到帧（符合预期），所以幽灵模式用的是移出屏幕而不是隐藏。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
