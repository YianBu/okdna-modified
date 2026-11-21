# -*- coding: utf-8 -*-
"""「测试」页的角色循环试跑。

不跑副本流程，只在当前画面按选中的角色循环放技能，方便单独验证手法：
  * 角色列表来自 `src/char/CharacterRotation.py`，带「/模式」的变体也能选；
  * 「只在战斗中」勾上时，只有左上角菱形变红才按技能；取消勾选则一直按；
  * 「先锁定」会在开始前按一次锁定键（循环里自己写了「锁定」就不重复）。
"""

from qfluentwidgets import FluentIcon

from ok import Logger, TaskDisabledException

from src.char.CharacterRotation import CHARACTER_ROTATIONS as ALL_ROTATIONS
from src.tasks.DNAOneTimeTask import DNAOneTimeTask
from src.tasks.fullauto.AutoHuntMoonTask import (
    AutoHuntMoonTask,
    COMBAT_TIMEOUT_KEY,
    CUSTOM_CHARACTER,
)

logger = Logger.get_logger(__name__)

DEFAULT_TEST_CHARACTER = ("黎瑟SP" if "黎瑟SP" in ALL_ROTATIONS
                          else next(iter(ALL_ROTATIONS)))


class CharacterRotationTestTask(AutoHuntMoonTask):
    """把角色循环单独拎出来跑：进战斗后启动，选角色即可。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.DEVELOPER_TOOLS
        self.name = "角色循环"
        self.description = "测试"
        self.group_name = "测试"
        self.group_icon = FluentIcon.DEVELOPER_TOOLS
        # 测试页要能选所有角色/模式，而不只是狩月人那张表
        self.rotation_table = dict(ALL_ROTATIONS)

        # 去掉副本流程的配置，只留角色循环相关
        for key in ("打几次", COMBAT_TIMEOUT_KEY, "主控角色"):
            self.default_config.pop(key, None)
            self.config_type.pop(key, None)
            self.config_description.pop(key, None)

        self.default_config.update({
            "角色": DEFAULT_TEST_CHARACTER,
            "只在战斗中": True,
            "先锁定": True,
        })
        self.config_type["角色"] = {
            "type": "drop_down",
            "options": list(ALL_ROTATIONS) + [CUSTOM_CHARACTER],
        }
        self.config_description.update({
            "角色": "选共享表里的角色或「角色/模式」；本任务不跑副本流程，只在当前画面按这套循环放技能",
            "只在战斗中": "勾上时只有左上角菱形变红才按技能；取消勾选则一直按",
            "先锁定": "开始前先按一次锁定键；循环里自己写了「锁定」就不重复",
        })

    def current_character(self):
        return self.config.get("角色", DEFAULT_TEST_CHARACTER)

    def run(self):
        DNAOneTimeTask.run(self)
        self.move_mouse_to_safe_position(save_current_pos=False)
        self.setup_character()
        self.reset_sequence_state()
        self.log_info_notify("角色循环测试已启动：请进入战斗")
        self.log_info("角色循环测试：%s" % self.current_character())
        if self.config.get("先锁定", True) and not self.plan_has_lock():
            self.log_info("先锁定目标（%s）" % self.get_lock_key())
            self.press_hotkey(self.get_lock_key())
            self.sleep(0.3)
        only_in_combat = bool(self.config.get("只在战斗中", True))
        try:
            while True:
                self.next_frame()
                if only_in_combat and not self.is_in_combat():
                    self.sleep(0.2)
                    continue
                self.play_character_sequence()
                self.sleep(0.05 if getattr(self, "charge_state", None) == "charging" else 0.2)
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error("CharacterRotationTestTask error", e)
            raise
