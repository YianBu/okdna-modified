"""在主界面运行栏里加一个“幽灵模式”开关。

开关直接改 ``config['browser']['ghost_mode']``；BrowserResolutionLock 每两秒
读一次这个值，所以运行中切换也会生效：打开后窗口被移出屏幕，关闭后回到原位。
只在内存里改，重启程序会回到 src/config.py 里的默认值。
"""

from ok import Logger

logger = Logger.get_logger(__name__)


def _browser_config():
    from ok import og

    config = getattr(og, 'config', None) or {}
    browser = config.get('browser')
    return browser if isinstance(browser, dict) else None


def _paint(button):
    enabled = bool((_browser_config() or {}).get('ghost_mode'))
    if getattr(button, '_ghost_on', None) is enabled:
        return
    button._ghost_on = enabled
    button.setText('幽灵模式 开' if enabled else '幽灵模式 关')
    # 关闭态用 secondary（没有专门规则，落到基础 Button 样式），保持可见边框；
    # subtle 会把 border-color 设成 transparent，看起来像没有边框。
    button.setProperty('variant', 'tonal' if enabled else 'secondary')
    button.style().unpolish(button)
    button.style().polish(button)


def attach_ghost_toggle(run_bar):
    """把开关插到运行栏中间（连接信息与右侧状态之间）。"""
    from ok.ui.qt.kit.buttons import Button

    layout = run_bar.layout()
    if layout is None:
        return None
    button = Button('幽灵模式 关', variant='secondary', size='small', parent=run_bar)
    button.setToolTip('把云游戏窗口移到屏幕外：桌面上看不到，但抓帧和后台点击继续。\n'
                      '约 2 秒内生效；关闭后窗口回到原位。')

    def _toggle():
        from src.ghost_mode import set_ghost_enabled

        browser = _browser_config()
        current = bool((browser or {}).get('ghost_mode'))
        value = not current
        set_ghost_enabled(value)
        if browser is not None:
            browser['ghost_mode'] = value
        _paint(button)
        logger.info(f"幽灵模式{'已开启' if value else '已关闭'}，约 2 秒内生效")

    button.clicked.connect(_toggle)
    layout.insertWidget(2, button)
    layout.insertStretch(3)
    run_bar.ghost_button = button
    _paint(button)
    return button


def install_ghost_toggle():
    """给 RunBar 打补丁；重复调用安全。"""
    from ok.ui.qt.shell.run_bar import RunBar

    if getattr(RunBar, '_dna_ghost_toggle', False):
        return

    original_init = RunBar.__init__

    def _init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        try:
            attach_ghost_toggle(self)
        except Exception as e:  # 不能因为一个开关拖垮主界面
            logger.warning(f'幽灵模式开关添加失败: {e}')

    original_refresh = RunBar.refresh

    def _refresh(self):
        original_refresh(self)
        button = getattr(self, 'ghost_button', None)
        if button is not None:
            _paint(button)

    RunBar.__init__ = _init
    RunBar.refresh = _refresh
    RunBar._dna_ghost_toggle = True
    logger.info('幽灵模式开关已安装到运行栏')
