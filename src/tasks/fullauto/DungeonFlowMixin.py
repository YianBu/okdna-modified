import time

from src.tasks.CommissionsTask import CommissionsTask, Mission, _default_movement
from src.tasks.fullauto.DungeonActionLogic import MODE_DEFENCE, MODE_EXPLORATION
from src.tasks.fullauto.DungeonSignals import DungeonSignalsMixin


class DungeonFlowMixin(DungeonSignalsMixin):
    """扼守 / 探险副本的通用局内循环。

    原先由「自动扼守」「自动探险」两个独立任务类提供，现在直接并进使用它的
    全自动任务里。任务只需要在启动时设置 ``dungeon_flow_mode``，并提供一个
    可选的 ``external_movement``（走位函数），然后调用 ``run_dungeon_flow()``。

    注意：本 mixin 要放在 DNAOneTimeTask / CommissionsTask 前面，这样它的
    ``is_in_combat`` 才会优先于 CommissionsTask 的默认实现。
    """

    dungeon_flow_mode = None

    def setup_dungeon_flow(self, mode, add_afk_config=True):
        """初始化局内循环需要的状态和技能计时器。

        ``add_afk_config=False`` 时沿用任务自己的配置，不额外加「挂机模式」
        「战斗侦测」两项（ImportTask 这种外部逻辑任务用）。
        """
        self.dungeon_flow_mode = mode
        self.external_movement = _default_movement
        self.skill_tick = self.create_skill_ticker()
        self._mission_started = False
        self.action_timeout = getattr(self, "action_timeout", 10)
        if add_afk_config:
            self.setup_mission_start_config()
            self.setup_combat_detection_config()

    def is_in_combat(self):
        """按当前副本类型取开战判据。"""
        if self.dungeon_flow_mode == MODE_EXPLORATION:
            return self.find_serum()
        if self.dungeon_flow_mode == MODE_DEFENCE and self.find_target_wave():
            return True
        return CommissionsTask.is_in_combat(self)

    def run_dungeon_flow(self):
        """跑完一次扼守 / 探险副本流程，直到任务被手动停止。"""
        self._dungeon_init_all()
        self.load_char()

        if self.external_movement is not _default_movement and self.in_team():
            self.open_in_mission_menu()

        while True:
            if self.in_team():
                if self.move_on_begin():
                    self._dungeon_handle_in_mission()

            _status = self.handle_mission_interface(stop_func=self._dungeon_stop_func)
            if _status == Mission.START:
                self.wait_until(self.in_team, time_out=30)
                self._dungeon_init_all()
                self._dungeon_handle_mission_start()
            elif _status == Mission.STOP:
                self.log_info("任务中止")
                self.quit_mission()
            elif _status == Mission.CONTINUE:
                self.log_info("任务继续")
                self._dungeon_init_for_next_round()
                self.wait_until(self.in_team, time_out=self.action_timeout)

            self.sleep(0.1)

    def _dungeon_init_all(self):
        self._dungeon_init_for_next_round()
        self.skill_tick.reset()
        self.current_round = 0
        self._mission_started = False

    def _dungeon_init_for_next_round(self):
        self._dungeon_init_runtime_state()

    def _dungeon_init_runtime_state(self):
        if self.dungeon_flow_mode == MODE_EXPLORATION:
            self.runtime_state = {"start_time": 0, "wait_next_round": False}
        else:
            self.runtime_state = {"wave_start_time": 0, "wave": -1, "wait_next_wave": False}
            self.reset_wave_info()

    def _dungeon_handle_in_mission(self):
        if self.dungeon_flow_mode == MODE_EXPLORATION:
            self._dungeon_handle_exploration_in_mission()
        else:
            self._dungeon_handle_defence_in_mission()

    def _dungeon_handle_defence_in_mission(self):
        self.get_wave_info()
        in_combat = self.current_wave != -1
        if in_combat:
            if self.current_wave != self.runtime_state["wave"]:
                self.runtime_state.update(
                    {"wave": self.current_wave, "wave_start_time": time.time(), "wait_next_wave": False})

            if (not self.runtime_state["wait_next_wave"] and self.combat_detection_enabled()
                    and time.time() - self.runtime_state["wave_start_time"] >= self.config.get("超时时间", 120)):
                if self.external_movement is not _default_movement:
                    self.log_info("任务超时")
                    self.give_up_mission()
                    return
                self.log_info_notify("任务超时")
                self.soundBeep()
                self.runtime_state["wait_next_wave"] = True
        elif self.runtime_state["wave"] > 0:
            self._dungeon_init_runtime_state()

        if not self.runtime_state["wait_next_wave"] and self.skills_ready(in_combat):
            self.skill_tick()

    def _dungeon_handle_exploration_in_mission(self):
        in_combat = self.find_serum()
        if in_combat:
            if self.runtime_state["start_time"] == 0:
                self.runtime_state["start_time"] = time.time()

            if (not self.runtime_state["wait_next_round"] and self.combat_detection_enabled()
                    and time.time() - self.runtime_state["start_time"] >= self.config.get("超时时间", 120)):
                if self.external_movement is not _default_movement:
                    self.log_info("任务超时")
                    self.give_up_mission()
                    return
                self.log_info_notify("任务超时")
                self.soundBeep()
                self.runtime_state["wait_next_round"] = True
        elif self.runtime_state["start_time"] > 0:
            self._dungeon_init_runtime_state()

        if not self.runtime_state["wait_next_round"] and self.skills_ready(in_combat):
            self.skill_tick()

    def _dungeon_handle_mission_start(self):
        if self.external_movement is not _default_movement:
            if self.dungeon_flow_mode == MODE_DEFENCE:
                self.log_info("任务开始，执行外部移动逻辑")
            else:
                self.log_info("任务开始")
            self.external_movement(delay=2)
            if self.dungeon_flow_mode == MODE_DEFENCE and not self.in_team():
                self.log_info("外部移动后未在队伍中（可能复位失败已退出副本），等待重开任务")
                return

            time_out = self.action_timeout + 10
            self.log_info(f"外部移动执行完毕，等待战斗开始，{time_out}秒后超时")
            if self.dungeon_flow_mode == MODE_DEFENCE:
                started = self.wait_until(lambda: self.is_in_combat() or self.find_esc_menu(),
                                          post_action=self.get_wave_info, time_out=time_out)
            else:
                started = self.wait_until(lambda: self.is_in_combat() or self.find_esc_menu(),
                                          time_out=time_out)
            if not started:
                self.log_info("等待战斗开始超时，重开任务")
                self.open_in_mission_menu()
            else:
                self.log_info("战斗开始")
        else:
            self.sleep(2)
            self.log_info_notify("任务开始")
            self.soundBeep()

    def _dungeon_stop_func(self):
        self.get_round_info()
        return self.current_round >= self.config.get("轮次", 3)
