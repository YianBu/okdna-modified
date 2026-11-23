# 数字配置的下限：默认值 > 0 也要允许调到 0（0 = 不限制/无限）
import time
import unittest

from ok.test.TaskTestCase import TaskTestCase
from ok.ui.qt.tasks.config_editors import config_editor

from src.config import config
from src.tasks.fullauto.AutoMijinTask import AutoMijinTask
from src.tasks.fullauto.AutoHuntMoonTask import AutoHuntMoonTask


class _FakeConfig:
    def __init__(self, values):
        self.values = values

    def get_default(self, key):
        return self.values.get(key)

    def get(self, key):
        return self.values.get(key)


class TestConfigNumberMin(TaskTestCase):
    task_class = AutoHuntMoonTask
    config = config

    def test_positive_default_allows_zero(self):
        editor = config_editor({}, {"超时重启": ""}, _FakeConfig({"超时重启": 60}),
                               "超时重启", 60, self.task)
        self.assertEqual(editor.spin_box.spin_box.minimum(), 0,
                         "默认 60 的超时重启也必须能调到 0")

    def test_explicit_min_still_wins(self):
        editor = config_editor({"x": {"min": 1}}, {"x": ""}, _FakeConfig({"x": 60}),
                               "x", 60, self.task)
        self.assertEqual(editor.spin_box.spin_box.minimum(), 1)

    def test_hunt_moon_timeout_zero_means_unlimited(self):
        original = self.task.config
        try:
            self.task.config = {"超时重启": 0, "打几次": 0}
            self.assertEqual(self.task.combat_timeout(), 0)
        finally:
            self.task.config = original


class TestMijinTimeoutZero(TaskTestCase):
    task_class = AutoMijinTask
    config = config

    def test_timeout_zero_is_unlimited(self):
        original_config = self.task.config
        had_done = hasattr(self.task, "sequence_done")
        original_done = getattr(self.task, "sequence_done", False)
        original_start = getattr(self.task, "round_start_time", 0.0)
        try:
            self.task.config = {"超时时间": 0}
            self.task.sequence_done = True
            self.task.round_start_time = time.time() - 9999
            self.assertFalse(self.task.round_timed_out())
        finally:
            self.task.config = original_config
            if had_done:
                self.task.sequence_done = original_done
            else:
                del self.task.sequence_done
            self.task.round_start_time = original_start


if __name__ == '__main__':
    unittest.main()
