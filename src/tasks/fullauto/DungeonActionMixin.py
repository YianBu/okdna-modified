"""「按图标位置判地图 -> 执行对应外部行动逻辑」的共用实现。

抽成 mixin（而不是塞进某一个任务）是因为两处都要用同这一份逻辑：

* ``AutoLetterOpenTask``：自动开密函（探险 / 扼守模式）进本后执行；
* ``AutoDungeonActionTestTask``：「测试」板块里的「行动逻辑测试」手动执行。
* ``AutoExploration_Fast``：「自动探险/无尽」的判图与探险走位（地图选择也取自这张表）。

地图表 / 选择函数在 ``DungeonActionLogic``；每张图的动作是本类里的 execute_* 方法。
这里只放行为。用了 ``super()``，所以
使用方必须把这个 mixin 放在基类列表的**最前面**，且基类链上要有 ``CommissionsTask``
（``is_in_combat`` 要落到它那份实现、``find_track_point`` 要落到 ``BaseDNATask``）。
"""

import time

from src.dna_ui.Defs import REF_WIDTH, REF_HEIGHT
from src.tasks.AutoDefence import AutoDefence
from src.tasks.AutoExploration import AutoExploration
from src.tasks.fullauto.DungeonActionLogic import (
    DUNGEON_MAPS,
    action_for_map,
    default_map_for_mode,
)

# 前进到开战：开战判据成立后再多走这么多秒（进交战区还差一点），走满 HOLD_W_TIME_OUT
# 秒还没开战就松手，交给外层超时重开（这里不自己放弃）。「自动扼守/无尽」的直走也走这里。
HOLD_W_EXTRA_TIME = 1.0
HOLD_W_TIME_OUT = 20

# 参考「自动狩月人」的 RUN_SETTLE：HUD 刚出来时角色还在落地/过场收尾，
# 这时按 W 会被游戏吃掉；先稳 1 秒再开始走位。
EXPLORATION_RUN_SETTLE_TIME = 1.0
# 先按下 Alt 锁视角，再按 W。Alt 和 W 之间留 100ms，等游戏把修饰键处理完；
# 否则开局第一下 W 可能被吞（表现为人没前进，后面的闪避却正常）。
EXPLORATION_ALT_SETTLE_TIME = 0.1

# 判地图要重试：进本后 HUD/镜头淡入要一两秒，原来只 sleep 2 秒再单次匹配，实测 19 次
# 判图只有 5 次命中，没命中就落到「默认平地」——高台就是这么被当成平地的。这里在几秒内
# 反复取帧，命中就停；真的都没命中才回落到默认，并把分数/候选位置打进日志、存一张截图。
DETECT_RETRIES = 10
DETECT_RETRY_INTERVAL = 0.5
# 诊断用：判图彻底失败时，每个框按这个低阈值取最高分；全屏也按这个阈值列候选。
DETECT_PROBE_THRESHOLD = 0.3
# 全屏候选要单独高一点：阈值太低时整块 UI 会有几百个命中，排序/去重会拖到秒级。
DETECT_PROBE_FULL_THRESHOLD = 0.5
DETECT_PROBE_LIMIT = 5


