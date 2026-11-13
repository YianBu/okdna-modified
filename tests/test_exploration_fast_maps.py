# 「自动探险/无尽」的地图选择：和「自动开密函」的探险共用同一张表
#
# 只钉契约，不碰真机：可选地图来自 DungeonActionLogic 的探险条目，判出来的图不在
# 选择里就报错重来，一张都判不出来时按该副本的默认图走（和「自动开密函」一致）。
import unittest

from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.fullauto.AutoExploration_Fast import (
    AutoExploration_Fast,
    MapDetectionError,
)
from src.tasks.fullauto.DungeonActionLogic import (
    MODE_EXPLORATION,
    default_map_for_mode,
    maps_for_mode,
)
from src.tasks.fullauto.DungeonActionMixin import DungeonActionMixin


class TestExplorationFastMaps(TaskTestCase):
    task_class = AutoExploration_Fast
    config = config

    _PATCHED = ('config', 'detect_current_map', 'run_dungeon_action', 'sleep', 'log_info',
                'next_frame')

    def setUp(self):
        self._saved = {name: getattr(self.task, name) for name in self._PATCHED}
        self.dispatched = []
        self.task.sleep = lambda seconds=0: None
        self.task.next_frame = lambda *args, **kwargs: None
        self.task.log_info = lambda *a, **k: None
        self.task.run_dungeon_action = lambda name: self.dispatched.append(name) is None

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(self.task, name, value)
        super().tearDown()

    def walk(self, detected, selection):
        self.task.detect_current_map = lambda mode=None: detected
        self.task.config = {'地图选择': selection}
        return self.task.walk_to_aim(0)

    # ---- 地图表和「自动开密函」的探险共用同一份 ----

    def test_belongs_to_shared_mixin(self):
        self.assertTrue(issubclass(AutoExploration_Fast, DungeonActionMixin))

    def test_map_options_are_letter_exploration_maps(self):
        options = self.task.config_type['地图选择']['options']
        self.assertEqual(options, list(maps_for_mode(MODE_EXPLORATION)))
        self.assertEqual(self.task.default_config['地图选择'], options)
        self.assertNotIn('探险电梯', options, '探险电梯不在「自动开密函」的探险地图表里')

    # ---- 判图 -> 派发 ----

    def test_detected_map_dispatches_to_shared_action(self):
        self.walk('探险高台', ['探险高台'])
        self.assertEqual(self.dispatched, ['探险高台'])

    def test_map_outside_selection_is_rejected(self):
        with self.assertRaises(MapDetectionError):
            self.walk('探险平地', ['探险高台'])
        self.assertEqual(self.dispatched, [], '不匹配选择时不该跑任何走位')

    def test_unknown_map_falls_back_to_mode_default(self):
        self.walk(None, [])
        self.assertEqual(self.dispatched, [default_map_for_mode(MODE_EXPLORATION)])


if __name__ == '__main__':
    unittest.main()

