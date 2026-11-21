# -*- coding: utf-8 -*-
"""角色循环的通用执行器。

任务继承 `CharacterRotationMixin` 后，共享表里的任意循环都能直接跑：
  * `opening`：一段序列；`loop=True` 时整段循环，`False` 时放一遍就停。
  * `timed`：按真实时间插入的组（如每 1.4 秒一次终结技）。
  * `spam`：一直按的动作（如普攻）。
  * `charge_shot`：开镜自动蓄力，读百分比文字满 100% 按普攻（黎瑟SP）。

“只有 opening、没有 steps”的收尾就在这里：`loop=False` 且没有 timed/spam 时，
放完 opening 自然返回，任务不需要再各自写保护。
"""

import re
import time

import cv2

from src.char.CharacterRotation import CHARACTER_ROTATIONS


NO_CHARACTER = "无"
CUSTOM_CHARACTER = "自定义"
CUSTOM_SEQUENCE_KEY = "自定义序列"
DEFAULT_CUSTOM_SEQUENCE = "终结技:1"
CUSTOM_ACTIONS = {
    "战技": "短按战技",
    "短按战技": "短按战技",
    "长按战技": "长按战技",
    "终结技": "终结技",
    "魔灵支援": "魔灵支援",
    "普攻": "普攻",
    "重击": "重击",
    "锁定": "锁定",
}
COMBAT_LONG_PRESS = 1.0
HEAVY_ATTACK_HOLD = 1.5
TIMED_BURST_GAP = 0.1

# 黎瑟SP：准星下方的蓄力百分比文字（Defs.SCREEN_BOX.SYR_CHARGE_PERCENT）
CHARGE_PERCENT_BOX = 'SYR_CHARGE_PERCENT'
CHARGE_PERCENT_RE = re.compile(r'(\d{1,3})\s*%')
CHARGE_FULL_PERCENT = 100
CHARGE_CONFIRM_FRAMES = 1
CHARGE_OCR_INTERVAL = 0.1
CHARGE_TEXT_SCALE = 2
CHARGE_RECOVER_MIN = 0.1
# 前 3 发读百分比；之后固定 1.2 秒射一次，不再走 OCR
CHARGE_SHOTS_BEFORE_FIXED = 3
FIXED_FIRE_INTERVAL = 1.2


def charge_text_normalize(cv_image):
    """把蓄力百分比的小框放大后再 OCR（原生约 40×24，PP-OCR 会漏掉 100%）。"""
    return cv2.resize(cv_image, None, fx=CHARGE_TEXT_SCALE, fy=CHARGE_TEXT_SCALE,
                      interpolation=cv2.INTER_CUBIC)


