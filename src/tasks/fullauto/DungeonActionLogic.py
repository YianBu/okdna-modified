"""扼守 / 探险 密函副本的「地图判定 -> 外部行动逻辑」。

这是一个**独立**模块：不改动 ``AutoLetterOpenTask``（驱离）的流程，也不改
``AutoExploration`` / ``AutoDefence`` / ``AutoExploration_Fast`` 的任何行为，只被
``AutoLetterOpenTask``（自动开密函的探险 / 扼守模式）引用。

判定方式与原版一致：看屏幕上固定位置的 ``track_point``（追踪点）图标落在哪个搜索
框里，就知道当前是哪张地图；每张地图对应一段外部行动逻辑（走位 / 解谜）。判定出
地图后，任务通过 ``getattr(self, action)()`` 派发到对应的行动函数。

坐标来源 / 对应关系（用户指定）
--------------------------------
* 图1 = 探险平地
* 图2 = 探险高台
* 图3 = 扼守斜走
* 扼守再加一张「直走」：扼守模式下图标不落在「斜走」框里，就按「直走」处理，见 fallback。

检测框（``track_point``）是对着用户这三张 1920x1080 截图，用原版 ``track_point`` 图标模板
（assets/images/3.png 的标注，3840x2160）缩放后 matchTemplate 量出来的。三张图里都有的
左上角固定 HUD 命中已排除，取的是尺度约 0.5 倍的世界追踪点：

* 图1 探险平地：图标 (0.458,0.294)-(0.476,0.324)，中心 (0.467,0.310)（正好落在原版「平地」框内）
* 图2 探险高台：中心 (0.3125,0.5815)（1920x1080 实拍，matchTemplate 0.94；旧值
  (0.269,0.618) 偏左偏下，图标落在旧框右上角外面，所以高台一直判不出来、兜底成平地）
* 图3 扼守斜走：图标 (0.662,0.243)-(0.680,0.272)，中心 (0.671,0.257)
* 扼守直走：不设检测框，只当扼守的兜底

每张图另有一个约 0.34 倍的小尺寸命中在左上角（疑似小地图上的点），没有采用。真机上用
「测试 → 行动逻辑测试」勾「只检测不执行」核对。每张图的行动函数（走位/格子）见
``DungeonActionMixin.execute_*``。
"""

# 副本类型：从委托密函列表的任务名里认出来的两种。
MODE_EXPLORATION = "探险"
MODE_DEFENCE = "扼守"

MODE_NAMES = (MODE_EXPLORATION, MODE_DEFENCE)

# 地图名 -> {"mode": 副本类型, "track_point": 检测框(屏幕比例 x1,y1,x2,y2) 或 None,
#            "action": 行动函数名（任务上的方法，参数是 task 自己）,
#            "fallback": 可选，判不出地图时的兜底（每种副本类型取第一个带它的）}
#
# 探险：平地 / 高台，各有一个世界追踪点框。
# 扼守：斜走有框；直走不设框、标 fallback —— 图标不在斜走框里就用直走。
DUNGEON_MAPS = {
    "探险平地": {
        "mode": MODE_EXPLORATION,
        # 以实测中心 (0.467,0.310) 为准适度放宽（1600 基准下约 96x77px），
        # 容得下镜头淡入/轻微漂移，又不会吃到左侧 0.422 那一带的背景误匹配。
        "track_point": (0.437, 0.266, 0.497, 0.352),
        "action": "execute_exploration_ground",
    },
    "探险高台": {
        "mode": MODE_EXPLORATION,
        # 实测中心 (0.3125,0.5815)，框约 146x86px（1600 基准）。旧框
        # (0.246,0.583)-(0.293,0.652) 的右边只有 0.293，够不到实测的 0.3125。
        "track_point": (0.267, 0.535, 0.358, 0.630),
        "action": "execute_exploration_high",
    },
    "扼守斜走": {
        "mode": MODE_DEFENCE,
        "track_point": (0.647, 0.223, 0.695, 0.292),
        "action": "execute_defence_diagonal",
    },
    "扼守直走": {
        "mode": MODE_DEFENCE,
        "track_point": None,
        "action": "execute_defence_straight",
        "fallback": True,
    },
}


def mode_of_task_name(name):
    """委托密函列表里的任务名属于哪种密函副本；都不是则返回 None。

    只认「扼守」「探险」两个词：界面上的「驱离」「驱逐」「调停」等其它任务都不算，
    免得跟原有「自动开密函」的驱离流程抢任务。
    """
    if name is None:
        return None
    if MODE_DEFENCE in name:
        return MODE_DEFENCE
    if MODE_EXPLORATION in name:
        return MODE_EXPLORATION
    return None


def maps_for_mode(mode):
    """某种副本类型下所有地图名（保持 DUNGEON_MAPS 的顺序）。"""
    return [name for name, config in DUNGEON_MAPS.items() if config["mode"] == mode]


def default_map_for_mode(mode):
    """认不出地图时的兜底。

    该副本类型里标了 fallback 的那张优先（扼守 = 直走：图标不在「斜走」框内就直走）；
    没有 fallback 就取第一张；未知类型返回 None。
    """
    first = None
    fallback = None
    for name, config in DUNGEON_MAPS.items():
        if config["mode"] != mode:
            continue
        if first is None:
            first = name
        if config.get("fallback") and fallback is None:
            fallback = name
    return fallback or first


def action_for_map(name):
    """地图对应的行动函数名；未知地图返回 None。"""
    config = DUNGEON_MAPS.get(name)
    return config["action"] if config else None
