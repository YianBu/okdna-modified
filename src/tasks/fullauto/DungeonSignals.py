import re


# 左侧目标栏「保护XX波次 x/y」那一行：不同防御副本的保护对象、总波次数都不一样，
# 所以只认「波次 x/y」这个计数本身，不写死名字和数字。
TARGET_WAVE_PATTERN = re.compile(r"波次\s*\d+\s*/\s*\d+")


class DungeonSignalsMixin:
    """扼守 / 探险共用的开战判据。

    这两个判据原本分别写在「自动扼守」「自动探险」任务类里；现在直接放在
    mixin 上，供全自动任务和「自动开密函」「行动逻辑测试」共用。
    """

    def find_target_wave(self):
        """左侧目标栏里「保护…波次 x/y」那一行的判据（刚进本时这一行还不存在）。"""
        return self.ocr(box=self.screen_box('DEFENCE_TARGET_WAVE'), match=TARGET_WAVE_PATTERN)

    def find_serum(self):
        """局内左侧的「血清水滴」图标：探险类副本进战斗后才出现。"""
        box = self.screen_box('SERUM_ICON')
        if self.width < 1920 and self.height < 1080:
            threshold = 0.7
        else:
            threshold = 0
        return bool(self.find_one("serum_icon", box=box, threshold=threshold))
