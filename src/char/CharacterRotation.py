"""角色技能循环表的唯一出处。

所有循环统一成「opening + loop」：
  * opening: ((动作, 放完等几秒), ...)，角色的一段序列；
  * loop:    True = 整段循环；False = 放一遍就停；
  * timed:   ((间隔秒数, (动作, ...)), ...) 可选，按真实时间插入；
  * spam:    "普攻" 或 (动作, 最小间隔秒数) 可选；
  * charge_shot: True = 开镜自动蓄力，读百分比满 100% 按普攻（黎瑟SP）。

执行逻辑在 `CharacterRotationMixin`，任务继承它即可；这里只放数据。
下拉选项按角色名的拼音首字母排序。
"""


# 首字母 -> 下拉排序用；新角色在这里补一个字，没写的退回 Unicode 顺序。
_INITIALS = {
    "法": "F",
    "扶": "F",
    "黎": "L",
    "老": "L",
    "巧": "Q",
    "苏": "S",
    "伊": "Y",
    "煜": "Y",
    "止": "Z",
}


def rotation_sort_key(name: str):
    """按拼音首字母排序；同首字母按完整名字排。"""
    first = name[0] if name else ""
    return (_INITIALS.get(first, first.upper()), name)


_ROTATIONS = {
    # 法露茜：以永恒梦魇为准。起手锁定 + 连按 5 下终结技；循环普攻、每 3 秒两下战技、
    # 每 20 秒补一次终结技。
    "法露茜": {"opening": (("锁定", 0.5), ("终结技", 0.1), ("终结技", 0.1),
                           ("终结技", 0.1), ("终结技", 0.1), ("终结技", 1.0)),
               "spam": "普攻",
               "timed": ((3.0, ("短按战技", "短按战技")), (20.0, ("终结技",)))},
    # 黎瑟：起手按一次终结技，只放这一下。
    "黎瑟": {"opening": (("终结技", 1.0),)},
    # 黎瑟SP：起手终结技（会自动开镜并开始蓄力）-> 长按战技 0.4 秒（第一次刷新）。
    # 之后每 1 秒刷新一次，每次只长按一次；开局 6 秒补一次魔灵支援。
    # 前 3 发读百分比（满 100% 射击）；之后固定 1.2 秒射击一次，不再 OCR。
    # 蓄力是开镜后自动涨的，满 100% 按普攻键射击，不需要按住射击键。
    "黎瑟SP": {"opening": (("终结技", 0.5), ("长按战技", 0.2)),
               "long_press": 0.4,
               "charge_shot": True,
               "refresh_interval": 1.0,
               "geniemon_delay": 6.0},
    # 伊薇/戏剧：整局开局只放一次终结技，之后（包括切层后）都不再释放技能。
    "伊薇/戏剧": {"opening": (("终结技", 1.0),), "reset_on_stage_switch": False},
    # 伊薇/迷津：战技 x7（每个后面停1秒），放一遍。
    "伊薇/迷津": {"opening": (("短按战技", 1.0), ("短按战技", 1.0), ("短按战技", 1.0),
                               ("短按战技", 1.0), ("短按战技", 1.0), ("短按战技", 1.0),
                               ("短按战技", 1.0)),
                 # 兼容还没迁到 CharacterRotationMixin 的旧迷津任务
                 "steps": (("短按战技", 1.0), ("短按战技", 1.0), ("短按战技", 1.0),
                           ("短按战技", 1.0), ("短按战技", 1.0), ("短按战技", 1.0),
                           ("短按战技", 1.0)),
                 "loop": False},
    # 止流/戏剧：起手长按战技 -> 短按战技 -> 终结技 -> 等4秒 -> 短按战技 x2 -> 终结技；
    # 循环每 1.4 秒放一次终结技。
    "止流/戏剧": {"opening": (("长按战技", 1.0), ("短按战技", 1.0), ("终结技", 4.0),
                             ("短按战技", 1.0), ("短按战技", 1.0), ("终结技", 1.0)),
                 "timed": ((1.4, ("终结技",)),)},
    # 止流/迷津：战技 -> 停1秒 -> 长按战技(1秒) -> 停1秒 -> 终结技，整段循环。
    "止流/迷津": {"opening": (("短按战技", 1.0), ("长按战技", 1.0), ("终结技", 1.0)),
                 "steps": (("短按战技", 1.0), ("长按战技", 1.0), ("终结技", 1.0)),
                 "loop": True},
}


# 共享表本身也按首字母排好，测试页/任务下拉直接 list() 就是有序的。
CHARACTER_ROTATIONS = {
    name: _ROTATIONS[name] for name in sorted(_ROTATIONS, key=rotation_sort_key)
}


# 旧任务（还没迁到 CharacterRotationMixin）仍用短名和 steps；保留它们原来的视图。
MODE_ROTATIONS = {
    "hunt_moon": {
        "法露茜": CHARACTER_ROTATIONS["法露茜"],
        "黎瑟SP": CHARACTER_ROTATIONS["黎瑟SP"],
    },
    "eternal_nightmare": {
        "法露茜": CHARACTER_ROTATIONS["法露茜"],
    },
    "theatre": {
        "黎瑟": CHARACTER_ROTATIONS["黎瑟"],
        "伊薇": CHARACTER_ROTATIONS["伊薇/戏剧"],
        "止流": CHARACTER_ROTATIONS["止流/戏剧"],
    },
    "mijin": {
        "伊薇": CHARACTER_ROTATIONS["伊薇/迷津"],
        "止流": CHARACTER_ROTATIONS["止流/迷津"],
    },
}


def rotations_for(mode: str = "") -> dict:
    """旧任务用的兼容视图；新任务直接引用 CHARACTER_ROTATIONS。"""
    if mode in MODE_ROTATIONS:
        return dict(MODE_ROTATIONS[mode])
    return dict(CHARACTER_ROTATIONS)
