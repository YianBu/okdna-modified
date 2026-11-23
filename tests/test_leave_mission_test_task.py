# 「测试」板块 -「退本测试」任务：配置面 + 两种正式退本入口的分派
#
# 用例只钉任务自己的行为（选哪种退本方式、有没有真的调正式状态机），
# 退本状态机本身由 CommissionsTask 负责。
import unittest

from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.fullauto.AutoLeaveMissionTestTask import (
    LEAVE_GIVE_UP,
    LEAVE_MENU_ONLY,
    LEAVE_METHODS,
    LEAVE_RETREAT,
    AutoLeaveMissionTestTask,
)


class TestLeaveMissionTestTask(TaskTestCase):
    task_class = AutoLeaveMissionTestTask
    config = config

    _PATCHED = ('in_team', 'next_frame', 'sleep', 'soundBeep', 'log_info',
                'log_info_notify', 'config', 'give_up_mission', 'quit_mission',
                'open_in_mission_menu', 'describe_screen', 'wait_until',
                'ensure_game_foreground', 'leave_once')

    def setUp(self):
        self._saved = {name: getattr(self.task, name) for name in self._PATCHED}
        self.task.next_frame = lambda *a, **k: None
        self.task.sleep = lambda seconds: None
        self.task.soundBeep = lambda *a, **k: None
        self.task.log_info = lambda *a, **k: None
        self.task.log_info_notify = lambda *a, **k: None
        self.task.describe_screen = lambda: "局内"
        self.task.wait_until = lambda *a, **k: True
        self.task.ensure_game_foreground = lambda: None

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(self.task, name, value)
        super().tearDown()

    # ---- 归到「测试」板块 ----

    def test_belongs_to_test_group(self):
        self.assertEqual(self.task.group_name, "测试")
        self.assertEqual(self.task.name, "退本测试")

    def test_config_defaults_and_options(self):
        self.assertEqual(self.task.default_config["退本方式"], LEAVE_GIVE_UP)
        self.assertEqual(self.task.default_config["测试局数"], 1)
        self.assertEqual(self.task.config_type["退本方式"]["options"],
                         list(LEAVE_METHODS))

    # ---- 两种正式退本入口 ----

    def test_give_up_uses_shared_state_machine(self):
        calls = []
        state = {"in_team": True}
        self.task.config = {"退本方式": LEAVE_GIVE_UP, "测试局数": 1, "超时时间(秒)": 30}
        self.task.in_team = lambda *a, **k: state["in_team"]

        def give_up(timeout=0):
            calls.append(("give_up", timeout))
            state["in_team"] = False
            return True

        self.task.give_up_mission = give_up
        self.task.quit_mission = lambda *a, **k: self.fail("放弃挑战不该走撤离")
        self.task.do_run()
        # 配置 30 秒 -> 状态机内部 max(30, timeout*2)，折半传入刚好 30 秒
        self.assertEqual(calls, [("give_up", 15)])

    def test_retreat_uses_quit_mission(self):
        calls = []
        state = {"in_team": True}
        self.task.config = {"退本方式": LEAVE_RETREAT, "测试局数": 1, "超时时间(秒)": 30}
        self.task.in_team = lambda *a, **k: state["in_team"]

        def quit_mission(timeout=0):
            calls.append(("quit", timeout))
            state["in_team"] = False
            return True

        self.task.quit_mission = quit_mission
        self.task.give_up_mission = lambda *a, **k: self.fail("撤离不该走放弃挑战")
        self.task.do_run()
        self.assertEqual(calls, [("quit", 15)])

    # ---- 只开菜单：绝不点退本按钮 ----

    def test_menu_only_does_not_leave_mission(self):
        calls = []
        self.task.config = {"退本方式": LEAVE_MENU_ONLY, "测试局数": 1, "超时时间(秒)": 5}
        self.task.in_team = lambda *a, **k: True
        self.task.give_up_mission = lambda *a, **k: self.fail("只开菜单不该放弃挑战")
        self.task.quit_mission = lambda *a, **k: self.fail("只开菜单不该撤离")
        self.task.open_in_mission_menu = lambda **kwargs: calls.append(kwargs) or True
        self.task.do_run()
        # 配置 5 秒会被下限抬到 30 秒
        self.assertEqual(calls, [{"time_out": 30.0, "raise_if_not_found": False}])

    def test_failure_retries_instead_of_stopping(self):
        """退本失败不再直接结束：等 2 秒重试；成功那次才收尾并响一声。"""
        calls, beeps = [], []
        self.task.config = {"退本方式": LEAVE_GIVE_UP, "测试局数": 1, "超时时间(秒)": 30}
        self.task.in_team = lambda *a, **k: True
        self.task.soundBeep = lambda *a, **k: beeps.append(1)

        def leave_once(method):
            calls.append(method)
            return len(calls) > 1  # 第一次失败，第二次成功

        self.task.leave_once = leave_once
        self.task.do_run()
        self.assertEqual(calls, [LEAVE_GIVE_UP, LEAVE_GIVE_UP], '失败后应重试')
        self.assertEqual(beeps, [1], '成功完成后才响一声')


if __name__ == '__main__':
    unittest.main()
