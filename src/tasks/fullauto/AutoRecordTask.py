import threading
import time
from pathlib import Path

from qfluentwidgets import FluentIcon

from ok import Logger, TaskDisabledException, og

from src.tasks.BaseDNATask import BaseDNATask
from src.tasks.DNAOneTimeTask import DNAOneTimeTask
from src.tasks.fullauto.RecordScript import (
    actions_to_steps,
    key_name,
    normalize_hotkey,
    sanitize_name,
    steps_payload,
    write_json,
)

logger = Logger.get_logger(__name__)

RECORD_KEYS = ("F7", "F6", "F9", "F10", "F11", "F12", "CapsLock", "ScrollLock", "关闭")
DEFAULT_NAME = "探险高台录制"
TOGGLE_DEBOUNCE_SECONDS = 0.6
ARROW_KEYS = ("left", "right", "up", "down")
# 云游戏/Edge 会吞 F 键（F7/F8/F9 都收不到）；这两个不占游戏按键，永远当备用热键。
ALT_HOTKEYS = ("caps_lock", "scroll_lock")


class AutoRecordTask(DNAOneTimeTask, BaseDNATask):
    """「操作录制」：在云游戏里按快捷键录 WASD/空格/Shift，存成可回放的 JSON。

    为什么不用外部的 keyboard_recorder.exe：它依赖系统热键/自己的窗口焦点，和程序
    自带的 Start/Stop 热键（F9）还容易冲突。这里直接挂程序已经在用的 pynput 全局
    键盘监听（「快捷启动键」F8 就是同一套），不要求游戏窗口失焦或切回程序。

    用法：
      1) 在「测试」里启动本任务；
      2) 切到云游戏，按录制热键（默认 F7，可改）开始；走完路线再按一次停止。
         云游戏/Edge 常吞 F 键：F7 没反应时直接按 CapsLock 或 ScrollLock，
         这两个是内置备用热键，不占游戏按键；
      3) 停止后保存成 mod/行动逻辑/<名字>.json；在「行动逻辑脚本测试」里选它、
         按 F8 就能回放（改完 JSON 再按一次 F8 会重新读文件）。

    录制时只收键盘，不收鼠标；云游戏里不要动视角。没录到按键时日志会说，不会静默。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.DEVELOPER_TOOLS
        self.name = "操作录制"
        self.description = "测试"
        self.group_name = "测试"
        self.group_icon = FluentIcon.DEVELOPER_TOOLS

        self.default_config.update({
            "文件名": DEFAULT_NAME,
            "录制热键": "F7",
            "启动即录制": True,
            "方向键移动鼠标": True,
            "水平速度": 20,
            "垂直速度": 20,
            "长按间隔(秒)": 0.05,
            "视角倍率": 1.0,
        })
        self.config_type["录制热键"] = {"type": "drop_down", "options": list(RECORD_KEYS)}
        self.config_description.update({
            "文件名": "保存用的名字；重名会自动加 -2，不会覆盖已有文件",
            "录制热键": "在云游戏里按这个键开始/停止；F 键可能被浏览器吞掉。"
                        "F7 没反应时直接按 CapsLock / ScrollLock（始终可用）",
            "启动即录制": "任务一启动就开始录，省得进游戏后再按一次；做完按热键或点停止结束",
            "方向键移动鼠标": "录制时用方向键微调视角（和外部录制器的「方向键控制」类似）；不想用就关掉",
            "水平速度": "方向键每次左右移动的鼠标像素",
            "垂直速度": "方向键每次上下移动的鼠标像素",
            "长按间隔(秒)": "按住方向键时，每隔这么久移动一次",
            "视角倍率": "原生游戏录、云游戏回放时校准鼠标位移：转得太多就调小，太少就调大",
        })

        self._lock = threading.Lock()
        self._connected = False
        self._recording = False
        self._events = []
        self._down = set()
        self._start = 0.0
        self._last_toggle = 0.0
        self._beep_pending = False
        self._beep_kind = "start"
        self._seen_names = set()
        self._seen_logs = 0
        self._last_key_name = None
        self._arrow_down = set()
        self._arrow_last = {}
        self._arrow_active = False
        self._arrow_thread = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def run(self):
        # 不走 DNAOneTimeTask.run：它会装鼠标抖动，录制时视角会自己动
        try:
            if hasattr(self.executor.interaction, "activate"):
                self.executor.interaction.activate()
            self._connect()
            if self.config.get("启动即录制", True):
                self._begin_recording()
            return self.do_run()
        except TaskDisabledException:
            pass
        finally:
            self._arrow_active = False
            if self._recording:
                self._finish_recording()
            self._disconnect()

    def do_run(self):
        hotkey = self.record_hotkey()
        key_text = hotkey.upper() if hotkey else "（未设置）"
        if self._recording:
            self.log_info_notify(
                f"操作录制已自动开始：切到云游戏直接走；做完按 {key_text} 或点停止结束")
        else:
            self.log_info_notify(f"操作录制已启动：在云游戏里按 {key_text} 开始/停止；"
                                 "录制时不要动鼠标视角")
        self.log_info("如果 F 键没反应（云游戏/Edge 常吞 F 键），直接按 CapsLock 或 ScrollLock 也能开始/停止")
        self.info_set("录制状态", "等待按键")
        while True:
            if self._beep_pending:
                self._beep_pending = False
                self._beep()
            self.sleep(0.2)

    # ------------------------------------------------------------------
    # 全局键盘监听
    # ------------------------------------------------------------------
    def _connect(self):
        try:
            og.my_app.pressed.connect(self.on_global_press)
            og.my_app.released.connect(self.on_global_release)
            self._connected = True
        except Exception as e:
            self.log_info(f"连接全局键盘监听失败：{e}")

    def _disconnect(self):
        if not self._connected:
            return
        self._connected = False
        try:
            og.my_app.pressed.disconnect(self.on_global_press)
        except Exception:
            pass
        try:
            og.my_app.released.disconnect(self.on_global_release)
        except Exception:
            pass

    def record_hotkey(self):
        return normalize_hotkey(self.config.get("录制热键", "F7"))

    def on_global_press(self, key):
        try:
            name = key_name(key)
            if name is None:
                return
            hotkey = self.record_hotkey()
            if hotkey and (name == hotkey or name in ALT_HOTKEYS):
                now = time.perf_counter()
                if now - self._last_toggle < TOGGLE_DEBOUNCE_SECONDS:
                    return
                self._last_toggle = now
                self._toggle()
                return

            if self._recording and self.arrow_mouse_enabled() and name in ARROW_KEYS:
                with self._lock:
                    # Windows 按住会连发 key_down；只在第一次按下时清零计时，
                    # 否则连发会把间隔重置，方向键会变成每 10ms 移动一次。
                    if name not in self._arrow_down:
                        self._arrow_last[name] = 0.0
                    self._arrow_down.add(name)
                self.info_set("方向键控制", name)
                return

            if not self._recording:
                # 没在录也报前几个键：用来确认云游戏窗口的按键到底能不能被 pynput 看到
                if name not in self._seen_names and self._seen_logs < 5:
                    self._seen_names.add(name)
                    self._seen_logs += 1
                    self.log_info(f"监听到按键：{name}（云游戏按键抓取正常）")
                if name != self._last_key_name:
                    self._last_key_name = name
                    self.info_set("最近按键", name)
                return

            with self._lock:
                # 按住不放时 Windows 会连发 key_down，只记第一次
                if name in self._down:
                    return
                self._down.add(name)
                self._events.append({
                    "type": "key_down",
                    "key": name,
                    "time": round(time.perf_counter() - self._start, 3),
                })
            self.info_set("录制事件", str(len(self._events)))
        except Exception as e:
            logger.error(f"操作录制处理按键按下失败：{e}")

    def on_global_release(self, key):
        try:
            name = key_name(key)
            if name is None or name == self.record_hotkey() or name in ALT_HOTKEYS:
                return
            if name in ARROW_KEYS and self.arrow_mouse_enabled():
                with self._lock:
                    self._arrow_down.discard(name)
                return
            with self._lock:
                if name not in self._down:
                    return
                self._down.discard(name)
                self._events.append({
                    "type": "key_up",
                    "key": name,
                    "time": round(time.perf_counter() - self._start, 3),
                })
        except Exception as e:
            logger.error(f"操作录制处理按键松开失败：{e}")

    # ------------------------------------------------------------------
    # 开始 / 停止 / 保存
    # ------------------------------------------------------------------
    def _toggle(self):
        if self._recording:
            self._finish_recording()
        else:
            self._begin_recording()

    def _begin_recording(self):
        old_thread = self._arrow_thread
        self._arrow_active = False
        if old_thread is not None and old_thread.is_alive():
            old_thread.join(timeout=0.2)
        with self._lock:
            self._events = []
            self._down.clear()
            self._arrow_down.clear()
            self._arrow_last.clear()
            self._start = time.perf_counter()
            self._recording = True
            self._last_key_name = None
        self._arrow_active = True
        self._arrow_thread = threading.Thread(target=self._arrow_loop, daemon=True)
        self._arrow_thread.start()
        self.info_set("录制状态", "录制中")
        self.info_set("录制事件", "0")
        self.log_info("开始录制……再按一次录制热键停止")
        self._beep_pending = True
        self._beep_kind = "start"

    def _finish_recording(self):
        with self._lock:
            if not self._recording:
                return
            self._recording = False
            now = time.perf_counter() - self._start
            for name in self._down:
                self._events.append({
                    "type": "key_up",
                    "key": name,
                    "time": round(now, 3),
                })
            self._down.clear()
            self._arrow_down.clear()
            actions = list(self._events)
        self._arrow_active = False
        self.info_set("录制状态", "已停止")
        self._beep_pending = True
        self._beep_kind = "stop"

        if not actions:
            self.log_info("没有录到任何按键：确认云游戏窗口在前台，并且按的是 WASD/空格/Shift")
            return

        name = sanitize_name(self.config.get("文件名", DEFAULT_NAME), DEFAULT_NAME)
        base = Path.cwd() / "mod"
        try:
            mouse_scale = float(self.config.get("视角倍率", 1.0))
        except (TypeError, ValueError):
            mouse_scale = 1.0
        steps_path = write_json(base / "行动逻辑" / f"{name}.json",
                                steps_payload(name, actions_to_steps(actions, mouse_scale=mouse_scale)))

        duration = max((float(a["time"]) for a in actions), default=0.0)
        self.log_info(f"录制完成：{len(actions)} 个事件，约 {duration:.2f} 秒")
        self.log_info(f"内置步骤已保存：{steps_path}")
        self.log_info_notify(f"操作录制已保存：{steps_path.stem}，共 {len(actions)} 个事件")

    # ------------------------------------------------------------------
    # 方向键 -> 鼠标相对移动（和外部录制器的「方向键控制」类似）
    # ------------------------------------------------------------------
    def arrow_mouse_enabled(self):
        return bool(self.config.get("方向键移动鼠标", True))

    def arrow_interval(self):
        try:
            return max(0.01, float(self.config.get("长按间隔(秒)", 0.05)))
        except (TypeError, ValueError):
            return 0.05

    def _arrow_loop(self):
        while self._arrow_active:
            with self._lock:
                if not self._recording:
                    return
                keys = list(self._arrow_down)
            now = time.perf_counter()
            for name in keys:
                if now - self._arrow_last.get(name, 0.0) >= self.arrow_interval():
                    self._arrow_last[name] = now
                    self._arrow_move(name)
            time.sleep(0.01)

    def _arrow_move(self, name):
        try:
            speed_h = int(self.config.get("水平速度", 20))
            speed_v = int(self.config.get("垂直速度", 20))
        except (TypeError, ValueError):
            speed_h, speed_v = 20, 20
        dx = speed_h if name == "right" else -speed_h if name == "left" else 0
        dy = speed_v if name == "down" else -speed_v if name == "up" else 0
        if dx == 0 and dy == 0:
            return
        try:
            self.move_mouse_relative(dx, dy)
        except Exception as e:
            logger.error(f"方向键移动鼠标失败：{e}")
            return
        with self._lock:
            if self._recording:
                self._events.append({
                    "type": "mouse_move",
                    "dx": dx,
                    "dy": dy,
                    "time": round(time.perf_counter() - self._start, 3),
                })
                self.info_set("录制事件", str(len(self._events)))

    def _beep(self):
        try:
            import winsound
            if self._beep_kind == "start":
                winsound.Beep(1200, 120)
                winsound.Beep(1600, 120)
            else:
                winsound.Beep(700, 180)
        except Exception:
            pass
