from PySide6.QtCore import QObject, Signal
from pynput import mouse, keyboard
import concurrent.futures
import time
from qfluentwidgets import DoubleSpinBox
from PySide6.QtWidgets import QApplication
from ok import Logger, og
from threading import Event, Thread

from src.ghost_mode import GhostWindowKeeper

logger = Logger.get_logger(__name__)


# --- 云游戏窗口分辨率 ---
# ok 框架的 BrowserCaptureMethod 启动完 Edge 后，会把“当前实际窗口尺寸”写回
# self._size；下次重开浏览器时又把这个实际尺寸当成目标尺寸。结果是云游戏窗口
# 被手动缩小过一次以后，之后一直停在 1008x576，config.py 里的 browser.resolution
# 看起来像没生效。这里每次启动浏览器前，把目标尺寸恢复成配置值。
try:
    from ok.device.capture_methods.browser import BrowserCaptureMethod

    if not getattr(BrowserCaptureMethod, "_dna_configured_resolution_patch", False):
        _original_start_browser = BrowserCaptureMethod.start_browser

        def _start_browser_with_configured_resolution(self):
            resolution = (self.config or {}).get("resolution")
            if resolution:
                target = (int(resolution[0]), int(resolution[1]))
                self._dna_target_size = target
                actual = tuple(self._size or (0, 0))
                # 浏览器已经开着时 start_browser 会直接返回，不会走启动逻辑；
                # 这里先把被手动缩小的窗口按差值补回去，再恢复目标尺寸。
                if (self.page is not None and not self.page.is_closed()
                        and self.hwnd and actual[0] > 10 and actual[1] > 10
                        and actual != target):
                    try:
                        import win32gui
                        from ok.util.window import resize_window
                        rect = win32gui.GetWindowRect(self.hwnd)
                        outer_w, outer_h = rect[2] - rect[0], rect[3] - rect[1]
                        resize_window(self.hwnd,
                                      outer_w + (target[0] - actual[0]),
                                      outer_h + (target[1] - actual[1]))
                    except Exception as e:
                        logger.warning(f"云游戏窗口调整失败: {e}")
                self._size = target
            return _original_start_browser(self)

        BrowserCaptureMethod.start_browser = _start_browser_with_configured_resolution
        BrowserCaptureMethod._dna_configured_resolution_patch = True
except Exception as e:
    logger.warning(f"无法应用云游戏窗口分辨率补丁: {e}")


# --- 运行栏“幽灵模式”开关 ---
try:
    from src.ghost_toggle import install_ghost_toggle

    install_ghost_toggle()
except Exception as e:
    logger.warning(f"无法安装幽灵模式开关: {e}")


