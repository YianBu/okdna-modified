import asyncio
import threading
import time

import win32api
import win32gui

from ok.device.interaction_methods.base import BaseInteraction
from ok.util.logger import Logger

logger = Logger.get_logger(__name__)

class BrowserInteraction(BaseInteraction):
    def __init__(self, capture):
        super().__init__(capture)
        # We don't access self.page directly for calls, we go through capture.run_in_loop
        self._held_keys = set()
        self._was_pointer_locked = False
        self._modifier_stop = threading.Event()
        self._modifier_thread = threading.Thread(
            target=self._watch_modifiers, daemon=True, name="BrowserModifierWatchdog")
        self._modifier_thread.start()
        logger.info('Browser modifier watchdog started')
        self.key_map = {
            "esc": "Escape",
            "return": "Enter",
            "enter": "Enter",
            "space": "Space",
            "backspace": "Backspace",
            "tab": "Tab",
            "left": "ArrowLeft",
            "right": "ArrowRight",
            "up": "ArrowUp",
            "down": "ArrowDown",
            "win": "Meta",
            "windows": "Meta",
            "command": "Meta",
            "cmd": "Meta",
            "cmd_l": "MetaLeft",
            "cmd_r": "MetaRight",
            "meta": "Meta",
            "alt": "Alt",
            "lalt": "Alt",
            "ralt": "Alt",
            "alt_l": "AltLeft",
            "alt_r": "AltRight",
            "alt_gr": "AltRight",
            "ctrl": "Control",
            "control": "Control",
            "lctrl": "Control",
            "rctrl": "Control",
            "lcontrol": "Control",
            "rcontrol": "Control",
            "ctrl_l": "ControlLeft",
            "ctrl_r": "ControlRight",
            "shift": "Shift",
            "lshift": "ShiftLeft",
            "rshift": "Shift",
            "shift_l": "ShiftLeft",
            "shift_r": "ShiftRight",
            "pageup": "PageUp",
            "pagedown": "PageDown",
            "page_up": "PageUp",
            "page_down": "PageDown",
            "capslock": "CapsLock",
            "caps_lock": "CapsLock",
            "numlock": "NumLock",
            "num_lock": "NumLock",
            "scrolllock": "ScrollLock",
            "scroll_lock": "ScrollLock",
            "printscreen": "PrintScreen",
            "print_screen": "PrintScreen",
            "delete": "Delete",
            "insert": "Insert",
            "home": "Home",
            "end": "End",
        }

    def _map_key(self, key):
        key_str = str(key).lower()
        if len(key_str) == 1:
            return key_str
        return self.key_map.get(key_str, key_str.title())

    def _run_action(self, action_coro):
        """Helper to run action on the capture's loop."""
        if hasattr(self.capture, 'run_in_loop'):
            self.capture.run_in_loop(action_coro)

    # Physical modifier keys -> Playwright key names. The cloud game forwards
    # local key events to the remote game, so a missing keyup leaves the remote
    # game (not just the page) thinking the modifier is still held.
    MODIFIER_VK = (
        (0x12, "Alt"),      # VK_MENU
        (0x11, "Control"),  # VK_CONTROL
        (0x10, "Shift"),    # VK_SHIFT
        (0x5B, "Meta"),     # VK_LWIN
        (0x5C, "Meta"),     # VK_RWIN
    )

    MODIFIER_KEYS = {
        "Alt": ("Alt", "AltLeft", "AltRight"),
        "Control": ("Control", "ControlLeft", "ControlRight"),
        "Shift": ("Shift", "ShiftLeft", "ShiftRight"),
        "Meta": ("Meta", "MetaLeft", "MetaRight"),
    }

    def _modifier_held(self, mapped):
        return any(key in self._held_keys for key in self.MODIFIER_KEYS.get(mapped, (mapped,)))

    def _watch_modifiers(self):
        """Keep page/keyboard state in sync without touching window focus.

        Sends a missing keyup when a physical modifier is released (Alt+Tab
        splits keydown/keyup across windows), releases real pointer lock when
        the Edge window goes to the background, and requests pointer lock again
        when the user brings the game back, so hovering back does not leave the
        running task waiting for a manual click.
        """
        previous = {}
        was_foreground = None
        while not self._modifier_stop.is_set():
            try:
                exit_event = getattr(self.capture, 'exit_event', None)
                if exit_event is not None and exit_event.is_set():
                    break
                if getattr(self.capture, 'page', None) is None:
                    previous.clear()
                    was_foreground = None
                    time.sleep(0.1)
                    continue
                hwnd = getattr(self.capture, 'hwnd', 0)
                if hwnd:
                    is_foreground = win32gui.GetForegroundWindow() == hwnd
                    if was_foreground is False and is_foreground:
                        if self._was_pointer_locked:
                            logger.debug('Cloud game foreground: reacquiring pointer lock')
                            self.reacquire_pointer_lock()
                        self._was_pointer_locked = False
                    elif was_foreground is True and not is_foreground:
                        # Focus emulation keeps the page "focused"; release real
                        # pointer lock so the OS cursor is usable in other apps.
                        logger.debug('Cloud game background: releasing pointer lock')
                        self._was_pointer_locked = (
                            self.exit_pointer_lock() or self.recently_pointer_locked())
                    was_foreground = is_foreground
                for vk, mapped in self.MODIFIER_VK:
                    down = bool(win32api.GetAsyncKeyState(vk) & 0x8000)
                    was_down = previous.get(vk, False)
                    previous[vk] = down
                    if was_down and not down and not self._modifier_held(mapped):
                        self._send_modifier_up(mapped)
            except Exception as e:
                logger.debug(f'Browser modifier watchdog failed: {e}')
            time.sleep(0.05)

    def _send_modifier_up(self, mapped):
        logger.debug(f'Browser modifier watchdog keyup {mapped}')

        async def _act():
            for key in self.MODIFIER_KEYS.get(mapped, (mapped,)):
                try:
                    await self.capture.page.keyboard.up(key)
                except Exception as e:
                    logger.debug(f'Browser modifier keyup {key} failed: {e}')

        self._run_action(_act())

    def release_modifiers(self, only_unheld=False):
        """Clear modifier state in the page without touching window focus."""
        async def _act():
            for mapped in ("Alt", "Control", "Shift", "Meta"):
                if only_unheld and self._modifier_held(mapped):
                    continue
                for key in self.MODIFIER_KEYS[mapped]:
                    try:
                        await self.capture.page.keyboard.up(key)
                    except Exception as e:
                        logger.debug(f'Browser modifier keyup {key} failed: {e}')

        self._run_action(_act())

    def exit_pointer_lock(self):
        """Release real pointer lock; return whether it was locked."""
        async def _act():
            try:
                locked = bool(await self.capture.page.evaluate(
                    "() => !!document.pointerLockElement"))
                if not locked:
                    return False
                await self.capture.page.evaluate(
                    "() => {"
                    "  if (document.pointerLockElement) {"
                    "    try { document.exitPointerLock(); } catch (e) {}"
                    "  }"
                    "}")
                await asyncio.sleep(0.1)
                return locked
            except Exception as e:
                logger.debug(f'Browser exit pointer lock failed: {e}')
                return False

        return bool(self._run_action(_act()))

    def reacquire_pointer_lock(self):
        """Re-lock the mouse when the user brings the cloud game back.

        Requesting pointer lock in the page avoids a manual click. If the
        browser still refuses it, one centre click is used as the same fallback
        the user would do by hand. The Edge window is already foreground here;
        this never activates or raises it.
        """
        try:
            from ok import og
            if og.executor is None or og.executor.current_task is None:
                return
        except Exception:
            pass

        async def _act():
            page = self.capture.page
            try:
                if await page.evaluate("() => !!document.pointerLockElement"):
                    return
                cdp = getattr(self.capture, '_focus_cdp', None)
                if cdp is None or getattr(self.capture, '_focus_cdp_page', None) is not page:
                    cdp = await page.context.new_cdp_session(page)
                    self.capture._focus_cdp = cdp
                    self.capture._focus_cdp_page = page
                await cdp.send('Runtime.evaluate', {
                    'expression': (
                        "(() => {"
                        "  const el = document.querySelector('canvas, video');"
                        "  if (!el) return false;"
                        "  const p = el.requestPointerLock();"
                        "  if (p && p.catch) p.catch(() => {});"
                        "  return true;"
                        "})()"
                    ),
                    'userGesture': True,
                    'awaitPromise': False,
                })
                await asyncio.sleep(0.15)
                if await page.evaluate("() => !!document.pointerLockElement"):
                    return
                size = await page.evaluate("() => [window.innerWidth, window.innerHeight]")
                await page.mouse.click(int(size[0] / 2), int(size[1] / 2))
            except Exception as e:
                logger.debug(f'Browser reacquire pointer lock failed: {e}')

        self._run_action(_act())

    def recently_pointer_locked(self, seconds=60):
        """Whether the page had real pointer lock within the last N seconds."""
        async def _act():
            try:
                locked_at = await self.capture.page.evaluate(
                    "() => window.__okPointerLockedAt || 0")
                return bool(locked_at) and (time.time() * 1000 - locked_at) <= seconds * 1000
            except Exception as e:
                logger.debug(f'Browser pointer lock timestamp failed: {e}')
                return False

        return bool(self._run_action(_act()))

    def on_destroy(self):
        self._modifier_stop.set()
        super().on_destroy()

    def focus_page(self):
        """让云游戏页面拿到键盘焦点（页面级，不切窗口）。

        浏览器窗口在后台时，Chromium 可能不把 Esc 交给网页，表现就是
        「任务发了 ESC，但游戏里的退本菜单打不开」。这里只做页面级处理：
        开启焦点模拟、调用 window.focus；不 bring_to_front，避免把浏览器
        窗口拉到前台、切走用户正在用的桌面。只在任务需要点画面取焦点时调用，
        不参与任务启动流程。
        """

        async def _act():
            try:
                page = self.capture.page
                cdp = getattr(self.capture, '_focus_cdp', None)
                if cdp is None or getattr(self.capture, '_focus_cdp_page', None) is not page:
                    cdp = await asyncio.wait_for(page.context.new_cdp_session(page), timeout=2)
                    self.capture._focus_cdp = cdp
                    self.capture._focus_cdp_page = page
                await asyncio.wait_for(
                    cdp.send('Emulation.setFocusEmulationEnabled', {'enabled': True}), timeout=2)
            except Exception as e:
                logger.debug(f'BrowserInteraction focus emulation failed: {e}')
            try:
                await asyncio.wait_for(
                    self.capture.page.evaluate(
                        "() => {"
                        "  try { window.focus(); } catch (e) {}"
                        "}"), timeout=2)
            except Exception as e:
                logger.debug(f'BrowserInteraction page focus failed: {e}')

        self._run_action(_act())

    def send_key(self, key, down_time=0.02):
        mapped_key = self._map_key(key)
        logger.debug(f'BrowserInteraction send_key {key}')

        async def _act():
            await self.capture.page.keyboard.press(mapped_key, delay=down_time * 1000)

        self._run_action(_act())

    def send_key_down(self, key):
        mapped_key = self._map_key(key)
        self._held_keys.add(mapped_key)

        async def _act():
            try:
                await self.capture.page.keyboard.down(mapped_key)
            except Exception:
                self._held_keys.discard(mapped_key)
                raise

        self._run_action(_act())

    def send_key_up(self, key):
        mapped_key = self._map_key(key)
        self._held_keys.discard(mapped_key)

        async def _act():
            await self.capture.page.keyboard.up(mapped_key)

        self._run_action(_act())

    def mouse_down(self, x=-1, y=-1, name=None, key="left"):
        button = "left"
        if key == "right":
            button = "right"
        elif key == "middle":
            button = "middle"

        async def _act():
            if x != -1 and y != -1:
                await self.capture.page.mouse.move(x, y)
            await self.capture.page.mouse.down(button=button)

        self._run_action(_act())

    def mouse_up(self, key="left"):
        button = "left"
        if key == "right":
            button = "right"
        elif key == "middle":
            button = "middle"

        async def _act():
            await self.capture.page.mouse.up(button=button)

        self._run_action(_act())

    def move(self, x, y):
        async def _act():
            await self.capture.page.mouse.move(x, y)

        self._run_action(_act())

    def scroll(self, x, y, scroll_amount):
        pixel_amount = scroll_amount * 100 * -1

        async def _act():
            if x != -1 and y != -1:
                await self.capture.page.mouse.move(x, y)
            await self.capture.page.mouse.wheel(0, pixel_amount)

        self._run_action(_act())
        time.sleep(0.02)

    def click(self, x=-1, y=-1, move_back=False, name=None, down_time=0.01, move=True, key="left"):
        # BaseInteraction logic skipped as we need specific async handling
        button = "left"
        if key == "right":
            button = "right"
        elif key == "middle":
            button = "middle"

        async def _act():
            if x != -1 and y != -1:
                await self.capture.page.mouse.click(x, y, button=button, delay=down_time * 1000)
            else:
                await self.capture.page.mouse.down(button=button)
                await asyncio.sleep(down_time)
                await self.capture.page.mouse.up(button=button)

        self._run_action(_act())

    def input_text(self, text):
        async def _act():
            await self.capture.page.keyboard.type(text)

        self._run_action(_act())

    def swipe(self, x1, y1, x2, y2, duration, settle_time=0):
        async def _act():
            await self.capture.page.mouse.move(x1, y1)
            await self.capture.page.mouse.down()

            steps = max(int(duration / 20), 5)
            dx = (x2 - x1) / steps
            dy = (y2 - y1) / steps

            for i in range(steps):
                await self.capture.page.mouse.move(x1 + dx * i, y1 + dy * i)
                await asyncio.sleep(duration / 1000 / steps)

            await self.capture.page.mouse.move(x2, y2)
            if settle_time > 0:
                await asyncio.sleep(settle_time)
            await self.capture.page.mouse.up()

        self._run_action(_act())
