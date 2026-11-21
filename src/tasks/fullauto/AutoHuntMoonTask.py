# -*- coding: utf-8 -*-
"""全自动「狩月人之阶」（巅峰赛活动，**仅限巅峰赛**）。

一轮的流程：
  活动界面点「开始挑战」（有「确认进入」弹窗就点它的「确定」）-> 进本加载 -> 左上角出现
  金色菱形（关卡已加载）-> 稳 RUN_SETTLE 秒后按黄色追踪点图标判地图（狩月平地 / 狩月高台，
  各走各的录制时间轴）-> 锁定目标（起手序列里写了「锁定」就用它）
  -> 菱形变红 = 已开战 -> 按「主控角色」的手法放技能（法露茜：起手锁定 + 连按 5 下终结技，循环普攻 + 每 3 秒连按两下战技）
  -> 结算页（成功点左下角圆形箭头图标重开，失败点「重新开始」）
  -> 点对应的重开按钮接着下一局，打满「打几次」结束（0 = 无限循环）。

可以从任意界面接手：活动页就点「开始挑战」，结算页按成功/失败点对应的
重开按钮，局内就继续打（已经在战斗中会跳过走位，直接按技能）。

失败自愈（照上游「自动狩月人」那份 AutoMoonHunterTask 的写法）：
  * 战斗中菱形连续消失 NO_COMBAT_TIME_OUT 秒（掉线 / 卡读条 / 结算页被漏读）：重开一局；
  * 连续失败 RESTART_FAILURE_LIMIT 次：报错停止，不再无限重开；
  * 卡在加载/过场 LOAD_TIME_OUT 秒还认不出界面：报错停止，不空转；
  * 点完「重新开始」会等结算页真的消失，免得重复点、重复计数。

技能按「主控角色」走：法露茜按它的手法（锁定后连按 5 下终结技，再一直普攻、每 3 秒连按两下战技、
每 20 秒补一次终结技）、
黎瑟SP 用终结技自动开镜，前 3 发读准星百分比到 100% 按普攻；之后固定 1.2 秒射击一次（不再 OCR）；每 1 秒长按战技 0.4 秒刷新，
开局 6 秒放一次魔灵支援。
「无」直接执行「全局技能设定」、「自定义」用「自定义序列」；走位、结算、重开期间不按技能。
"""

from qfluentwidgets import FluentIcon
import cv2
import re
import time

from ok import Logger, TaskDisabledException
from src.dna_ui.Defs import COORD, REF_HEIGHT, REF_WIDTH
from src.char.CharacterRotation import CHARACTER_ROTATIONS, rotations_for
from src.char.CharacterRotationMixin import CharacterRotationMixin
from src.tasks.DNAOneTimeTask import DNAOneTimeTask
from src.tasks.CommissionsTask import CommissionsTask
from src.tasks.BaseCombatTask import BaseCombatTask

logger = Logger.get_logger(__name__)

# ---- 界面判据 label（标注在 assets 的 coco 标注里，运行期从模板取）----
# 和沉浸式戏剧一样，这些 label 的搜索框就是标注本身（框架按标注位置 ±0.4% 的方差搜），
# 位置固定、框也很紧，所以不写进 Defs.DISCRIMINATORS；点击坐标统一放 Defs.COORD。
START_BTN = 'syr_start_btn_17'                    # 活动界面「开始挑战」按钮里的 ◯ 图标（起手判据）
HUD_START = 'syr_hud_start'                    # 局内左上角金色菱形：关卡已加载、还没开战
HUD_FIGHT = 'syr_hud_fight'                    # 同一个菱形的战斗态标注，只做判据兜底
RESULT_RESTART = 'syr_hud_restart'             # 结算页「重新开始」的环形箭头
# 1.7 的结算页有两种布局：成功 = 左下角单独的圆形箭头图标按钮（旁边是「退出」「前往」），
# 失败 = 底部「退出」「重新开始」。两边用的是同一个箭头图标，靠它落的位置区分。
RESULT_WIN_BOX = (425, 730, 485, 785)       # 1600×900 基准，成功页左下角图标
RESULT_FAIL_BOX = (805, 730, 865, 785)      # 失败页「重新开始」按钮里的图标
RESULT_ICON_THRESHOLD = 0.8
START_CONFIRM = 'start_screen_start_btn_3_1'   # 「确认进入」弹窗的「确定」（各模式共用）
ESC_RETRY = 'esc_retry'                        # 局内菜单「重新开始」（和戏剧共用同一个菜单）
RESTART_CONFIRM = 'esc_restart_check_btn'      # 「是否重新开始战斗」二次确认弹窗的「确定」

