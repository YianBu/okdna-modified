# 自动开密函（已并入 扼守/探险）：模式挑选 + 地图判定 -> 行动逻辑派发 + 本轮次
#
# 不依赖真机截图：OCR / 图标检测 / 行动函数全部打桩，只钉住规则本身：
#   * 「模式」选哪个就只挑哪种任务（驱离/探险/扼守），另外两种不碰；
#   * 判地图只看图标（track_point）位置，判出来才派发到对应行动函数；
#   * 进一次本打多少轮：探险/扼守默认都是 20，配置可改。
import time
import unittest

from ok.feature.Box import Box
from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.dna_ui.Defs import COORD
from src.tasks.fullauto.AutoLetterOpenTask import (
    AutoLetterOpenTask,
    AUTO_ROUNDS_RE,
    COLUMN_NAMES,
    DEFAULT_ROUNDS,
    MODE_DRIVE,
    ROUND_CONFIG_KEYS,
)
from src.tasks.fullauto.DungeonActionLogic import (
    DUNGEON_MAPS,
    MODE_DEFENCE,
    MODE_EXPLORATION,
    action_for_map,
    default_map_for_mode,
    mode_of_task_name,
)


def box(x, y, name, w=60, h=24):
    return Box(x, y, w, h, 0.99, name)


# 图1 列表的仿真 OCR：角色栏有「探险/无尽」、武器栏有「扼守」、魔之楔栏有「驱离」。
BOARD_OCR = [
    box(216, 340, '角色'), box(560, 340, '武器'), box(891, 339, '魔之楔'),
    box(201, 374, '持有数35'), box(545, 375, '持有数50'), box(887, 375, '持有数815'),
    box(204, 439, '当前开放'), box(550, 442, '当前开放'), box(892, 442, '当前开放'),
    box(110, 496, '探险/无尽'), box(322, 496, 'Lv.40'),
    box(430, 559, '扼守'),
    box(796, 631, '驱离'), box(1009, 631, 'Lv.40'),
]