class DungeonActionMixin:

    # ------------------------------------------------------------------
    # 判地图：只看固定位置的 track_point（追踪点）图标
    # ------------------------------------------------------------------
    def track_point_box(self, x1, y1, x2, y2, name="dungeon_track_point"):
        """屏幕比例框 -> 实际像素框（和 AutoExploration_Fast 同款，按 REF 分辨率缩放）。"""
        return self.box_of_screen_scaled(REF_WIDTH, REF_HEIGHT,
                                         REF_WIDTH * x1, REF_HEIGHT * y1,
                                         REF_WIDTH * x2, REF_HEIGHT * y2,
                                         name=name, hcenter=True)

    def find_track_point(self, x1, y1, x2, y2):
        """按屏幕比例框找追踪点图标（和 AutoExploration_Fast.find_track_point 同款）。"""
        box = self.track_point_box(x1, y1, x2, y2)
        return super().find_track_point(threshold=0.7, box=box)

    def detect_current_map(self, mode=None):
        """按图标位置判当前地图，返回地图名；一个都没命中返回 None。

        ``mode`` 传入副本类型时只在那种副本的地图里找；传 None（例如启动时人已经在
        本里、没经过列表挑选）则在所有地图里找。
        """
        detected = []
        for name, config in DUNGEON_MAPS.items():
            if mode is not None and config["mode"] != mode:
                continue
            track_point = config.get("track_point")
            if not track_point:
                # 没有检测框的条目（扼守直走）只当兜底，不参与判定
                continue
            if self.find_track_point(*track_point):
                detected.append(name)
                self.log_info(f"检测到地图标记：{name}")
        if not detected:
            return None
        if len(detected) > 1:
            self.log_info(f"同时检测到多个地图标记 {detected}，取第一个")
        return detected[0]

    def detect_current_map_stable(self, mode=None, attempts=DETECT_RETRIES,
                                  interval=DETECT_RETRY_INTERVAL):
        """在 attempts 次内反复判图，命中即停；都失败才返回 None 并打诊断日志。

        只包一层 detect_current_map，不改变它的判定规则（单次调用仍然是单次），
        所以「行动逻辑测试」和单元测试里的打桩行为都不受影响。
        """
        attempts = max(1, int(attempts))
        for attempt in range(attempts):
            map_name = self.detect_current_map(mode)
            if map_name is not None:
                return map_name
            if attempt + 1 < attempts:
                self.sleep(interval)
                # ok 的 self.frame 是缓存帧：不取新帧的话重试会一直匹配同一张图
                self.next_frame()
        self.log_map_detection_failure(mode, attempts)
        return None

    def log_map_detection_failure(self, mode=None, attempts=DETECT_RETRIES):
        """判图彻底失败时留证据：每个框的最高分 + 全屏得分较高的追踪点位置 + 截图。

        这一步只在失败时跑，不影响正常开局。日志里的坐标是屏幕比例，拿到新截图/日志后
        就能直接看出该改哪个框（例如高台的图标其实落在别的中心附近）。
        """
        try:
            if self.frame is None:
                return
        except Exception:
            return

        scores = []
        for name, config in DUNGEON_MAPS.items():
            if mode is not None and config["mode"] != mode:
                continue
            track_point = config.get("track_point")
            if not track_point:
                continue
            found = None
            try:
                box = self.track_point_box(*track_point, name=f"probe_{name}")
                found = self.find_one("track_point", threshold=DETECT_PROBE_THRESHOLD, box=box)
            except Exception:
                found = None
            scores.append(f"{name}={found.confidence:.2f}" if found else
                          f"{name}<{DETECT_PROBE_THRESHOLD:.2f}")

        candidates = []
        try:
            frame_box = self.box_of_screen_scaled(REF_WIDTH, REF_HEIGHT, 0, 0,
                                                  REF_WIDTH, REF_HEIGHT,
                                                  name="probe_track_point_all")
            found = self.find_feature(feature_name="track_point",
                                      threshold=DETECT_PROBE_FULL_THRESHOLD,
                                      box=frame_box) or []
            # find_feature 的 limit 是按位置截断（从上到下），不是按分数；这里自己按
            # 置信度取前几个，才能把真正的世界追踪点（可能在下半屏）列出来。
            found = sorted(found, key=lambda b: b.confidence, reverse=True)[:DETECT_PROBE_LIMIT]
            width = max(1, self.width)
            height = max(1, self.height)
            for item in found:
                cx = (item.x + item.width / 2) / width
                cy = (item.y + item.height / 2) / height
                candidates.append(f"({cx:.3f},{cy:.3f}){item.confidence:.2f}")
        except Exception:
            candidates = []

        self.log_info(
            f"地图识别失败：{attempts} 次重试没有命中任何检测框；"
            f"每框最高分 {'，'.join(scores) or '无'}；"
            f"全屏追踪点候选 {'，'.join(candidates) or '无'}")
        try:
            self.screenshot(name="map_detect_fail")
            self.log_info("已保存判图失败截图：screenshots/map_detect_fail（重启程序会清空）")
        except Exception as e:
            self.log_debug(f"保存判图失败截图失败：{e}")

    def walk_to_aim(self, delay=0):
        """外部行动逻辑入口：判地图 -> 执行对应行动函数。"""
        self.sleep(delay)
        map_name = self.detect_current_map_stable(self._dungeon_mode)
        if map_name is None:
            map_name = default_map_for_mode(self._dungeon_mode)
            if map_name is not None:
                self.log_info(f"未识别到地图，先按默认「{map_name}」走；"
                              "若实际不是这张图，请把上面这条日志和 map_detect_fail 截图发回")
        if map_name is None:
            self.log_info("未识别到地图且没有默认，跳过外部行动逻辑")
            return False
        self.log_info(f"识别到地图「{map_name}」，执行对应外部行动逻辑")
        return self.run_dungeon_action(map_name)

    def run_dungeon_action(self, map_name):
        """把地图名派发到登记的行动函数（DungeonActionLogic.DUNGEON_MAPS）。"""
        action = action_for_map(map_name)
        if action is None:
            self.log_info(f"地图「{map_name}」没有登记行动逻辑，跳过")
            return False
        return getattr(self, action)()

    # ---- 各图的行动逻辑 ----
    def solve_exploration_mechanism(self, time_out=10, interval=0.0):
        """到机关后按 F 破解，直到开战或超时。

        照「自动沉浸式戏剧」AutoTheatreTask.walk_and_interact_once 的写法：走位到机关、
        按下 F 打开机关之后，**按一次交互键（F，按住 0.1 秒）**，按键本身就是约
        100ms 一次；interval 是两次按键之间的额外等待，默认 0。一直按到
        is_in_combat() 成立为止；走满 time_out 秒还没开战就停手。
        """
        deadline = time.time() + time_out
        while time.time() < deadline:
            if self.is_in_combat():
                self.log_info("机关已破解（已开战）")
                return True
            self.send_key(self.get_interact_key(), down_time=0.1)
            self.sleep(interval)
        return self.is_in_combat()

    def execute_exploration_high(self):
        """探险高台（图2）：按 mod/行动逻辑/1-3.json 精修后的走位。

        录制里开头 7.085s 是切屏/等加载，不属于路线；这里从进本可控状态直接开始。
        路线（相对 W 按下）：W 2.982s（0.297s 后闪避 0.221s）-> 等 0.630
        -> A 3.155s -> 等 0.595 -> W 0.747s -> 等 1.151 -> 反复 F 破解。
        全程按住左 Alt 锁视角，避免切屏/抖动把镜头带偏。
        """
        self.log_info("[探险高台] 开始走位")
        self.sleep(EXPLORATION_RUN_SETTLE_TIME)
        dodge = self.get_dodge_key()
        self.send_key_down("lalt")
        try:
            self.sleep(EXPLORATION_ALT_SETTLE_TIME)
            self.send_key_down("w")
            self.sleep(0.297)
            self.send_key_down(dodge)
            self.sleep(0.221)
            self.send_key_up(dodge)
            self.sleep(2.464)
            self.send_key_up("w")
            self.sleep(0.630)
            self.send_key_down("a")
            self.sleep(3.155)
            self.send_key_up("a")
            self.sleep(0.595)
            self.send_key_down("w")
            self.sleep(0.747)
            self.send_key_up("w")
            self.sleep(1.151)
            self.solve_exploration_mechanism()        # 反复按 F 破解，直到开战
        finally:
            self.send_key_up("w")
            self.send_key_up("a")
            self.send_key_up(dodge)
            self.send_key_up("space")
            self.send_key_up("lalt")

    def execute_exploration_ground(self):
        """探险平地（图1）：按 mod/行动逻辑/3-2.json 优化后的走位。

        走位段来自 3-2，但按住 Alt 时角色跳不起来，所以两次空格全部去掉；
        原来空格按住的时间改成继续前进，Shift 冲刺和 W 的总时长保持不变。
        起手 Alt/W 和高台一致：Alt 按住，100ms 后按 W，走位中不松开 Alt。

        路线（相对 W 按下）：W 5.122s；0.569s 后 Shift 按住 1.829s；W 松开后
        1.013s A 0.492；再 0.638s 到机关，直接反复 F 破解。
        """
        self.log_info("[探险平地] 开始走位")
        self.sleep(EXPLORATION_RUN_SETTLE_TIME)
        dodge = self.get_dodge_key()
        # 和高台同一套 Alt/W 起手：先按住 Alt 锁视角，100ms 后再按 W
        self.send_key_down("lalt")
        try:
            self.sleep(EXPLORATION_ALT_SETTLE_TIME)
            self.send_key_down("w")
            self.sleep(0.569)
            self.send_key_down(dodge)
            self.sleep(1.829)          # 原 1.615 + 第一次空格 0.176 + 0.038
            self.send_key_up(dodge)
            self.sleep(2.724)          # 原 0.330 + 第二次空格 0.129 + 2.265
            self.send_key_up("w")
            self.sleep(1.013)
            self.send_key_down("a")
            self.sleep(0.492)
            self.send_key_up("a")
            self.sleep(0.638)
            self.solve_exploration_mechanism()        # 反复按 F 破解，直到开战
        finally:
            self.send_key_up("w")
            self.send_key_up("a")
            self.send_key_up(dodge)
            self.send_key_up("lalt")

    def execute_defence_diagonal(self):
        """扼守斜走（图3）：实测可行的走位序列（固化自 mod/行动逻辑/示例-行动逻辑.json）。

        对应 JSON 序列：

            log -> key w 2.0s -> key d 3.8s -> key w 6.0s
        """
        self.log_info("[扼守斜走] 开始走位")
        self.send_key("w", down_time=2.0)
        self.send_key("d", down_time=3.8)
        self.send_key("w", down_time=6.0)

    def execute_defence_straight(self):
        """扼守直走（图4）：先往左轻点一下，再按住 W 前进到开战。

        对应序列：a 0.2s -> 按住 W 前进到开战（见 hold_w_until_combat）：开战后再走
        HOLD_W_EXTRA_TIME 秒。
        """
        self.log_info("[扼守直走] 开始走位")
        self.send_key("a", down_time=0.2)
        return self.hold_w_until_combat()

    def hold_w_until_combat(self):
        """按住 W 前进到开战（「自动扼守/无尽」和「自动开密函」的直走共用这一份）。

        开战判据成立后再走 HOLD_W_EXTRA_TIME 秒；走满 HOLD_W_TIME_OUT 秒还没开战就记
        一条日志、松手返回 False（重开交给外层）。不管走哪条路径，结束时都把移动键和
        闪避键全部松开。
        """
        self.send_key_down("w")
        try:
            deadline = time.time() + HOLD_W_TIME_OUT
            while time.time() < deadline:
                self.next_frame()
                if self.is_in_combat():
                    self.log_info(f"已进入战斗，再前进 {HOLD_W_EXTRA_TIME} 秒")
                    extra_deadline = time.time() + HOLD_W_EXTRA_TIME
                    while time.time() < extra_deadline:
                        self.next_frame()
                    return True
            self.log_info(f"前进 {HOLD_W_TIME_OUT} 秒仍未开战，交给超时重开")
            return False
        finally:
            for key in ("w", "a", "s", "d"):
                self.send_key_up(key)
            self.send_key_up(self.get_dodge_key())
            self.send_key_up("lshift")

    def try_solving_puzzle(self):
        """原版解谜处理（迷宫 / 轮盘），被上面的探险行动函数调用。

        ``AutoExploration_Fast`` 也用这个 mixin，所以这里**延迟导入**它，避免
        ``AutoExploration_Fast -> DungeonActionMixin -> AutoExploration_Fast`` 的循环导入。
        """
        from src.tasks.fullauto.AutoExploration_Fast import AutoExploration_Fast

        return AutoExploration_Fast.try_solving_puzzle(self)

    # ---- 开战判据：探险看血清、扼守看波次，都复用原版 ----
    def find_target_wave(self):
        return AutoDefence.find_target_wave(self)

    def find_serum(self):
        return AutoExploration.find_serum(self)

    def is_in_combat(self):
        """开战判据：扼守的「波次 x/y」、探险的血清图标，任一命中即开战。"""
        if self.find_target_wave() or self.find_serum():
            return True
        return super().is_in_combat()