# 「已开战」用的颜色框（Defs.SCREEN_BOX 里的名字）
HUD_MARKER_BOX = 'SYR_HUD_MARKER'

# 左上角菱形变红 = 已开战，**只看颜色**：金/红两个菱形是同一个控件、形状完全一样，
# 去均值归一化的相关度会把绝对色差抵掉，靠模板分数分不开。红色占比实测（阈值 0.15）：
#   未开战 0.0000 / 已开战 0.6154 / 活动页与结算页同位置 0.0000。
SYR_MARKER_RED = {'r': (185, 255), 'g': (0, 120), 'b': (0, 120)}
SYR_MARKER_RED_THRESHOLD = 0.15

# 走位时间轴（狩月平地），录自 `mod\示例-脚本工具\回放和录制软件\scripts\map\custom\狩月人.json`
# （12 个动作、总长 5.2047 秒（最后一步从录制里的 0.4571 改成了 0.40）；这份录制里没有 f12 热键）。时间点换算成"相对上一步的等待秒数"：
#   (等待秒数, 按键, 按下/抬起)
WALK_SCHEDULE_FLAT = (
    (0.5286, 'w', True),
    (0.3853, 'shift', True),
    (0.4403, 'shift', False),
    (0.9652, 'shift', True),
    (0.8642, 'shift', False),
    (0.4469, 'shift', True),
    (0.3370, 'shift', False),
    (0.0844, 'w', False),
    (0.0051, 'd', True),
    (0.3361, 'shift', True),
    (0.4116, 'shift', False),
    (0.40, 'd', False),
)
# 走位期间按住 lalt 锁视角，免得防挂机的鼠标抖动把镜头带偏（其他全自动任务同样处理）
WALK_HOLD_KEYS = ('lalt',)
# shift 是录制里的冲刺键，也要松开：中途被打断时不能让它一直按着
WALK_RELEASE_KEYS = ('w', 'a', 's', 'd', 'shift', 'space')

# 走位时间轴（狩月高台），录自 `mod/行动逻辑/4-2.json`。
# 录制开头是按住 alt（锁视角）再松开，以及进本后的 3.8 秒等待 —— 这些进本流程
# （wait_mission_loaded + RUN_SETTLE + 全程按住 lalt）已经做过了，不重复等；
# 末尾那下 esc 是结束录制时按的，也不重放。
WALK_SCHEDULE_HIGH = (
    (0.5, 'w', True),
    (0.196, 'shift', True),
    (0.735, 'shift', False),
    (4.096, 'w', False),
    # 先松掉 Alt（走位期间一直按着 lalt），不然空格跳不起来
    (0.1, 'lalt', False),
    # 最后连按两次空格，两下间隔 100ms
    (0.1, 'space', True),
    (0.1, 'space', False),
    (0.1, 'space', True),
    (0.1, 'space', False),
)

# ---- 地图判定 ----
# 和「自动探险」同一套判法：看世界里的黄色追踪点图标（track_point）落在哪个固定框。
# 两张图各有一个框，互不重叠（x 方向差 0.13）；两个都没命中才按平地兜底。
MAP_FLAT = '狩月平地'
MAP_HIGH = '狩月高台'
# 平地的追踪点框（屏幕比例，1600×900 基准）：从用户 1604×900 实拍量出来，
# 图标中心 (0.623,0.308)、外接框 (0.616,0.294)-(0.631,0.321)，四周留一点余量。
MAP_FLAT_TRACK_POINT = (0.609, 0.288, 0.638, 0.327)
# 高台的追踪点框（屏幕比例，1600×900 基准）：从 1920×1080 实拍量出来，
# 图标中心 (0.495,0.306)、外接框 (0.487,0.292)-(0.503,0.319)，四周留一点余量。
# 框都收得比较紧：图标在进本后是静止的，收紧可以避免两个框互相蹭到。
MAP_HIGH_TRACK_POINT = (0.480, 0.285, 0.511, 0.328)
# 判图重试：进本后镜头淡入要一会儿，单次匹配容易漏（自动探险那边也是这么做的）
MAP_DETECT_RETRIES = 6
MAP_DETECT_INTERVAL = 0.5

MOON_MAPS = {
    MAP_FLAT: {"track_point": MAP_FLAT_TRACK_POINT, "walk": WALK_SCHEDULE_FLAT},
    MAP_HIGH: {"track_point": MAP_HIGH_TRACK_POINT, "walk": WALK_SCHEDULE_HIGH},
}

