from PySide6.QtCore import QObject, Signal
from pynput import mouse, keyboard
import concurrent.futures
from qfluentwidgets import DoubleSpinBox
from PySide6.QtWidgets import QApplication
from ok import Logger, og
from threading import Event

logger = Logger.get_logger(__name__)

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
        # 快捷启动键要启动的那个任务（任务列表启动后固定，查一次就缓存）
        self._hotkey_task = None
        self._thread_pool_executor_max_workers = 0
        self.thread_pool_executor = None
        self.thread_pool_exit_event = Event()
        self.shared_frame = None
        exit_event.bind_stop(self)
        self.init_pynput()

    def stop(self):
        logger.info("pynput stop")
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

    def hotkey_target_task(self):
        """快捷启动键指向的任务实例（缓存；找不到就返回 None）。"""
        if self._hotkey_task is None:
            try:
                from src.tasks.fullauto.AutoActionLogicScriptTask import AutoActionLogicScriptTask
                self._hotkey_task = og.executor.get_task_by_class(AutoActionLogicScriptTask)
            except Exception as e:
                logger.error("快捷启动键：找不到目标任务", e)
        return self._hotkey_task

    def handle_task_hotkey(self, key):
        """按一个键启动 / 停止某个任务（默认 F8 -> 行动逻辑脚本测试）。

        为什么挂这里：框架自带的 Start/Stop 热键是 RegisterHotKey 的系统级热键，只认
        F9~F12、而且是"暂停/恢复执行器"；而 pynput 这个全局键盘监听本来就在跑（任务
        靠它做按键检测），顺手就能用，也不占系统热键。判断逻辑都在
        src/tasks/TaskHotkey.py，这里只接线 + 兜底，绝不能让快捷键把输入链路带崩。
        """
        try:
            from src.tasks.TaskHotkey import handle, hotkey_of, key_name
            task = self.hotkey_target_task()
            if task is None or og.executor is None or og.app is None:
                return
            target = hotkey_of(task)
            if target is None or key_name(key) != target:
                return
            handle(og.executor, og.app.start_controller, task, key, tell=logger.info)
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