class TestLetterOpenDungeon(TaskTestCase):
    task_class = AutoLetterOpenTask
    config = config

    _PATCHED = ('screen_box', 'draw_boxes', 'ocr', 'in_team', 'move_on_begin',
                'sleep', 'skill_tick', 'random_walk_tick', 'config', 'wait_until',
                '_click_detected', 'find_track_point', 'get_round_info',
                'detect_current_map', 'run_dungeon_action', 'log_info',
                'send_key', 'move_mouse_relative', 'advance_until_combat',
                'external_movement', '_walked_this_mission', 'walk_to_aim', 'move_on_begin',
                'hold_w_until_combat', 'send_key_down', 'send_key_up', 'next_frame',
                'is_in_combat', 'get_dodge_key', 'current_round', '_round_counted',
                'init_for_next_round', 'check_for_monthly_card', 'find_letter_reward_btn',
                'find_start_interface', 'find_action_dialog_continue', 'start_mission',
                'find_action_dialog_retreat', 'find_esc_menu',
                'solve_exploration_mechanism', 'get_interact_key', 'find_one', '_dungeon_mode')
    _PATCHED = _PATCHED + ('leave_letter_start', 'quit_mission', '_leave_after_rounds')
    _PATCHED = _PATCHED + ('leave_to_board',)
    _PATCHED = _PATCHED + ('find_auto_rounds', 'click_box_random',
                           '_auto_rounds_off_confirmed', '_next_auto_rounds_check',
                           '_entry_letter_count', '_entry_rounds_done')
    _PATCHED = _PATCHED + ('update_rounds_info', 'info_set')
    _PATCHED = _PATCHED + ('account_drive_away_round', 'ensure_auto_rounds_off')
    _PATCHED = _PATCHED + ('click_ui_coord',)

    def setUp(self):
        self._saved = {name: getattr(self.task, name) for name in self._PATCHED}
        # 判图重试会取新帧（detect_current_map_stable）；单测没有真实画面，别让它等抓帧超时
        self.task.next_frame = lambda *args, **kwargs: None

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(self.task, name, value)
        super().tearDown()

    def stub_board(self, results):
        self.task.screen_box = lambda name: box(60, 320, name, 1050, 380)
        self.task.draw_boxes = staticmethod(lambda *a, **k: None)
        self.task.ocr = lambda **kw: list(results)
        self.task._board_cache = None
        self.task._board_cache_time = 0

    # ---- 任务名 -> 副本类型 ----

    def test_mode_of_task_name(self):
        self.assertEqual(mode_of_task_name('探险/无尽'), MODE_EXPLORATION)
        self.assertEqual(mode_of_task_name('扼守'), MODE_DEFENCE)
        self.assertEqual(mode_of_task_name('扼守/无尽'), MODE_DEFENCE)
        for other in ('驱离', '驱逐', '调停', 'Lv.40', '当前开放', None):
            self.assertIsNone(mode_of_task_name(other), f'{other} 不该算探险/扼守')

    # ---- 列表挑选：按优先级 驱离 > 探险 > 扼守（看图上有哪种）----

    def pick(self, results):
        self.stub_board(results)
        clicked = []
        self.task._click_detected = lambda target, **kw: clicked.append(target)
        self.task.wait_until = lambda *a, **k: True
        self.task.ensure_auto_rounds_off = lambda *a, **k: False
        self.task._picked_drive_away = False
        self.task._dungeon_mode = None
        ok = self.task.pick_drive_away()
        return ok, clicked

    def test_pick_prefers_drive_away(self):
        """三种都有时挑「驱离」（优先级最高）。"""
        ok, clicked = self.pick(BOARD_OCR)
        self.assertTrue(ok)
        self.assertEqual(self.task._dungeon_mode, MODE_DRIVE)
        self.assertEqual(clicked[0].name, '驱离')

    def test_pick_exploration_when_no_drive_away(self):
        """没有驱离时挑「探险/无尽」（探险 优先于 扼守）。"""
        ok, clicked = self.pick([
            box(216, 340, '角色'), box(560, 340, '武器'), box(891, 339, '魔之楔'),
            box(201, 374, '持有数35'), box(545, 375, '持有数50'), box(887, 375, '持有数815'),
            box(204, 439, '当前开放'), box(550, 442, '当前开放'), box(892, 442, '当前开放'),
            box(110, 496, '探险/无尽'),
            box(430, 559, '扼守'),
        ])
        self.assertTrue(ok)
        self.assertEqual(self.task._dungeon_mode, MODE_EXPLORATION)
        self.assertEqual(clicked[0].name, '探险/无尽')

    def test_pick_defence_when_only_defence(self):
        """只有「扼守」时挑它。"""
        ok, clicked = self.pick([
            box(216, 340, '角色'), box(560, 340, '武器'), box(891, 339, '魔之楔'),
            box(201, 374, '持有数35'), box(545, 375, '持有数50'), box(887, 375, '持有数815'),
            box(204, 439, '当前开放'), box(550, 442, '当前开放'), box(892, 442, '当前开放'),
            box(430, 559, '扼守'),
        ])
        self.assertTrue(ok)
        self.assertEqual(self.task._dungeon_mode, MODE_DEFENCE)
        self.assertEqual(clicked[0].name, '扼守')

    def test_pick_skips_zero_count_column(self):
        """该栏持有数为 0 就跳过，换下一栏有能打的任务的。"""
        ok, clicked = self.pick([
            box(216, 340, '角色'), box(560, 340, '武器'), box(891, 339, '魔之楔'),
            box(201, 374, '持有数0'), box(545, 375, '持有数50'), box(887, 375, '持有数815'),
            box(204, 439, '当前开放'), box(550, 442, '当前开放'), box(892, 442, '当前开放'),
            box(110, 496, '探险/无尽'),
            box(430, 559, '探险/无尽'),
        ])
        self.assertTrue(ok)
        self.assertEqual(self.task._dungeon_mode, MODE_EXPLORATION)
        self.assertEqual(clicked[0].y, 559, '第 1 栏持有数 0，应跳到第 2 栏')

    def test_unselected_column_is_skipped(self):
        """「栏目选择」没勾「魔之楔」：就算它有驱离也不挑，改挑「角色」栏的探险。"""
        self.task.config = {'栏目选择': ['角色', '武器']}
        ok, clicked = self.pick(BOARD_OCR)
        self.assertTrue(ok)
        self.assertEqual(self.task._dungeon_mode, MODE_EXPLORATION, '驱离那栏没勾，跳到探险')
        self.assertEqual(clicked[0].name, '探险/无尽')

    def test_no_column_selected_picks_nothing(self):
        """「栏目选择」一个都没勾：什么都不挑（交给「等待刷新」那套）。"""
        self.task.config = {'栏目选择': []}
        ok, clicked = self.pick(BOARD_OCR)
        self.assertFalse(ok)
        self.assertEqual(clicked, [])

    def test_selected_columns_reads_the_multi_selection(self):
        """「栏目选择」是「地图选择」那种多选：按勾上的栏给结果，缺配置按三栏全勾。"""
        self.task.config = {'栏目选择': ['魔之楔']}
        self.assertEqual(self.task.selected_columns(), ['魔之楔'])
        self.task.config = {'栏目选择': ['武器', '角色']}
        self.assertEqual(self.task.selected_columns(), ['角色', '武器'], '按列表固定顺序给结果')
        self.task.config = {}
        self.assertEqual(self.task.selected_columns(), list(COLUMN_NAMES), '老存档没这个键 = 三栏全打')
        self.assertEqual(self.task.default_config['栏目选择'], list(COLUMN_NAMES))

    def test_column_selection_is_a_multi_selection_like_map_selection(self):
        """界面上要是「地图选择」那种一排勾选框（multi_selection），不是三个开关。"""
        field = self.task.config_type['栏目选择']
        self.assertEqual(field['type'], 'multi_selection')
        self.assertEqual(field['options'], list(COLUMN_NAMES))

    def test_pick_none_when_nothing_playable(self):
        """列表上没有可打的委托：不挑。"""
        ok, clicked = self.pick([
            box(216, 340, '角色'), box(560, 340, '武器'), box(891, 339, '魔之楔'),
            box(201, 374, '持有数0'), box(545, 375, '持有数0'), box(887, 375, '持有数0'),
            box(204, 439, '当前开放'), box(550, 442, '当前开放'), box(892, 442, '当前开放'),
            box(110, 496, '探险/无尽'), box(430, 559, '扼守'), box(796, 631, '驱离'),
        ])
        self.assertFalse(ok)
        self.assertFalse(self.task._picked_drive_away)

    # ---- 图2 的「自动轮次」开着就自动关掉 ----

    def test_ensure_auto_rounds_off_clicks_switch(self):
        clicks = []
        label = box(957, 533, '自动轮次')
        state = {'on': True}
        self.task.find_auto_rounds = lambda: (state['on'], label)

        def click(target, **kw):
            clicks.append(target)
            state['on'] = False        # 点了就当成关掉了

        self.task.click_box_random = click
        self.assertTrue(self.task.ensure_auto_rounds_off())
        self.assertEqual(len(clicks), 1, '检测到开着就点一次开关')
        self.assertGreater(clicks[0].x, 957, '开关是标题右边那个滑块（不是左边）')

    def test_ensure_auto_rounds_off_noop_when_already_off(self):
        clicks = []
        self.task.find_auto_rounds = lambda: (False, None)
        self.task.click_box_random = lambda target, **kw: clicks.append(target)
        self.assertTrue(self.task.ensure_auto_rounds_off(), '本来就是关的也算成功')
        self.assertEqual(clicks, [], '本来就是关的，不点')

    def test_auto_rounds_regex_matches_round_line(self):
        """「轮次x/99」的判据要真能匹配（曾经 \\d/\\s 被写成 d/s，永远匹配不到）。"""
        self.assertTrue(AUTO_ROUNDS_RE.search('轮次1/99'))
        self.assertTrue(AUTO_ROUNDS_RE.search('轮次 12/99'))
        self.assertTrue(AUTO_ROUNDS_RE.search('轮次3/9'))
        self.assertFalse(AUTO_ROUNDS_RE.search('自动轮次'), '只看得到标题、没有那行轮次时不算开着')

    def test_pick_skips_zero_count_column(self):
        """该栏持有数为 0 就跳过，换下一栏有本模式任务的。"""
        self.stub_board([
            box(216, 340, '角色'), box(560, 340, '武器'), box(891, 339, '魔之楔'),
            box(201, 374, '持有数0'), box(545, 375, '持有数50'), box(887, 375, '持有数815'),
            box(204, 439, '当前开放'), box(550, 442, '当前开放'), box(892, 442, '当前开放'),
            box(110, 496, '探险/无尽'),
            box(430, 559, '探险/无尽'),
        ])
        self.task.config = {"模式": MODE_EXPLORATION}
        clicked = []
        self.task._click_detected = lambda target, **kw: clicked.append(target)
        self.task.wait_until = lambda *a, **k: True
        self.assertTrue(self.task.pick_drive_away())
        self.assertEqual(self.task._dungeon_mode, MODE_EXPLORATION)
        self.assertEqual(clicked[0].y, 559, '第 1 栏持有数 0，应跳到第 2 栏')

    # ---- 地图判定（只看图标位置）----

    def test_map_tables_are_well_formed(self):
        for name, cfg in DUNGEON_MAPS.items():
            self.assertIn(cfg['mode'], (MODE_EXPLORATION, MODE_DEFENCE), name)
            track_point = cfg['track_point']
            if track_point is not None:
                self.assertEqual(len(track_point), 4, name)
                for value in track_point:
                    self.assertTrue(0.0 <= value <= 1.0, f'{name} 的检测框要用屏幕比例')
            self.assertTrue(hasattr(AutoLetterOpenTask, cfg['action']),
                            f'{name} 的行动函数 {cfg["action"]} 不存在')
        # 扼守必须有兜底（直走）：图标不在「斜走」框里就直走
        self.assertIsNone(DUNGEON_MAPS['扼守直走']['track_point'], '直走是兜底，不该有检测框')
        self.assertIsNotNone(DUNGEON_MAPS['扼守斜走']['track_point'])

    def test_detect_current_map_matches_icon_position(self):
        target = DUNGEON_MAPS['探险高台']['track_point']
        self.task.find_track_point = lambda x1, y1, x2, y2: (x1, y1, x2, y2) == target
        self.assertEqual(self.task.detect_current_map(MODE_EXPLORATION), '探险高台')

    def test_detect_current_map_filters_by_mode(self):
        """图标落在探险的框上时，做扼守也不会把探险地图认成扼守。"""
        target = DUNGEON_MAPS['探险高台']['track_point']
        self.task.find_track_point = lambda x1, y1, x2, y2: (x1, y1, x2, y2) == target
        self.assertIsNone(self.task.detect_current_map(MODE_DEFENCE))

    def test_detect_current_map_none_when_no_icon(self):
        self.task.find_track_point = lambda *a: False
        self.assertIsNone(self.task.detect_current_map(MODE_EXPLORATION))

    def test_default_map_for_mode(self):
        self.assertEqual(default_map_for_mode(MODE_EXPLORATION), '探险平地')
        self.assertEqual(default_map_for_mode(MODE_DEFENCE), '扼守直走')
        self.assertIsNone(default_map_for_mode('未知'))

    # ---- 行动逻辑派发 / 探险高台固化序列 ----

    def test_run_dungeon_action_dispatch(self):
        calls = []
        self.task.execute_exploration_high = lambda: calls.append('high')
        self.task.run_dungeon_action('探险高台')
        self.assertEqual(calls, ['high'])
        self.assertEqual(action_for_map('探险高台'), 'execute_exploration_high')
        self.assertEqual(action_for_map('探险平地'), 'execute_exploration_ground')
        self.assertEqual(action_for_map('扼守斜走'), 'execute_defence_diagonal')
        self.assertEqual(action_for_map('扼守直走'), 'execute_defence_straight')

    def test_exploration_high_runs_frozen_sequence(self):
        """探险高台按 1-3.json 精修：w2.982（含闪避）-> a3.155 -> w0.747 -> f。"""
        events = []
        self.task.log_info = lambda msg, **kw: events.append(('log', msg))
        self.task.send_key = lambda key, **kw: events.append(('key', key, kw.get('down_time')))
        self.task.send_key_down = lambda key: events.append(('down', key))
        self.task.send_key_up = lambda key: events.append(('up', key))
        self.task.sleep = lambda seconds: events.append(('sleep', seconds))
        self.task.move_mouse_relative = lambda dx, dy, **kw: events.append(('mouse', dx, dy))
        self.task.solve_exploration_mechanism = lambda: events.append(('solve',))
        self.task.get_interact_key = lambda: 'f'
        self.task.get_dodge_key = lambda: 'lshift'
        self.task.execute_exploration_high()
        self.assertEqual(events[0], ('log', '[探险高台] 开始走位'), '日志带 [探险高台] 前缀')
        self.assertEqual(events[1:], [
            ('sleep', 1.0), ('down', 'lalt'), ('sleep', 0.1), ('down', 'w'), ('sleep', 0.297),
            ('down', 'lshift'), ('sleep', 0.221), ('up', 'lshift'), ('sleep', 2.464),
            ('up', 'w'), ('sleep', 0.630), ('down', 'a'), ('sleep', 3.155), ('up', 'a'),
            ('sleep', 0.595), ('down', 'w'), ('sleep', 0.747), ('up', 'w'), ('sleep', 1.151),
            ('solve',),
            ('up', 'w'), ('up', 'a'), ('up', 'lshift'), ('up', 'space'), ('up', 'lalt'),
        ])

    def test_exploration_ground_runs_frozen_sequence(self):
        """探险平地：3-2 的移动段 + 高台 Alt/W 起手；按住 Alt 跳不起来，去掉两次空格。"""
        events = []
        self.task.log_info = lambda msg, **kw: events.append(('log', msg))
        self.task.send_key = lambda key, **kw: events.append(('key', key, kw.get('down_time')))
        self.task.send_key_down = lambda key: events.append(('down', key))
        self.task.send_key_up = lambda key: events.append(('up', key))
        self.task.sleep = lambda seconds: events.append(('sleep', seconds))
        self.task.solve_exploration_mechanism = lambda: events.append(('solve',))
        self.task.get_interact_key = lambda: 'f'
        self.task.get_dodge_key = lambda: 'lshift'
        self.task.execute_exploration_ground()
        self.assertEqual(events[0], ('log', '[探险平地] 开始走位'))
        self.assertEqual(events[1:], [
            ('sleep', 1.0), ('down', 'lalt'), ('sleep', 0.1), ('down', 'w'),
            ('sleep', 0.569), ('down', 'lshift'),
            ('sleep', 1.829), ('up', 'lshift'), ('sleep', 2.724), ('up', 'w'),
            ('sleep', 1.013), ('down', 'a'), ('sleep', 0.492), ('up', 'a'),
            ('sleep', 0.638), ('solve',),
            ('up', 'w'), ('up', 'a'), ('up', 'lshift'), ('up', 'lalt'),
        ])

    def test_solve_exploration_mechanism_presses_f_until_combat(self):
        """破解照戏剧写法：每 interval 按一次交互键（F），开战就停手。"""
        import src.tasks.fullauto.DungeonActionMixin as mixin
        saved_time = mixin.time
        clock = {'t': 0.0}

        def fake_time():
            clock['t'] += 0.5
            return clock['t']

        keys = []
        try:
            self.task.get_interact_key = lambda: 'f'
            self.task.send_key = lambda key, **kw: keys.append(key)
            self.task.sleep = lambda seconds: None
            seq = [False, False, True]
            self.task.is_in_combat = lambda: seq.pop(0) if seq else True
            mixin.time = type('FakeTime', (), {'time': staticmethod(fake_time)})
            self.assertTrue(self.task.solve_exploration_mechanism())
        finally:
            mixin.time = saved_time
        self.assertEqual(keys, ['f', 'f'], '没开战就继续按 F，开战后停手')

    def test_defence_diagonal_runs_frozen_sequence(self):
        """扼守斜走的实测序列已固化：w2.0 -> d3.8 -> w6.0。"""
        events = []
        self.task.log_info = lambda msg, **kw: events.append(('log', msg))
        self.task.send_key = lambda key, **kw: events.append(('key', key, kw.get('down_time')))
        self.task.execute_defence_diagonal()
        self.assertEqual(events[0], ('log', '[扼守斜走] 开始走位'))
        self.assertEqual(events[1:], [('key', 'w', 2.0), ('key', 'd', 3.8), ('key', 'w', 6.0)])

    def test_defence_straight_is_a_then_hold_w_until_combat(self):
        """扼守直走的序列：a 0.2 -> 按住 W 前进到开战。"""
        events = []
        self.task.log_info = lambda msg, **kw: events.append(('log', msg))
        self.task.send_key = lambda key, **kw: events.append(('key', key, kw.get('down_time')))
        self.task.hold_w_until_combat = lambda: events.append(('hold_w',))
        self.task.execute_defence_straight()
        self.assertEqual(events[0], ('log', '[扼守直走] 开始走位'))
        self.assertEqual(events[1:], [('key', 'a', 0.2), ('hold_w',)])

    def test_hold_w_until_combat_extra_one_second_and_release(self):
        """照「自动扼守/无尽」：开战后只多走 1 秒，结束把移动键/闪避键全松开。"""
        import src.tasks.fullauto.DungeonActionMixin as mixin
        saved_time = mixin.time
        clock = {'t': 0.0}

        def fake_time():
            clock['t'] += 0.5
            return clock['t']

        events = []
        try:
            self.task.send_key_down = lambda key: events.append(('down', key))
            self.task.send_key_up = lambda key: events.append(('up', key))
            self.task.next_frame = lambda: None
            self.task.get_dodge_key = lambda: 'lshift'
            self.task.log_info = lambda msg, **kw: events.append(('log', msg))
            seq = [False, False, True]
            self.task.is_in_combat = lambda: seq.pop(0) if seq else True
            mixin.time = type('FakeTime', (), {'time': staticmethod(fake_time)})
            self.assertTrue(self.task.hold_w_until_combat())
        finally:
            mixin.time = saved_time
        self.assertEqual(events[0], ('down', 'w'))
        for key in ('w', 'a', 's', 'd'):
            self.assertIn(('up', key), events)
        self.assertIn(('log', '已进入战斗，再前进 1.0 秒'), events)

    def test_hold_w_until_combat_gives_up_on_timeout(self):
        """20 秒没开战：记一条日志、松手返回 False，不自己放弃副本。"""
        import src.tasks.fullauto.DungeonActionMixin as mixin
        saved_time = mixin.time
        clock = {'t': 0.0}

        def fake_time():
            clock['t'] += 0.5
            return clock['t']

        events = []
        try:
            self.task.send_key_down = lambda key: None
            self.task.send_key_up = lambda key: events.append(('up', key))
            self.task.next_frame = lambda: None
            self.task.get_dodge_key = lambda: 'lshift'
            self.task.log_info = lambda msg, **kw: events.append(('log', msg))
            self.task.is_in_combat = lambda: False
            mixin.time = type('FakeTime', (), {'time': staticmethod(fake_time)})
            self.assertFalse(self.task.hold_w_until_combat())
        finally:
            mixin.time = saved_time
        self.assertIn(('log', '前进 20 秒仍未开战，交给超时重开'), events)
        self.assertIn(('up', 'w'), events)

    # ---- 进本第一帧走位（开密函路径不返回 Mission.START）----

    def test_walks_once_per_mission_on_entry(self):
        """开密函路径不进 Mission.START，所以走位必须由进本第一帧触发，且一局只走一次。"""
        calls = []
        self.task.walk_to_aim = lambda delay=0: calls.append(delay)
        self.task.skill_tick = lambda: None
        self.task.random_walk_tick = lambda: None
        self.task.runtime_state = {"start_time": 0}
        self.task.config = {"超时时间": 999}
        self.task._dungeon_mode = MODE_EXPLORATION
        self.task._walked_this_mission = False
        self.task.count = 0
        self.task.handle_in_mission()
        self.task.handle_in_mission()
        self.assertEqual(calls, [2], '进本第一帧走位，同一局不再重复走')

    def test_drive_mode_does_not_walk(self):
        """模式=驱离：进本不判图、不走位，保持老行为。"""
        calls = []
        self.task.walk_to_aim = lambda delay=0: calls.append(delay)
        self.task.skill_tick = lambda: None
        self.task.random_walk_tick = lambda: None
        self.task.runtime_state = {"start_time": 0}
        self.task.config = {"超时时间": 999}
        self.task._dungeon_mode = None
        self.task._walked_this_mission = False
        self.task.count = 0
        self.task.handle_in_mission()
        self.assertEqual(calls, [], '驱离模式不走位')

    def test_in_mission_resets_round_counted(self):
        """回局内要把 _round_counted 清零，否则 get_round_info 只数一轮（轮次永远停在 1）。"""
        self.task.walk_to_aim = lambda delay=0: None
        self.task.skill_tick = lambda: None
        self.task.random_walk_tick = lambda: None
        self.task.runtime_state = {"start_time": 0}
        self.task.config = {"超时时间": 999}
        self.task._dungeon_mode = MODE_EXPLORATION
        self.task._walked_this_mission = True
        self.task.count = 0
        self.task._round_counted = True
        self.task.handle_in_mission()
        self.assertFalse(self.task._round_counted, '回局内要允许下一次行动抉择再记一轮')

    # ---- 行动抉择弹窗的「撤离」：图标判据失效时的文字兜底 ----

    def test_find_retreat_button_by_hint_and_button(self):
        """认弹窗上那行说明文字，再点它下面那个「撤离」（OCR 把撤认成撒也要认出来）。"""
        self.task.ocr = lambda **kw: [
            box(293, 378, '选择撤离则直接结算当前奖励', w=200, h=14),
            box(330, 399, '撒离', w=52, h=23),
        ]
        found = self.task.find_retreat_button()
        self.assertIsNotNone(found, '有说明文字 + 下面的撤离按钮，要认出来')
        self.assertEqual(found.y, 399, '取说明文字下面那个按钮')

    def test_find_retreat_button_none_without_hint(self):
        """没有那行说明文字就不是行动抉择弹窗（别的界面也有「撤离」字样，别乱点）。"""
        self.task.ocr = lambda **kw: [box(330, 399, '撤离', w=52, h=23)]
        self.assertIsNone(self.task.find_retreat_button())

    # ---- 超时/放弃：ESC 菜单开着时要真的去点「放弃挑战」----

    def test_give_up_clicks_esc_menu_abandon(self):
        """菜单盖住 HUD 时 in_team() 会是假 —— 不能因此就当成"已经到能重开的界面"直接返回。"""
        clicks = []
        state = {'menu': True}
        self.task.in_team = lambda *a, **k: False
        self.task.find_esc_menu = lambda **kw: state['menu']
        self.task.find_start_interface = lambda **kw: not state['menu']
        self.task.find_action_dialog_continue = lambda **kw: None
        self.task.find_action_dialog_retreat = lambda **kw: None
        self.task.find_result_again_btn = lambda **kw: None
        self.task.find_center_confirm = lambda **kw: None
        self.task.ocr = lambda **kw: []

        def click(coord, **kw):
            clicks.append(coord)
            state['menu'] = False

        self.task.click_ui_coord = click
        self.assertTrue(self.task.give_up_mission(timeout=1))
        self.assertEqual(clicks, [COORD.ESC_GIVEUP], '要点一次「放弃挑战」')

    def test_result_screen_resets_walk_flag(self):
        """结算界面出现 = 这一局结束：下一局（点「再次进行」）要重新判图 + 走位。"""
        self.task._walked_this_mission = True
        self.task._dungeon_mode = MODE_EXPLORATION
        self.task.in_team = lambda *a, **k: False
        self.task.check_for_monthly_card = lambda: (False, 0)
        self.task.find_letter_reward_btn = lambda **kw: None
        self.task.find_letter_interface = lambda **kw: None
        self.task.find_manual_select_btn = lambda **kw: None
        self.task.find_start_interface = lambda **kw: None
        self.task.find_action_dialog_continue = lambda **kw: None
        self.task.find_action_dialog_retreat = lambda **kw: None
        self.task.find_esc_menu = lambda **kw: None
        self.task.find_result_again_btn = lambda **kw: True
        self.task.start_mission = lambda *a, **k: None
        self.task.handle_mission_interface(stop_func=lambda: False)
        self.assertFalse(self.task._walked_this_mission, '结算后要重新走位')

    def test_only_picking_from_board_resets_walk_flag(self):
        """同一局里打多少波都不重走；只有从列表挑新任务才会复位走位标志。"""
        self.stub_board(BOARD_OCR)
        self.task._click_detected = lambda *a, **k: True
        self.task.wait_until = lambda *a, **k: True
        self.task.ensure_auto_rounds_off = lambda *a, **k: False
        self.task._walked_this_mission = True
        self.task.current_round = 5
        self.task._round_counted = True
        self.assertTrue(self.task.pick_drive_away())
        self.assertFalse(self.task._walked_this_mission, '挑新任务后下一局要重新走位')
        self.assertEqual(self.task.current_round, 0, '每进一把轮次都从 0 开始数')
        self.assertFalse(self.task._round_counted)

    def test_walk_to_aim_uses_detected_map(self):
        self.task.sleep = lambda seconds: None
        self.task._dungeon_mode = MODE_EXPLORATION
        self.task.detect_current_map = lambda mode=None: '探险平地'
        calls = []
        self.task.run_dungeon_action = lambda name: calls.append(name)
        self.task.walk_to_aim(delay=2)
        self.assertEqual(calls, ['探险平地'])

    def test_walk_to_aim_falls_back_to_default(self):
        self.task.sleep = lambda seconds: None
        self.task._dungeon_mode = MODE_DEFENCE
        self.task.detect_current_map = lambda mode=None: None
        calls = []
        self.task.run_dungeon_action = lambda name: calls.append(name)
        self.task.walk_to_aim()
        self.assertEqual(calls, ['扼守直走'], '扼守图标不在斜走框内 -> 直走')

    # ---- 进一次本打多少轮（默认 20）----

    def test_round_config_defaults(self):
        self.assertEqual(self.task.default_config['探险轮次'], 20)
        self.assertEqual(self.task.default_config['扼守轮次'], 20)
        self.assertEqual(ROUND_CONFIG_KEYS, {MODE_EXPLORATION: '探险轮次',
                                             MODE_DEFENCE: '扼守轮次'})
        self.assertEqual(DEFAULT_ROUNDS, 20)

    def test_rounds_for_mode_reads_config(self):
        self.task.config = {'探险轮次': 7, '扼守轮次': 3}
        self.assertEqual(self.task.rounds_for_mode(MODE_EXPLORATION), 7)
        self.assertEqual(self.task.rounds_for_mode(MODE_DEFENCE), 3)
        self.task.config = {}
        self.assertEqual(self.task.rounds_for_mode(MODE_EXPLORATION), 20)
        self.task.config = {'探险轮次': '坏值'}
        self.assertEqual(self.task.rounds_for_mode(MODE_EXPLORATION), 20)

    def test_rounds_per_mission_config_and_column_cap(self):
        """每局打「配置轮次」；这一栏的持有数是总上限，累计到上限就收工。"""
        self.task.config = {'探险轮次': 20, '扼守轮次': 3}
        self.task._dungeon_mode = MODE_EXPLORATION
        self.task._entry_letter_count = 50
        self.task._entry_rounds_done = 0
        self.assertEqual(self.task.rounds_this_mission(), 20, '每局按配置轮次打')
        self.task._entry_rounds_done = 40
        self.assertEqual(self.task.rounds_this_mission(), 10, '离上限只剩 10 轮就只打 10 轮')
        self.task._entry_rounds_done = 50
        self.assertTrue(self.task.entry_rounds_full())
        self.task._entry_letter_count = None
        self.task._entry_rounds_done = 999
        self.assertFalse(self.task.entry_rounds_full(), '读不到持有数就不设上限')
        self.assertEqual(self.task.rounds_this_mission(), 20)

    def test_account_mission_rounds_accumulates(self):
        self.task.config = {'探险轮次': 20}
        self.task.current_round = 20
        self.task._entry_rounds_done = 0
        self.task.account_mission_rounds()
        self.assertEqual(self.task._entry_rounds_done, 20, '这一局打的轮次要累加')
        self.assertEqual(self.task.current_round, 0, '新一局从头数')

    def test_rounds_info_column(self):
        """信息栏「轮次计算」显示 已打/上限。"""
        shown = {}
        self.task.info_set = lambda key, value: shown.__setitem__(key, value)
        self.task._entry_letter_count = 30
        self.task._entry_rounds_done = 7
        self.task.current_round = 2
        self.task.update_rounds_info()
        self.assertEqual(shown.get('轮次计算'), '9/30', '这一局打的也算进去')
        self.task._entry_letter_count = None
        self.task._entry_rounds_done = 0
        self.task.current_round = 0
        self.task.update_rounds_info()
        self.assertEqual(shown.get('轮次计算'), '0/?', '读不到持有数上限就显示 ?')

    def test_pick_records_column_count_as_cap(self):
        shown = {}
        self.task.info_set = lambda key, value: shown.__setitem__(key, value)
        ok, _ = self.pick(BOARD_OCR)
        self.assertTrue(ok)
        self.assertEqual(self.task._entry_letter_count, 815, '记下这一栏「持有数」当总上限')
        self.assertEqual(self.task._entry_rounds_done, 0, '这一栏累计轮次从头数')
        self.assertEqual(self.task.current_round, 0, '当前轮次也归零')
        self.assertEqual(shown.get('当前轮次'), 0, '信息栏「当前轮次」显示 0')
        self.assertEqual(shown.get('轮次计算'), '0/815', '「轮次计算」从 0/上限 起')

    def test_stop_func_stops_at_configured_rounds(self):
        self.task.get_round_info = lambda: None
        self.task.config = {'探险轮次': 5, '扼守轮次': 5}
        self.task._dungeon_mode = MODE_EXPLORATION
        self.task.current_round = 4
        self.assertFalse(self.task.letter_stop_func(), '没打满不该收工')
        self.task.current_round = 5
        self.assertTrue(self.task.letter_stop_func(), '打满 5 轮就该收工')

    def test_stop_func_uses_mode_specific_rounds(self):
        self.task.get_round_info = lambda: None
        self.task.config = {'探险轮次': 20, '扼守轮次': 2}
        self.task.current_round = 2
        self.task._dungeon_mode = MODE_DEFENCE
        self.assertTrue(self.task.letter_stop_func())
        self.task._dungeon_mode = MODE_EXPLORATION
        self.assertFalse(self.task.letter_stop_func())

    def test_drive_mode_never_stops_on_rounds(self):
        """驱离模式没有轮次上限（老行为）：stop_func 永远 False。"""
        self.task.get_round_info = lambda: None
        self.task.config = {'探险轮次': 1, '扼守轮次': 1}
        self.task._dungeon_mode = None
        self.task.current_round = 99
        self.assertFalse(self.task.letter_stop_func())

    def test_drive_mode_counts_rounds_too(self):
        """驱离也要数轮次（信息栏「轮次计算」才看得到进度），只是不设上限、不收工。"""
        shown = {}
        self.task.get_round_info = lambda: setattr(self.task, 'current_round', 3)
        self.task.info_set = lambda key, value: shown.__setitem__(key, value)
        self.task._dungeon_mode = None
        self.task._entry_letter_count = 815
        self.task._entry_rounds_done = 0
        self.assertFalse(self.task.letter_stop_func(), '驱离不该收工')
        self.assertEqual(shown.get('轮次计算'), '3/815', '驱离也要算出已打轮次')

    def test_drive_away_counts_one_round_per_result_screen(self):
        """驱离没有波次信号：进一次结算界面就算打了一轮。"""
        shown = {}
        self.task.info_set = lambda key, value: shown.__setitem__(key, value)
        self.task._entry_letter_count = 5
        self.task._entry_rounds_done = 2
        self.task.current_round = 0
        self.task.account_drive_away_round()
        self.assertEqual(self.task._entry_rounds_done, 3, '结算一次 +1 轮')
        self.assertEqual(shown.get('轮次计算'), '3/5')
        self.task.account_drive_away_round()
        self.assertEqual(self.task._entry_rounds_done, 4)
        self.assertFalse(self.task.entry_rounds_full(), '4 < 5 还没到上限')
        self.task.account_drive_away_round()
        self.assertTrue(self.task.entry_rounds_full(), '到 5 就满上限了')

    def test_finish_round_returns_to_board_when_deadline_hit(self):
        """到刷新时间了：把这一轮次打完（STOP）就回列表，不再点「再次进行」重开。"""
        events = []
        self.task._dungeon_mode = MODE_EXPLORATION
        self.task._leave_after_rounds = True
        self.task.in_team = lambda *a, **k: False
        self.task.find_action_dialog_retreat = lambda **kw: None
        self.task.leave_to_board = lambda *a, **k: events.append('leave')
        self.assertTrue(self.task.finish_letter_round(), '到点后打完轮次应该回列表')
        self.assertEqual(events, ['leave'])
        self.assertFalse(self.task._leave_after_rounds)

    def test_finish_round_restarts_when_not_deadline(self):
        """没到刷新时间：撤离到结算界面重开一局（current_round 归零）。"""
        events = []
        self.task._dungeon_mode = MODE_EXPLORATION
        self.task._leave_after_rounds = False
        self.task.current_round = 20
        self.task.in_team = lambda *a, **k: True
        self.task.quit_mission = lambda *a, **k: events.append('quit')
        self.task.leave_letter_start = lambda *a, **k: events.append('leave')
        self.task.leave_to_board = lambda *a, **k: events.append('leave')
        self.assertFalse(self.task.finish_letter_round(), '没到点不该回列表')
        self.assertEqual(events, ['quit'])
        self.assertEqual(self.task.current_round, 0, '新的一"大轮"从头数起')

    # ---- 空窗：没有探险/扼守时按「等待刷新」收工 ----

    def test_no_dungeon_task_and_wait_off_stops(self):
        from ok import TaskDisabledException
        self.stub_board([])
        self.task.config = {'等待刷新': False}
        with self.assertRaises(TaskDisabledException):
            self.task.handle_no_drive_away()

if __name__ == '__main__':
    unittest.main()
