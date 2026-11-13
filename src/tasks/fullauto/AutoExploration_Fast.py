from ok import Logger, TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks.AutoExploration import AutoExploration
from src.tasks.CommissionsTask import CommissionsTask, QuickAssistTask
from src.tasks.DNAOneTimeTask import DNAOneTimeTask
from src.tasks.trigger.AutoMazeTask import AutoMazeTask
from src.tasks.trigger.AutoRouletteTask import AutoRouletteTask
from src.tasks.BaseCombatTask import BaseCombatTask
from src.tasks.fullauto.DungeonActionLogic import (
    MODE_EXPLORATION,
    default_map_for_mode,
    maps_for_mode,
)
from src.tasks.fullauto.DungeonActionMixin import DungeonActionMixin

logger = Logger.get_logger(__name__)
DEFAULT_ACTION_TIMEOUT = 10

# 「地图选择」可选的地图 = 「自动开密函」探险那一份（DungeonActionLogic 里 mode=探险 的条目）。
# 判图框（track_point）和走位（DungeonActionMixin.execute_exploration_*）都跟它共用同一份，
# 改那张表两边一起变。
EXPLORATION_MAPS = tuple(maps_for_mode(MODE_EXPLORATION))


class MapDetectionError(Exception):
    """地图识别错误异常"""
    pass


class AutoExploration_Fast(DungeonActionMixin, DNAOneTimeTask, CommissionsTask, BaseCombatTask):
    """全自动探险/无尽：判图与走位复用「自动开密函」的探险那套（DungeonActionMixin）。

    地图名 / 判图框 / 行动函数都在 ``DungeonActionLogic`` / ``DungeonActionMixin``；
    本类只负责「按「地图选择」筛一遍 -> 派发 -> 局内计时与重开」。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.FLAG
        self.group_icon = FluentIcon.CALENDAR
        self.name = "自动探险/无尽"
        self.description = "全自动"
        self.group_name = "全自动（日常）"
        self.default_config.update({
            '轮次': 3,
            '超时时间': 120,
            '解密失败自动重开': True,
            '地图选择': list(EXPLORATION_MAPS),
        })
        self.config_description.update({
            '轮次': '打几个轮次',
            '超时时间': '超时后将发出提示',
            '解密失败自动重开': '不重开时会发出声音提示',
            '地图选择': '选择要自动执行的地图类型',
        })
        self.setup_commission_config()

        # 地图选择：选项就是「自动开密函」探险那套地图
        self.config_type["地图选择"] = {
            "type": "multi_selection",
            "options": list(EXPLORATION_MAPS),
        }
        self.action_timeout = DEFAULT_ACTION_TIMEOUT
        self.quick_assist_task = QuickAssistTask(self)

    def run(self):
        DNAOneTimeTask.run(self)
        self.move_mouse_to_safe_position(save_current_pos=False)
        self.set_check_monthly_card()
        _to_do_task = None
        original_info_set = None
        try:
            _to_do_task = self.get_task_by_class(AutoExploration)
            _to_do_task.config_external_movement(self.walk_to_aim, self.config)
            original_info_set = _to_do_task.info_set
            _to_do_task.info_set = self.info_set
            while True:
                try:
                    return _to_do_task.do_run()
                except MapDetectionError as e:
                    # 地图识别错误，记录日志并重试
                    self.log_info(f"地图识别错误: {e}，重新开始任务")
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error('AutoExploration_Fast error', e)
            raise
        finally:
            if _to_do_task is not None and _to_do_task is not self and original_info_set is not None:
                _to_do_task.info_set = original_info_set

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

    def try_solving_puzzle(self):
        """原版解谜处理（迷宫 / 轮盘）。

        DungeonActionMixin（「自动开密函」/「行动逻辑测试」）会调到这一份；本任务自己的探险
        走位改用 solve_exploration_mechanism（反复按交互键到开战），不再走这里。
        """
        maze_task = self.get_task_by_class(AutoMazeTask)
        roulette_task = self.get_task_by_class(AutoRouletteTask)
        if not self.wait_until(
            self.in_team,
            post_action=lambda: self.send_key(self.get_interact_key(), after_sleep=0.1),
            time_out=1.5
        ):
            maze_task.run()
            roulette_task.run()
            if not self.wait_until(self.in_team, time_out=1.5):
                if self.config.get("解密失败自动重开", True):
                    self.log_info("未成功处理解密，等待重开")
                    self.open_in_mission_menu()
                else:
                    self.log_info_notify("未成功处理解密，请求人工接管")
                    self.soundBeep()
                    self.wait_until(self.in_team, time_out=60)
                return False
        return True

