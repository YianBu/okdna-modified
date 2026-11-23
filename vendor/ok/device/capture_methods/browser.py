import asyncio
import ctypes
import os
import re
import threading
from ctypes import wintypes

import win32con
import win32gui

from ok.core.events import communicate
from ok.task.exceptions import CaptureException
from ok.util.logger import Logger
from ok.util.window import DWMWA_EXTENDED_FRAME_BOUNDS, windows_graphics_available, find_hwnd

from ok.device.capture_methods.base import BaseCaptureMethod
from ok.device.capture_methods.windows_graphics import WindowsGraphicsCaptureMethod

logger = Logger.get_logger(__name__)

# Pages ask for pointer lock on mouse down (e.g. cloud game SDKs). The automated browser window is
# usually not the OS foreground window, so Chromium rejects the lock (pointerlockerror) and such pages
# fall back to cursor mode, drop the click or send Esc. Fake a granted lock; pages still release it
# through exitPointerLock exactly as with a real lock. Disable with browser config 'fake_pointer_lock': False.
FAKE_POINTER_LOCK_JS = '''() => {
  if (window.__okFakePointerLock === undefined) {
    window.__okFakePointerLock = null;
    Object.defineProperty(Document.prototype, 'pointerLockElement', {configurable: true,
      get() { return window.__okFakePointerLock; }});
    window.__okRequestPointerLock = function () {
      if (window.__okFakePointerLock !== this) {
        window.__okFakePointerLock = this;
        document.dispatchEvent(new Event('pointerlockchange'));
      }
      return Promise.resolve();
    };
    Element.prototype.requestPointerLock = window.__okRequestPointerLock;
    Document.prototype.exitPointerLock = function () {
      if (window.__okFakePointerLock) {
        window.__okFakePointerLock = null;
        document.dispatchEvent(new Event('pointerlockchange'));
      }
    };
  }
  // Already loaded pages may have cached the native function on the element itself.
  for (const el of document.querySelectorAll('video, canvas')) {
    if (Object.prototype.hasOwnProperty.call(el, 'requestPointerLock')) {
      el.requestPointerLock = window.__okRequestPointerLock;
    }
  }
  return true;
}'''


# Cloud games call navigator.keyboard.lock() while pointer lock is active. That is what makes
# Alt+Tab / Win / Ctrl disappear into the page until the browser chrome gets focus. Report the
# lock as granted, but leave the real keyboard with Windows. Disable with browser config
# 'fake_keyboard_lock': False.
FAKE_KEYBOARD_LOCK_JS = '''() => {
  const patch = (obj, name, value) => {
    try {
      Object.defineProperty(obj, name, {configurable: true, writable: true, value});
      return true;
    } catch (e) {
      try { obj[name] = value; return true; } catch (e2) { return false; }
    }
  };
  const apply = () => {
    const kb = navigator.keyboard;
    if (!kb) return false;
    const proto = Object.getPrototypeOf(kb) ||
      (typeof Keyboard !== 'undefined' ? Keyboard.prototype : null);
    if (!proto) return false;
    // A reused page may already hold a real lock; release it before faking
    // the API so the first Alt+Tab is not still captured.
    try { if (typeof kb.unlock === 'function') kb.unlock(); } catch (e) {}
    if (!window.__okFakeKeyboardLock) {
      window.__okFakeKeyboardLock = true;
      const realGetLayoutMap = typeof kb.getLayoutMap === 'function'
        ? kb.getLayoutMap.bind(kb) : null;
      patch(proto, 'lock', function () { return Promise.resolve(); });
      patch(proto, 'unlock', function () {});
      if (realGetLayoutMap) {
        patch(proto, 'getLayoutMap', function () { return realGetLayoutMap(); });
      }
      patch(kb, 'lock', function () { return Promise.resolve(); });
      patch(kb, 'unlock', function () {});
    }
    return true;
  };
  if (!apply() && document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', apply, {once: true});
  }
  return true;
}'''


# Remember when the page last had real pointer lock. Chromium may release it
# synchronously when the window loses focus, before the outer watchdog can
# observe it; this timestamp lets the watchdog still resume the game on return.
POINTER_LOCK_TRACKER_JS = '''() => {
  if (!window.__okPointerLockTracker) {
    window.__okPointerLockTracker = true;
    window.__okPointerLockedAt = document.pointerLockElement ? Date.now() : 0;
    document.addEventListener('pointerlockchange', () => {
      if (document.pointerLockElement) window.__okPointerLockedAt = Date.now();
    }, true);
  }
  return true;
}'''


