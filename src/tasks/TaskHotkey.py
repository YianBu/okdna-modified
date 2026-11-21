"""快捷启动键：按一个键启动 / 停止某个一次性任务（默认 F8 -> 行动逻辑脚本测试，
F7 -> 操作录制）。

为什么不直接用框架自带的 Start/Stop 热键：那套是 RegisterHotKey 的系统级热键，
只认 F9~F12，而且干的是"暂停 / 恢复执行器"，不是"启动某个任务"；这台机器上它还
注册失败过（日志里 Failed to register hotkey F9，多半被别的程序占了）。这里改成
复用 Globals 已有的 pynput 全局键盘监听，按哪个键由**任务自己的配置**决定。

语义只有三条，好记：
  * 目标任务没在跑 -> 启动它（和界面上点"开始"同一条路 start_controller.start）；
  * 正在跑的正好是目标任务 -> 停掉它；再按一次就等于重跑，顺便重新读一遍 JSON；
    （操作录制例外：任务在跑时键交给录制任务自己开 / 停录制，任务本身由「保存后退出」收尾）
  * 有别的任务在跑 -> 什么都不做，只记一行日志。

按住键会连发，所以有一秒去抖；这一层只做判断和回调，不碰 Qt / ok，方便单测。
"""

DEFAULT_KEY = "F8"
CONFIG_KEY = "快捷启动键"
DISABLED = "关闭"
KEY_OPTIONS = (DEFAULT_KEY, "F6", "F7", DISABLED)
DEBOUNCE_SECONDS = 1.0

# 每个任务、每个键单独去抖：行动逻辑按 F8、操作录制按 F7，不能互相把对方压掉
_last_press = {}


def reset_debounce():
    """测试用：把去抖计时清零。"""
    _last_press.clear()


def key_name(key):
    """pynput 的按键对象 -> 'f8' / 'a' 这种小写名字；认不出来返回 None。"""
    name = getattr(key, "name", None)
    if name:
        return str(name).lower()
    char = getattr(key, "char", None)
    return str(char).lower() if char else None


def hotkey_of(task, default=DEFAULT_KEY):
    """任务配置里的快捷启动键（小写）；配置成「关闭」/ 空 / 读不到 -> None。"""
    if task is None:
        return None
    try:
        value = task.config.get(CONFIG_KEY, default)
    except Exception:
        value = default
    value = (value or "").strip()
    if not value or value == DISABLED:
        return None
    return value.lower()


def stops_when_running(task):
    """这个任务正在跑时，快捷启动键要不要把它停掉。

    操作录制在跑时，键要交给录制任务自己开 / 停录制；这里如果也停任务，
    一次按键会被两边同时处理。其他任务保持原来的「再按一次就是停止」。
    """
    return bool(getattr(task, "hotkey_stops_running", True))


def action_for(executor, task):
    """现在这个键该干什么：start / stop / ignore。"""
    current = getattr(executor, "current_task", None)
    if current is None:
        return "start"
    if current is task:
        return "stop"
    return "ignore"


def handle(executor, start_controller, task, key, tell=None, now=None, default=DEFAULT_KEY):
    """处理一次按键，返回做了什么：start / stop / ignore；不是这个键就返回空串。

    tell 是可选的日志回调，签名 tell(message)。
    """
    if now is None:
        import time
        now = time.time()
    name = key_name(key)
    target = hotkey_of(task, default)
    if name is None or target is None or name != target:
        return ""

    action = action_for(executor, task)
    if action == "stop" and not stops_when_running(task):
        # 这一步不归快捷启动管：任务自己的全局按键监听会处理（比如开 / 停录制）
        return ""

    stamp = (id(task), name)
    if now - _last_press.get(stamp, 0.0) < DEBOUNCE_SECONDS:
        return ""
    _last_press[stamp] = now

    name_of_task = getattr(task, "name", getattr(task, "class_name", "任务"))
    if action == "start":
        start_controller.start(task)
        message = f"快捷启动：启动「{name_of_task}」（{target}）"
    elif action == "stop":
        executor.stop_current_task()
        message = f"快捷启动：停止「{name_of_task}」（{target}）"
    else:
        message = f"快捷启动：有别的任务在跑，忽略（{target}）"
    if tell:
        tell(message)
    return action
