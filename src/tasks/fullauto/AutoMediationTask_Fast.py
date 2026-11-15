import re
import time

from qfluentwidgets import FluentIcon

from src.tasks.AutoExpulsion import AutoExpulsion
from src.tasks.CommissionsTask import Mission
from src.tasks.fullauto.DungeonActionMixin import (
    EXPLORATION_ALT_SETTLE_TIME,
    EXPLORATION_RUN_SETTLE_TIME,
)

DEFAULT_TIMEOUT = 90
DEFAULT_SETTLE = 1.0

# 4.json 的移动段（F 之前）；Alt/W 起手参考自动探险
OPEN_W_BEFORE_SHIFT = 0.262
OPEN_SHIFT_TIME = 2.243
OPEN_AFTER_SHIFT = 0.148          # 0.048 + 100ms：W 多走一点，确保碰到开关
EVAC_READY_TIMEOUT = 30
DEFAULT_EVAC_DELAY = 1.0

# 退本前统一松开的键。云游戏里 Alt 按着时 ESC 会变成 Alt+Esc，菜单打不开。
RELEASE_KEYS = (
    "lalt", "ralt", "alt_l", "alt_r", "alt",
    "lshift", "rshift", "shift", "shift_l", "shift_r",
    "lcontrol", "rcontrol", "ctrl", "ctrl_l", "ctrl_r",
    "control", "lctrl", "rctrl",
    "w", "a", "s", "d", "space", "tab", "enter", "esc",
    "1", "2", "3", "4", "f", "q", "e", "r",
)
# 图1「破解机关，暴露“大烟花”的引信」还在破解机关，不算解锁完成；
# 图2「破坏“大烟花”的引信，阻止爆炸」才是解锁完成。
# 「可前往撤离点」是打完柱子之后的目标，也不用于解锁判据。
UNLOCK_DONE_RE = re.compile(r'破坏.*引信|阻止爆炸')
# 柱子打完、撤离点可用时，左侧目标变成「可前往撤离点」
EVAC_READY_RE = re.compile(r'可前往撤离点|前往撤离点')