class CharacterRotationMixin:
    """角色循环的执行逻辑；任务只需要设置配置键和共享表。"""

    # 默认值：任务没调 setup_character 时也不会 AttributeError
    character_opening = ()
    character_loop = False
    character_spam = None
    character_timed = ()
    charge_shot = False
    long_press = COMBAT_LONG_PRESS
    refresh_interval = 0.0
    geniemon_delay = 0.0
    character_reset_on_stage_switch = True
    fallback_skill_tick = None
    refresh_holding = False
    refresh_release_at = 0.0
    refresh_key = None

    # 配置里选角色的键名：大多数任务叫「主控角色」，迷津叫「使用角色」
    character_config_key = "主控角色"
    # 默认用完整共享表；任务可以覆盖成自己的子集
    rotation_table = CHARACTER_ROTATIONS
    # 永恒梦魇那套：timed 里的终结技组要先等一个周期，避免开场刚放完又立刻补
    delay_timed_ultimate = False

    def current_character(self):
        return self.config.get(self.character_config_key, NO_CHARACTER)

    def has_character_rotation(self):
        return bool(self.character_opening or self.character_spam is not None
                    or self.character_timed or self.charge_shot)

    def plan_has_lock(self):
        """这套手法里是不是自己带了「锁定」动作。"""
        actions = [action for action, _ in self.character_opening]
        if self.character_spam:
            actions.append(self.character_spam[0])
        for _, group in self.character_timed:
            actions += list(group)
        return "锁定" in actions

    def _clear_rotation(self):
        self.character_opening = ()
        self.character_loop = False
        self.character_spam = None
        self.character_timed = ()
        self.charge_shot = False
        self.long_press = COMBAT_LONG_PRESS
        self.refresh_interval = 0.0
        self.geniemon_delay = 0.0
        self.character_reset_on_stage_switch = True
        self.fallback_skill_tick = None

    def setup_character(self):
        """按配置里的角色名取循环；取不到就退回全局技能计时器。"""
        name = self.current_character()
        if name == CUSTOM_CHARACTER:
            steps = self.parse_custom_steps()
            if steps:
                self._clear_rotation()
                self.log_info("自定义技能序列: %s" % self.describe_steps(steps))
                self.character_opening = steps
                self.reset_sequence_state()
                return
            self.log_info("「%s」没解析出任何步骤，改用「%s」"
                          % (CUSTOM_SEQUENCE_KEY, NO_CHARACTER))
            name = NO_CHARACTER
        if name == NO_CHARACTER:
            self.log_info("主控角色「%s」：直接执行「全局技能设定」的技能配置" % NO_CHARACTER)
            self._clear_rotation()
            self.fallback_skill_tick = self.create_skill_ticker()
            self.reset_sequence_state()
            return
        rotation = self.rotation_table.get(name)
        if rotation is None:
            self.log_info("没有「%s」的技能手法，退回全局技能计时器" % name)
            self._clear_rotation()
            self.fallback_skill_tick = self.create_skill_ticker()
            self.reset_sequence_state()
            return

        self.character_opening = rotation.get("opening") or ()
        self.character_loop = bool(rotation.get("loop", False))
        spam = rotation.get("spam")
        self.character_spam = (spam, 0.0) if isinstance(spam, str) else spam
        self.character_timed = rotation.get("timed") or ()
        self.charge_shot = bool(rotation.get("charge_shot", False))
        self.long_press = float(rotation.get("long_press", COMBAT_LONG_PRESS))
        self.refresh_interval = float(rotation.get("refresh_interval", 0.0))
        self.geniemon_delay = float(rotation.get("geniemon_delay", 0.0))
        self.lock_settle = float(rotation.get("lock_settle",
                                             getattr(self, "LOCK_SETTLE", 1.5)))
        self.character_reset_on_stage_switch = bool(
            rotation.get("reset_on_stage_switch", True))
        self.fallback_skill_tick = None
        self.reset_sequence_state()

    def parse_custom_steps(self):
        """把「自定义序列」解析成 ((动作, 等待秒数), ...)。"""
        raw = str(self.config.get(CUSTOM_SEQUENCE_KEY, DEFAULT_CUSTOM_SEQUENCE) or "")
        steps = []
        for part in re.split(r"[,;，；、\n\r]+", raw):
            part = part.strip()
            if not part:
                continue
            action, _, wait_text = part.partition(":")
            action = CUSTOM_ACTIONS.get(action.strip())
            if action is None:
                self.log_info("自定义序列第 %d 步技能名不认识，已跳过: %s"
                              % (len(steps) + 1, part))
                continue
            try:
                wait = float(wait_text) if wait_text.strip() else 1.0
            except ValueError:
                wait = 1.0
            steps.append((action, max(0.0, wait)))
        return tuple(steps)

    def reset_sequence_state(self):
        """这一局的循环还没开始；清掉起手、计时和蓄力状态。"""
        if self.refresh_holding and self.refresh_key:
            try:
                self.hotkey_up(self.refresh_key)
            except Exception:
                pass
        self.opening_done = False
        self.sequence_done = False
        self.step_index = 0
        self.timed_next = []
        self.timed_started = False
        self.combat_t0 = None
        self.refresh_count = 0
        self.next_refresh_at = None
        self.next_geniemon_at = None
        self.geniemon_done = False
        self.charge_state = "idle"
        self.charge_full_frames = 0
        self.charge_started_at = 0.0
        self.last_charge_percent = None
        self.last_charge_ocr = 0.0
        self.charge_shots = 0
        self.fixed_fire_at = 0.0
        self.refresh_holding = False
        self.refresh_release_at = 0.0
        self.refresh_key = None

    def play_character_sequence(self):
        """一次主循环只推进一步；opening/timed/spam/蓄力都由这里统一处理。"""
        if not self.has_character_rotation():
            # 戏剧等任务自己有 self.skill_tick（测试也会替换它），优先用它；
            # 没有的任务再用 setup_character 建好的 fallback。
            tick = getattr(self, "skill_tick", None) or self.fallback_skill_tick
            if tick is not None:
                tick()
            return

        if not self.opening_done:
            self.opening_done = True
            if self.charge_shot and self.combat_t0 is None:
                self.combat_t0 = time.time()
                self.next_refresh_at = (self.combat_t0 + self.refresh_interval
                                        if self.refresh_interval > 0 else None)
                self.next_geniemon_at = (self.combat_t0 + self.geniemon_delay
                                         if self.geniemon_delay > 0 else None)
                self.refresh_count = 1
                self.geniemon_done = False
                self.log_info("黎瑟SP 时间轴：%.0f 秒后刷新战技，%.0f 秒后魔灵支援"
                              % (self.refresh_interval, self.geniemon_delay))
            # loop=True 的整段 opening 要一步一放，不能在这里先整段放完
            if self.character_opening and not self.character_loop:
                self.log_info("开场技能（只放一次）: %s" % self.describe_steps(self.character_opening))
                for action, wait in self.character_opening:
                    self.release_character_action(action)
                    self.sleep(wait)

        if self.charge_shot:
            self.tick_charge_shot()
            return

        if self.character_spam is not None or self.character_timed:
            self.play_timed_rotation()
            return

        if not self.character_opening or not self.character_loop:
            # 没有循环，或只有一次性 opening：放完就停；这里就是原来各任务里
            # “只有 opening、没有 steps”的返回保护，现在由共享执行器统一处理。
            return

        if not self.sequence_done:
            self.sequence_done = True
            self.log_info("开始循环「%s」技能手法: %s"
                          % (self.current_character(), self.describe_steps(self.character_opening)))
        action, wait = self.character_opening[self.step_index % len(self.character_opening)]
        self.step_index += 1
        self.log_info("循环技能第 %d 步: %s" % (self.step_index, action))
        self.release_character_action(action)
        self.sleep(wait)

    def play_timed_rotation(self):
        """按真实时间放技能（spam + timed）：一次调用最多做一件事。"""
        now = time.time()
        if not self.timed_started:
            self.timed_started = True
            self.timed_next = [
                now + (interval if self.delay_timed_ultimate and "终结技" in actions else 0.0)
                for interval, actions in self.character_timed
            ]
        for index, (interval, actions) in enumerate(self.character_timed):
            if now >= self.timed_next[index]:
                self.timed_next[index] = now + interval
                self.log_info("定时技能（每 %.1f 秒）: %s"
                              % (interval, " + ".join(actions)))
                for action in actions:
                    self.release_character_action(action)
                    self.sleep(TIMED_BURST_GAP)
                return
        if self.character_spam is None:
            self.sleep(0.05)
            return
        action, gap = self.character_spam
        self.release_character_action(action)
        if gap > 0:
            self.sleep(gap)

    def tick_charge_shot(self):
        """黎瑟SP：前 3 发读百分比；之后固定 1.2 秒射击，不再 OCR。"""
        now = time.time()

        # 非阻塞长按战技：到点松手，长按期间继续读百分比/射击
        if self.refresh_holding and now >= self.refresh_release_at:
            if self.refresh_key:
                self.hotkey_up(self.refresh_key)
            self.refresh_holding = False
            self.refresh_key = None
            self.refresh_release_at = 0.0

        # 3 发之后：固定 1.2 秒射击，不读百分比
        if self.charge_state == "fixed_fire":
            if now >= self.fixed_fire_at:
                self.log_info("固定射击（每 %.1f 秒，不再 OCR）" % FIXED_FIRE_INTERVAL)
                self.release_character_action("普攻")
                self.fixed_fire_at = now + FIXED_FIRE_INTERVAL
                return
            # 没到点，继续处理下面的刷新/支援

        if self.charge_state == "idle":
            self.charge_state = "charging"
            self.charge_full_frames = 0
            self.charge_started_at = now
            self.last_charge_percent = None
            self.last_charge_ocr = 0.0
            return

        if self.charge_state == "charging":
            if self.last_charge_ocr == 0.0:
                # 起手会阻塞零点几秒，先取一张新帧再读百分比
                self.next_frame()
            if now - self.last_charge_ocr < CHARGE_OCR_INTERVAL:
                return
            self.last_charge_ocr = now
            percent = self.read_charge_percent()
            if percent is None:
                self.charge_full_frames = 0
                self.last_charge_percent = None
            else:
                if (self.last_charge_percent is None
                        or percent != self.last_charge_percent):
                    if (self.last_charge_percent is None
                            or percent % 10 == 0 or percent >= CHARGE_FULL_PERCENT):
                        self.log_info("蓄力百分比：%d%%" % percent)
                    self.last_charge_percent = percent
                if percent >= CHARGE_FULL_PERCENT:
                    self.charge_full_frames += 1
                else:
                    self.charge_full_frames = 0
                if self.charge_full_frames >= CHARGE_CONFIRM_FRAMES:
                    self.log_info("蓄力已满（%d%%），按普攻键射击（%s）"
                                  % (percent, self.get_normal_attack_key()))
                    self.release_character_action("普攻")
                    self.charge_shots += 1
                    if self.charge_shots >= CHARGE_SHOTS_BEFORE_FIXED:
                        self.log_info("已射击 %d 次，转入固定 %.1f 秒射击（不再 OCR）"
                                      % (self.charge_shots, FIXED_FIRE_INTERVAL))
                        self.charge_state = "fixed_fire"
                        self.fixed_fire_at = now + FIXED_FIRE_INTERVAL
                    else:
                        self.charge_state = "recover"
                        self.charge_started_at = now
                    self.charge_full_frames = 0
                    self.last_charge_percent = None
                    return

        # 刷新/支援：不打断蓄力；放在射击判断之后，满蓄时先射击
        if (not self.geniemon_done and self.next_geniemon_at is not None
                and now >= self.next_geniemon_at):
            self.geniemon_done = True
            self.log_info("开局 %.0f 秒，使用魔灵支援（键 %s）"
                          % (self.geniemon_delay, self.get_geniemon_key()))
            self.release_character_action("魔灵支援")
            return

        if (self.refresh_interval > 0 and self.next_refresh_at is not None
                and now >= self.next_refresh_at):
            # 固定射击马上到点时先不刷新，避免 0.4 秒长按把射击点盖过去
            if (self.charge_state == "fixed_fire"
                    and 0 <= self.fixed_fire_at - now <= 0.6):
                return
            self.do_charge_refresh()
            self.next_refresh_at += self.refresh_interval
            if self.next_refresh_at <= now:
                self.next_refresh_at = now + self.refresh_interval
            return

        if self.charge_state != "recover":
            return

        if now - self.charge_started_at < CHARGE_RECOVER_MIN:
            return
        self.charge_state = "idle"

    def do_charge_refresh(self):
        """按 refresh_interval 刷新；长按不阻塞主循环，到点再松手。"""
        if self.refresh_holding:
            return
        self.refresh_count += 1
        self.log_info("刷新战技（第 %d 次，按住 %.1f 秒）"
                      % (self.refresh_count, self.long_press))
        key = self.get_combat_key()
        self.hotkey_down(key)
        self.refresh_holding = True
        self.refresh_key = key
        self.refresh_release_at = time.time() + self.long_press

    def read_charge_percent(self):
        """读准星下方的蓄力百分比；读不到返回 None。"""
        try:
            texts = self.ocr(box=self.screen_box(CHARGE_PERCENT_BOX),
                             frame=self.frame, frame_processor=charge_text_normalize)
        except Exception as e:
            self.log_warning("蓄力百分比 OCR 失败: %s" % e)
            return None
        if not texts:
            return None
        raw = "".join((getattr(box, "name", "") or "") for box in texts)
        raw = raw.replace(" ", "")
        raw = raw.replace("O", "0").replace("l", "1").replace("I", "1")
        raw = raw.replace("％", "%")
        match = CHARGE_PERCENT_RE.search(raw) or re.search(r'(?<!\d)(\d{2,3})(?!\d)', raw)
        if not match:
            return None
        try:
            value = int(match.group(1))
        except (TypeError, ValueError):
            return None
        return value if 0 <= value <= 100 else None

    def describe_steps(self, steps=None):
        steps = self.character_opening if steps is None else steps
        return " -> ".join("%s后等%.1f秒" % (action, wait) for action, wait in steps)

    def release_character_action(self, action):
        """按一次角色序列里的动作；键值取「游戏快捷键设置」。"""
        if action == "长按战技":
            self.log_info("放技能: 长按战技（键 %s，按住 %.1f 秒）"
                          % (self.get_combat_key(), self.long_press))
            self.send_key(self.get_combat_key(), down_time=self.long_press)
        elif action == "短按战技":
            self.log_info("放技能: 短按战技（键 %s）" % self.get_combat_key())
            self.send_key(self.get_combat_key())
        elif action == "终结技":
            self.log_info("放技能: 终结技（键 %s）" % self.get_ultimate_key())
            self.send_key(self.get_ultimate_key())
        elif action == "魔灵支援":
            self.log_info("放技能: 魔灵支援（键 %s）" % self.get_geniemon_key())
            self.send_key(self.get_geniemon_key())
        elif action == "普攻":
            self.log_info("放技能: 普攻（键 %s）" % self.get_normal_attack_key())
            self.press_hotkey(self.get_normal_attack_key())
        elif action == "锁定":
            self.log_info("锁定目标（键 %s）" % self.get_lock_key())
            self.press_hotkey(self.get_lock_key())
        elif action == "重击":
            self.log_info("放技能: 重击（按住 %.1f 秒）" % HEAVY_ATTACK_HOLD)
            self.mouse_down()
            try:
                self.sleep(HEAVY_ATTACK_HOLD)
            finally:
                self.mouse_up()
        else:
            raise ValueError("未知技能动作: %s" % action)
