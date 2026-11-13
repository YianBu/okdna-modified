import unittest

from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.fullauto.AutoMediationTask_Fast import AutoMediationTask_Fast


class TestMediationTask(TaskTestCase):
    task_class = AutoMediationTask_Fast
    config = config

    _MUTATED = (
        "log_info", "send_key", "send_key_down", "send_key_up", "sleep",
        "solve_unlock", "use_ultimate", "wait_evac_green_then_geniemon",
        "get_interact_key", "get_geniemon_key", "info_set", "screen_box",
        "calculate_color_percentage", "evac_icon_green", "wait_until",
        "play_mediation_route", "play_route_once", "unlock_completed",
        "solve_unlock", "is_in_combat", "ocr", "evac_ready_text",
    )

    def setUp(self):
        self._saved = {name: getattr(self.task, name) for name in self._MUTATED}

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(self.task, name, value)
        super().tearDown()

    def test_name_group_and_note(self):
        self.assertEqual(self.task.name, "自动调停/老道")
        self.assertEqual(self.task.group_name, "全自动（日常）")
        self.assertNotIn("备注", self.task.default_config)
        self.assertIn("超时时间", self.task.default_config)
        self.assertIn("进本等待(秒)", self.task.default_config)
        self.assertEqual(self.task.default_config["撤离点延迟(秒)"], 2.0)
        self.assertNotIn("行动逻辑文件", self.task.default_config)

    def test_route_only_once_per_mission(self):
        calls = []
        saved_route = self.task.play_mediation_route
        saved_sleep = self.task.sleep
        saved_config = self.task.config
        try:
            self.task.play_mediation_route = lambda: calls.append(1)
            self.task.sleep = lambda seconds=0: None
            self.task.config = {"进本等待(秒)": 0}
            self.task._steps_done_this_mission = False
            self.task.play_route_once()
            self.task.play_route_once()
            self.assertEqual(len(calls), 1, "同一局只该跑一次开场")

            self.task.init_all()
            self.task.play_route_once()
            self.assertEqual(len(calls), 2, "新一局要重新跑开场")
        finally:
            self.task.play_mediation_route = saved_route
            self.task.sleep = saved_sleep
            self.task.config = saved_config

    def test_route_sequence(self):
        events = []
        self.task.log_info = lambda *args, **kwargs: None
        self.task.send_key_down = lambda key: events.append(("down", key))
        self.task.send_key_up = lambda key: events.append(("up", key))
        self.task.sleep = lambda seconds: events.append(("sleep", seconds))
        self.task.solve_unlock = lambda: events.append(("solve",))
        self.task.use_ultimate = lambda: events.append(("ultimate",))
        self.task.wait_evac_green_then_geniemon = lambda: events.append(("evac",))
        self.task.get_interact_key = lambda: "f"
        self.task.get_dodge_key = lambda: "lshift"
        self.task.play_mediation_route()
        self.assertEqual(events, [
            ("sleep", 1.0), ("down", "lalt"), ("sleep", 0.1), ("down", "w"),
            ("sleep", 0.262), ("down", "lshift"), ("sleep", 2.243),
            ("up", "lshift"), ("sleep", 0.148), ("up", "w"), ("up", "lalt"),
            ("solve",), ("ultimate",), ("evac",),
            ("up", "w"), ("up", "a"), ("up", "lshift"), ("up", "lalt"),
            ("up", "f"), ("up", "space"),
        ])

    def test_evac_green_threshold(self):
        self.task.info_set = lambda *args, **kwargs: None
        self.task.screen_box = lambda name: "box"
        self.task.calculate_color_percentage = lambda color, box: 0.004
        self.assertTrue(self.task.evac_icon_green())
        self.task.calculate_color_percentage = lambda color, box: 0.002
        self.assertFalse(self.task.evac_icon_green())

    def test_wait_green_then_geniemon(self):
        events = []
        self.task.evac_icon_green = lambda: True
        self.task.evac_ready_text = lambda: True
        self.task.wait_until = lambda cond, time_out=0, raise_if_not_found=False: cond()
        self.task.sleep = lambda seconds: events.append(("sleep", seconds))
        self.task.send_key = lambda key, **kw: events.append(("key", key, kw.get("down_time")))
        self.task.get_geniemon_key = lambda: "3"
        self.task.wait_evac_green_then_geniemon()
        self.assertEqual(events, [("sleep", 2.0), ("key", "3", 0.1)])

    def test_wait_evac_timeout_still_uses_geniemon(self):
        events = []
        self.task.evac_ready_text = lambda: False
        self.task.evac_icon_green = lambda: False
        self.task.wait_until = lambda cond, time_out=0, raise_if_not_found=False: False
        self.task.sleep = lambda seconds: events.append(("sleep", seconds))
        self.task.send_key = lambda key, **kw: events.append(("key", key, kw.get("down_time")))
        self.task.get_geniemon_key = lambda: "3"
        self.task.wait_evac_green_then_geniemon()
        self.assertEqual(events, [("sleep", 2.0), ("key", "3", 0.1)],
                         "流程必需的魔灵支援，超时也不能跳过")

    def test_text_criterion_has_priority(self):
        checked = []
        self.task.evac_ready_text = lambda: True
        self.task.evac_icon_green = lambda: checked.append("icon") or True
        self.task.wait_until = lambda cond, time_out=0, raise_if_not_found=False: cond()
        self.task.sleep = lambda seconds: None
        self.task.send_key = lambda *args, **kwargs: None
        self.task.get_geniemon_key = lambda: "3"
        self.task.wait_evac_green_then_geniemon()
        self.assertEqual(checked, [], "文字已确认时不再等绿色图标")

    def test_unlock_completed_reads_objective(self):
        class Item:
            def __init__(self, name):
                self.name = name

        self.task.screen_box = lambda name: "box"
        self.task.ocr = lambda box=None, match=None: [Item("破坏\u201c大烟花\u201d的引信，阻止爆炸")]
        self.assertTrue(self.task.unlock_completed())
        self.task.ocr = lambda box=None, match=None: [Item("破解机关，暴露\u201c大烟花\u201d的引信")]
        self.assertFalse(self.task.unlock_completed(), "图1还在破解机关，不能算解锁完成")
        self.task.ocr = lambda box=None, match=None: [Item("可前往撤离点")]
        self.assertFalse(self.task.unlock_completed(), "可前往撤离点是打完柱子后的目标")
        self.task.ocr = lambda box=None, match=None: []
        self.assertFalse(self.task.unlock_completed())

    def test_solve_unlock_stops_when_objective_done(self):
        calls = []
        self.task.is_in_combat = lambda: False
        self.task.unlock_completed = lambda: bool(calls)
        self.task.get_interact_key = lambda: "f"
        self.task.send_key = lambda key, **kw: calls.append(key)
        self.task.sleep = lambda seconds: None
        self.assertTrue(self.task.solve_unlock(time_out=2, interval=0, check_interval=0))
        self.assertEqual(calls, ["f"], "目标完成后不再继续按 F")



if __name__ == "__main__":
    unittest.main()
