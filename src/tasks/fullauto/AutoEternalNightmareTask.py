# -*- coding: utf-8 -*-
"""全自动「永恒梦魇」。

一轮的流程：
  活动首页点「开始挑战」-> 等待进本 -> 稳 RUN_SETTLE 秒 -> 按住 W 前进 1 秒
  -> 按「主控角色」的手法持续放技能 -> 打完出现结算页 -> 点「再次进行」进下一轮
  -> 打满「轮次」结束（0 = 无限循环）。

起手有讲究：本模块**只在「永恒梦魇」活动界面才能开始**。进任务先给
ACTIVITY_INTERFACE_TIMEOUT 秒缓冲去找「开始挑战」按钮，或左侧的「永恒 / 高难挑战」文案，找不到就带系统提示
停止（"请进入永恒梦魇的活动界面"），不会乱点。

失败自愈（照上游「自动狩月人」那份 AutoMoonHunterTask 的写法）：
  * 进本后连续 NO_COMBAT_TIME_OUT 秒认不出局内（掉线 / 卡读条 / 结算页被漏读）：重开一局；
  * 连续失败 RESTART_FAILURE_LIMIT 次：报错停止，不再无限重开；
  * 卡在加载/过场 LOAD_TIME_OUT 秒还认不出界面：报错停止，不空转；
  * 点完「再次进行」会等结算页真的消失，免得重复点、重复计数。

技能按「主控角色」走：法露茜按它的手法（锁定后连按 5 下终结技，再一直普攻、每 3 秒连按两下战技）、
「无」直接执行「全局技能设定」、「自定义」用「自定义序列」；走位、结算、重开期间不按技能。
"""

from qfluentwidgets import FluentIcon
import re
import time

from ok import Logger, TaskDisabledException
from src.dna_ui.Defs import COORD
from src.tasks.DNAOneTimeTask import DNAOneTimeTask
from src.tasks.CommissionsTask import CommissionsTask
from src.tasks.BaseCombatTask import BaseCombatTask

logger = Logger.get_logger(__name__)

# ---- 界面判据 label（标注在 assets 的 coco 标注里，运行期从模板取）----
# 和沉浸式戏剧一样，这些 label 的搜索框就是标注本身（框架按标注位置 ±0.4% 的方差搜），
# 位置固定、框也很紧，所以不写进 Defs.DISCRIMINATORS；点击坐标统一放 Defs.COORD。
START_BTN = 'en_start_btn'                     # 活动首页「开始挑战」按钮里的 ◯ 图标（起手判据）
START_CONFIRM = 'start_screen_start_btn_3_1'   # 「确认进入」弹窗的「确定」（各模式共用）
ESC_RETRY = 'esc_retry'                        # 局内菜单「重新开始」（和戏剧共用同一个菜单）
RESTART_CONFIRM = 'esc_restart_check_btn'      # 「是否重新开始战斗」二次确认弹窗的「确定」

# 活动首页左侧难度栏的文案（OCR 区域见 Defs.SCREEN_BOX.EN_ACTIVITY_TABS）。
# 两个难度都会显示在左栏，选中哪个都能认出这是活动首页；真正要打哪个由用户先选好。
ACTIVITY_TEXTS = ('永恒', '高难挑战')
ACTIVITY_OCR_INTERVAL = 0.5

# 走位时间轴：先按 W，保持 1 秒后松开，即直线前进 1 秒。
# 每一项是 (相对上一步的等待秒数, 按键, 按下/抬起)。
WALK_SCHEDULE = (
    (0.0, 'w', True),
    (1.0, 'w', False),
)
# 走位期间按住 lalt 锁视角，免得防挂机的鼠标抖动把镜头带偏（其他全自动任务同样处理）
WALK_HOLD_KEYS = ('lalt',)
# 中途被打断时不能让它一直按着；shift 也一并松开，防止旧按键残留
WALK_RELEASE_KEYS = ('w', 'a', 's', 'd', 'shift')

