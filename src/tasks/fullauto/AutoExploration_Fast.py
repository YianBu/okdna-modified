from ok import Logger, TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks.CommissionsTask import CommissionsTask
from src.tasks.DNAOneTimeTask import DNAOneTimeTask
from src.tasks.BaseCombatTask import BaseCombatTask
from src.tasks.fullauto.DungeonActionLogic import (
    MODE_EXPLORATION,
    default_map_for_mode,
    maps_for_mode,
)
from src.tasks.fullauto.DungeonActionMixin import DungeonActionMixin
from src.tasks.fullauto.DungeonFlowMixin import DungeonFlowMixin

logger = Logger.get_logger(__name__)
DEFAULT_ACTION_TIMEOUT = 10

# 「地图选择」可选的地图 = 「自动开密函」探险那一份（DungeonActionLogic 里 mode=探险 的条目）。
# 判图框（track_point）和走位（DungeonActionMixin.execute_exploration_*）都跟它共用同一份，
# 改那张表两边一起变。
EXPLORATION_MAPS = tuple(maps_for_mode(MODE_EXPLORATION))


class MapDetectionError(Exception):
    """地图识别错误异常"""
    pass


class AutoExploration_Fast(DungeonFlowMixin, DungeonActionMixin, DNAOneTimeTask, CommissionsTask, BaseCombatTask):
    """全自动探险/无尽：判图与走位复用「自动开密函」的探险那套（DungeonActionMixin）。

    地图名 / 判图框 / 行动函数都在 ``DungeonActionLogic`` / ``DungeonActionMixin``；
    本类只负责「按「地图选择」筛一遍 -> 派发 -> 局内计时与重开」。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = "icons/tasks/auto_exploration.svg"
        self.group_icon = FluentIcon.CALENDAR
        self.name = "自动探险/无尽"
        self.description = "全自动"
        self.group_name = "日常"
        self.default_config.update({
            '轮次': 3,
            '超时时间': 120,
            '地图选择': list(EXPLORATION_MAPS),
        })
        self.config_description.update({
            '轮次': '打几个轮次',
            '超时时间': '超时后将发出提示（0 = 不限制）',
            '地图选择': '选择要自动执行的地图类型',
        })
        self.setup_commission_config()
        self.setup_dungeon_flow(MODE_EXPLORATION)

        # 地图选择：选项就是「自动开密函」探险那套地图
        self.config_type["地图选择"] = {
            "type": "multi_selection",
            "options": list(EXPLORATION_MAPS),
        }
        self.action_timeout = DEFAULT_ACTION_TIMEOUT

    def run(self):
        DNAOneTimeTask.run(self)
        self.move_mouse_to_safe_position(save_current_pos=False)
        self.set_check_monthly_card()
        self.external_movement = self.walk_to_aim
        try:
            while True:
                try:
                    return self.run_dungeon_flow()
                except MapDetectionError as e:
                    # 地图识别错误，记录日志并重试
                    self.log_info(f"地图识别错误: {e}，重新开始任务")
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error('AutoExploration_Fast error', e)
            raise

    def walk_to_aim(self, delay=0):
        """判当前是哪张探险图，跑「自动开密函」那套对应走位。

        判图用 DungeonActionLogic 里的 track_point；一张都没命中就照它的规则回落到该副本
        的默认图。判出来的图不在「地图选择」里就抛 MapDetectionError 重来。
        """
        self.sleep(delay)
        map_selection = self.config.get("地图选择", [])
        current_map = self.detect_current_map_stable(MODE_EXPLORATION)
        if current_map is None:
            current_map = default_map_for_mode(MODE_EXPLORATION)
            self.log_info(f"未识别到地图，先按默认「{current_map}」走；"
                          "若实际不是这张图，请把上面这条日志和 map_detect_fail 截图发回")
        if len(map_selection) != 0 and current_map not in map_selection:
            raise MapDetectionError(f"当前地图[{current_map}]不匹配选择的地图{map_selection}")
        self.log_info(f"识别到地图类型：{current_map}，开始执行移动逻辑")
        return self.run_dungeon_action(current_map)

