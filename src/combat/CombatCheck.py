import time
from ok import og
from src.tasks.BaseDNATask import BaseDNATask

class CombatCheck(BaseDNATask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._in_combat = False
        self.last_combat_check = 0
        self.combat_check_interval = 0.5
        self.out_of_combat_reason = ""
        self.manual_in_combat = False

    def in_combat(self):
        """检查当前是否处于战斗状态。

        Returns:
            bool: 如果处于战斗状态则返回True，否则返回False。
        """
        if self._in_combat:
            now = time.time()
            if now - self.last_combat_check > self.combat_check_interval:
                in_combat = self.manual_in_combat and og.device_manager.hwnd_window.is_foreground()
                self.last_combat_check = now
                if in_combat:
                    return True
                return self.reset_to_false(recheck=True, reason='on user stop')
            return True
        else:
            in_combat = self.manual_in_combat and og.device_manager.hwnd_window.is_foreground()
            if in_combat:
                self._in_combat = True
            else:
                self.reset_to_false(recheck=True, reason='on user stop')
        return self._in_combat
    
    def reset_to_false(self, recheck=False, reason=""):
        self.out_of_combat_reason = reason
        self.do_reset_to_false()
        return False
    
    def do_reset_to_false(self):
        self._in_combat = False
        self.manual_in_combat = False
