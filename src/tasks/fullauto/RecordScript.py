"""把录到的按键时间轴转成「行动逻辑脚本测试」用的相对步骤。

录制本身只产生 ``actions``（绝对时间轴的 key_down/key_up）：

    [{"type": "key_down", "key": "w", "time": 0.52},
     {"type": "key_up",   "key": "w", "time": 6.81}]

纯函数，方便单测。
"""

import json
import re
from pathlib import Path


# pynput 的名字 -> ok 的 validate_key 认的名字。游戏里默认闪避是左 Shift，统一成 lshift。
KEY_ALIASES = {
    "shift": "lshift",
    "shift_l": "lshift",
    "shift_r": "rshift",
    "ctrl": "lcontrol",
    "control": "lcontrol",
    "ctrl_l": "lcontrol",
    "control_l": "lcontrol",
    "ctrl_r": "rcontrol",
    "control_r": "rcontrol",
    "return": "enter",
    "escape": "esc",
}

# 配置里写 CapsLock/ScrollLock 这种人看得懂的名字，内部统一成 pynput 的键名。
HOTKEY_ALIASES = {
    "capslock": "caps_lock",
    "caps_lock": "caps_lock",
    "scrolllock": "scroll_lock",
    "scroll_lock": "scroll_lock",
    "pageup": "page_up",
    "page_up": "page_up",
    "pagedown": "page_down",
    "page_down": "page_down",
}


def key_name(key):
    """pynput 的按键对象 -> 'w' / 'space' / 'lshift' / 'f7' 这种小写名字。"""
    name = getattr(key, "name", None)
    if name:
        name = str(name).lower()
        return KEY_ALIASES.get(name, name)
    char = getattr(key, "char", None)
    if char:
        return str(char).lower()
    return None


def normalize_hotkey(name):
    """配置里的热键名 -> pynput 的键名；关闭/空返回 None。"""
    value = str(name or "").strip().lower()
    if not value or value in ("关闭", "off", "none"):
        return None
    return HOTKEY_ALIASES.get(value, value)


def sanitize_name(name, fallback="录制"):
    """文件名去掉 Windows 不允许的字符；空名字用 fallback。"""
    name = (name or "").strip() or fallback
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .")
    return name or fallback


def actions_to_steps(actions, min_wait=0.02, mouse_scale=1.0):
    """绝对时间轴 -> 相对 steps（key_down/key_up 之间用 wait 补时间）。"""
    steps = []
    last = 0.0
    for event in actions:
        t = float(event.get("time", 0.0))
        if t - last > min_wait:
            steps.append({"type": "wait", "seconds": round(t - last, 3)})
        if event.get("type") == "mouse_move":
            steps.append({"type": "mouse_move",
                          "dx": int(round(event.get("dx", 0) * mouse_scale)),
                          "dy": int(round(event.get("dy", 0) * mouse_scale))})
        else:
            steps.append({"type": event["type"], "key": event["key"]})
        last = max(last, t)
    steps.append({"type": "log", "text": "录制结束"})
    return steps


def steps_payload(name, steps):
    """「行动逻辑脚本测试」使用的 steps 文件。"""
    return {"note": f"由「操作录制」生成：{name}", "steps": steps}


def write_json(path, data, overwrite=False):
    """写 UTF-8 JSON；默认不覆盖，重名自动加 -2/-3。返回实际路径。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and path.exists():
        stem, suffix = path.stem, path.suffix
        index = 2
        while True:
            candidate = path.with_name(f"{stem}-{index}{suffix}")
            if not candidate.exists():
                path = candidate
                break
            index += 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path
