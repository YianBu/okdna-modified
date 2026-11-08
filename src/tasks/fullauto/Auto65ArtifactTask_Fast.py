from qfluentwidgets import FluentIcon

from ok import Logger, TaskDisabledException
from src.tasks.DNAOneTimeTask import DNAOneTimeTask
from src.tasks.CommissionsTask import CommissionsTask
from src.tasks.BaseCombatTask import BaseCombatTask

from src.tasks.AutoDefence import AutoDefence
from src.tasks.fullauto.DungeonActionLogic import (
    MODE_DEFENCE,
    default_map_for_mode,
    maps_for_mode,
)
from src.tasks.fullauto.DungeonActionMixin import DungeonActionMixin

logger = Logger.get_logger(__name__)

# 「地图选择」可选的地图 = 「自动开密函」扼守那一份（DungeonActionLogic 里 mode=扼守 的条目）：
# 扼守斜走 / 扼守直走。判图框（track_point）和走位（execute_defence_*）都跟它共用同一份，
# 改那张表两边一起变。
DEFENCE_MAPS = tuple(maps_for_mode(MODE_DEFENCE))


class MapDetectionError(Exception):
    """地图识别错误异常"""
    pass


class Auto65ArtifactTask_Fast(DungeonActionMixin, DNAOneTimeTask, CommissionsTask, BaseCombatTask):
    """
    移动更快的自动30/65级mod，路径参考EMT

    进本后先按 DungeonActionLogic 的 track_point 判当前是哪张防御图，再跑「自动开密函」
    扼守那套对应走位（斜走 / 直走）；判不出来就按该副本的默认图走。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.FLAG
        self.name = "自动防御"
        self.description = "全自动"
        self.group_name = "全自动（日常）"
        self.group_icon = FluentIcon.CALENDAR

        self.setup_commission_config()
        self.default_config.update({
            "地图选择": list(DEFENCE_MAPS),
        })
        self.config_description.update({
            "地图选择": "选择要自动执行的地图类型",
        })
        # 「地图选择」：跟「自动探险/无尽」同一个样式；判出来的图不在勾选里就重开任务。
        self.config_type["地图选择"] = {
            "type": "multi_selection",
            "options": list(DEFENCE_MAPS),
        }

        self.action_timeout = 10

    def run(self):
        """主运行方法"""
        DNAOneTimeTask.run(self)
        self.move_mouse_to_safe_position(save_current_pos=False)
        self.set_check_monthly_card()
        _to_do_task = None
        original_info_set = None
        try:
            _to_do_task = self.get_task_by_class(AutoDefence)
            _to_do_task.config_external_movement(self.walk_to_aim, self.config)
            original_info_set = _to_do_task.info_set
            _to_do_task.info_set = self.info_set
            while True:
                try:
                    return _to_do_task.do_run()
                except MapDetectionError as e:
                    # 判出来的地图不在「地图选择」里：记日志后重新开始一轮
                    self.log_info(f"地图识别错误: {e}，重新开始任务")
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error("AutoMyDungeonTask error", e)
            raise
        finally:
            if _to_do_task is not None and _to_do_task is not self and original_info_set is not None:
                _to_do_task.info_set = original_info_set

    def walk_to_aim(self, delay=0):
        """判当前是哪张防御图，跑「自动开密函」扼守那套对应走位。

        判图用 DungeonActionLogic 里的 track_point；一张都没命中就照它的规则回落到该副本
        的默认图（扼守直走）。判出来的图不在「地图选择」里就抛 MapDetectionError 重来。
        """
        self.sleep(delay)
        map_selection = self.config.get("地图选择", [])
        current_map = self.detect_current_map(MODE_DEFENCE)
        if current_map is None:
            current_map = default_map_for_mode(MODE_DEFENCE)
            self.log_info(f"未识别到地图，改用默认：{current_map}")
        if len(map_selection) != 0 and current_map not in map_selection:
            raise MapDetectionError(f"当前地图[{current_map}]不匹配选择的地图{map_selection}")
        self.log_info(f"识别到地图类型：{current_map}，开始执行移动逻辑")
        return self.run_dungeon_action(current_map)
