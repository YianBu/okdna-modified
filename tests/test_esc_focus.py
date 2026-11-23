# 统一 ESC 兜底：页面焦点 + 第一次 ESC 被吞时点画面重试
import time
import unittest
from unittest.mock import patch

from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.fullauto.AutoLeaveMissionTestTask import AutoLeaveMissionTestTask


class _FakeHwnd:
    def __init__(self, foreground):
        self.foreground = foreground
        self.bring_calls = 0

    def is_foreground(self):
        return self.foreground

    def bring_to_front(self):
        self.bring_calls += 1
        self.foreground = True
        return True


class _FakeInteraction:
    def __init__(self):
        self.activate_calls = 0
        self.focus_page_calls = 0

    def activate(self):
        self.activate_calls += 1

    def focus_page(self):
        self.focus_page_calls += 1


class TestEscFocus(TaskTestCase):
    task_class = AutoLeaveMissionTestTask
    config = config

    _PATCHED = ('sleep', 'is_browser', 'ensure_game_foreground', 'click_relative',
                'in_team', 'find_action_dialog_retreat', 'confirm_giveup_dialog',
                'find_esc_menu', 'find_retreat_button', 'send_key', 'wait_until',
                'click_game_to_focus', 'try_bring_to_front')

    def setUp(self):
        self._saved = {name: getattr(self.task, name) for name in self._PATCHED}
        self.task.sleep = lambda seconds: None

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(self.task, name, value)
        if '_last_focus_click' in self.task.__dict__:
            del self.task.__dict__['_last_focus_click']
        super().tearDown()

    def _patch_hwnd(self, fake):
        return patch.object(type(self.task), 'hwnd', new=property(lambda self: fake))

    def _patch_interaction(self, fake):
        return patch.object(type(self.task.executor), 'interaction',
                            new=property(lambda self: fake))

    # ---- 焦点：浏览器只做页面级处理，不切窗口 ----

    def test_foreground_native_window_does_nothing(self):
        hwnd = _FakeHwnd(foreground=True)
        interaction = _FakeInteraction()
        with self._patch_hwnd(hwnd), self._patch_interaction(interaction):
            self.task.is_browser = lambda: False
            self.assertFalse(self.task.ensure_game_foreground())
        self.assertEqual(hwnd.bring_calls, 0)
        self.assertEqual(interaction.activate_calls, 0)

    def test_browser_only_focuses_page_not_window(self):
        hwnd = _FakeHwnd(foreground=False)
        interaction = _FakeInteraction()
        with self._patch_hwnd(hwnd), self._patch_interaction(interaction):
            self.task.is_browser = lambda: True
            self.assertFalse(self.task.ensure_game_foreground(),
                             "浏览器模式不切窗口，返回值表示没有动窗口")
        self.assertEqual(hwnd.bring_calls, 0, "不能切走用户正在用的桌面")
        self.assertEqual(interaction.focus_page_calls, 1, "只抢页面焦点")

    def test_background_native_window_is_activated(self):
        hwnd = _FakeHwnd(foreground=False)
        interaction = _FakeInteraction()
        fronts = []
        with self._patch_hwnd(hwnd), self._patch_interaction(interaction):
            self.task.is_browser = lambda: False
            self.task.try_bring_to_front = lambda: fronts.append(1)
            self.assertTrue(self.task.ensure_game_foreground())
        self.assertEqual(fronts, [1])
        self.assertEqual(interaction.activate_calls, 1)

    # ---- 统一 ESC：第一次没打开就点画面，第二次再按 ----

    def test_press_esc_until_clicks_to_focus_then_retries(self):
        state = {"open": False, "waits": 0}
        calls = []
        self.task.send_key = lambda key, **k: calls.append(key)
        self.task.click_game_to_focus = lambda *a, **k: calls.append("click") or True

        def fake_wait(condition, **kwargs):
            state["waits"] += 1
            if state["waits"] == 2:
                state["open"] = True
            return condition()

        self.task.wait_until = fake_wait
        self.assertTrue(self.task.press_esc_until(lambda: state["open"], time_out=5))
        self.assertEqual(calls, ["esc", "click", "esc"])

    def test_leave_mission_once_uses_shared_esc_helper(self):
        state = {"open": False, "waits": 0}
        calls = []
        self.task.in_team = lambda *a, **k: True
        self.task.find_action_dialog_retreat = lambda *a, **k: None
        self.task.confirm_giveup_dialog = lambda *a, **k: False
        self.task.find_esc_menu = lambda *a, **k: "menu" if state["open"] else None
        self.task.find_retreat_button = lambda *a, **k: None
        self.task.send_key = lambda key, **k: calls.append(key)
        self.task.click_game_to_focus = lambda *a, **k: calls.append("click") or True

        def fake_wait(condition, **kwargs):
            state["waits"] += 1
            if state["waits"] == 2:
                state["open"] = True
            return condition()

        self.task.wait_until = fake_wait
        self.assertFalse(self.task.leave_mission_once())
        self.assertEqual(calls, ["esc", "click", "esc"])

    def test_press_esc_until_can_disable_click_on_ui_screens(self):
        state = {"open": False, "waits": 0}
        calls = []
        self.task.send_key = lambda key, **k: calls.append(key)
        self.task.click_game_to_focus = lambda *a, **k: calls.append("click") or True

        def fake_wait(condition, **kwargs):
            state["waits"] += 1
            if state["waits"] == 2:
                state["open"] = True
            return condition()

        self.task.wait_until = fake_wait
        self.assertTrue(self.task.press_esc_until(lambda: state["open"], time_out=5,
                                                  click_fallback=False))
        self.assertEqual(calls, ["esc", "esc"], "UI 画面上不能点中心，避免误按按钮")

    # ---- 点画面取焦点：只在浏览器里做，10 秒内只点一次 ----

    def test_click_game_to_focus_only_in_browser(self):
        clicks = []
        self.task.is_browser = lambda: False
        self.task.click_relative = lambda *a, **k: clicks.append(a)
        self.assertFalse(self.task.click_game_to_focus())
        self.assertEqual(clicks, [])

    def test_click_game_to_focus_is_rate_limited(self):
        clicks = []
        self.task.is_browser = lambda: True
        self.task.ensure_game_foreground = lambda: False
        self.task.click_relative = lambda *a, **k: clicks.append(a)
        self.task._last_focus_click = time.time()

        self.assertFalse(self.task.click_game_to_focus())
        self.assertEqual(clicks, [])
        self.assertTrue(self.task.click_game_to_focus(force=True))
        self.assertEqual(len(clicks), 1)


if __name__ == '__main__':
    unittest.main()
