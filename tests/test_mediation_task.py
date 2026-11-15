import time
import unittest

from ok.test.TaskTestCase import TaskTestCase

import src.tasks.CommissionsTask as commissions
from src.config import config
from src.tasks.fullauto.AutoMediationTask_Fast import AutoMediationTask_Fast


class TestMediationTask(TaskTestCase):
    task_class = AutoMediationTask_Fast
    config = config

    _MUTATED = (
        "log_info", "send_key", "send_key_down", "send_key_up", "sleep",
        "solve_unlock", "use_ultimate", "wait_evac_ready_then_geniemon",
        "get_interact_key", "get_geniemon_key", "info_set", "screen_box",
        "wait_until",
        "play_mediation_route", "play_route_once", "unlock_completed",
        "solve_unlock", "is_in_combat", "ocr", "evac_ready_text", "release_all_keys",
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
        self.assertEqual(self.task.default_config["超时时间"], 90)
        self.assertIn("进本等待(秒)", self.task.default_config)
        self.assertEqual(self.task.default_config["进本等待(秒)"], 1.0)
        self.assertEqual(self.task.default_config["撤离点延迟(秒)"], 1.0)
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
        self.task.wait_evac_ready_then_geniemon = lambda: events.append(("evac",))
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

    def test_wait_evac_ready_then_geniemon(self):
        events = []
        self.task.evac_ready_text = lambda: True
        self.task.wait_until = lambda cond, time_out=0, raise_if_not_found=False: cond()
        self.task.sleep = lambda seconds: events.append(("sleep", seconds))
        self.task.send_key = lambda key, **kw: events.append(("key", key, kw.get("down_time")))
        self.task.get_geniemon_key = lambda: "3"
        self.task.wait_evac_ready_then_geniemon()
        self.assertEqual(events, [("sleep", 1.0), ("key", "3", 0.1)])

    def test_wait_evac_timeout_still_uses_geniemon(self):
        events = []
        self.task.evac_ready_text = lambda: False
        self.task.wait_until = lambda cond, time_out=0, raise_if_not_found=False: False
        self.task.sleep = lambda seconds: events.append(("sleep", seconds))
        self.task.send_key = lambda key, **kw: events.append(("key", key, kw.get("down_time")))
        self.task.get_geniemon_key = lambda: "3"
        self.task.wait_evac_ready_then_geniemon()
        self.assertEqual(events, [("sleep", 1.0), ("key", "3", 0.1)],
                         "流程必需的魔灵支援，超时也不能跳过")

    def test_timeout_counts_from_mission_start(self):
        saved_config = self.task.config
        try:
            self.task.config = {"超时时间": 180}
            now = time.time()
            self.assertFalse(self.task.timeout_expired(now - 10, now))
            self.assertTrue(self.task.timeout_expired(now - 200, now))
            self.assertFalse(self.task.timeout_expired(0, now))
        finally:
            self.task.config = saved_config

    def test_settlement_count_increments_once(self):
        self.task.info_set = lambda *args, **kwargs: None
        self.task.log_info = lambda *args, **kwargs: None
        self.task.session_count = 0
        self.task._settlement_counted = False
        self.task.count_settlement(False)
        self.assertEqual(self.task.session_count, 0)
        self.task.count_settlement(True)
        self.task.count_settlement(True)
        self.assertEqual(self.task.session_count, 1, "同一结算界面只加一场")
        self.task._settlement_counted = False
        self.task.count_settlement(True)
        self.assertEqual(self.task.session_count, 2)

    def test_release_all_keys_sends_ups(self):
        sent = []
        self.task.send_key_up = lambda key: sent.append(key)
        self.task.sleep = lambda seconds: None
        self.task.fidget_params = {"hold_lalt": True}
        self.task.get_dodge_key = lambda: "lshift"
        self.task.get_interact_key = lambda: "f"
        self.task.get_combat_key = lambda: "1"
        self.task.get_ultimate_key = lambda: "2"
        self.task.get_geniemon_key = lambda: "3"
        self.task.release_all_keys()
        for key in ("lalt", "w", "a", "s", "d", "space", "lshift", "f", "1", "2", "3"):
            self.assertIn(key, sent)
        self.assertFalse(self.task.fidget_params["hold_lalt"])

    def test_leave_mission_once_releases_keys_first(self):
        events = []
        self.task.release_all_keys = lambda: events.append("release")
        saved = commissions.CommissionsTask.leave_mission_once
        commissions.CommissionsTask.leave_mission_once = lambda self: events.append("step")
        try:
            self.task.leave_mission_once()
        finally:
            commissions.CommissionsTask.leave_mission_once = saved
        self.assertEqual(events, ["release", "step"])

    def test_give_up_releases_keys_first(self):
        events = []
        self.task.release_all_keys = lambda: events.append("release")
        saved = commissions.CommissionsTask.give_up_mission
        commissions.CommissionsTask.give_up_mission = lambda self, timeout=0: events.append("giveup")
        try:
            self.task.give_up_mission()
        finally:
            commissions.CommissionsTask.give_up_mission = saved
        self.assertEqual(events, ["release", "giveup"])

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