# 关卡加载完之后先稳这么久再走位：判据刚出来时角色还在落地/过场收尾，按走位键会被吃掉
RUN_SETTLE = 1
# 起手序列里没写「锁定」时，走位完自动按「锁定键」（游戏快捷键设置里配，默认鼠标中键）
# 锁定目标，再稳这么久往下。按太快那一下会被游戏吃掉（实测中键后 88ms 就按技能）。
# 这是默认值，角色表里可以用 lock_settle 覆盖
LOCK_SETTLE = 1.5
# 起手判据的缓冲（秒）：进任务后最多找这么久，还没在「永恒梦魇」活动界面就提示停止
ACTIVITY_INTERFACE_TIMEOUT = 2.0
# 点了「开始挑战」/「重新开始」之后等离开当前界面、等进关卡加载完成的上限
LOAD_TIME_OUT = 30
# 加载/过场画面连续这么久都认不出来才报错停止：云游戏偶尔加载超过 30 秒（实测有），
# 那期间只存一张截图 + 提示 + 继续等，别把这一整局白丢掉
UNKNOWN_SCREEN_GIVE_UP = 180
# 兜底：进本后连续这么久认不出局内（掉线、卡在读条、结算页被漏读）就 ESC 重开一局
NO_COMBAT_TIME_OUT = 30
# 连续失败（开不了战 / 结算点不动）几次后报错停止。配置里只留「轮次」，这个用内部常量
RESTART_FAILURE_LIMIT = 3
# 「超时重启」：从进战那一刻开始算，打这么久还没进结算页就重启这一局（0 = 不限制）
COMBAT_TIMEOUT_KEY = "超时重启"
COMBAT_TIMEOUT_DEFAULT = 180

# 「主控角色」-> 该角色的技能手法：
#   opening: 起手序列。走位之后先放一遍（只放一次），放完再接循环序列；可以写「锁定」动作
#   lock_settle: 可选。起手序列里**没写**「锁定」时，走位完自动锁定 + 等这么久（默认 LOCK_SETTLE）
#   spam + timed: 可选，"按真实时间"的循环手法（和 steps 二选一）：
#     spam  = "普攻"（一直按，不加额外间隔）或 (动作, 最小间隔秒数)
#     timed = ((间隔秒数, (动作, ...)), ...)：每隔这么多秒，把这一组动作连着按完
#             例：spam 普攻 + timed 每 3 秒连按两下战技
#   steps:   ((动作, 放完之后等几秒), ...)，动作取值沿用「全局技能设定」那套
#            （短按战技 / 长按战技 / 终结技 / 魔灵支援 / 普攻 / 重击）
#   loop:    True  = steps 一直循环放；循环型每进一次主循环只走一步，循环期间还能继续判界面
#            False = steps 整串放一遍就停
# 走位和主控角色无关（所有角色共用上面那段录制时序），角色之间只差这张表。
CHARACTER_ROTATIONS = {
    # 法露茜：起手序列 = 锁定（等 0.5 秒）-> 连按 5 下终结技（冷却中游戏会忽略；哪一下被
    # 吃掉，后面几下补上；最后一个后面留 1 秒等演出）。
    # 循环序列 = 一直连按普攻、每 3 秒连按两下战技、每 20 秒放一次终结技。
    "法露茜": {"opening": (("锁定", 0.5), ("终结技", 0.1), ("终结技", 0.1), ("终结技", 0.1),
                           ("终结技", 0.1), ("终结技", 1.0)),
               "spam": "普攻",
               "timed": ((3.0, ("短按战技", "短按战技")),
                         (20.0, ("终结技",)))},
}

# 「无」：不套角色手法，直接执行「全局技能设定」的技能配置
NO_CHARACTER = "无"
# 「自定义」：技能与等待全由用户自己写（见「自定义序列」）
CUSTOM_CHARACTER = "自定义"
# 默认主控角色 = 无（不套角色手法，用全局技能配置）
DEFAULT_CHARACTER = NO_CHARACTER
CUSTOM_SEQUENCE_KEY = "自定义序列"
DEFAULT_CUSTOM_SEQUENCE = "终结技:1"
# 自定义序列里允许的动作名（战技 = 短按），和 release_character_action 的分支一一对应
CUSTOM_ACTIONS = {
    "战技": "短按战技",
    "短按战技": "短按战技",
    "长按战技": "长按战技",
    "终结技": "终结技",
    "魔灵支援": "魔灵支援",
    "普攻": "普攻",
    "重击": "重击",
    "锁定": "锁定",
}
# 「长按战技」按住的秒数、「重击」按住左键的秒数（和「全局技能设定」的默认值一致）
COMBAT_LONG_PRESS = 1.0
HEAVY_ATTACK_HOLD = 1.5
# timed 那一组里"连按几下"的间隔（比如连按两下战技，中间隔这么久）
TIMED_BURST_GAP = 0.1