class BrowserResolutionLock:
    """持续把云游戏浏览器窗口锁在 config["browser"]["resolution"]。

    只处理 BrowserCaptureMethod 自己的 Edge 窗口；最小化时不动，最大化时先还原
    再改回目标尺寸。用户在运行中手动拖大小，下一轮检查会拉回来。
    """

    def __init__(self, interval=2.0, tolerance=2):
        self.interval = interval
        self.tolerance = tolerance
        self._logged_target = None
        self._stop_event = Event()
        self._thread = Thread(target=self._run, daemon=True, name="BrowserResolutionLock")
        self._ghost = GhostWindowKeeper()
        self._ghost_state = None
        self._ghost_applied = False
        self._ghost_fail_count = 0

    def start(self):
        self._thread.start()
        logger.info(f"云游戏窗口分辨率锁定已启动：每 {self.interval:g} 秒检查一次")

    def stop(self):
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1)
        self._ghost.release()

    def _run(self):
        failures = 0
        while not self._stop_event.wait(self.interval):
            try:
                self._tick()
                failures = 0
            except Exception as e:
                failures += 1
                if failures == 1 or failures % 60 == 0:
                    logger.warning(f"云游戏窗口锁定检查失败（连续第 {failures} 次）: {e}")

    def _tick(self):
        from ok.device.capture_methods.browser import BrowserCaptureMethod
        from ok.util.window import find_hwnd
        import win32con
        import win32gui

        device_manager = getattr(og, "device_manager", None)
        capture = getattr(device_manager, "capture_method", None)
        if not isinstance(capture, BrowserCaptureMethod):
            return
        # 不在后台线程里碰 Playwright 的对象（page.is_closed 不是线程安全的）；
        # hwnd 和 WGC 存在就说明浏览器窗口已经起来了。
        if not capture.hwnd or not getattr(capture, "wgc_capture", None):
            return
        if not win32gui.IsWindow(capture.hwnd):
            return

        target = getattr(capture, "_dna_target_size", None)
        if not target:
            target = tuple((capture.config or {}).get("resolution") or ())
        if len(target) != 2:
            return
        target = (int(target[0]), int(target[1]))
        if target != self._logged_target:
            self._logged_target = target
            logger.info(f"云游戏窗口分辨率锁定目标: {target[0]}x{target[1]}")

        hwnd = capture.hwnd
        if not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
            return
        if win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE) & win32con.WS_MAXIMIZE:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.2)
        self._sync_ghost(capture, hwnd)

        # selected_hwnd 保证只量 BrowserCaptureMethod 自己那个 Edge 窗口，
        # 不会误伤用户另外打开的浏览器窗口。
        result = find_hwnd(None, ["chrome.exe", "msedge.exe", "chromium.exe"],
                           target[0], target[1], selected_hwnd=hwnd)
        if not result or not result[1]:
            return
        _, found_hwnd, _, _, _, real_w, real_h, _ = result
        if found_hwnd != hwnd or real_w <= 10 or real_h <= 10:
            return
        if (abs(real_w - target[0]) <= self.tolerance
                and abs(real_h - target[1]) <= self.tolerance):
            return

        rect = win32gui.GetWindowRect(hwnd)
        outer_w, outer_h = rect[2] - rect[0], rect[3] - rect[1]
        new_w = outer_w + (target[0] - real_w)
        new_h = outer_h + (target[1] - real_h)
        logger.info(f"云游戏窗口被改成了 {real_w}x{real_h}，锁回 {target[0]}x{target[1]}")
        win32gui.SetWindowPos(hwnd, 0, 0, 0, new_w, new_h,
                              win32con.SWP_NOMOVE | win32con.SWP_NOZORDER
                              | win32con.SWP_NOACTIVATE)

    def _sync_ghost(self, capture, hwnd):
        """幽灵模式：把云游戏窗口固定到屏幕外，屏幕上看不到但不影响抓帧。"""
        import win32gui
        from src.ghost_mode import ghost_enabled

        enabled = ghost_enabled(getattr(capture, "config", None))
        if enabled != self._ghost_state:
            self._ghost_state = enabled
            logger.info(f"幽灵模式{'开启' if enabled else '关闭'}，目标窗口 0x{hwnd:x}")
        if not enabled:
            if self._ghost_applied:
                self._ghost_applied = False
                logger.info("幽灵模式关闭，云游戏窗口已还原")
            self._ghost.release()
            return
        try:
            applied = self._ghost.keep(hwnd)
        except Exception as e:
            self._ghost_fail_count += 1
            if self._ghost_fail_count == 1 or self._ghost_fail_count % 30 == 0:
                logger.warning(f"幽灵模式移动窗口失败（第 {self._ghost_fail_count} 次）: {e}")
            return
        if applied and not self._ghost_applied:
            self._ghost_applied = True
            logger.info(f"幽灵模式已生效：窗口现在位于 {win32gui.GetWindowRect(hwnd)}")

# --- 猴子补丁 ---
# 修改 DoubleSpinBox，使其默认拥有一个更大的最大值
_original_init = DoubleSpinBox.__init__


def _new_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    self.setMaximum(99999.0)


DoubleSpinBox.__init__ = _new_init


# --- 猴子补丁 ---


