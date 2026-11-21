from qfluentwidgets import FluentIcon
import re
import time

from ok import Box, Logger, TaskDisabledException

from src.tasks.AutoExpulsion import AutoExpulsion
from src.tasks.CommissionsTask import Mission
from src.tasks.fullauto.DungeonActionMixin import DungeonActionMixin
from src.tasks.fullauto.DungeonActionLogic import (
    MODE_DEFENCE,
    MODE_EXPLORATION,
    mode_of_task_name,
)
from src.dna_ui.Defs import COORD, LETTER_BOARD_COLUMN_X

logger = Logger.get_logger(__name__)

# 委托密函列表（图1）的三个栏目，从左到右。下标要和 LETTER_BOARD_COLUMN_X 对齐。
COLUMN_NAMES = ("角色", "武器", "魔之楔")
# 「持有数35」和「持有数：815」两种形态都只取数字。
COUNT_RE = re.compile(r'持有数\s*[:：]?\s*(\d+)')
# 图1 的「24分34秒刷新密函委托」和图2 的「刷新密函委托21分47秒」共用这一条。
REFRESH_RE = re.compile(r'(\d+)\s*分\s*(\d+)\s*秒')
# 只要数字（密函卡上的持有数）。
DIGIT_RE = re.compile(r'[0-9]+')
# 「Lv.40」这类等级文字，记录"这一栏有哪些任务"时要排掉（OCR 大小写不稳，忽略大小写）
LEVEL_RE = re.compile(r'^l?v?\.?\s*\d+$', re.IGNORECASE)
# 刷新容错：流程是"先读刷新倒计时 xx分xx秒，再一直跑这段时间，然后回图1 重读"。
# 实际跑的时长比读到的多 1 分钟（xx+1分xx秒），保证回到图1 时刷新确实发生过、委托已重roll。
REFRESH_TOLERANCE_SECONDS = 60
# 「等待刷新」时每轮重新扫列表的间隔（秒）：分段等，别一口气睡到下个刷新
NO_DRIVE_AWAY_POLL_SECONDS = 10
# 读不到刷新倒计时时的兜底等待（秒）
REFRESH_WAIT_FALLBACK_SECONDS = 65
# 空窗期保活的默认间隔（分钟）：「等待刷新」时每隔这么久点进一个委托再退出来。
# 云游戏会以"长时间未操作"断会话（实拍弹「连接中断 / 由于您长时间未操作，连接已断开」），
# 而框架那套鼠标抖动（两三像素的相对位移）平台不认，所以得真点几下。
# 2026-10-06 那次运行的实测：59 / 48 / 30 分钟的空窗**都活下来了**，只有最后那次
# 15:01:01 起的那段在 15:01:01~15:30:54 之间断掉（15:01:01 时列表还能正常 OCR，
# 15:30:54 抓帧才失败）。所以阈值不是固定 30 分钟；那几段活下来的大概率是"人在电脑前"
# 提供了真实输入。默认取 10 分钟是按最坏情况留余量，代价只是每 10 分钟点两下。
KEEPALIVE_INTERVAL_MINUTES_DEFAULT = 10
# 卡住时的提醒间隔（秒）：会话断了之后脚本会一直重试，最多这么久提醒一次，别刷屏
STUCK_NOTIFY_INTERVAL_SECONDS = 300
# 图2 里连续这么多秒认不出任何「密函流程界面」，就当这一栏打不下去了（密函开完、
# 或刷新后当前委托失效），回图1 重新选。
LETTER_FLOW_STALL_TIME_OUT = 45
# 「密函卡那一带读不到持有数」要持续这么久才算"这一栏开完"：单次 OCR 漏读（实拍：角色密函
# 的持有数是立绘格角上的小角标，容易漏）不该直接撤离。
LETTER_EXHAUSTED_CONFIRM_SECONDS = 2.0

# 图2 的「自动轮次」开关：开着时标题下面多一行「轮次x/99」。开着会干扰本任务的轮次
# 计算，所以进图2 时检测到就自动点掉。
# 开关是那一行**右侧**的滑块（实拍：标题在 x957，亮色滑块 96x27 在 x1452-1548、
# 和标题同一行；关的时候滑块挪到轨道左边、轨道变暗）。所以按现场 OCR 到的标题行 y，
# 点固定的 x（1600x900 基准 1500）。
AUTO_ROUNDS_RE = re.compile(r'轮次\s*\d+\s*/\s*\d+')
AUTO_ROUNDS_LABEL_RE = re.compile(r'自动轮次')
# 「自动轮次」四个字在 1600x900 基准约 108px 宽；滑块中心在标题左边缘往右约 543px
# （实拍：标题 x957 → 滑块中心 x1500）。实际分辨率下按标题实际宽度等比缩放。
AUTO_ROUNDS_LABEL_W = 108
AUTO_ROUNDS_SWITCH_DX = 543
AUTO_ROUNDS_SWITCH_W = 60

# 三种委托混在列表那三栏里，挑的时候按优先级来：驱离 > 探险 > 扼守。
#   * 驱离：走原来的流程（进本只放技能，不判图不走位）；
#   * 探险 / 扼守：进本先判地图 + 走位 + 破解（DungeonActionMixin 那套）。
MODE_DRIVE = "驱离"
# 挑任务的优先级：驱离 > 探险 > 扼守（三种任务共用列表那三栏）
TASK_MODES = (MODE_DRIVE, MODE_EXPLORATION, MODE_DEFENCE)
WALK_MODES = (MODE_EXPLORATION, MODE_DEFENCE)
# 「进一次本打多少轮」的两个配置（只在对应模式下用），默认都是 20。
DEFAULT_ROUNDS = 20
ROUND_CONFIG_KEYS = {MODE_EXPLORATION: "探险轮次", MODE_DEFENCE: "扼守轮次"}