# 关卡加载完之后先稳这么久再走位：判据刚出来时角色还在落地/过场收尾，按走位键会被吃掉
RUN_SETTLE = 1
# 起手序列里没写「锁定」时，走位完自动按「锁定键」（游戏快捷键设置里配，默认鼠标中键）
# 锁定目标，再稳这么久往下。按太快那一下会被游戏吃掉（实测中键后 88ms 就按技能）。
# 这是默认值，角色表里可以用 lock_settle 覆盖
LOCK_SETTLE = 1.5
# 点了「开始挑战」/「重新开始」之后等离开当前界面、等进关卡加载完成的上限
LOAD_TIME_OUT = 30
# 加载/过场画面连续这么久都认不出来才报错停止：云游戏偶尔加载超过 30 秒（实测有），
# 那期间只存一张截图 + 提示 + 继续等，别把这一整局白丢掉
UNKNOWN_SCREEN_GIVE_UP = 180
# 兜底：红菱形连续消失这么久（掉线、卡在读条、结算页被漏读）才算没在战斗：ESC 重开一局
NO_COMBAT_TIME_OUT = 30
# 连续失败（开不了战 / 结算点不动）几次后报错停止。配置里只留「打几次」，这个用内部常量
RESTART_FAILURE_LIMIT = 3
# 「超时重启」：从进战那一刻开始算，打这么久还没进结算页就重启这一局（0 = 不限制）
COMBAT_TIMEOUT_KEY = "超时重启"
COMBAT_TIMEOUT_DEFAULT = 60

# ---- 黎瑟SP：开镜后自动蓄力，准星下方显示百分比 ----
# 皮肤会改蓄力环的颜色，所以满蓄以文字为准：OCR 到「100%」才算满。
CHARGE_PERCENT_BOX = 'SYR_CHARGE_PERCENT'
CHARGE_PERCENT_RE = re.compile(r'(\d{1,3})\s*%')
CHARGE_FULL_PERCENT = 100
# 连续读到几次 100% 才按普攻，避免 OCR 单帧误读
CHARGE_CONFIRM_FRAMES = 1
# 主循环 0.2 秒一轮；蓄力文字最多每 0.2 秒读一次
CHARGE_OCR_INTERVAL = 0.1
CHARGE_TEXT_SCALE = 2
# 开火后至少等这么久再进下一发，最多等这么久（等百分比掉下去/文字消失）
CHARGE_RECOVER_MIN = 0.1
CHARGE_RECOVER_MAX = 1.5


def charge_text_normalize(cv_image):
    """把蓄力百分比的小框放大后再 OCR（原生约 40×24，PP-OCR 会漏掉 100%）。"""
    return cv2.resize(cv_image, None, fx=CHARGE_TEXT_SCALE, fy=CHARGE_TEXT_SCALE,
                      interpolation=cv2.INTER_CUBIC)

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
# 走位和主控角色无关（所有角色共用上面那段录制时序），角色之间只差共享表。

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