class BrowserCaptureMethod(BaseCaptureMethod):
    name = "Browser Capture"
    description = "Capture from Browser using Playwright and Windows Graphics Capture"

    def __init__(self, config, exit_event, global_config=None):
        super().__init__()
        self.config = config
        self.exit_event = exit_event
        self.global_config = global_config
        self._audio_mute = None
        res = config.get('resolution', (1280, 720))
        self._size = (res[0], res[1])
        logger.info(f'BrowserCaptureMethod init {self._size}')
        self.playwright = None
        self.browser = None
        self.page = None
        self.latest_frame = None
        self.wgc_capture = None
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._start_loop, daemon=True, name="PlaywrightLoop")
        self.loop_thread.start()

        self.hwnd = 0
        self.x_offset = 0
        self.y_offset = 0
        self.last_width = 0
        self.last_height = 0
        self.last_hwnd = 0
        self.exe_full_path = None

    def _start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_in_loop(self, coro):
        if self.loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            try:
                return future.result()
            except Exception as e:
                logger.error(f"Playwright execution error: {e}")
        return None

    async def _start_browser_async(self):
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()

        width, height = self._size


        disable_features = ["CalculateNativeWinOcclusion"]

        args = [
            f"--window-size={width},{height}",
            "--force-device-scale-factor=1",
            "--high-dpi-support=1",
            "--disable-infobars",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
        ]


        args.append(f"--disable-features={','.join(disable_features)}")
        args.extend(self.config.get('args', []))

        user_data_dir = os.path.join('cache', 'playwright')

        channels = self.config.get('channels', ['msedge', 'chrome', 'chromium'])
        for channel in channels:
            try:
                logger.info(f'Attempting to launch persistent context with channel: {channel}')
                self.browser = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel=channel,
                    headless=False,
                    args=args,
                    viewport={'width': width, 'height': height},
                    device_scale_factor=1
                )
                logger.info(f'Successfully launched {channel}')
                break
            except Exception as e:
                logger.warning(f"Failed to launch {channel}: {e}")

        if self.browser is None:
            raise Exception("Failed to launch system browser.")

        fake_pointer_lock = self.config.get('fake_pointer_lock', True)
        if fake_pointer_lock:
            await self.browser.add_init_script(script=f'({FAKE_POINTER_LOCK_JS})()')

        fake_keyboard_lock = self.config.get('fake_keyboard_lock', True)
        if fake_keyboard_lock:
            await self.browser.add_init_script(script=f'({FAKE_KEYBOARD_LOCK_JS})()')

        await asyncio.sleep(0.1)

        self.page = None
        url = self.config.get('url')

        if len(self.browser.pages) > 1:
            for p in self.browser.pages:
                if p.url == "about:blank":
                    try:
                        await p.close()
                    except:
                        pass

        if url:
            for p in self.browser.pages:
                logger.debug(f'BrowserCaptureMethod checking page: {p.url}')
                if p.url.rstrip('/') == url.rstrip('/'):
                    self.page = p
                    logger.info(f'Reusing existing page with URL: {p.url}')
                    break

        if self.page is None:
            if self.browser.pages:
                self.page = self.browser.pages[0]
            else:
                self.page = await self.browser.new_page()

            if url:
                try:
                    await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
                except Exception as error:
                    # Cloud-game pages can keep loading past Playwright's 30s
                    # navigation timeout. The page and window are still usable;
                    # continue with window discovery instead of aborting capture.
                    logger.warning(f'BrowserCaptureMethod page.goto failed, continuing: {error}')

        if fake_pointer_lock:
            # A reused page loaded before the init script was registered.
            await self.page.evaluate(FAKE_POINTER_LOCK_JS)

        if fake_keyboard_lock:
            # A reused page may already have called navigator.keyboard.lock().
            await self.page.evaluate(FAKE_KEYBOARD_LOCK_JS)
            logger.info('Browser keyboard lock disabled (system shortcuts stay with Windows)')

        await self._attach_browser_window_async()

    async def _enable_page_focus(self):
        """Let the page act focused while its Edge window stays in the background.

        The cloud game forwards key events to the remote game only while it
        believes the page is focused. CDP focus emulation gives it that state
        without calling bring_to_front/SetForegroundWindow, so the user's
        current foreground app is never disturbed.
        """
        page = self.page
        if page is None:
            return
        try:
            cdp = getattr(self, '_focus_cdp', None)
            if cdp is None or getattr(self, '_focus_cdp_page', None) is not page:
                cdp = await page.context.new_cdp_session(page)
                self._focus_cdp = cdp
                self._focus_cdp_page = page
            await cdp.send('Emulation.setFocusEmulationEnabled', {'enabled': True})
            try:
                await cdp.send('Page.setWebLifecycleState', {'state': 'active'})
            except Exception as e:
                logger.debug(f'Browser page lifecycle active failed: {e}')
            logger.info('Browser page focus emulation enabled (background input)')
        except Exception as e:
            logger.warning(f'Browser page focus emulation failed: {e}')
        try:
            await page.evaluate(POINTER_LOCK_TRACKER_JS)
        except Exception as e:
            logger.debug(f'Browser pointer lock tracker failed: {e}')

    async def _attach_browser_window_async(self):
        width, height = self._size
        await self.page.bring_to_front()
        await self.page.set_viewport_size({'width': width, 'height': height})
        await self._enable_page_focus()

        for p in self.browser.pages:
            if p != self.page:
                try:
                    await p.close()
                except:
                    pass

        logger.info(f'BrowserCaptureMethod attach browser window {width, height}')

        for _ in range(20):
            try:
                target_title = await self.page.title()
            except Exception as error:
                logger.debug(f'BrowserCaptureMethod page.title failed: {error}')
                target_title = ''
            if target_title:
                title_pattern = re.compile(re.escape(target_title))
                res = find_hwnd(title_pattern, ['chrome.exe', 'msedge.exe', 'chromium.exe'], width, height)
            else:
                res = (None, 0, None, 0, 0, 0, 0, [])
            if res[1] <= 0:
                # Titles from cloud pages may be blank while loading. Fall back
                # to the largest Chromium window so WGC capture can still attach.
                res = find_hwnd(None, ['chrome.exe', 'msedge.exe', 'chromium.exe'], width, height)
            if res[1] > 0:
                self.hwnd = res[1]
                self.exe_full_path = res[2]
                self.x_offset = res[3]
                self.y_offset = res[4]

                if not self.update_window_geometry():
                    await asyncio.sleep(0.1)
                    continue

                logger.info(
                    f"Browser window found: {self.hwnd} offsets: {self.x_offset},{self.y_offset} size: {self._size}")
                self.wgc_capture = BrowserWGC(self)
                if getattr(self, 'global_config', None) is not None:
                    from ok.device.browser_audio import BrowserAudioMute
                    self._audio_mute = BrowserAudioMute(
                        self.page,
                        lambda: win32gui.GetForegroundWindow() == self.hwnd,
                        lambda: self.global_config.get_config('Basic Options').get(
                            'Mute Game while in Background'), self.exit_event)
                    self._audio_mute.start()
                return
            await asyncio.sleep(0.5)
        logger.warning('BrowserCaptureMethod could not attach to a Chromium window')

    def get_viewport_rect(self):
        """Return the visible page renderer's bounds in screen coordinates."""
        rects = []

        def collect(hwnd, _):
            if (win32gui.IsWindowVisible(hwnd)
                    and win32gui.GetClassName(hwnd) == 'Chrome_RenderWidgetHostHWND'):
                left, top, right, bottom = win32gui.GetClientRect(hwnd)
                if right > left and bottom > top:
                    x, y = win32gui.ClientToScreen(hwnd, (left, top))
                    rects.append((x, y, x + right - left, y + bottom - top))
            return True

        win32gui.EnumChildWindows(self.hwnd, collect, None)
        return max(rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), default=None)

    def update_window_geometry(self):
        viewport = self.get_viewport_rect()
        if viewport is None:
            return False
        client_x, client_y = win32gui.ClientToScreen(self.hwnd, (0, 0))
        _, _, client_w, client_h = win32gui.GetClientRect(self.hwnd)
        self.x_offset = viewport[0] - client_x
        self.y_offset = viewport[1] - client_y
        width, height = self._size
        # Playwright's fixed viewport can extend below the native window when
        # Chromium displays an infobar. Grow the window instead of losing pixels.
        missing_w = max(0, self.x_offset + width - client_w)
        missing_h = max(0, self.y_offset + height - client_h)
        if missing_w or missing_h:
            left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
            win32gui.SetWindowPos(self.hwnd, 0, 0, 0,
                                 right - left + missing_w, bottom - top + missing_h,
                                 win32con.SWP_NOMOVE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
            return False
        return True

    async def _close_async(self):
        logger.info(f'BrowserCaptureMethod _close_async')
        if getattr(self, '_audio_mute', None) is not None:
            await self._audio_mute.close()
            self._audio_mute = None
        if self.page:
            try:
                await self.page.close()
            except:
                pass
        if self.browser:
            try:
                await self.browser.close()
            except:
                pass
        if self.playwright:
            try:
                await self.playwright.stop()
            except:
                pass

    def start_browser(self):
        if not windows_graphics_available():
            raise CaptureException("Windows Graphics Capture is not supported on this system.")
        if self.page is not None and not self.page.is_closed():
            if self.wgc_capture is not None and self.hwnd > 0:
                return
            self.run_in_loop(self._attach_browser_window_async())
            return
        self.run_in_loop(self._start_browser_async())

    def close(self):
        logger.info(f'BrowserCaptureMethod close browser')
        if self.wgc_capture:
            self.wgc_capture.close()
            self.wgc_capture = None

        if self.loop.is_running():
            self.run_in_loop(self._close_async())
            self.loop.call_soon_threadsafe(self.loop.stop)
        else:
            try:
                if not self.loop.is_closed():
                    self.loop.run_until_complete(self._close_async())
            except Exception as e:
                logger.warning(f"Failed to run _close_async in stopped loop: {e}")
            logger.info(f'BrowserCaptureMethod close not loop.is_running')

        self.browser = None
        self.playwright = None
        self.page = None
        self.latest_frame = None
        if self.loop_thread.is_alive():
            self.loop_thread.join(timeout=1)

        self.hwnd = 0
        self.last_hwnd = 0

    def do_get_frame(self):
        return self.do_get_frame_wait(0)

    def do_get_frame_wait(self, timeout):
        if self.exit_event.is_set():
            logger.info(f'BrowserCaptureMethod self.exit_event.is_set()')
            self.close()
            return None

        if self.page is None or self.page.is_closed():
            if self.loop.is_running() and self.page is None:
                pass
            elif self.page is not None:
                logger.warning('BrowserCaptureMethod page closed')
                self.page = None
                self.browser = None
                communicate.notification.emit('Paused because browser exited', None, True, True, "start", None, None)
            return None

        if self.wgc_capture:
            if not self.update_window_geometry():
                return None
            return self.wgc_capture.do_get_frame_wait(timeout)

        return None

    def connected(self):
        return (self.page is not None and not self.page.is_closed()
                and self.wgc_capture is not None and self.hwnd > 0)



class BrowserWindowAdapter:
    def __init__(self, capture):
        self.capture = capture

    @property
    def hwnd(self):
        return self.capture.hwnd

    @property
    def exists(self):
        return self.capture.connected() and self.capture.hwnd > 0

    @property
    def app_exit_event(self):
        return self.capture.exit_event

    @property
    def width(self):
        return self.capture.width

    @property
    def height(self):
        return self.capture.height

    @property
    def exe_full_path(self):
        return self.capture.exe_full_path

    @property
    def capture_target_signature(self):
        return (
            self.hwnd,
            self.width,
            self.height,
            self.capture.x_offset,
            self.capture.y_offset,
            self.capture.exe_full_path,
        )

    def get_abs_cords(self, x, y):
        try:
            return win32gui.ClientToScreen(
                self.capture.hwnd, (self.capture.x_offset + x, self.capture.y_offset + y))
        except:
            return x, y



class BrowserWGC(WindowsGraphicsCaptureMethod):

    def __init__(self, browser_method):
        self.browser_method = browser_method
        super().__init__(BrowserWindowAdapter(browser_method))

    def crop_image(self, frame):
        if frame is None:
            return None

        fh, fw = frame.shape[:2]
        target_w = int(getattr(self.hwnd_window, "width", 0) or 0)
        target_h = int(getattr(self.hwnd_window, "height", 0) or 0)
        if target_w <= 0 or target_h <= 0:
            return frame

        # WGC excludes the invisible resize borders, whereas renderer offsets
        # are relative to the native client area. Convert both to screen space.
        bounds = wintypes.RECT()
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            self.browser_method.hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(bounds), ctypes.sizeof(bounds))
        if result != 0:
            return None
        screen_x, screen_y = self.hwnd_window.get_abs_cords(0, 0)
        x = screen_x - bounds.left
        y = screen_y - bounds.top
        if x < 0 or y < 0 or x + target_w > fw or y + target_h > fh:
            return None
        return frame[y:y + target_h, x:x + target_w]