class AutoLetterOpenTask(DungeonActionMixin, AutoExpulsion):
    """全自动「自动开密函」：在委托密函列表里挑任务开密函，一直打到不能再打。

    **看列表上有什么就挑什么，优先级 驱离 > 探险 > 扼守**（三种任务混在那三栏里）：

      * 驱离：进本只放技能（老行为，不判图不走位）；
      * 探险 / 扼守：进本先判地图、走位、破解机关（DungeonActionMixin 那套），每进一局
        走一次；进一次本按「探险轮次」/「扼守轮次」打满一轮就撤离到结算界面点「再次进行」
        重开一局。

    图1 = 委托密函列表（角色 / 武器 / 魔之楔 三栏，每栏一行「持有数N」+ 任务槽）；
    图2 = 某个密函任务的开始界面，也就是「自动驱离」平时开工的那个界面。

    流程：
      1) 图1：读三栏的「持有数」，在**勾了**的栏里挑优先级最高的任务（驱离 > 探险 > 扼守，
         见下「栏目选择」），持有数>0 才点它进图2；
         （图2 只有从图1 点任务才进得去，别处到不了）
      2) 图2：点「选择密函」开打。打完一把游戏给的是**结算界面**（委托完成 / 再次进行 /
         退出委托），所以内层循环就在结算界面点「再次进行」-> 密函选择 -> 打 -> 密函奖励
         -> 结算，一直重复打这一栏，中途不主动回列表；
      3) 出现下面任一种情况才点「退出委托」/按 ESC 回图1，重新扫描换任务：
           - 密函选择弹窗里能选的密函卡都没了（只剩「⊘ 不使用」，卡牌那一条读不到持有数）
             -> 这一栏的密函开完了；
           - 跑满了"刷新倒计时 + 1 分钟容错"这段时间（见下面的计时说明）；
           - 连续 LETTER_FLOW_STALL_TIME_OUT 秒认不出任何密函流程界面（当前委托失效等）；
           - 游戏自己把我们踢回了图1 列表。
      4) 三栏都没有可打的任务时，读图1 右下角倒计时等刷新再扫一遍；
         「等待刷新」关掉则直接结束任务。

    栏目选择（角色 / 武器 / 魔之楔，多选，默认三栏全勾）：
      勾了哪几栏就打哪几栏的密函本。没勾的那栏跳过（哪怕它持有数>0、有可打的任务也不碰），
      只看勾上的栏。三栏一个都没勾时等于没有可打的委托，走「等待刷新」。

    计时（先检测、再按检测到的时长跑，跑完回图1 重新检测）：
      进这一栏之前先在**图1** 读一次「xx分xx秒刷新密函委托」兜底，进图2 后再读一次
      「刷新密函委托xx分xx秒」（图2 优先）。跑的时间 = 读到的 xx分xx秒 **再加 1 分钟容错**，
      也就是界面上写 xx分xx秒 就跑 xx+1分xx秒。到点回图1，重新读、重新算、再跑下一轮。
      到点时如果人还在本里，就先打完这一局（不半路硬拽出来），一离开局内马上回图1
      —— 最多多打一局；每局本身还有「超时时间」上限兜底。
      至少要已经打过一局才认这个时间，避免单次 OCR 读错就在两屏之间空转。

    不要把游戏丢在界面上一动不动：
      一局开不起来（start_mission 点不动、"任务无法继续"）时不当成任务结束，而是吞掉它
      回图1 重选接着跑；「等待刷新」也是分段等（每段 10 秒回主循环重扫一次列表）。
      任务一旦真的结束，游戏就留在界面上没人管，云游戏那边时间一长会掉线 ——
      只当用户自己按停止才真的结束（见 recoverable_stop）。
      空窗期（列表上一直刷不出「驱离」）每隔「空窗保活间隔(分钟)」（默认 10 分钟）点进
      一个委托再退出来一次：云游戏是按"长时间未操作"断会话的（实拍弹「连接中断：由于您
      长时间未操作，连接已断开」），框架那套两三像素的鼠标抖动平台不认，得真点几下。
      实测（2026-10-06）：59 / 48 / 30 分钟的空窗都活下来了，只有一段在 30~59 分钟之间
      断掉，所以阈值不是固定的 30 分钟；默认 10 分钟是按最坏情况留的余量。
      保活点进图2 后如果没退回来，_picked_drive_away 会拦住"顺手把随便一个委托开了"。

    实现上直接继承 AutoExpulsion：局内的走位/技能/密函选择/密函奖励完全复用，
    这里只加"图1 选任务"和"图1 <-> 图2 的往返判断"。界面判据与坐标见 src/dna_ui/Defs.py。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = "icons/tasks/auto_letter.svg"
        self.name = "自动开密函"
        self.description = "全自动"
        self.group_name = "日常"
        self.group_icon = FluentIcon.GAME

        self.default_config.update({
            "栏目选择": list(COLUMN_NAMES),
            "等待刷新": True,
            "空窗保活间隔(分钟)": KEEPALIVE_INTERVAL_MINUTES_DEFAULT,
            "探险轮次": DEFAULT_ROUNDS,
            "扼守轮次": DEFAULT_ROUNDS,
        })
        self.config_description.update({
            "栏目选择": "选择要打哪几栏的密函本（角色 / 武器 / 魔之楔，默认三栏全打）",
            "等待刷新": "列表里暂时没有可打的任务时，等它下次刷新后再扫一遍；关掉则直接结束任务",
            "空窗保活间隔(分钟)": "空窗期每隔这么多分钟点进一个委托再退出来，避免云游戏判定"
                                "「长时间未操作」而断线（实测 30~59 分钟之间会被踢，默认 10 分钟留余量）",
            "探险轮次": "探险模式下，进一次本打多少轮（默认 20）",
            "扼守轮次": "扼守模式下，进一次本打多少轮（默认 20）",
        })
        # 「栏目选择」：勾选框的那几栏（跟「自动探险/无尽」的「地图选择」同一个样式），
        # 勾了哪几栏就打哪几栏，没勾的整栏跳过。
        self.config_type["栏目选择"] = {
            "type": "multi_selection",
            "options": list(COLUMN_NAMES),
        }
        # 本任务不需要「随机游走 / 挂机模式 / 开局向前走」：驱离进本就原地不动放技能，
        # 探险/扼守 的走位是固定的录制序列（走完再挂机）。
        for key in ("随机游走", "挂机模式", "开局向前走"):
            self.default_config.pop(key, None)

        # 有没有真正进过局内 —— 图2 和"打完一局又回到图2"是同一个界面，靠它区分
        self._entered_mission = False
        # 列表 OCR 的短缓存，避免主循环每 0.1 秒都跑一次整块 OCR
        self._board_cache = None
        self._board_cache_time = 0
        # 图1 上读到的刷新时刻（进图2 前先读一次，图2 那串读不到时用它兜底）
        self._board_deadline = None
        # 「等待刷新」下一次重新读倒计时的时刻（分段等待用）
        self._next_refresh_check = None
        # 下一次空窗期保活的时刻（点进一个委托再退出来）
        self._next_keepalive = 0
        # 上一次"卡住"提醒的时刻（限频用）
        self._last_stuck_notify = 0
        # 是不是本任务自己挑的「驱离」才进的图2 —— 只有它为真才允许在图2 开打，
        # 免得空窗期保活/误点进图2 之后，脚本顺手把随便一个委托开了
        self._picked_drive_away = False
        # 这一把选的是哪种模式（MODE_DRIVE / MODE_EXPLORATION / MODE_DEFENCE）
        self._dungeon_mode = None
        # 探险/扼守：这一局有没有走过位（进本第一帧走一次；结算后重开一局会再走）
        self._walked_this_mission = False
        # 到刷新时间了、但这一轮次还没打完：打完再回列表（探险/扼守用）
        self._leave_after_rounds = False
        # 图2 的「自动轮次」是否已确认关掉；没确认前在图2 上（点「选择密函」之前）反复查
        self._auto_rounds_off_confirmed = False
        self._next_auto_rounds_check = 0
        # 这一把这一栏读到的密函「持有数」：每打一轮消耗一张，比配置轮次少时按它收工
        self._entry_letter_count = None
        # 这一栏累计已经打了多少轮（每局打完在结算界面累加，到持有数上限就撤离回列表）
        self._entry_rounds_done = 0
        # 密函卡那一带从什么时候开始就读不到持有数了（要连续一段才算"开完"，防单次漏读）
        self._letter_exhausted_since = 0
        # get_round_info 用它给"这一次行动抉择只数一次"去重
        self._round_counted = False
        # 「自动驱离」在自己 do_run 里初始化这个计数器，这里覆盖了 do_run 就得自己补上，
        # 否则继承来的 handle_in_mission 执行 self.count += 1 时会 AttributeError。
        self.count = 0

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def do_run(self):
        self.init_all()
        self.load_char()
        self.wait_for_start_state()
        while True:
            if self.in_team():
                self._entered_mission = True
                self.handle_in_mission()
                self.sleep(0.1)
                continue

            # 图1：列表上就选任务（放在最前面判：万一同位置还有其他按钮也不能抢到这条分支）
            if self.is_letter_board():
                self._entered_mission = False
                self._picked_drive_away = False
                if not self.pick_drive_away():
                    self.handle_no_drive_away()
                self.sleep(0.2)
                continue

            self.run_letter_missions()
            self.sleep(0.1)

    # ------------------------------------------------------------------
    # 进本后：探险 / 扼守 才判图 + 走位；驱离只放技能（保持原行为）
    # ------------------------------------------------------------------
    def walk_when_entered(self):
        """进本第一帧走位：判地图并跑对应的外部行动逻辑，**每次进本只跑一次**。

        只有探险 / 扼守要，驱离直接跳过。开密函这条路径（点开始 -> 选密函 -> 进本）
        不返回 Mission.START，所以走位挂在进本第一帧；结算后点「再次进行」重开一局会
        再走一次（见 handle_mission_interface 里的清零）。
        """
        if not self.is_walk_mode() or self._walked_this_mission:
            return
        self._walked_this_mission = True
        self.log_info("已进入副本：判地图并执行外部行动逻辑")
        self.walk_to_aim(delay=2)

    def move_on_begin(self):
        """进本后原地不动：本任务没有「挂机模式」这种开局处理。

        驱离就是站着放技能；探险/扼守 的走位在 walk_when_entered 里做，和这里无关。
        """
        return True

    def handle_in_mission(self):
        # 回到局内 = 这一波打完了：下一次行动抉择要能再记一轮（每轮清零）。
        # 不清零的话 get_round_info 会被"这一轮已数过"挡住，轮次永远停在 1。
        self._round_counted = False
        self.walk_when_entered()
        super().handle_in_mission()

    def handle_mission_interface(self, stop_func=lambda: False):
        if self.is_walk_mode() and self.find_result_again_btn():
            # 结算界面 = 这一局结束；接下去点「再次进行」是新的一局，要重新判图 + 走位
            self._walked_this_mission = False
        return super().handle_mission_interface(stop_func=stop_func)

    def handle_mission_start(self):
        """任务开始：探险/扼守先判图 + 走位再等开战；驱离沿用原行为（睡 2 秒）。"""
        if not self.is_walk_mode():
            return super().handle_mission_start()
        self.walk_when_entered()
        if not self.in_team():
            self.log_info("外部行动后未在副本内（可能已退出），等待重开任务")
            return
        time_out = self.action_timeout + 10
        self.log_info(f"外部行动执行完毕，等待战斗开始，{time_out} 秒后超时")
        if not self.wait_until(lambda: self.is_in_combat() or self.find_esc_menu(),
                               post_action=self.get_wave_info, time_out=time_out):
            self.log_info("等待战斗开始超时，重开任务")
            self.open_in_mission_menu()
        else:
            self.log_info("战斗开始")

    def letter_stop_func(self):
        """行动抉择弹窗出现时调用：探险/扼守打满本轮次返回 True；驱离只计数不设上限。

        三种模式都会数轮次（驱离也数，信息栏「轮次计算」才看得到进度）；只有探险/扼守
        会在打到"配置轮次 / 这把的剩余上限"时返回 True 收工。
        """
        self.get_round_info()
        self.update_rounds_info()
        if not self.is_walk_mode():
            return False
        return self.current_round >= self.rounds_this_mission()

    def rounds_this_mission(self):
        """这一局打多少轮：**配置轮次**，但不超过这一栏"还没打到上限"的剩余轮数。

        无尽模式每打一轮消耗一张密函。配置轮次是每局打的量；进本时读到的持有数是这一栏
        的总上限 —— 每局打完在结算界面把轮次累加（account_mission_rounds），累计到上限
        就撤离回列表（finish_letter_round 里判）。读不到持有数时不设上限，按配置轮次打。
        """
        rounds = self.rounds_for_mode(self.current_task_mode())
        if self._entry_letter_count is None:
            return rounds
        left = max(0, self._entry_letter_count - self._entry_rounds_done)
        return min(rounds, left)

    def account_mission_rounds(self):
        """一局结束：把这一局打的轮次累加进"这一栏已打多少轮"。"""
        self._entry_rounds_done += max(0, self.current_round)
        self.current_round = 0
        self._round_counted = False
        self.update_rounds_info()

    def account_drive_away_round(self):
        """驱离：一进结算界面就算打了一轮（它没有「行动抉择」那种波次信号可数）。"""
        self._entry_rounds_done += 1
        self.current_round = 0
        self._round_counted = False
        self.update_rounds_info()

    def update_rounds_info(self):
        """信息栏「轮次计算」那一栏：已打/轮次上限（持有数，读不到就显示 ?）。

        每从图1 挑一次任务（= 回到初始界面）都会重置成 0/上限，之后每打一轮往上加。
        """
        done = self._entry_rounds_done + max(0, self.current_round)
        cap = "?" if self._entry_letter_count is None else self._entry_letter_count
        self.info_set("轮次计算", f"{done}/{cap}")

    def entry_rounds_full(self):
        """这一栏累计已经打到（或超过）持有数上限了。"""
        return (self._entry_letter_count is not None
                and self._entry_rounds_done >= self._entry_letter_count)

    def leave_to_board(self):
        """回到委托密函列表：先撤离副本，再从结算/开始界面回列表。

        撤离本身走 CommissionsTask.quit_mission（和委托副本同一套状态机：行动抉择点
        「撤离」/ ESC 菜单点「放弃挑战」+ 二次确认「确定」）；这里只负责之后那几步：
        结算界面点「退出委托」、图2 开始界面按 ESC，直到回到图1 列表。
        """
        self.log_info("撤离：回委托密函列表")
        self.quit_mission()
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.is_letter_board(force=True):
                self._entered_mission = False
                self.log_info("已经回到委托密函列表")
                return True
            if self.find_result_again_btn():
                # 结算界面：点「退出委托」回列表
                self.click_ui_coord(COORD.RESULT_QUIT, name="letter_result_quit", after_sleep=1)
                continue
            # 图2 开始界面（或过场）：按 ESC 回列表
            self.send_key("esc")
            if self.wait_until(self.is_letter_board, time_out=2, raise_if_not_found=False):
                self._entered_mission = False
                return True
        self.notify_stuck("撤离副本超时，没能回到委托密函列表")
        return False

    def finish_letter_round(self):
        """探险/扼守本内打满一轮。

        返回 True = 已经回列表了（调用方直接 return）；False = 接着在结算界面点
        「再次进行」重开一局。每局结束先把这局打的轮次累加；累计到这一栏的持有数上限
        （或刷新时间到）就回列表。
        """
        self._walked_this_mission = False
        played = max(0, self.current_round)
        self.account_mission_rounds()
        if self._leave_after_rounds:
            self._leave_after_rounds = False
            self.log_info("本轮次打完（已到刷新时间），回列表重新选择")
            self.leave_to_board()
            return True
        if self.entry_rounds_full():
            self.log_info(f"这一栏已累计打满 {self._entry_rounds_done}/"
                          f"{self._entry_letter_count} 轮，撤离回列表重新选择")
            self.leave_to_board()
            return True
        cap = self._entry_letter_count
        tail = f"（这栏累计 {self._entry_rounds_done}/{cap}）" if cap is not None else ""
        self.log_info(f"本局已打 {played} 轮{tail}，撤离到结算界面重新开始")
        try:
            if self.in_team() or self.find_action_dialog_retreat():
                self.quit_mission()
        except Exception as e:
            self.log_info(f"撤离失败（{e}），回列表重新选择")
            self.leave_letter_start()
            return True
        return False

    def wait_for_start_state(self, time_out=300):
        """等界面处于能开工的状态：图1 列表、图2 开始界面，或结算界面（这一局还没退）。

        从大世界/主菜单怎么打开委托密函列表不由本任务管（用户会先自己打开列表），
        所以启动时如果三个界面都认不到，就提示用户先打开列表再启动。
        """
        if self.is_letter_board() or self.find_start_interface() or self.find_result_again_btn():
            return True
        self.log_info_notify("请先打开「委托密函」列表（角色 / 武器 / 魔之楔 三栏）再启动本任务")
        self.soundBeep()
        if not self.wait_until(lambda: self.is_letter_board() or self.find_start_interface()
                               or self.find_result_again_btn(),
                               time_out=time_out, raise_if_not_found=False):
            raise Exception("等待「委托密函」列表超时，请先打开该界面再启动任务")
        return True

    # ------------------------------------------------------------------
    # 图2：一直重复打当前这一栏
    # ------------------------------------------------------------------
    def run_letter_missions(self):
        """在图2 里一直重复打当前这一栏，直到刷新 / 打不下去 / 被游戏踢回列表。

        整个循环体包在 try 里：start_mission 点了开始但界面一直不往前走时会抛
        TaskDisabledException（"任务无法继续"），那只说明这一局没开成 —— 吞掉它、
        回列表重选继续跑。任务真结束的代价是游戏被丢在界面上没人管，云游戏会掉线。
        用户自己按的停止不算在内（见 recoverable_stop）。
        """
        # 先检测刷新倒计时，再跑这段时间：图2 的倒计时优先（进这一栏时刚读的），
        # 读不到就用点「驱离」前在图1 读到的那个。
        if not self._picked_drive_away:
            # 不是本任务挑的「驱离」就进来了（空窗期保活、误点、或启动时本来就停在图2）：
            # 不要顺手把随便一个委托开了，退回列表重新挑。
            self.log_info("当前不是自己挑的「驱离」，先退回列表")
            self.leave_letter_start()
            return
        deadline = self.usable_deadline(self.start_screen_refresh_deadline() or self._board_deadline)
        self.log_info("本次预计运行到刷新后 1 分钟：%s" % self.format_deadline(deadline))
        last_flow_time = time.time()
        deadline_hit_logged = False
        while True:
            try:
                if self.in_team():
                    self._entered_mission = True
                    last_flow_time = time.time()
                    # 到点了但人还在本里：不半路硬拽出来（本局奖励还在），打完这一局、
                    # 一离开局内上面的分支就让位给下面那条"到点回列表"，最多多打一局。
                    if deadline and not deadline_hit_logged and time.time() >= deadline:
                        deadline_hit_logged = True
                        if self.is_walk_mode():
                            # 探险/扼守：人到点还在本里，不半路硬拽出来 —— 把这一轮次打完再回列表
                            self._leave_after_rounds = True
                            self.log_info("已到刷新时间：打完当前这一轮次就回列表重新选择")
                        else:
                            self.log_info("已到刷新时间但还在本内，等本局结束就回列表重新选择")
                    self.handle_in_mission()
                    self.sleep(0.1)
                    continue

                # 游戏自己把我们踢回列表了（刷新后当前委托失效等）
                if self.is_letter_board():
                    self._entered_mission = False
                    self.log_info("已经回到委托密函列表")
                    return

                # 密函选择弹窗：能选的密函卡都没了（只剩 ⊘ 不使用）-> 这一栏开完了
                if self._entered_mission and self.find_letter_interface() and self.letter_exhausted():
                    if self._letter_exhausted_since == 0:
                        self._letter_exhausted_since = now
                        self.log_info("密函卡那一条没读到持有数，先再确认一下（怕单次 OCR 漏读）")
                    elif now - self._letter_exhausted_since >= LETTER_EXHAUSTED_CONFIRM_SECONDS:
                        self.log_info("这一栏的密函已经开完，回列表重新选择")
                        self.leave_to_board()
                        return
                else:
                    self._letter_exhausted_since = 0

                now = time.time()
                # 至少要打过一局才认这个刷新时间：图2 那串倒计时只读得到一次，读错了不至于空转
                # 探险/扼守不在本外直接回列表：它们的到点是"打完当前这一轮次再回"（见上面
                # _leave_after_rounds + letter_stop_func），半路把副本丢下会丢奖励。
                if deadline and now >= deadline and self._entered_mission and not self.is_walk_mode():
                    self.log_info("密函委托已到刷新时间，回列表重新选择")
                    self.leave_letter_start()
                    return

                if self.in_letter_flow_screen():
                    last_flow_time = now
                elif now - last_flow_time > LETTER_FLOW_STALL_TIME_OUT:
                    self.log_info("密函任务无法继续进行，回列表重新选择")
                    self.leave_letter_start()
                    return

                if self._leave_after_rounds and self.find_result_again_btn():
                    # 到刷新时间了，且这一局也打完了（结算界面）：回列表重新选
                    self.log_info("本轮次打完（已到刷新时间），回列表重新选择")
                    self._leave_after_rounds = False
                    self.leave_to_board()
                    return

                if self._entered_mission and self.find_result_again_btn():
                    # 一局结束（结算界面）：先把这一局算进"这一栏已打多少轮"
                    if self.is_walk_mode():
                        # 探险/扼守：一局里能打好几波，按 get_round_info 数到的轮次累加
                        self.account_mission_rounds()
                    else:
                        # 驱离：没有「行动抉择」那种波次信号，一进结算界面就算打了一轮
                        self.account_drive_away_round()
                    # 累计到持有数上限就回列表，否则接着点「再次进行」打下一局
                    if self.entry_rounds_full():
                        self.log_info(f"这一栏已累计打满 {self._entry_rounds_done}/"
                                      f"{self._entry_letter_count} 轮，撤离回列表重新选择")
                        self.leave_to_board()
                        return

                if (not self._auto_rounds_off_confirmed and self.find_start_interface()
                        and now >= self._next_auto_rounds_check):
                    # 图2 上、点「选择密函」之前：确认「自动轮次」是关的（开着会干扰轮次计算）
                    self._next_auto_rounds_check = now + 2
                    if self.ensure_auto_rounds_off():
                        self._auto_rounds_off_confirmed = True

                status = self.handle_mission_interface(stop_func=self.letter_stop_func)
                if status == Mission.STOP:
                    if self.finish_letter_round():
                        return
                    self.sleep(0.1)
                    continue
                if status == Mission.CONTINUE and self.is_walk_mode():
                    # 探险/扼守：和全自动扼守流程的「继续轮次」一样，续下一轮前重置本局
                    # 状态（超时计时变成按波算）、等回到局内。驱离保持原样不动。
                    self.log_info("任务继续")
                    self.init_for_next_round()
                    self.wait_until(self.in_team, time_out=self.action_timeout,
                                    raise_if_not_found=False)
                if status == Mission.START:
                    # 等进局内别抛异常：加载慢时 in_team 晚几秒认出来，抛出去会把任务打死
                    self.wait_until(self.in_team, time_out=30, raise_if_not_found=False)
                    self.init_all()
                    self._entered_mission = True
                    self.handle_mission_start()
                    # 顺手重读一次刷新倒计时（只有回到图2 时才读得到，读不到就沿用原来的）
                    fresh_deadline = self.start_screen_refresh_deadline()
                    if fresh_deadline:
                        deadline = fresh_deadline
                self.sleep(0.1)
            except TaskDisabledException:
                if not self.recoverable_stop():
                    raise
                self.log_info("这一局没能开起来，回列表重新选择")
                self.leave_letter_start()
                return

    def recoverable_stop(self):
        """这一次 TaskDisabledException 是用户按了停止，还是只是这一局没开成？

        TaskDisabledException 有两个来源：
          * 用户在界面上停止任务 —— executor.check_enabled 会先把 current_task 清成
            None 再抛，这种必须继续往上抛、让任务真的结束；
          * start_mission 点了开始但界面一直不往前走、20 秒后主动放弃这一局
            （"任务无法继续"）—— 那种只是这一局没开成，吞掉它、回列表重选继续跑。
        任务真结束的代价是游戏被丢在界面上没人管，云游戏那边时间一长就掉线。
        """
        return self.executor.current_task is not None

    def letter_exhausted(self):
        """密函选择弹窗里还有没有可选的密函卡。

        判据：卡牌矩阵那一行本来每张密函卡都印着持有数（实拍 100 / 85 / 85 ...），
        「⊘ 不使用」那一格没有数字；密函开完后只剩「不使用」，这一行就读不到任何数字了。
        只在密函选择弹窗上调用。
        """
        box = self.screen_box('LETTER_CARD_ROW')
        self.draw_boxes(box.name, box, 'blue')
        return not self.ocr(box=box, match=DIGIT_RE)

    def leave_letter_start(self, time_out=20):
        """从图2 离开回图1：结算界面点「退出委托」，其它情况按 ESC 返回。"""
        # 不管这次能不能回到列表，都把图1 上那个刷新时刻作废：它已经用过了，
        # 留着会让下一轮内层循环"一进去就到点"，在两屏之间来回空转。
        self._board_deadline = None
        if self.is_letter_board(force=True):
            self._entered_mission = False
            return True
        deadline = time.time() + time_out
        while time.time() < deadline:
            if self.find_result_again_btn():
                self.click_ui_coord(COORD.RESULT_QUIT, name="letter_result_quit", after_sleep=1)
            else:
                self.send_key("esc")
            if self.wait_until(self.is_letter_board, time_out=2, raise_if_not_found=False):
                self._entered_mission = False
                return True
        # 回不去列表通常意味着画面已经不对劲了（云游戏断线后就是这种表现），
        # 这里带限频地提醒一下，别让你几小时后才发现脚本一直在空转。
        self.notify_stuck("没能返回委托密函列表，请检查界面是否正常")
        return False

    def in_letter_flow_screen(self):
        """当前是不是密函流程里某个能认出来的界面（用来判断这一栏还打不打得了）。"""
        return bool(self.find_start_interface()
                    or self.find_result_again_btn()
                    or self.find_letter_interface()
                    or self.find_manual_select_btn()
                    or self.find_letter_reward_btn()
                    or self.find_action_dialog_continue()
                    or self.find_action_dialog_retreat()
                    or self.find_esc_menu())

    def start_screen_refresh_deadline(self):
        """读图2 右上角「刷新密函委托xx分xx秒」，换算成"跑完该跑的时间"的绝对时刻。"""
        box = self.screen_box('LETTER_START_REFRESH')
        self.draw_boxes(box.name, box, 'blue')
        found = self.ocr(box=box, match=REFRESH_RE)
        if not found:
            return None
        match = REFRESH_RE.search(found[0].name)
        if not match:
            return None
        return self.refresh_deadline(int(match.group(1)) * 60 + int(match.group(2)))

    @staticmethod
    def refresh_deadline(seconds):
        """把"还剩多少秒刷新"换算成绝对时刻：读到的时长 + 1 分钟容错。

        读到的倒计时是"距离刷新还剩多久"，容错加 1 分钟后再回图1，能保证刷新真发生过了。
        """
        return time.time() + seconds + REFRESH_TOLERANCE_SECONDS

    @staticmethod
    def format_deadline(deadline):
        if not deadline:
            return "没读到刷新倒计时"
        return time.strftime("%H:%M:%S", time.localtime(deadline))

    @staticmethod
    def usable_deadline(deadline, now=None):
        """已经过期的刷新时刻当作没读到。

        图1 上读到的那个是上一栏留下的；如果"回列表"没成功又绕回内层循环，这个时刻
        往往已经过期 —— 照用就会变成"刚进来就立刻回列表"的空转。
        """
        if deadline is None:
            return None
        now = time.time() if now is None else now
        return None if deadline <= now else deadline

    def keepalive_interval_seconds(self):
        """空窗期保活间隔（秒），取自配置「空窗保活间隔(分钟)」。"""
        try:
            minutes = float(self.config.get("空窗保活间隔(分钟)", KEEPALIVE_INTERVAL_MINUTES_DEFAULT))
        except (TypeError, ValueError):
            minutes = KEEPALIVE_INTERVAL_MINUTES_DEFAULT
        return max(1.0, minutes) * 60

    def frame_missing(self):
        """现在是不是已经取不到游戏画面了。

        云游戏断线 / 页面被关掉之后抓帧会一直拿不到东西（ok 的日志是
        windows_graphics:no frame for 10 sec, try to restart），这种时候认界面、
        点击全是白费 —— 与其一直"认不出界面"地空转，不如说出来等画面回来。
        """
        try:
            return self.frame is None
        except Exception:
            return True

    def notify_stuck(self, message):
        """卡住时的提醒：最多每 STUCK_NOTIFY_INTERVAL_SECONDS 秒响一次，别刷屏。"""
        if self.frame_missing():
            message += "（现在连游戏画面都取不到，云游戏大概率已经断线了）"
        now = time.time()
        if now - self._last_stuck_notify < STUCK_NOTIFY_INTERVAL_SECONDS:
            self.log_info(message)
            return
        self._last_stuck_notify = now
        self.log_info(message)
        self.log_info_notify(message)
        self.soundBeep()

    # ------------------------------------------------------------------
    # 图1：读列表、点「驱离」
    # ------------------------------------------------------------------
    def is_letter_board(self, force=False):
        return self.scan_letter_board(force=force)["on_board"]

    def scan_letter_board(self, force=False, ttl=1.0):
        """OCR 委托密函列表，解析出每栏的「持有数」和「驱离」位置。

        返回 {"on_board": bool, "counts": [int|None]x3, "drive_away": [Box|None]x3}。
        整块列表一次 OCR，再按 x 把文字归到对应栏目 —— 比每个元素单独开一次 OCR
        少跑很多趟，也不怕文字被检测器切成两段。
        """
        now = time.time()
        if not force and self._board_cache is not None and now - self._board_cache_time < ttl:
            return self._board_cache

        box = self.screen_box('LETTER_BOARD')
        self.draw_boxes(box.name, box, 'blue')
        results = self.ocr(box=box, match=None)

        data = {"on_board": False, "counts": [None, None, None],
                "drive_away": [None, None, None], "tasks": [[], [], []],
                "task_boxes": [[], [], []]}
        opened = 0
        headers = 0
        for item in results:
            index = self.column_index(item.x)
            if index is None:
                continue
            name = item.name.strip()
            if '当前开放' in name:
                opened += 1
                continue
            if name in COLUMN_NAMES:
                headers += 1
                continue
            count_match = COUNT_RE.search(name)
            if count_match:
                data["counts"][index] = int(count_match.group(1))
                continue
            # 只认「驱离」：界面上还有个形近的「驱逐」，是另一种任务，所以别按「驱」前缀匹配
            if '驱离' in name and data["drive_away"][index] is None:
                data["drive_away"][index] = item
            if not LEVEL_RE.match(name):
                data["tasks"][index].append(name)
                data["task_boxes"][index].append(item)

        # 「当前开放」每栏一行、「角色/武器/魔之楔」每栏一个标题：两个信号都只在列表上出现，
        # 各放宽到 2 是为了容 OCR 漏一两个，同时避开密函奖励界面（那里也有「持有数」，
        # 但没有这两个词，所以不会被误判成列表）。图2 里的栏目名在 y757，不在列表框内。
        data["on_board"] = opened >= 2 or headers >= 2
        self._board_cache = data
        self._board_cache_time = now
        return data

    @staticmethod
    def column_index(x):
        """文字左边缘 x 落在哪个栏目区间里；不在任何一栏就返回 None。"""
        for index, (left, right) in enumerate(LETTER_BOARD_COLUMN_X):
            if left <= x < right:
                return index
        return None

    def find_any_board_task(self):
        """空窗期保活用：随便挑一个列表上的任务文字框（点它才会进图2）。"""
        data = self.scan_letter_board(force=True)
        if not data["on_board"]:
            return None
        for boxes in data["task_boxes"]:
            if boxes:
                return boxes[0]
        return None

    def keepalive_click_around(self):
        """空窗期保活：点进任意一个委托、再按 ESC 退出来。

        云游戏是按"长时间未操作"断会话的（实拍会弹「连接中断：由于您长时间未操作，
        连接已断开」），框架那套鼠标抖动是两三像素的相对位移，平台不认；所以每隔
        配置「空窗保活间隔(分钟)」那么久真点两下：点进图2、ESC 回列表。
        退不出来也没关系，主循环里的 _picked_drive_away 判断会拦住"顺手开打"。
        """
        self._next_keepalive = time.time() + self.keepalive_interval_seconds()
        target = self.find_any_board_task()
        if target is None:
            return
        self.log_info("空窗期保活：点进一个委托再退出来")
        self._click_detected(target, name="keepalive_task", after_sleep=0.8)
        # 不管点进去成没成，都按一下 ESC 收尾：进去了就返回列表，没点动也无害
        self.wait_until(self.find_start_interface, time_out=5, raise_if_not_found=False)
        self.send_key("esc")
        if not self.wait_until(self.is_letter_board, time_out=8, raise_if_not_found=False):
            self.log_info("保活后没能直接回到列表，再按一次 ESC")
            self.send_key("esc")
            self.wait_until(self.is_letter_board, time_out=8, raise_if_not_found=False)

    def pick_drive_away(self):
        """按优先级挑一个任务点进去，成功返回 True。

        优先级 **驱离 > 探险 > 扼守**：三种任务混在列表那三栏里，每次都挑优先级最高、
        且该栏「持有数>0」的那种。挑中之后这一把就按它的类型跑对应逻辑（驱离只放技能；
        探险 / 扼守 判图 + 走位）。只挑「栏目选择」勾上的栏（默认三栏全勾）。
        """
        data = self.scan_letter_board(force=True)
        if not data["on_board"]:
            return False

        columns = self.selected_columns()
        if not columns:
            self.log_onetime_info("「栏目选择」一栏都没勾，先不打密函本")
            return False

        for mode in TASK_MODES:
            for index, column in enumerate(COLUMN_NAMES):
                # 没勾上的那栏直接不碰（「栏目选择」多选，默认三栏全勾）
                if column not in columns:
                    continue
                target, name = self.column_task(data, index, mode)
                if target is None:
                    continue
                count = data["counts"][index]
                if count is None:
                    self.log_onetime_info(f"[{column}] 有「{name}」但持有数没认出来，跳过这一栏")
                    continue
                if count <= 0:
                    # 空窗期每十来秒就会重新挑一次，这条要去重，否则把日志刷满
                    self.log_onetime_info(f"[{column}] 持有数 {count}，没有密函可开")
                    continue
                self.log_info(f"[{column}] 持有数 {count}，有「{name}」，"
                              f"这一栏打 {count} 轮（打完就撤离回列表）")
                # 点完就离开列表：缓存作废，避免下一圈还当成"在列表上"再点一次
                self._board_cache = None
                self._entered_mission = False
                self._picked_drive_away = True
                self._dungeon_mode = mode
                # 记下这一栏的密函数量：每打一轮消耗一张，持有数不够配置轮次时按持有数收工
                self._entry_letter_count = count
                # 探险/扼守：每进一把都从 0 开始数轮次、下一局要重新走位
                self._walked_this_mission = False
                # 这一栏的持有数就是上限：打满就撤离回列表（回到列表会重新读最新的持有数）
                self._entry_rounds_done = 0
                self._leave_after_rounds = False
                self._auto_rounds_off_confirmed = False
                self._next_auto_rounds_check = 0
                self._letter_exhausted_since = 0
                self.current_round = 0
                # 信息栏「当前轮次」也一起归零：不然撤离回列表后它还挂着上一栏的旧值，
                # 要等下一波 get_round_info 才会更新。
                self.info_set("当前轮次", 0)
                self._round_counted = False
                # 轮次计数归零之后再刷「轮次计算」（顺序反了会带上上一栏的旧轮次）
                self.update_rounds_info()
                self._next_refresh_check = None
                # 进图2 之前先在图1 读一次刷新倒计时，图2 那串读不到时拿它兜底
                seconds = self.read_refresh_countdown()
                self._board_deadline = self.refresh_deadline(seconds) if seconds else None
                self._click_detected(target, name="letter_board_task", after_sleep=0.5)
                # 等界面真的切到图2 再回主循环：列表淡出/图2 淡入那一两秒里 OCR 还会认到列表，
                # 不等的话下一圈会以为"还在列表上"又点一次。
                self.wait_until(self.find_start_interface, time_out=5, raise_if_not_found=False)
                # 图2 上先关「自动轮次」（开着会干扰轮次计算）；没确认到就交给主循环再查
                self._auto_rounds_off_confirmed = self.ensure_auto_rounds_off()
                return True
        return False

    # ---- 图2 的「自动轮次」开关 ----
    def find_auto_rounds(self):
        """图2 的「自动轮次」：返回 (是不是开着, 标题框)。

        两个信号一起用：开着时标题下面多一行「轮次x/99」；而且整块内容上移约 95px，
        所以「标题落在搜索框上半部分」也算开着（收紧的 STATE 框偶尔读不出来时兜底）。
        """
        label_box = self.screen_box('LETTER_AUTO_ROUNDS_LABEL')
        self.draw_boxes('letter_auto_rounds_label', label_box, 'blue')
        label = self.ocr(box=label_box, match=AUTO_ROUNDS_LABEL_RE)
        lb = label[0] if label else None
        state_box = self.screen_box('LETTER_AUTO_ROUNDS_STATE')
        self.draw_boxes('letter_auto_rounds_state', state_box, 'blue')
        if self.ocr(box=state_box, match=AUTO_ROUNDS_RE):
            return True, lb
        if lb is not None and (lb.y - label_box.y) < label_box.height * 0.5:
            return True, lb
        return False, lb

    def ensure_auto_rounds_off(self, attempts=3):
        """把「自动轮次」关掉：返回 True 表示现在是关的（本来就关、或这次关掉了）。

        开关是「自动轮次」那一行右侧的滑块；标题位置会随开/关上下移（约 95px），所以
        按现场 OCR 到的标题框算点击位置：y 取标题中心，x = 标题左边 + 固定距离（按标题
        宽度等比缩放，适配不同分辨率）。点一次没关掉，就沿滑块左右再试两次。
        """
        on, _ = self.find_auto_rounds()
        if not on:
            return True
        for attempt, dx in enumerate((0, -30, 30)[:attempts]):
            on, lb = self.find_auto_rounds()
            if not on:
                self.log_info("已关闭「自动轮次」")
                return True
            if lb is None:
                self.log_info("「自动轮次」开着，但没读到标题位置，跳过")
                return False
            scale = lb.width / AUTO_ROUNDS_LABEL_W if AUTO_ROUNDS_LABEL_W else 1.0
            cx = int(lb.x + AUTO_ROUNDS_SWITCH_DX * scale) + int(dx * scale)
            cy = lb.y + lb.height // 2
            switch = Box(cx - AUTO_ROUNDS_SWITCH_W // 2, cy - 12,
                         AUTO_ROUNDS_SWITCH_W, 24, 0.99, 'auto_rounds_switch')
            self.draw_boxes(switch.name, switch, 'green')
            self.log_info(f"检测到「自动轮次」开着，点开关关掉（第 {attempt + 1} 次，"
                          "开着会干扰轮次计算）")
            self.click_box_random(switch, after_sleep=0.8)
        if not self.find_auto_rounds()[0]:
            self.log_info("已关闭「自动轮次」")
            return True
        self.log_info("「自动轮次」没关掉（开关位置可能不对）")
        return False

    @staticmethod
    def column_task(data, index, mode):
        """某栏里某一种委托的 (Box, 名字)；没有就 (None, None)。"""
        if mode == MODE_DRIVE:
            box = data["drive_away"][index]
            return (box, MODE_DRIVE) if box is not None else (None, None)
        for task_name, task_box in zip(data["tasks"][index], data["task_boxes"][index]):
            if mode_of_task_name(task_name) == mode:
                return task_box, task_name
        return None, None

    def current_task_mode(self):
        """这一把挑中的是哪种委托（驱离/探险/扼守）；还没挑过就按驱离算。"""
        return self._dungeon_mode if self._dungeon_mode in TASK_MODES else MODE_DRIVE

    def is_walk_mode(self):
        """这一把要不要判图 + 走位（探险 / 扼守 要，驱离不要）。"""
        return self.current_task_mode() in WALK_MODES

    def rounds_for_mode(self, mode):
        """该模式「进一次本打多少轮」；配置读不到就回落到默认 20。"""
        key = ROUND_CONFIG_KEYS.get(mode, "探险轮次")
        try:
            return int(self.config.get(key, DEFAULT_ROUNDS))
        except (TypeError, ValueError):
            return DEFAULT_ROUNDS

    def selected_columns(self):
        """「栏目选择」勾了哪几栏，按 角色/武器/魔之楔 的顺序返回。

        配置缺失（老的存档里没这个键）按三栏全勾算；返回空列表 = 一个都没勾，
        交给「等待刷新」那套等下次刷新。
        """
        selection = self.config.get("栏目选择", COLUMN_NAMES)
        if selection is None:
            return list(COLUMN_NAMES)
        return [column for column in COLUMN_NAMES if column in selection]

    def handle_no_drive_away(self):
        """三栏都没有可打的任务：等到"刷新倒计时 + 1 分钟"再扫一遍。

        等待是分段的（每段 NO_DRIVE_AWAY_POLL_SECONDS 秒就返回主循环重扫一次列表）：
        列表上一出现能打的任务马上就能接上，停任务也能立刻响应；而且等待期间任务照常在
        取帧/发输入（框架的"鼠标抖动"线程在 sleep 里也照跑）。

        光靠抖动不够：云游戏是按"长时间未操作"断会话的，所以每隔「空窗保活间隔(分钟)」
        再点进一个委托、ESC 退出来一次（见 keepalive_click_around）。
        """
        if not self.config.get("等待刷新", True):
            self.log_info_notify("委托密函列表里没有可打的委托，任务结束")
            self.soundBeep()
            raise TaskDisabledException
        now = time.time()
        if self._next_refresh_check is None or now >= self._next_refresh_check:
            data = self.scan_letter_board(force=True)
            detail = "  ".join("%s: 持有数=%s 任务=%s" % (column, data["counts"][index], data["tasks"][index])
                               for index, column in enumerate(COLUMN_NAMES))
            self.log_info("三栏现状 -> " + detail)
            seconds = self.read_refresh_countdown()
            wait = seconds + REFRESH_TOLERANCE_SECONDS if seconds else REFRESH_WAIT_FALLBACK_SECONDS
            self._next_refresh_check = now + wait
            self._next_keepalive = now + self.keepalive_interval_seconds()
            self.log_info_notify(f"暂时没有可打的委托（驱离/探险/扼守），{int(wait)} 秒后（刷新后 1 分钟）再扫一遍")
            self.soundBeep()
        self.sleep(NO_DRIVE_AWAY_POLL_SECONDS)
        # 空窗期别让会话凉着：定期点进一个委托再退出来
        if time.time() >= self._next_keepalive:
            self.keepalive_click_around()

    def read_refresh_countdown(self):
        """读图1 右下角「xx分xx秒刷新密函委托」的倒计时，返回秒数；读不到返回 None。"""
        box = self.screen_box('LETTER_REFRESH')
        self.draw_boxes(box.name, box, 'blue')
        found = self.ocr(box=box, match=REFRESH_RE)
        if not found:
            return None
        match = REFRESH_RE.search(found[0].name)
        if not match:
            return None
        return int(match.group(1)) * 60 + int(match.group(2))