class AutoHuntMoonTask(CharacterRotationMixin, DNAOneTimeTask, CommissionsTask, BaseCombatTask):
    """全自动「狩月人之阶」：活动界面点开始 -> 判图走位开战 -> 按主控角色放技能 -> 结算重开。

    可以从活动页 / 结算页 / 局内任意一步接手；活动页和结算页的按钮见 START_BTN /
    find_result_kind。失败自愈见模块开头的说明。
    """

    # 法露茜的 20 秒终结技组要等满一个周期，别在开场 5 连终结技后立刻再补一发
    delay_timed_ultimate = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.FLAG
        self.name = "自动狩月人之阶"
        self.description = "1.7版本推荐打134层类似的高台图，平台图会被一下打死"
        self.group_name = "全自动（活动）"
        self.group_icon = FluentIcon.GAME

        # 狩月人的角色视图；子类（如「角色循环」测试）可以换成完整共享表
        self.rotation_table = rotations_for("hunt_moon")

        # 这个模式没有轮次，也没有「挂机模式」那套移动/复位配置：只有打几次 + 超时重启
        self.default_config.update({
            "打几次": 0,
            COMBAT_TIMEOUT_KEY: COMBAT_TIMEOUT_DEFAULT,
            "主控角色": DEFAULT_CHARACTER,
            CUSTOM_SEQUENCE_KEY: DEFAULT_CUSTOM_SEQUENCE,
        })
        self.config_type["主控角色"] = {
            "type": "drop_down",
            "options": list(self.rotation_table) + [NO_CHARACTER, CUSTOM_CHARACTER],
        }
        self.config_description.update({
            "打几次": "打几次，0 = 无限循环",
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
        self.lock_settle = LOCK_SETTLE
        self.character_opening = ()
        self.character_loops = False
        self.opening_done = False
        self.fallback_skill_tick = None
        self.step_index = 0
        self.sequence_done = False
        self.mission_started = False
        self.current_map = MAP_FLAT
        self.current_run = 0
        self.run_failures = 0
        # 黎瑟SP：开镜自动蓄力 + 定时刷新的状态
        self.long_press = COMBAT_LONG_PRESS
        self.charge_shot = False
        self.refresh_interval = 0.0
        self.geniemon_delay = 0.0
        self.combat_t0 = None
        self.refresh_count = 0
        self.next_refresh_at = None
        self.next_geniemon_at = None
        self.geniemon_done = False
        self.charge_state = "idle"
        self.charge_full_frames = 0
        self.charge_started_at = 0.0
        self.last_charge_percent = None
        self.last_charge_ocr = 0.0

    def run(self):
        DNAOneTimeTask.run(self)
        self.move_mouse_to_safe_position(save_current_pos=False)
        self.set_check_monthly_card()
        try:
            return self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error("AutoHuntMoonTask error", e)
            raise

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def do_run(self):
        """主循环：看画面属于哪个界面就处理哪个，打满「打几次」正常返回。

        从任意一步接手：结算页 -> 处理结算；局内 -> 继续打；活动页 -> 点开始；
        加载/过场 -> 等下一个认得出的界面。
        """
        self.load_char()
        self.setup_character()
        self.init_all()
        while True:
            self.next_frame()
            # 结算页先判：它的圆形箭头和活动页的 ◯ 图标很像，放后面容易被当成活动页
            if self.find_result_kind():
                if self.handle_result():
                    return
            elif self.in_moon_hunter_mission():
                self.handle_in_mission()
            elif self.find_one(START_BTN, threshold=0.9):
                self.start_mission()
            else:
                self.wait_screen_back()
            # 蓄力时加快轮询；其他阶段保持 0.2 秒，避免无谓占 CPU
            self.sleep(0.05 if getattr(self, "charge_state", None) == "charging" else 0.2)

    def init_all(self):
        """每次启动都从头开始：计数清零、这一局还没走位、技能序列还没放。"""
        self.current_run = 0
        self.run_failures = 0
        self.mission_started = False
        self.current_map = MAP_FLAT
        self.reset_sequence_state()

    def wait_screen_back(self, time_out=LOAD_TIME_OUT):
        """卡在加载/过场画面：等认出下一个界面。

        每等满 time_out 秒还认不出来：第一次存一张截图，然后响一下、提示一条，继续等。
        连续 UNKNOWN_SCREEN_GIVE_UP 秒都认不出来才报错停止 —— 云游戏加载慢时不会再把
        这一局白丢掉；真卡在别的界面上，截图（screenshots/hunt_moon_unknown_screen）
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
                    self.screenshot(name='hunt_moon_unknown_screen')
                self.soundBeep()
                self.log_info_notify(f'已等了 {int(now - start)} 秒还认不出当前界面，继续等'
                                     f'（截图见 screenshots/hunt_moon_unknown_screen）')
            if now - start >= UNKNOWN_SCREEN_GIVE_UP:
                raise Exception(f'连续 {UNKNOWN_SCREEN_GIVE_UP} 秒认不出当前界面，停止任务'
                                f'（截图见 screenshots/hunt_moon_unknown_screen）')

    def target_runs(self):
        """读「打几次」配置：0 表示无限循环，读不出来也当无限。"""
        try:
            return max(0, int(self.config.get('打几次', 0)))
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
        """记一次连续失败：超过上限就报错停止（配置里只有「打几次」，上限用内部常量）。"""
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
        return (self.find_result_kind() is not None
                or self.find_one(START_BTN, threshold=0.9) is not None
                or self.in_moon_hunter_mission())

    def in_moon_hunter_mission(self):
        """是不是在局内（局内菜单盖在 HUD 上时也算）。"""
        return self.in_team() or self.find_one(ESC_RETRY) is not None

    def find_hud_marker(self):
        """左上角那颗菱形（金/红都在同一个位置）。

        命中就代表"关卡已经加载完、可以开始走位"；局内菜单和结算页都不命中。
        """
        return self.find_one(HUD_START) or self.find_one(HUD_FIGHT)

    def is_in_combat(self):
        """左上角菱形变红 = 已开战（只看颜色，和界面语言、背景明暗都无关）。

        位置优先用菱形模板（只截菱形内部、不含背景，亮暗场景都能命中），没匹上就退回固定框 ——
        模板在明亮场景里会失手，差一点点就会把"已开战"漏判成没开战（表现：明明在打，
        却按"没进战斗"处理，几十秒后误判成超时重开一局）。
        """
        box = self.find_hud_marker() or self.screen_box(HUD_MARKER_BOX)
        return self.calculate_color_percentage(SYR_MARKER_RED, box) > SYR_MARKER_RED_THRESHOLD

    # ------------------------------------------------------------------
    # 活动界面
    # ------------------------------------------------------------------

    def left_start_screen(self):
        """已经不在活动界面（无论在加载还是已经进图）。"""
        return (self.find_one(START_BTN, threshold=0.9) is None
                and self.find_one(START_CONFIRM) is None)

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
                                   COORD.SYR_START, name=START_BTN, after_sleep=1),
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
            # 任务可能是在战斗中途接手的：已经在打就跳过走位，免得把角色拉走
            self.next_frame()
            if self.is_in_combat():
                self.log_info("接手时已经在战斗中，跳过走位，直接按技能")
            else:
                self.current_map = self.detect_moon_map()
                self.log_info("识别到地图：%s" % self.current_map)
                self.play_walk()
                # 两下空格之后稳 200ms，直接进起手/循环；锁定属于角色手法，流程里不再单独按
                self.sleep(0.2)
        # 不再单独"等开战"：直接进开打循环，技能由里面的"菱形变红"判断控制
        if not self.fight_until_result():
            # 红菱形长时间不在（掉线、卡在读条）：已经重开了一局，退回重新走位
            self.mission_started = False

    def wait_mission_loaded(self, time_out=LOAD_TIME_OUT):
        """等关卡加载完：左上角菱形或者通用局内 HUD（左下角 Lv）出来都算。

        带上 in_team() 兜底是必须的：菱形模板在明亮的关卡场景里会失手，
        只用它会在那种关卡误报"没进关卡"。
        """
        if not self.wait_until(lambda: self.find_hud_marker() is not None or self.in_team(),
                               time_out=time_out, raise_if_not_found=False):
            raise Exception(f'等了 {time_out} 秒还没进关卡（门票/体力不足或掉线？）')

    def track_point_box(self, x1, y1, x2, y2, name="hunt_moon_track_point"):
        """屏幕比例框 -> 实际像素框（和「自动探险」的判图框同款）。"""
        return self.box_of_screen_scaled(REF_WIDTH, REF_HEIGHT,
                                         REF_WIDTH * x1, REF_HEIGHT * y1,
                                         REF_WIDTH * x2, REF_HEIGHT * y2,
                                         name=name, hcenter=True)

    def detect_moon_map(self):
        """看黄色追踪点图标落在哪个图的框里，返回地图名。

        狩月人之阶有两张图：各有一个追踪点框，两个都没命中才按平地兜底。
        进本后镜头淡入要一会儿，所以像「自动探险」那样取新帧重试几次。
        """
        for attempt in range(MAP_DETECT_RETRIES):
            for name, config in MOON_MAPS.items():
                track_point = config.get("track_point")
                if not track_point:
                    continue
                if self.find_track_point(threshold=0.7,
                                         box=self.track_point_box(*track_point)):
                    return name
            if attempt + 1 < MAP_DETECT_RETRIES:
                self.sleep(MAP_DETECT_INTERVAL)
                # ok 的 self.frame 是缓存帧：不取新帧的话重试会一直匹配同一张图
                self.next_frame()
        self.log_info("两张图的追踪点都没认出，按平地兜底（若不是平地，请把当前截图发回）")
        return MAP_FLAT

    def play_walk(self):
        """按当前地图的录制时间轴走位；全程按住 lalt 锁视角，不管成功失败都松开所有按键。"""
        schedule = MOON_MAPS.get(self.current_map, MOON_MAPS[MAP_FLAT])["walk"]
        self.log_info("开始走位（%s）" % self.current_map)
        for key in WALK_HOLD_KEYS:
            self.send_key_down(key)
        try:
            for wait, key, down in schedule:
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
        """挂机。返回 True = 结算页出现（这一局打完），False = 该重开一局。

        「超时重启」：从**进战那一刻**开始计时，超过配置的秒数还没进结算页就重启这一局；
        结算（或者重开完的下一局）会重新从进战开始算。
        红菱形闪一下不算"没进战斗"（判据在实机上会闪）：只有连续消失 NO_COMBAT_TIME_OUT 秒
        （掉线、卡在读条、结算页被漏读后停在加载画面）才算没在战斗 —— 重开一局。
        """
        no_combat_since = None
        combat_since = None
        while True:
            self.next_frame()
            if self.find_result_kind():
                return True
            if self.find_one(ESC_RETRY):
                # 局内菜单被打开了（一般是玩家自己按的 ESC）：关掉继续，绝不在这里点菜单
                self.send_key("esc", after_sleep=0.5)
                continue
            in_combat = self.is_in_combat()
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
                self.note_failure(f'{NO_COMBAT_TIME_OUT} 秒没进战斗')
                self.restart_in_mission()
                return False
            # 蓄力时加快轮询；其他阶段保持 0.2 秒
            self.sleep(0.05 if getattr(self, "charge_state", None) == "charging" else 0.2)

    def restart_in_mission(self, time_out=10, load_time_out=LOAD_TIME_OUT):
        """局内重来：ESC 开菜单 -> 点「重新开始」-> 点二次确认的「确定」。

        两个都是云游戏爱丢的点击，所以都是"点到出结果为止"：先点到弹窗出来，再点到弹窗消失。
        重开会把关卡重新加载一遍，菜单/弹窗/加载画面都会盖掉菱形判据，所以"先消失再回来"
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

    def result_icon_box(self, box, name):
        """结算页图标框（1600×900 基准）-> 实际像素框。"""
        x1, y1, x2, y2 = box
        return self.box_of_screen_scaled(REF_WIDTH, REF_HEIGHT, x1, y1, x2, y2,
                                         name=name, hcenter=True)

    def find_result_kind(self):
        """结算页是哪种：'win' / 'fail' / None。

        1.7 的两种结算页用的是同一个圆形箭头图标，只是位置不同：
        成功页在左下角单独一个图标按钮（旁边是「退出」「前往」），
        失败页在「重新开始」按钮里。分别在两个固定框里找同一个模板。
        """
        if self.find_one(RESULT_RESTART, threshold=RESULT_ICON_THRESHOLD,
                         box=self.result_icon_box(RESULT_WIN_BOX, 'syr_result_win')):
            return 'win'
        if self.find_one(RESULT_RESTART, threshold=RESULT_ICON_THRESHOLD,
                         box=self.result_icon_box(RESULT_FAIL_BOX, 'syr_result_fail')):
            return 'fail'
        return None

    def handle_result(self):
        """结算页：成功点左下角重试图标，失败点「重新开始」。返回是否该结束任务。"""
        kind = self.find_result_kind()
        self.mission_started = False
        self.run_failures = 0
        self.current_run += 1
        self.info_set("局数", str(self.current_run))
        self.log_info(f'第 {self.current_run} 局完成（{"挑战成功" if kind == "win" else "挑战结束"}）')
        target = self.target_runs()
        if target and self.current_run >= target:
            self.log_info(f'已经打满 {target} 局，任务结束')
            return True
        if kind == 'win':
            self.log_info("挑战成功，点左下角的重试图标")
            coord = COORD.SYR_RESULT_WIN_RETRY
        else:
            self.log_info("挑战结束，点「重新开始」")
            coord = COORD.SYR_RESULT_FAIL_RESTART
        self.click_ui_coord(coord, name=RESULT_RESTART, after_sleep=1)
        self.wait_left_result()
        return False

    def wait_left_result(self, time_out=LOAD_TIME_OUT):
        """点完重开之后等结算页消失，免得下一轮又点一次、重复计数。"""
        if not self.wait_until(lambda: self.find_result_kind() is None,
                               time_out=time_out, raise_if_not_found=False):
            raise Exception(f'点了重开之后 {time_out} 秒还停在结算页（门票/体力不足？）')

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
                self.long_press = COMBAT_LONG_PRESS
                self.charge_shot = False
                self.refresh_interval = 0.0
                self.geniemon_delay = 0.0
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
            self.long_press = COMBAT_LONG_PRESS
            self.charge_shot = False
            self.refresh_interval = 0.0
            self.geniemon_delay = 0.0
            self.fallback_skill_tick = self.create_skill_ticker()
            return
        rotation = self.rotation_table.get(name)
        if rotation is None:
            self.log_info("没有「%s」的技能手法，退回全局技能计时器" % name)
            self.character_steps = None
            self.character_spam = None
            self.character_timed = ()
            self.lock_settle = LOCK_SETTLE
            self.character_opening = ()
            self.character_loops = False
            self.long_press = COMBAT_LONG_PRESS
            self.charge_shot = False
            self.refresh_interval = 0.0
            self.geniemon_delay = 0.0
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
            self.long_press = float(rotation.get("long_press", COMBAT_LONG_PRESS))
            self.charge_shot = bool(rotation.get("charge_shot", False))
            self.refresh_interval = float(rotation.get("refresh_interval", 0.0))
            self.geniemon_delay = float(rotation.get("geniemon_delay", 0.0))
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
        self.timed_next = [0.0] * len(self.character_timed)
        self.combat_t0 = None
        self.refresh_count = 0
        self.next_refresh_at = None
        self.next_geniemon_at = None
        self.geniemon_done = False
        self.charge_state = "idle"
        self.charge_full_frames = 0
        self.charge_started_at = 0.0
        self.last_charge_percent = None
        self.last_charge_ocr = 0.0

    def play_character_sequence(self):
        """按「主控角色」的手法放技能：锁定目标之后才开始。

        opening（可选）：这一局开打后先放一遍，只放一次（法露茜的终结技就是这条）。
        spam + timed（可选）：按真实时间跑的循环 —— 一直按 spam、每隔 N 秒放一组 timed。
        steps + loop=True：一直循环 steps；loop=False：steps 整串放一遍就停。
        """
        if (self.character_steps is None and self.character_spam is None
                and not self.character_timed and not self.character_opening):
            # 没有角色手法（「无」或认不出的名字）：退回全局技能计时器
            if self.fallback_skill_tick is not None:
                self.fallback_skill_tick()
            return

        if not self.opening_done:
            self.opening_done = True
            if self.charge_shot and self.combat_t0 is None:
                # 起手终结技会自动开镜并开始蓄力；起手那次长按战技算第一次刷新。
                self.combat_t0 = time.time()
                self.next_refresh_at = (self.combat_t0 + self.refresh_interval
                                        if self.refresh_interval > 0 else None)
                self.next_geniemon_at = (self.combat_t0 + self.geniemon_delay
                                         if self.geniemon_delay > 0 else None)
                self.refresh_count = 1
                self.geniemon_done = False
                self.log_info("黎瑟SP 时间轴：%.0f 秒后刷新战技，%.0f 秒后魔灵支援"
                              % (self.refresh_interval, self.geniemon_delay))
            if self.character_opening:
                self.log_info("开场技能（只放一次）: %s" % self.describe_steps(self.character_opening))
                for action, wait in self.character_opening:
                    self.release_character_action(action)
                    self.sleep(wait)

        if self.charge_shot:
            self.tick_charge_shot()
            return

        if self.character_spam is not None or self.character_timed:
            self.play_timed_rotation()
            return

        if self.character_steps is None:
            # 只有 opening 的手法（如黎瑟）：起手放完就停，不进入循环。
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

    # ------------------------------------------------------------------
    # 黎瑟SP：开镜自动蓄力 -> 满 100% 按普攻 -> 定时刷新战技 / 魔灵支援
    # ------------------------------------------------------------------

    def tick_charge_shot(self):
        """黎瑟SP 的循环：一次主循环只推进一步。

        蓄力是开镜后自动进行的（终结技会自动开镜），这里只读准星下方的百分比文字；
        满 100% 按一次普攻键。战技刷新和魔灵支援到点优先执行，它们不打断蓄力，
        做完继续读同一个蓄力过程。
        """
        now = time.time()
        if (not self.geniemon_done and self.next_geniemon_at is not None
                and now >= self.next_geniemon_at):
            self.geniemon_done = True
            self.log_info("开局 %.0f 秒，使用魔灵支援（键 %s）"
                          % (self.geniemon_delay, self.get_geniemon_key()))
            self.release_character_action("魔灵支援")
            return

        if (self.refresh_interval > 0 and self.next_refresh_at is not None
                and now >= self.next_refresh_at):
            self.do_charge_refresh()
            self.next_refresh_at += self.refresh_interval
            if self.next_refresh_at <= now:
                self.next_refresh_at = now + self.refresh_interval
            return

        if self.charge_state == "idle":
            self.charge_state = "charging"
            self.charge_full_frames = 0
            self.charge_started_at = now
            self.last_charge_percent = None
            self.last_charge_ocr = 0.0
            return

        if self.charge_state == "charging":
            if self.last_charge_ocr == 0.0:
                # 起手会阻塞零点几秒，先取一张新帧再读百分比
                self.next_frame()
            if now - self.last_charge_ocr < CHARGE_OCR_INTERVAL:
                return
            self.last_charge_ocr = now
            percent = self.read_charge_percent()
            if percent is None:
                # 关镜后百分比文字会消失；清掉满蓄计数，等重新开镜后重读。
                self.charge_full_frames = 0
                self.last_charge_percent = None
                return
            if (self.last_charge_percent is None
                    or percent != self.last_charge_percent):
                if (self.last_charge_percent is None
                        or percent % 10 == 0 or percent >= CHARGE_FULL_PERCENT):
                    self.log_info("蓄力百分比：%d%%" % percent)
                self.last_charge_percent = percent
            if percent >= CHARGE_FULL_PERCENT:
                self.charge_full_frames += 1
            else:
                self.charge_full_frames = 0
            if self.charge_full_frames >= CHARGE_CONFIRM_FRAMES:
                self.log_info("蓄力已满（%d%%），按普攻键射击（%s）"
                              % (percent, self.get_normal_attack_key()))
                self.release_character_action("普攻")
                self.charge_state = "recover"
                self.charge_started_at = now
                self.charge_full_frames = 0
                self.last_charge_percent = None
            return

        # recover：等百分比掉下去或文字消失，避免同一发满蓄被连按两次普攻
        if now - self.charge_started_at < CHARGE_RECOVER_MIN:
            return
        percent = self.read_charge_percent()
        if (percent is None or percent < CHARGE_FULL_PERCENT
                or now - self.charge_started_at >= CHARGE_RECOVER_MAX):
            self.charge_state = "idle"

    def do_charge_refresh(self):
        """按 refresh_interval 刷新，每次只长按一次。"""
        self.refresh_count += 1
        self.log_info("刷新战技（第 %d 次，按住 %.1f 秒）"
                      % (self.refresh_count, self.long_press))
        self.release_character_action("长按战技")
        self.sleep(0.1)

    def read_charge_percent(self):
        """读准星下方的蓄力百分比；读不到返回 None。"""
        try:
            texts = self.ocr(box=self.screen_box(CHARGE_PERCENT_BOX),
                             frame=self.frame, frame_processor=charge_text_normalize)
        except Exception as e:
            self.log_warning("蓄力百分比 OCR 失败: %s" % e)
            return None
        if not texts:
            return None
        raw = "".join((getattr(box, "name", "") or "") for box in texts)
        raw = raw.replace(" ", "")
        # OCR 偶尔把 0 认成 O、1 认成 l/I；先归一化再匹配
        raw = raw.replace("O", "0").replace("l", "1").replace("I", "1")
        raw = raw.replace("％", "%")
        # 没有百分号时只认 2~3 位数字，避免把噪声里的单个 0 当成蓄力值
        match = CHARGE_PERCENT_RE.search(raw) or re.search(r'(?<!\d)(\d{2,3})(?!\d)', raw)
        if not match:
            return None
        try:
            value = int(match.group(1))
        except (TypeError, ValueError):
            return None
        return value if 0 <= value <= 100 else None

    def play_timed_rotation(self):
        """按真实时间放技能（spam + timed）：一次调用最多做一件事。

        先看有没有到点的 timed 组（到了就把这一组连着按完、再安排下一次），没有就按一下 spam。
        法露茜那套「一直普攻、每 3 秒连按两下战技」就是这种 —— 按真实时间算，
        不受主循环一轮多久影响。
        """
        now = time.time()
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
                          % (self.get_combat_key(), self.long_press))
            self.send_key(self.get_combat_key(), down_time=self.long_press)
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

    # 角色循环统一走共享执行器（src/char/CharacterRotationMixin.py）：
    # 任务里的旧实现保留作为字段/兼容参考，实际调用全部指向 mixin。
    current_character = CharacterRotationMixin.current_character
    plan_has_lock = CharacterRotationMixin.plan_has_lock
    setup_character = CharacterRotationMixin.setup_character
    parse_custom_steps = CharacterRotationMixin.parse_custom_steps
    reset_sequence_state = CharacterRotationMixin.reset_sequence_state
    play_character_sequence = CharacterRotationMixin.play_character_sequence
    play_timed_rotation = CharacterRotationMixin.play_timed_rotation
    tick_charge_shot = CharacterRotationMixin.tick_charge_shot
    do_charge_refresh = CharacterRotationMixin.do_charge_refresh
    read_charge_percent = CharacterRotationMixin.read_charge_percent
    describe_steps = CharacterRotationMixin.describe_steps
    release_character_action = CharacterRotationMixin.release_character_action

