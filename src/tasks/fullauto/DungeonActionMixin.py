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
# 秒还没开战就松手，交给外层超时重开（这里不自己放弃）。「自动防御」的直走也走这里。
HOLD_W_EXTRA_TIME = 1.0
HOLD_W_TIME_OUT = 20


class DungeonActionMixin:

    # ------------------------------------------------------------------
    # 判地图：只看固定位置的 track_point（追踪点）图标
    # ------------------------------------------------------------------
    def find_track_point(self, x1, y1, x2, y2):
        """按屏幕比例框找追踪点图标（和 AutoExploration_Fast.find_track_point 同款）。"""
        box = self.box_of_screen_scaled(REF_WIDTH, REF_HEIGHT,
                                        REF_WIDTH * x1, REF_HEIGHT * y1,
                                        REF_WIDTH * x2, REF_HEIGHT * y2,
                                        name="dungeon_track_point", hcenter=True)
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

    def walk_to_aim(self, delay=0):
        """外部行动逻辑入口：判地图 -> 执行对应行动函数。"""
        self.sleep(delay)
        map_name = self.detect_current_map(self._dungeon_mode)
        if map_name is None:
            map_name = default_map_for_mode(self._dungeon_mode)
            if map_name is not None:
                self.log_info(f"未识别到地图，改用默认：{map_name}")
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
    def solve_exploration_mechanism(self, time_out=10, interval=0.5):
        """到机关后按 F 破解，直到开战或超时。

        照「自动沉浸式戏剧」AutoTheatreTask.walk_and_interact_once 的写法：走位到机关、
        按下 F 打开机关之后，**每 interval 秒按一次交互键（F，按住 0.1 秒）**，一直按到
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
        """探险高台（图2）：实测可行的走位序列。

        原先放在 mod/行动逻辑/示例-行动逻辑.json（已测通过），现在固化到这里，**不再
        运行时读那个文件** —— 你再改 JSON 去试别的图不会牵动探险高台。对应的 JSON 序列：

            log -> key w 6.0s -> wait 0.3s -> key a 3.1s -> key w 1.3s
                -> key f 0.5s -> wait 1.0s -> key f 0.5s
        """
        self.log_info("[探险高台] 开始走位")
        self.send_key("w", down_time=6.0)
        self.sleep(0.3)
        self.send_key("a", down_time=3.1)
        self.send_key("w", down_time=1.3)
        self.send_key("f", down_time=0.5)         # 交互探险机关
        self.sleep(1)
        self.solve_exploration_mechanism()        # 反复按 F 破解，直到开战

    def execute_exploration_ground(self):
        """探险平地（图1）：实测可行的走位序列（固化自 mod/行动逻辑/示例-行动逻辑.json）。

        对应 JSON 序列：

            log -> key w 4.0s -> key space 0.5s -> wait 0.1s -> key space 0.5s
                -> key w 4.6s -> key a 0.5s -> key f 0.5s -> wait 1.0s -> key f 0.5s
        """
        self.log_info("[探险平地] 开始走位")
        self.send_key("w", down_time=4.0)
        self.send_key("space", down_time=0.5)
        self.sleep(0.1)
        self.send_key("space", down_time=0.5)
        self.send_key("w", down_time=4.6)
        self.send_key("a", down_time=0.5)
        self.send_key("f", down_time=0.5)         # 交互探险机关
        self.sleep(1)
        self.solve_exploration_mechanism()        # 反复按 F 破解，直到开战

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
        """按住 W 前进到开战（「自动防御」和「自动开密函」的直走共用这一份）。

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