class AutoMediationTask_Fast(AutoExpulsion):
    """「自动调停/老道」：开场走位 -> 解锁 -> 终结技 -> 等撤离点变绿 -> 魔灵支援。

    和「自动驱离」共用 CommissionsTask 状态机（开始/委托手册/密函/结算/再次进行），
    所以结算后自动点「再次进行」，下一局重新走一遍，循环到手动停止。

    队伍备注：使用 黎瑟 + 巧手 + 老道。

    进本后：
      1) 进本等待（默认 1 秒）；
      2) 开场 Alt/W 参考自动探险：先稳 1 秒，Alt 按住，100ms 后按 W；
         然后走 W 2.653s（0.262s 后 Shift 按住 2.243s，Shift 松开后再走 148ms），W 松开后
         立刻松 Alt；
      3) 反复 F 破解解锁；左侧目标变成「破坏“大烟花”的引信，阻止爆炸」就停，
         不再死等开战（「可前往撤离点」是打完柱子后的目标，不用于解锁判据）；
      4) 按终结技；
      5) 文字确认「可前往撤离点」后延迟 1 秒按魔灵支援。
    4.json 里固定两下 F 不再使用；解锁改为反复 F + 目标文字 OCR。

    和自动驱离一样，从「调停/老道」的开始界面启动，不自动在委托列表里选任务。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.FLAG
        self.name = "自动调停/老道"
        self.description = "全自动（使用黎瑟+巧手+老道，可带两个高伤C打柱子）"
        self.group_name = "全自动（日常）"
        self.group_icon = FluentIcon.CALENDAR

        self.default_config.update({
            "超时时间": DEFAULT_TIMEOUT,
            "进本等待(秒)": DEFAULT_SETTLE,
            "撤离点延迟(秒)": DEFAULT_EVAC_DELAY,
        })
        self.config_description.update({
            "超时时间": "进本后超过这么久还没结束就放弃并重开",
            "进本等待(秒)": "进本可控后先等这么久再开始开场移动；默认 1 秒",
            "撤离点延迟(秒)": "确认可前往撤离点后，等这么久再按魔灵支援；默认 1 秒",
        })

        # 走位固定，不需要自动驱离那套随机游走/挂机开局配置
        for key in ("随机游走", "挂机模式", "开局向前走"):
            self.default_config.pop(key, None)

        self._steps_done_this_mission = False
        self.session_count = 0
        self._settlement_counted = False

    # ------------------------------------------------------------------
    # 固定开场路线
    # ------------------------------------------------------------------
    def play_route_once(self):
        if self._steps_done_this_mission:
            return
        self._steps_done_this_mission = True
        self._settlement_counted = False
        try:
            wait = float(self.config.get("进本等待(秒)", DEFAULT_SETTLE))
        except (TypeError, ValueError):
            wait = DEFAULT_SETTLE
        if wait > 0:
            self.log_info(f"[自动调停/老道] 进本可控，等待 {wait:g} 秒后开始")
            self.sleep(wait)
        self.play_mediation_route()

    def play_mediation_route(self):
        self.log_info("[自动调停/老道] 开场移动")
        self.sleep(EXPLORATION_RUN_SETTLE_TIME)
        dodge = self.get_dodge_key()
        self.send_key_down("lalt")
        try:
            self.sleep(EXPLORATION_ALT_SETTLE_TIME)
            self.send_key_down("w")
            self.sleep(OPEN_W_BEFORE_SHIFT)
            self.send_key_down(dodge)
            self.sleep(OPEN_SHIFT_TIME)
            self.send_key_up(dodge)
            self.sleep(OPEN_AFTER_SHIFT)
            self.send_key_up("w")
            self.send_key_up("lalt")
            self.solve_unlock()
            self.use_ultimate()
            self.wait_evac_ready_then_geniemon()
        finally:
            self.send_key_up("w")
            self.send_key_up("a")
            self.send_key_up(dodge)
            self.send_key_up("lalt")
            self.send_key_up(self.get_interact_key())
            self.send_key_up("space")

    def unlock_completed(self):
        """左侧任务目标变成「破坏“大烟花”的引信，阻止爆炸」= 解锁完成。"""
        return bool(UNLOCK_DONE_RE.search(self.read_objective_text()))

    def read_objective_text(self):
        box = self.screen_box("MEDIATION_OBJECTIVE")
        found = self.ocr(box=box, match=None)
        return " ".join(item.name for item in found if getattr(item, "name", None))

    def evac_ready_text(self):
        """柱子打完、撤离点可用：左侧目标变成「可前往撤离点」。"""
        return bool(EVAC_READY_RE.search(self.read_objective_text()))

    def solve_unlock(self, time_out=10, interval=0.0, check_interval=0.5):
        """反复 F 解锁；F 约 100ms 一次，目标/开战判据每 0.5 秒查一次。"""
        self.log_info("[自动调停/老道] 反复 F 解锁")
        deadline = time.time() + time_out
        next_check = 0.0
        while time.time() < deadline:
            now = time.time()
            if now >= next_check:
                if self.is_in_combat() or self.unlock_completed():
                    self.log_info("[自动调停/老道] 解锁完成")
                    return True
                next_check = now + check_interval
            self.send_key(self.get_interact_key(), down_time=0.1)
            self.sleep(interval)
        done = self.is_in_combat() or self.unlock_completed()
        if done:
            self.log_info("[自动调停/老道] 解锁完成")
        return done

    def use_ultimate(self):
        self.log_info("[自动调停/老道] 解锁后使用终结技")
        self.send_key(self.get_ultimate_key(), down_time=0.1)

    def wait_evac_ready_then_geniemon(self):
        # 只看文字：目标变「可前往撤离点」= 柱子打完。文字超时也继续按流程使用。
        self.log_info("[自动调停/老道] 等待柱子打完…")
        text_ok = self.wait_until(self.evac_ready_text, time_out=EVAC_READY_TIMEOUT,
                                  raise_if_not_found=False)
        if not text_ok:
            self.log_info("等待「可前往撤离点」超时，仍按流程使用魔灵支援")
        else:
            self.log_info("文字已确认可前往撤离点")
        try:
            delay = float(self.config.get("撤离点延迟(秒)", DEFAULT_EVAC_DELAY))
        except (TypeError, ValueError):
            delay = DEFAULT_EVAC_DELAY
        if delay > 0:
            self.sleep(delay)
        self.log_info("[自动调停/老道] 使用魔灵支援")
        self.send_key(self.get_geniemon_key(), down_time=0.1)

    def release_all_keys(self):
        """松开所有可能按住的键；退本/ESC 前必须调用，避免 Alt+Esc。"""
        self.fidget_params["hold_lalt"] = False
        self.sleep(0.05)
        keys = set(RELEASE_KEYS)
        for getter in ("get_dodge_key", "get_interact_key", "get_combat_key",
                       "get_ultimate_key", "get_geniemon_key", "get_spiral_dive_key"):
            try:
                key = getattr(self, getter)()
                if key:
                    keys.add(str(key))
            except Exception:
                pass
        for key in keys:
            try:
                self.send_key_up(key)
            except Exception:
                pass
        self.sleep(0.15)

    def leave_mission_once(self):
        # 每一步退本前都松键；ESC 不生效时 give_up_mission 会继续循环重试
        self.release_all_keys()
        return super().leave_mission_once()

    def give_up_mission(self, timeout=0):
        self.log_info("[自动调停/老道] 放弃前先松开所有按键")
        self.release_all_keys()
        return super().give_up_mission(timeout=timeout)

    # ------------------------------------------------------------------
    # 和 AutoExpulsion 状态机对接
    # ------------------------------------------------------------------
    def do_run(self):
        """局内处理每局只做一次；结算界面只负责点「再次进行」。"""
        self.init_all()
        self.load_char()
        self.count = 0
        self.session_count = 0
        self._settlement_counted = False
        self.info_set("场次", 0)
        mission_started_at = 0.0
        while True:
            on_result = self.find_result_again_btn()
            self.count_settlement(on_result)
            # 结算界面即使 in_team() 仍为 True，也不能重跑开场；先交给 handle_mission_interface
            if (self.in_team() and not self._steps_done_this_mission
                    and not on_result):
                self.log_info("[自动调停/老道] 局内处理")
                mission_started_at = time.time()
                self.play_route_once()
                continue

            # 进本后开始计时；满超时时间还没进结算就按 ESC 放弃并重开
            if (self.in_team() and mission_started_at
                    and not on_result
                    and self.timeout_expired(mission_started_at)):
                elapsed = time.time() - mission_started_at
                self.log_info(f"[自动调停/老道] 任务超时 {elapsed:.0f} 秒，ESC重开")
                self.give_up_mission()
                mission_started_at = 0.0
                continue

            status = self.handle_mission_interface(stop_func=self.stop_func)
            if status == Mission.START:
                self.wait_until(self.in_team, time_out=30)
                self.init_all()
                mission_started_at = 0.0
            elif status == Mission.STOP:
                pass
            elif status == Mission.CONTINUE:
                pass
            self.sleep(0.1)

    def count_settlement(self, on_result):
        """进一次结算界面只加一场，防止同一屏反复计数。"""
        if not on_result or self._settlement_counted:
            return
        self._settlement_counted = True
        self.session_count += 1
        self.info_set("场次", self.session_count)
        self.log_info(f"[自动调停/老道] 完成第 {self.session_count} 场")

    def init_all(self):
        super().init_all()
        self._steps_done_this_mission = False

    def timeout_seconds(self):
        try:
            return max(1.0, float(self.config.get("超时时间", DEFAULT_TIMEOUT)))
        except (TypeError, ValueError):
            return float(DEFAULT_TIMEOUT)

    def timeout_expired(self, started_at, now=None):
        if not started_at:
            return False
        now = time.time() if now is None else now
        return now - started_at >= self.timeout_seconds()


