# -*- coding: utf-8 -*-
"""「测试」页 - 退本测试：在局内单独验证正式任务共用的一套退本状态机。

正式任务里退本有两条入口，本任务原样调用，不另写一套：

  * 「放弃挑战」：`CommissionsTask.give_up_mission()` —— ESC 菜单 -> 放弃挑战 ->
    二次确认「确定」，一直等到回到开始/结算界面（超时重开、阵亡重开走这条）。
  * 「撤离」：`CommissionsTask.quit_mission()` —— 行动抉择弹窗点「撤离」；
    没有弹窗时同样走 ESC 菜单 -> 放弃挑战（打满轮次、回任务列表走这条）。
  * 「只打开 ESC 菜单」：只按 ESC 并确认菜单出来，用来核对菜单/按钮判据，
    不会真的退本。

用法：进入任意副本后启动本任务。设置「测试局数」可以连续测多次，每退一次
会提示重新进本；设 0 则一直循环到手动停止。
"""

import time

from qfluentwidgets import FluentIcon

from ok import Logger, TaskDisabledException

from src.tasks.BaseCombatTask import BaseCombatTask
from src.tasks.CommissionsTask import CommissionsTask
from src.tasks.DNAOneTimeTask import DNAOneTimeTask

logger = Logger.get_logger(__name__)

LEAVE_GIVE_UP = "放弃挑战（ESC 菜单）"
LEAVE_RETREAT = "撤离（行动抉择弹窗）"
LEAVE_MENU_ONLY = "只打开 ESC 菜单"
LEAVE_METHODS = (LEAVE_GIVE_UP, LEAVE_RETREAT, LEAVE_MENU_ONLY)


class AutoLeaveMissionTestTask(DNAOneTimeTask, CommissionsTask, BaseCombatTask):
    """把退本单独拎出来跑：进本后启动，按选中的方式退本并报告结果。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.CLOSE
        self.name = "退本测试"
        self.description = "测试"
        self.group_name = "测试"
        self.group_icon = FluentIcon.DEVELOPER_TOOLS

        self.default_config.update({
            "退本方式": LEAVE_GIVE_UP,
            "测试局数": 1,
            "超时时间(秒)": 30,
        })
        self.config_type["退本方式"] = {
            "type": "drop_down",
            "options": list(LEAVE_METHODS),
        }
        self.config_description.update({
            "退本方式": "放弃挑战 / 撤离都调用正式任务同一套状态机；"
                        "只打开 ESC 菜单用于核对菜单判据",
            "测试局数": "连续测几次退本；0 = 一直重复（每次退本后按提示重新进本；"
                        "只打开 ESC 菜单时只测一次）",
            "超时时间(秒)": "单次退本最多等多久（下限 30 秒）；到点还没退出去就判定失败",
        })

    def run(self):
        DNAOneTimeTask.run(self)
        self.move_mouse_to_safe_position(save_current_pos=False)
        self.set_check_monthly_card()
        try:
            return self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error("AutoLeaveMissionTestTask error", e)
            raise

    def do_run(self):
        method = self.config.get("退本方式", LEAVE_GIVE_UP)
        if method == LEAVE_MENU_ONLY:
            self.run_menu_only()
            return

        rounds = self.test_rounds()
        loop = rounds <= 0
        done = 0
        self.log_info(f"『退本测试』：{method}；进入副本后开始")
        self.log_info_notify("退本测试已启动，请进入副本")
        while loop or done < rounds:
            if not self.wait_in_team():
                return
            done += 1
            self.log_info(f"[测试] 第 {done} 次退本，当前画面：{self.describe_screen()}")
            if not self.leave_once(method):
                return
            if done == rounds:
                break
            self.log_info("请重新进入副本，下一轮会自动继续（随时可以停止任务）")
            self.log_info_notify("请重新进入副本")
        self.log_info_notify(f"退本测试完成（{done} 次）")
        self.soundBeep()

    def test_rounds(self):
        try:
            return int(self.config.get("测试局数", 1))
        except (TypeError, ValueError):
            return 1

    def leave_timeout(self):
        try:
            return max(30.0, float(self.config.get("超时时间(秒)", 30)))
        except (TypeError, ValueError):
            return 30.0

    def wait_in_team(self):
        """等到进本；任务被手动停止时由 next_frame/sleep 抛 TaskDisabledException。"""
        announced = False
        while True:
            self.next_frame()
            if self.in_team():
                return True
            if not announced:
                self.log_info("等待进入副本……")
                announced = True
            self.sleep(0.5)

    def describe_screen(self):
        """把这一帧认到的界面拼成一行，退本前后各打一次，方便看状态机走到哪。"""
        states = []
        if self.in_team():
            states.append("局内")
        if self.find_start_interface():
            states.append("开始界面")
        if self.find_result_again_btn():
            states.append("结算界面")
        if self.find_action_dialog_continue():
            states.append("行动抉择")
        if self.find_esc_menu():
            states.append("ESC菜单")
        return "/".join(states) if states else "未识别"

    def leave_once(self, method):
        """按配置跑一次正式退本流程，成功/失败都写日志并返回结果。"""
        timeout = self.leave_timeout()
        started = time.time()
        self.log_info(f"[测试] 开始退本：{method}（超时 {timeout:.0f} 秒）")
        # give_up_mission/quit_mission 内部的截止时间是 max(30, timeout*2)；
        # 折半传入，让配置里的「超时时间」就是实际最长等待（下限仍是 30 秒）。
        state_timeout = timeout / 2
        if method == LEAVE_RETREAT:
            left = self.quit_mission(timeout=state_timeout)
        else:
            left = self.give_up_mission(timeout=state_timeout)
        elapsed = time.time() - started

        if left and self.wait_until(lambda: not self.in_team(), time_out=3,
                                    raise_if_not_found=False):
            self.log_info(f"[测试] 退本成功，用时 {elapsed:.1f} 秒；"
                          f"当前画面：{self.describe_screen()}")
            return True

        self.log_info_notify(f"退本失败（用时 {elapsed:.1f} 秒，仍在局内），测试结束")
        self.soundBeep()
        return False

    def run_menu_only(self):
        """只验证 ESC 菜单能不能打开，不点任何退本按钮。"""
        self.log_info("『退本测试』：只打开 ESC 菜单，核对菜单判据")
        if not self.wait_in_team():
            return
        self.log_info(f"[测试] 当前画面：{self.describe_screen()}")
        timeout = self.leave_timeout()
        if self.open_in_mission_menu(time_out=timeout, raise_if_not_found=False):
            self.log_info("[测试] ESC 菜单已打开，任务结束（按 ESC 可关闭菜单）")
            self.log_info_notify("ESC 菜单已打开")
        else:
            self.log_info_notify(f"ESC 菜单没打开（{timeout:.0f} 秒超时）")
            self.soundBeep()
