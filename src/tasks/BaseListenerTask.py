from ok import Logger, og
from pynput import keyboard

logger = Logger.get_logger(__name__)


class BaseListenerTask:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connected = False

    def setup_listener_config(self):
        required_attrs = ['default_config', 'config_description', 'config_type']
        if not all(hasattr(self, attr) for attr in required_attrs):
            return
        self.default_config.update({
            '激活键': 'x1',
            '键盘': 'ctrl_r',
        })
        self.config_type['激活键'] = {'type': 'drop_down', 'options': ['x1', 'x2', '使用键盘']}
        self.config_description.update({
            '激活键': '鼠标键或键盘按键',
        })

    def try_disconnect_listener(self):
        if self.connected:
            logger.debug(f"{self.__class__.__name__} disconnect listener")
            og.my_app.clicked.disconnect(self.on_global_click)
            og.my_app.pressed.disconnect(self.on_global_press)
            og.my_app.released.disconnect(self.on_global_release)
            self.connected = False

    def try_connect_listener(self):
        if not self.connected:
            logger.debug(f"{self.__class__.__name__} connect listener")
            og.my_app.clicked.connect(self.on_global_click)
            og.my_app.pressed.connect(self.on_global_press)
            og.my_app.released.connect(self.on_global_release)
            self.connected = True

    def on_global_click(self, x, y, button, pressed):
        pass

    def on_global_press(self, key):
        pass

    def on_global_release(self, key):
        pass

    def normalize_hotkey(self, name: str):
        name = name.lower()
        if hasattr(keyboard.Key, name):
            return getattr(keyboard.Key, name)
        else:
            return keyboard.KeyCode.from_char(name)

    def key_equal(self, k1, k2):
        if isinstance(k1, keyboard.KeyCode) and isinstance(k2, keyboard.KeyCode):
            return k1.char == k2.char
        return k1 == k2
