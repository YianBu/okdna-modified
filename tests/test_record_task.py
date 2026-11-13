import json
import shutil
import unittest
from pathlib import Path

from src.tasks.fullauto.RecordScript import (
    actions_to_steps,
    key_name,
    normalize_hotkey,
    sanitize_name,
    steps_payload,
    write_json,
)


class FakeKey:
    def __init__(self, name=None, char=None):
        self.name = name
        self.char = char


class TestRecordScript(unittest.TestCase):

    def test_key_names_match_ok_conventions(self):
        self.assertEqual(key_name(FakeKey(char="W")), "w")
        self.assertEqual(key_name(FakeKey(name="space")), "space")
        self.assertEqual(key_name(FakeKey(name="shift")), "lshift")
        self.assertEqual(key_name(FakeKey(name="ctrl_l")), "lcontrol")
        self.assertEqual(key_name(FakeKey(name="f7")), "f7")
        self.assertIsNone(key_name(FakeKey()))

    def test_hotkey_names_are_normalized(self):
        self.assertEqual(normalize_hotkey("CapsLock"), "caps_lock")
        self.assertEqual(normalize_hotkey("ScrollLock"), "scroll_lock")
        self.assertEqual(normalize_hotkey("F7"), "f7")
        self.assertIsNone(normalize_hotkey("关闭"))

    def test_actions_to_steps_keeps_order_and_timing(self):
        actions = [
            {"type": "key_down", "key": "w", "time": 0.5},
            {"type": "key_down", "key": "lshift", "time": 0.55},
            {"type": "key_up", "key": "lshift", "time": 0.6},
            {"type": "key_up", "key": "w", "time": 1.5},
        ]
        steps = actions_to_steps(actions)
        self.assertEqual(steps[0], {"type": "wait", "seconds": 0.5})
        self.assertEqual(steps[1], {"type": "key_down", "key": "w"})
        self.assertEqual(steps[2], {"type": "wait", "seconds": 0.05})
        self.assertEqual(steps[-2], {"type": "key_up", "key": "w"})
        self.assertEqual(steps[-1]["type"], "log")

    def test_actions_to_steps_supports_arrow_mouse_move(self):
        actions = [
            {"type": "mouse_move", "dx": 20, "dy": 0, "time": 0.2},
            {"type": "mouse_move", "dx": 0, "dy": -20, "time": 0.3},
        ]
        steps = actions_to_steps(actions)
        self.assertEqual(steps[0], {"type": "wait", "seconds": 0.2})
        self.assertEqual(steps[1], {"type": "mouse_move", "dx": 20, "dy": 0})
        self.assertEqual(steps[3], {"type": "mouse_move", "dx": 0, "dy": -20})

    def test_mouse_scale_adjusts_view_movement(self):
        actions = [{"type": "mouse_move", "dx": 20, "dy": -10, "time": 0.1}]
        steps = actions_to_steps(actions, mouse_scale=1.5)
        self.assertEqual(steps[1], {"type": "mouse_move", "dx": 30, "dy": -15})

    def test_steps_payload_has_replay_fields(self):
        self.assertEqual(steps_payload("测试", [])["steps"], [])

    def test_sanitize_name_removes_windows_bad_chars(self):
        self.assertEqual(sanitize_name('a/b:c*?"<>|d'), "a_b_c_d")
        self.assertEqual(sanitize_name("   ", "录制"), "录制")

    def test_write_json_does_not_overwrite(self):
        folder = Path.cwd() / "_record_test_tmp"
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir()
        self.addCleanup(shutil.rmtree, folder, True)
        first = write_json(folder / "a.json", {"n": 1})
        second = write_json(folder / "a.json", {"n": 2})
        self.assertEqual(first.name, "a.json")
        self.assertEqual(second.name, "a-2.json")
        self.assertEqual(json.loads(first.read_text(encoding="utf-8"))["n"], 1)


if __name__ == "__main__":
    unittest.main()