class Globals(QObject):
    clicked = Signal(int, int, object, bool)
    pressed = Signal(object)
    released = Signal(object)

    def __init__(self, exit_event):
        super().__init__()
        self.pynput_mouse = None
        self.pynput_keyboard = None
        # 快捷启动键支持的任务实例（任务列表启动后固定，查一次就缓存）
        self._hotkey_tasks = {}
        self._thread_pool_executor_max_workers = 0
        self.thread_pool_executor = None
        self.thread_pool_exit_event = Event()
        self.shared_frame = None
        exit_event.bind_stop(self)
        self.init_pynput()
        self._browser_resolution_lock = BrowserResolutionLock()
        self._browser_resolution_lock.start()

    def stop(self):
        logger.info("pynput stop")
        if getattr(self, "_browser_resolution_lock", None):
            self._browser_resolution_lock.stop()
            self._browser_resolution_lock = None
        self.reset_pynput()
        self.shutdown_thread_pool_executor()

    def init_pynput(self):
        logger.info("pynput start")
        if self.pynput_mouse is None:
            self.pynput_mouse = mouse.Listener(on_click=self.on_click)
            self.pynput_mouse.start()
        if self.pynput_keyboard is None:
            self.pynput_keyboard = keyboard.Listener(on_press=self.on_press,
                                                     on_release=self.on_release)
            self.pynput_keyboard.start()

    def reset_pynput(self):
        if self.pynput_mouse:
            self.pynput_mouse.stop()
            self.pynput_mouse = None
        if self.pynput_keyboard:
            self.pynput_keyboard.stop()
            self.pynput_keyboard = None

    def on_click(self, x, y, button, pressed):
        self.clicked.emit(x, y, button, pressed)

    def on_press(self, key):
        self.pressed.emit(key)
        self.handle_task_hotkey(key)

    def on_release(self, key):
        self.released.emit(key)

    def hotkey_target_tasks(self):
        """支持快捷启动的任务实例（缓存；找不到的就下次再查）。"""
        try:
            from src.tasks.fullauto.AutoActionLogicScriptTask import AutoActionLogicScriptTask
            from src.tasks.fullauto.AutoRecordTask import AutoRecordTask
        except Exception as e:
            logger.error("快捷启动键：找不到目标任务类", e)
            return []
        targets = []
        for cls in (AutoActionLogicScriptTask, AutoRecordTask):
            task = self._hotkey_tasks.get(cls)
            if task is None:
                try:
                    task = og.executor.get_task_by_class(cls)
                except Exception as e:
                    logger.error("快捷启动键：找不到目标任务", e)
                    continue
                if task is not None:
                    self._hotkey_tasks[cls] = task
            if task is not None:
                targets.append(task)
        return targets

    def handle_task_hotkey(self, key):
        """按一个键启动 / 停止某个任务（默认 F8 -> 行动逻辑脚本测试，
        F7 -> 操作录制）。

        为什么挂这里：框架自带的 Start/Stop 热键是 RegisterHotKey 的系统级热键，只认
        F9~F12、而且是"暂停/恢复执行器"；而 pynput 这个全局键盘监听本来就在跑（任务
        靠它做按键检测），顺手就能用，也不占系统热键。判断逻辑都在
        src/tasks/TaskHotkey.py，这里只接线 + 兜底，绝不能让快捷键把输入链路带崩。
        """
        try:
            from src.tasks.TaskHotkey import DEFAULT_KEY, handle, hotkey_of, key_name
            if og.executor is None or og.app is None:
                return
            name = key_name(key)
            if name is None:
                return
            for task in self.hotkey_target_tasks():
                default = getattr(task, "DEFAULT_HOTKEY", DEFAULT_KEY)
                target = hotkey_of(task, default)
                if target is None or name != target:
                    continue
                if handle(og.executor, og.app.start_controller, task, key,
                          tell=logger.info, default=default):
                    return
        except Exception as e:
            logger.error("快捷启动键处理失败", e)

    def get_thread_pool_executor(self, max_workers=6):
        """
        获取全局执行器。
        如果请求的 max_workers 大于当前值，将安全地重建线程池。
        """
        if self.thread_pool_executor is not None and max_workers > self._thread_pool_executor_max_workers:
            logger.info(
                f"thread pool max_workers not enough, reset max_workers {self._thread_pool_executor_max_workers} -> {max_workers}")
            self.shutdown_thread_pool_executor()

        if self.thread_pool_executor is None:
            logger.info(f"create thread pool executor, max_workers: {max_workers}")
            self.thread_pool_exit_event.clear() 
            self.thread_pool_executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
            self._thread_pool_executor_max_workers = max_workers

        return self.thread_pool_executor

    def shutdown_thread_pool_executor(self):
        if self.thread_pool_executor is not None:
            logger.info("Shutting down thread pool executor...")
            self.thread_pool_exit_event.set()
            self.thread_pool_executor.shutdown(wait=False, cancel_futures=True)
            self.thread_pool_executor = None
            self._thread_pool_executor_max_workers = 0

    def submit_periodic_task(self, delay, task, *args, **kwargs):
        """
        提交一个循环任务到线程池。
        如果要停止循环，任务函数应返回 False。
        
        :param task: 要执行的函数
        :param delay: 每次执行后的间隔时间（秒）
        :param args: 位置参数
        :param kwargs: 关键字参数
        """
        executor = self.get_thread_pool_executor()

        def loop_wrapper():
            logger.debug(f"Periodic task {task.__name__} started.")
            
            while not self.thread_pool_exit_event.is_set():
                should_stop = False
                try:
                    if task(*args, **kwargs) is False:
                        should_stop = True
                except Exception as e:
                    logger.error(f"Error in periodic task {task.__name__}: {e}")

                if should_stop:
                    logger.debug(f"Periodic task {task.__name__} decided to stop.")
                    break
        
                if self.thread_pool_exit_event.wait(timeout=delay):
                    logger.debug(f"Periodic task {task.__name__} received stop signal.")
                    break
            
            logger.debug(f"Periodic task {task.__name__} stopped.")

        executor.submit(loop_wrapper)

if __name__ == "__main__":
    glbs = Globals(exit_event=None)