class AutoEternalNightmareTask(DNAOneTimeTask, CommissionsTask, BaseCombatTask):
    """全自动「永恒梦魇」：活动界面点开始 -> 走位开战 -> 按主控角色放技能 -> 结算重开。

    只在「永恒梦魇」活动界面才启动（起手判据见 ensure_activity_interface）；
    失败自愈（局内重开 / 失败上限 / 认不出界面报错 / 等结算页消失）见模块开头的说明。
    角色技能手法沿用「自动狩月人之阶」，界面识别和轮次流程按永恒梦魇调整。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.FLAG
        self.name = "自动永恒梦魇"
        self.description = "自动刷永恒梦魇"
        self.group_name = "全自动（活动）"
        self.group_icon = FluentIcon.GAME

        # 这个模式没有「挂机模式」那套移动/复位配置：只有轮次 + 超时重启
        self.default_config.update({
            "轮次": 0,
            COMBAT_TIMEOUT_KEY: COMBAT_TIMEOUT_DEFAULT,
            "主控角色": DEFAULT_CHARACTER,
            CUSTOM_SEQUENCE_KEY: DEFAULT_CUSTOM_SEQUENCE,
        })
        self.config_type["主控角色"] = {
            "type": "drop_down",
            "options": list(CHARACTER_ROTATIONS) + [NO_CHARACTER, CUSTOM_CHARACTER],
        }
        self.config_description.update({
            "轮次": "连打多少轮，0 = 无限循环",
            COMBAT_TIMEOUT_KEY: "从进战开始算，超过这么多秒还没结算就重启这一局（0 = 不限制）",
            "主控角色": "选角色就按它的手法放技能；选「无」不套手法、直接执行「全局技能设定」"
                          "（走位和主控角色无关）",
            CUSTOM_SEQUENCE_KEY: "选「自定义」时用：每一步写成「技能:等待秒数」，逗号分隔。"
                                 "例：终结技:1, 战技:1",
        })

        self.character_steps = None
        self.character_spam = None
        self.character_timed = ()
        self.timed_next = []
        self.timed_started = False
        self.lock_settle = LOCK_SETTLE
        self.character_opening = ()
        self.character_loops = False
        self.opening_done = False
        self.fallback_skill_tick = None
        self.step_index = 0
        self.sequence_done = False
        self.mission_started = False
        self.current_run = 0
        self.run_failures = 0
        self.next_activity_ocr = 0.0
        self.activity_tabs_found = False

    def run(self):
        DNAOneTimeTask.run(self)
        self.move_mouse_to_safe_position(save_current_pos=False)
        self.set_check_monthly_card()
        try:
            return self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error("AutoEternalNightmareTask error", e)
            raise

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def do_run(self):
        """主循环：看画面属于哪个界面就处理哪个，打满「轮次」正常返回。

        起手必须停在「永恒梦魇」活动界面（起手判据）；中途的加载/过场画面只是等一下。
        """
        self.load_char()
        if not self.ensure_activity_interface():
            self.log_info_notify("请进入永恒梦魇的活动界面")
            self.soundBeep()
            raise TaskDisabledException
        self.setup_character()
        self.init_all()
        while True:
            self.next_frame()
            if self.find_result_again_btn():
                if self.handle_result():
                    return
            elif self.in_mission():
                self.handle_in_mission()
            elif self.on_activity_interface():
                self.start_mission()
            else:
                self.wait_screen_back()
            self.sleep(0.2)

    def ensure_activity_interface(self):
        """起手：给 ACTIVITY_INTERFACE_TIMEOUT 秒缓冲找活动界面，找不到返回 False。"""
        deadline = time.time() + ACTIVITY_INTERFACE_TIMEOUT
        while True:
            self.next_frame()
            if self.on_activity_interface():
                self.log_info("已在「永恒梦魇」活动界面，开始执行")
                return True
            if time.time() >= deadline:
                return False
            self.sleep(0.2)

    def init_all(self):
        """每次启动都从头开始：计数清零、这一局还没走位、技能序列还没放。"""
        self.current_run = 0
        self.run_failures = 0
        self.mission_started = False
        self.reset_sequence_state()

    def wait_screen_back(self, time_out=LOAD_TIME_OUT):
        """卡在加载/过场画面：等认出下一个界面。

        每等满 time_out 秒还认不出来：第一次存一张截图，然后响一下、提示一条，继续等。
        连续 UNKNOWN_SCREEN_GIVE_UP 秒都认不出来才报错停止 —— 云游戏加载慢时不会再把
        这一局白丢掉；真卡在别的界面上，截图（screenshots/eternal_nightmare_unknown_screen）
        和日志能直接看出来。
        """
        self.log_info('等待界面切换（加载/过场）...')
        start = time.time()
        next_warn = start + time_out
        shot = False
        while True:
            self.sleep(0.5)
            if self.known_screen():
                return
            now = time.time()
            if now >= next_warn:
                next_warn = now + time_out
                if not shot:
                    shot = True
                    self.screenshot(name='eternal_nightmare_unknown_screen')
                self.soundBeep()
                self.log_info_notify(f'已等了 {int(now - start)} 秒还认不出当前界面，继续等'
                                     f'（截图见 screenshots/eternal_nightmare_unknown_screen）')
            if now - start >= UNKNOWN_SCREEN_GIVE_UP:
                raise Exception(f'连续 {UNKNOWN_SCREEN_GIVE_UP} 秒认不出当前界面，停止任务'
                                f'（截图见 screenshots/eternal_nightmare_unknown_screen）')

    def target_runs(self):
        """读「轮次」配置：0 表示无限循环，读不出来也当无限。"""
        try:
            return max(0, int(self.config.get('轮次', 0)))
        except (TypeError, ValueError):
            return 0

    def combat_timeout(self):
        """「超时重启」配置：进战后最多打多少秒，0 = 不限制。"""
        try:
            return max(0.0, float(self.config.get(COMBAT_TIMEOUT_KEY,
                                                  COMBAT_TIMEOUT_DEFAULT)))
        except (TypeError, ValueError):
            return COMBAT_TIMEOUT_DEFAULT

    def note_failure(self, reason):
        """记一次连续失败：超过上限就报错停止（配置里只有「轮次」，上限用内部常量）。"""
        self.run_failures += 1
        if self.run_failures > RESTART_FAILURE_LIMIT:
            raise Exception(f'连续 {self.run_failures} 次{reason}，停止任务')
        self.log_info(f'{reason}（第 {self.run_failures} 次，最多 {RESTART_FAILURE_LIMIT} 次），'
                      f'ESC 重新开始')

    # ------------------------------------------------------------------
    # 界面判据
    # ------------------------------------------------------------------

    def known_screen(self):
        """是不是一个能开工的界面（活动界面 / 结算页 / 局内）。"""
        return (self.in_mission()
                or self.find_result_again_btn() is not None
                or self.on_activity_interface())

    def in_mission(self):
        """是不是在局内（局内菜单盖在 HUD 上时也算）。"""
        return self.in_team() or self.find_one(ESC_RETRY) is not None

    # ------------------------------------------------------------------
    # 活动界面
    # ------------------------------------------------------------------

    def activity_tabs_visible(self):
        """OCR 活动首页左侧难度栏，缓存 ACTIVITY_OCR_INTERVAL 秒。"""
        if time.time() < self.next_activity_ocr:
            return self.activity_tabs_found
        self.next_activity_ocr = time.time() + ACTIVITY_OCR_INTERVAL
        self.activity_tabs_found = False
        texts = self.ocr(box=self.screen_box('EN_ACTIVITY_TABS'), threshold=0.35)
        for text_box in texts:
            name = text_box.name.replace(' ', '')
            if any(needle in name for needle in ACTIVITY_TEXTS):
                self.activity_tabs_found = True
                break
        return self.activity_tabs_found

    def on_activity_interface(self):
        """在活动首页：开始挑战按钮命中，或左侧「永恒 / 高难挑战」文案命中。"""
        return (self.find_one(START_BTN) is not None
                or self.activity_tabs_visible())

    def left_start_screen(self):
        """已经不在活动界面（无论在加载还是已经进图）。"""
        return not self.on_activity_interface() and self.find_one(START_CONFIRM) is None

    def start_mission(self, time_out=LOAD_TIME_OUT):
        """活动界面：点「开始挑战」，有「确认进入」弹窗就点「确定」，然后等离开这个界面。

        弹窗不是每次都有（游戏里能设成不再提示），而且弹窗一盖上来「开始挑战」就被压暗到
        认不出来 —— 所以"弹窗出现"和"已经进图"都算这一步走通，谁先到算谁。
        云游戏会丢点击，所以点一次没动静就再点一次（间隔 1 秒）。
        """
        def confirm_or_left():
            return self.find_one(START_CONFIRM) is not None or self.left_start_screen()

        if not self.wait_until(confirm_or_left, time_out=time_out,
                               post_action=lambda: self.click_ui_coord(
                                   COORD.EN_START, name=START_BTN, after_sleep=1),
                               raise_if_not_found=False):
            raise Exception(f'点了「开始挑战」之后 {time_out} 秒还停在活动界面'
                            f'（门票/体力不足或点击没生效）')
        if self.find_one(START_CONFIRM):
            if not self.wait_until(self.left_start_screen, time_out=time_out,
                                   post_action=lambda: self.click_ui_coord(
                                       COORD.START_CONFIRM, name=START_CONFIRM, after_sleep=1),
                                   raise_if_not_found=False):
                raise Exception('点了「确认进入」的「确定」之后没能进关卡（门票/体力不足？）')

    # ------------------------------------------------------------------
    # 局内：等加载 -> 走位 -> 打到结算页
    # ------------------------------------------------------------------

    def handle_in_mission(self):
        """局内一次处理：走位触发战斗，然后一直打到结算页或需要重开一局。"""
        if self.find_one(ESC_RETRY):
            # 局内菜单被打开了（一般是玩家自己按的 ESC）：关掉继续，绝不在这里点菜单
            self.send_key("esc", after_sleep=0.5)
            return
        if not self.mission_started:
            self.wait_mission_loaded()
            self.sleep(RUN_SETTLE)
            self.mission_started = True
            self.reset_sequence_state()
            self.play_walk()
            # 起手序列里自己写了「锁定」的（法露茜），锁定和它的等待都在起手序列里，这里不重复锁；
            # 没写的（「无」/「自定义」）走位完自动锁一下 + 稳 lock_settle 秒
            if not self.plan_has_lock():
                self.log_info("走位结束，按锁定键（%s）锁定目标，稳 %.1f 秒"
                              % (self.get_lock_key(), self.lock_settle))
                self.press_hotkey(self.get_lock_key())
                self.sleep(self.lock_settle)
        # 进本后直接进入开打循环；这个活动没有狩月人之阶那种红菱形判据，
        # 用局内 HUD（左下角 Lv / 右下角 Q）确认还在局内，然后持续放技能。
        if not self.fight_until_result():
            # 长时间认不出局内（掉线、卡在读条）：已经重开了一局，退回重新走位
            self.mission_started = False

    def wait_mission_loaded(self, time_out=LOAD_TIME_OUT):
        """等关卡加载完：通用局内 HUD（左下角 Lv / 右下角 Q）出来就算。"""
        if not self.wait_until(lambda: self.in_mission(),
                               time_out=time_out, raise_if_not_found=False):
            raise Exception(f'等了 {time_out} 秒还没进关卡（门票/体力不足或掉线？）')

    def play_walk(self):
        """按固定时间轴前进 1 秒；全程按住 lalt 锁视角，不管成功失败都松开所有按键。"""
        self.log_info("开始走位")
        for key in WALK_HOLD_KEYS:
            self.send_key_down(key)
        try:
            for wait, key, down in WALK_SCHEDULE:
                self.sleep(wait)
                if down:
                    self.send_key_down(key)
                else:
                    self.send_key_up(key)
        finally:
            for key in WALK_RELEASE_KEYS:
                self.send_key_up(key)
            for key in WALK_HOLD_KEYS:
                self.send_key_up(key)
        self.log_info("走位结束")

    def fight_until_result(self):
        """挂机。返回 True = 结算页出现（这一轮打完），False = 该重开一局。

        「超时重启」：从**进战那一刻**开始计时，超过配置的秒数还没进结算页就重启这一局；
        结算（或者重开完的下一局）会重新从进战开始算。
        只有连续 NO_COMBAT_TIME_OUT 秒认不出局内 HUD（掉线、卡在读条、结算页被漏读）
        才算没在战斗 —— 重开一局。
        """
        no_combat_since = None
        combat_since = None
        while True:
            self.next_frame()
            if self.find_result_again_btn():
                return True
            if self.find_one(ESC_RETRY):
                # 局内菜单被打开了（一般是玩家自己按的 ESC）：关掉继续，绝不在这里点菜单
                self.send_key("esc", after_sleep=0.5)
                continue
            in_combat = self.in_team()
            if in_combat:
                no_combat_since = None
                self.run_failures = 0
                if combat_since is None:
                    combat_since = time.time()
                timeout = self.combat_timeout()
                if timeout and time.time() - combat_since >= timeout:
                    self.log_info(f'进战已 {int(time.time() - combat_since)} 秒还没结算'
                                  f'（超时重启 {int(timeout)} 秒），重启这一局')
                    self.restart_in_mission()
                    return False
                self.play_character_sequence()
            elif no_combat_since is None:
                no_combat_since = time.time()
            elif time.time() - no_combat_since > NO_COMBAT_TIME_OUT:
                self.note_failure(f'{NO_COMBAT_TIME_OUT} 秒没在局内')
                self.restart_in_mission()
                return False
            self.sleep(0.2)

    def restart_in_mission(self, time_out=10, load_time_out=LOAD_TIME_OUT):
        """局内重来：ESC 开菜单 -> 点「重新开始」-> 点二次确认的「确定」。

        两个都是云游戏爱丢的点击，所以都是"点到出结果为止"：先点到弹窗出来，再点到弹窗消失。
        重开会把关卡重新加载一遍，菜单/弹窗/加载画面都会盖掉局内判据，所以"先消失再回来"
        正好当重开完成的信号；万一它没消失（秒重开）也不会卡住，直接往下走。
        """
        start = time.time()
        while not self.find_one(ESC_RETRY):
            if time.time() - start > time_out:
                raise Exception('局内菜单打不开，没法重新开始')
            self.send_key("esc")
            self.wait_until(lambda: self.find_one(ESC_RETRY) is not None, time_out=2,
                            raise_if_not_found=False)
        self.wait_until(
            condition=lambda: self.find_one(RESTART_CONFIRM) is not None,
            post_action=lambda: self.click_ui_coord(COORD.ESC_MENU_RETRY, name=ESC_RETRY,
                                                    after_sleep=0.5),
            time_out=time_out,
        )
        self.wait_until(
            condition=lambda: not self.find_one(RESTART_CONFIRM),
            post_action=lambda: self.click_ui_coord(COORD.ESC_MENU_RETRY_CONFIRM,
                                                    name=RESTART_CONFIRM, after_sleep=0.5),
            time_out=time_out,
        )
        # 弹窗没了不等于真重开了：局内菜单必须也关掉，否则走位键全打进菜单里。
        # 云游戏丢那一下点击时就是这种情况：菜单还开着，可 in_team() 已经是真，
        # wait_mission_loaded() 会立刻放行 -> 后面每一步都失败。
        if not self.wait_until(lambda: self.find_one(ESC_RETRY) is None, time_out=time_out,
                               raise_if_not_found=False):
            raise Exception('点了「重新开始」之后局内菜单一直没关掉，停止任务')
        self.wait_mission_loaded(time_out=load_time_out)

    # ------------------------------------------------------------------
    # 结算页
    # ------------------------------------------------------------------

    def handle_result(self):
        """结算页：点「再次进行」直接开下一轮。返回是否该结束任务。"""
        self.mission_started = False
        self.run_failures = 0
        self.current_run += 1
        self.info_set("已完成轮次", str(self.current_run))
        self.log_info(f'第 {self.current_run} 轮完成')
        target = self.target_runs()
        if target and self.current_run >= target:
            self.log_info(f'已经打满 {target} 轮，任务结束')
            return True
        self.log_info('点击「再次进行」')
        self.click_ui_coord(COORD.RESULT_AGAIN, name='result_again_btn', after_sleep=1)
        self.wait_left_result()
        return False

    def wait_left_result(self, time_out=LOAD_TIME_OUT):
        """点了「再次进行」之后等离开结算页，免得下一轮又点一次。"""
        if not self.wait_until(lambda: self.find_result_again_btn() is None,
                               time_out=time_out, raise_if_not_found=False):
            raise Exception(f'点了「再次进行」之后 {time_out} 秒还停在结算页（门票/体力不足？）')

    # ------------------------------------------------------------------
    # 主控角色手法（和「自动迷津」同一套写法）
    # ------------------------------------------------------------------

    def current_character(self):
        return self.config.get("主控角色", DEFAULT_CHARACTER)

    def plan_has_lock(self):
        """这套手法里是不是自己带了「锁定」动作（带了就不在走位之后自动锁）。"""
        actions = [action for action, _ in self.character_opening]
        if self.character_steps:
            actions += [action for action, _ in self.character_steps]
        if self.character_spam:
            actions.append(self.character_spam[0])
        for _, group in self.character_timed:
            actions += list(group)
        return "锁定" in actions

    def setup_character(self):
        """按「主控角色」取技能序列；取不到就退回全局技能计时器。"""
        name = self.current_character()
        if name == CUSTOM_CHARACTER:
            steps = self.parse_custom_steps()
            if steps:
                self.log_info("自定义技能序列: %s"
                              % " -> ".join("%s后等%.1f秒" % step for step in steps))
                self.character_steps = steps
                self.character_spam = None
                self.character_timed = ()
                self.lock_settle = LOCK_SETTLE
                self.character_opening = ()
                self.character_loops = False
                self.fallback_skill_tick = None
                return
            self.log_info("「%s」没解析出任何步骤，改用「%s」"
                          % (CUSTOM_SEQUENCE_KEY, DEFAULT_CHARACTER))
            name = DEFAULT_CHARACTER
        if name == NO_CHARACTER:
            self.log_info("主控角色「%s」：直接执行「全局技能设定」的技能配置" % NO_CHARACTER)
            self.character_steps = None
            self.character_spam = None
            self.character_timed = ()
            self.lock_settle = LOCK_SETTLE
            self.character_opening = ()
            self.character_loops = False
            self.fallback_skill_tick = self.create_skill_ticker()
            return
        rotation = CHARACTER_ROTATIONS.get(name)
        if rotation is None:
            self.log_info("没有「%s」的技能手法，退回全局技能计时器" % name)
            self.character_steps = None
            self.character_spam = None
            self.character_timed = ()
            self.lock_settle = LOCK_SETTLE
            self.character_opening = ()
            self.character_loops = False
            self.fallback_skill_tick = self.create_skill_ticker()
        else:
            self.character_steps = rotation.get("steps")
            spam = rotation.get("spam")
            # spam 可以写 "普攻"（一直按、不加额外间隔），也可以写 (动作, 间隔秒数)
            self.character_spam = (spam, 0.0) if isinstance(spam, str) else spam
            self.character_timed = rotation.get("timed") or ()
            self.lock_settle = float(rotation.get("lock_settle", LOCK_SETTLE))
            self.character_opening = rotation.get("opening") or ()
            self.character_loops = bool(rotation.get("loop", False))
            self.fallback_skill_tick = None

    def parse_custom_steps(self):
        """把「自定义序列」解析成 ((动作, 等待秒数), ...)；解析不出任何一步就返回空。

        格式：每一步用中英文逗号、分号、顿号或换行分隔，写成「技能」或「技能:等待秒数」。
        技能名写「战技」按短按处理，「长按战技」按住 COMBAT_LONG_PRESS 秒。
        """
        raw = str(self.config.get(CUSTOM_SEQUENCE_KEY, DEFAULT_CUSTOM_SEQUENCE) or "")
        steps = []
        for part in re.split(r"[,;，；、\n\r]+", raw):
            part = part.strip()
            if not part:
                continue
            action, _, wait_text = part.partition(":")
            action = CUSTOM_ACTIONS.get(action.strip())
            if action is None:
                self.log_info("自定义序列第 %d 步技能名不认识，已跳过: %s"
                              % (len(steps) + 1, part))
                continue
            try:
                wait = float(wait_text) if wait_text.strip() else 1.0
            except ValueError:
                wait = 1.0
            steps.append((action, max(0.0, wait)))
        return tuple(steps)

    def reset_sequence_state(self):
        """这一局的技能序列还没放（开场技也还没放）。"""
        self.sequence_done = False
        self.opening_done = False
        self.step_index = 0
        self.timed_next = []
        self.timed_started = False

    def play_character_sequence(self):
        """按「主控角色」的手法放技能：锁定目标之后才开始。

        opening（可选）：这一局开打后先放一遍，只放一次（法露茜的终结技就是这条）。
        spam + timed（可选）：按真实时间跑的循环 —— 一直按 spam、每隔 N 秒放一组 timed。
        steps + loop=True：一直循环 steps；loop=False：steps 整串放一遍就停。
        """
        if (self.character_steps is None and self.character_spam is None
                and not self.character_timed):
            # 没有角色手法（「无」或认不出的名字）：退回全局技能计时器
            if self.fallback_skill_tick is not None:
                self.fallback_skill_tick()
            return

        if not self.opening_done:
            self.opening_done = True
            if self.character_opening:
                self.log_info("开场技能（只放一次）: %s" % self.describe_steps(self.character_opening))
                for action, wait in self.character_opening:
                    self.release_character_action(action)
                    self.sleep(wait)

        if self.character_spam is not None or self.character_timed:
            self.play_timed_rotation()
            return

        if not self.character_loops:
            if self.sequence_done:
                return
            self.sequence_done = True
            self.log_info("执行「%s」技能序列（放一遍）: %s"
                          % (self.current_character(), self.describe_steps()))
            for action, wait in self.character_steps:
                self.release_character_action(action)
                self.sleep(wait)
            return

        if not self.sequence_done:
            self.sequence_done = True
            self.log_info("开始循环「%s」技能手法: %s"
                          % (self.current_character(), self.describe_steps()))
        action, wait = self.character_steps[self.step_index % len(self.character_steps)]
        self.step_index += 1
        self.log_info("循环技能第 %d 步: %s" % (self.step_index, action))
        self.release_character_action(action)
        self.sleep(wait)

    def play_timed_rotation(self):
        """按真实时间放技能（spam + timed）：一次调用最多做一件事。

        先看有没有到点的 timed 组（到了就把这一组连着按完、再安排下一次），没有就按一下 spam。
        法露茜那套「一直普攻、每 3 秒连按两下战技、每 20 秒放一次终结技」就是这种 ——
        按真实时间算，不受主循环一轮多久影响。
        """
        now = time.time()
        if not self.timed_started:
            # 开场序列跑完后再开始计时。带终结技的定时组先等满一个周期，
            # 避免开场刚连放 5 下终结技，循环一开始又立刻补放一次。
            self.timed_started = True
            self.timed_next = [
                now + (interval if "终结技" in actions else 0.0)
                for interval, actions in self.character_timed
            ]
        for index, (interval, actions) in enumerate(self.character_timed):
            if now >= self.timed_next[index]:
                self.timed_next[index] = now + interval
                self.log_info("定时技能（每 %.1f 秒）: %s"
                              % (interval, " + ".join(actions)))
                for action in actions:
                    self.release_character_action(action)
                    self.sleep(TIMED_BURST_GAP)
                return
        if self.character_spam is None:
            self.sleep(0.05)
            return
        action, gap = self.character_spam
        self.release_character_action(action)
        if gap > 0:
            self.sleep(gap)      # 没写间隔就是"一直按"，节奏由主循环决定

    def describe_steps(self, steps=None):
        steps = self.character_steps if steps is None else steps
        return " -> ".join("%s后等%.1f秒" % (action, wait) for action, wait in steps)

    def release_character_action(self, action):
        """放一次角色序列里的动作。

        直接按键，不走角色对象；键值一律取「游戏快捷键设置」里的战技 / 终结技 / 魔灵支援，
        普攻取「普攻键」（默认鼠标左键），所以游戏里改过键，只要 App 里这份设置跟着改就一致。
        """
        if action == "长按战技":
            self.log_info("放技能: 长按战技（键 %s，按住 %.1f 秒）"
                          % (self.get_combat_key(), COMBAT_LONG_PRESS))
            self.send_key(self.get_combat_key(), down_time=COMBAT_LONG_PRESS)
        elif action == "短按战技":
            self.log_info("放技能: 短按战技（键 %s）" % self.get_combat_key())
            self.send_key(self.get_combat_key())
        elif action == "终结技":
            self.log_info("放技能: 终结技（键 %s）" % self.get_ultimate_key())
            self.send_key(self.get_ultimate_key())
        elif action == "魔灵支援":
            self.log_info("放技能: 魔灵支援（键 %s）" % self.get_geniemon_key())
            self.send_key(self.get_geniemon_key())
        elif action == "普攻":
            self.log_info("放技能: 普攻（键 %s）" % self.get_normal_attack_key())
            self.press_hotkey(self.get_normal_attack_key())
        elif action == "锁定":
            self.log_info("锁定目标（键 %s）" % self.get_lock_key())
            self.press_hotkey(self.get_lock_key())
        elif action == "重击":
            self.log_info("放技能: 重击（按住 %.1f 秒）" % HEAVY_ATTACK_HOLD)
            self.mouse_down()
            try:
                self.sleep(HEAVY_ATTACK_HOLD)
            finally:
                self.mouse_up()
        else:
            raise ValueError("未知技能动作: %s" % action)

