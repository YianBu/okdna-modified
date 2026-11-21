from ok.ui.qt.tasks.tasks_page import TasksPage, KIND_ALL, KIND_ONETIME, task_category_icon


class MainTasksPage(TasksPage):
    """主打任务页：只放日常/活动/休闲，测试和任务设定拆到侧栏页面。"""

    state_name = "main_tasks_page"
    excluded_groups = {"测试", "任务设定"}

    def __init__(self):
        super().__init__(title="任务")
        self.setObjectName(self.__class__.__name__)

    def collect_tasks(self):
        onetime, _ = super().collect_tasks()
        return [task for task in onetime
                if getattr(task, 'group_name', None) not in self.excluded_groups], []

    def _title_sections(self, key):
        super()._title_sections(key)
        if key == KIND_ALL:
            self.onetime_section.set_title("全自动", task_category_icon(KIND_ONETIME, "bolt"))


class _GroupTasksPage(TasksPage):
    """侧栏里的专用任务页：只显示一个任务分组。"""

    group_name = None
    page_title = "任务"
    page_icon = "grid"
    section = "game"

    def __init__(self):
        super().__init__(title=self.page_title)
        self.setObjectName(self.__class__.__name__)

    @property
    def name(self):
        return self.page_title

    @property
    def icon(self):
        return self.page_icon

    @property
    def add_after_default_tabs(self):
        return True

    def collect_tasks(self):
        onetime, _ = super().collect_tasks()
        return [task for task in onetime
                if getattr(task, 'group_name', None) == self.group_name], []

    def _build_filters(self):
        self.filter_tabs.blockSignals(True)
        self.filter_tabs.clear()
        self.filter_tabs.setVisible(False)
        self.filter_tabs.blockSignals(False)
        self.groups = {}

    def _title_sections(self, key):
        self.onetime_section.set_title(self.page_title, self.page_icon)


class TestTasksPage(_GroupTasksPage):
    state_name = "test_tasks_page"
    group_name = "测试"
    page_title = "测试"
    page_icon = "bug"
    section = "develop"


class TaskSettingsPage(_GroupTasksPage):
    state_name = "task_settings_page"
    group_name = "任务设定"
    page_title = "任务设定"
    page_icon = "gear"
    section = "game"

    def _make_row(self, task, is_trigger):
        row = super()._make_row(task, is_trigger)
        action_button = getattr(row, 'action_button', None)
        if action_button is not None:
            action_button.hide()
        return row

    def select_task(self, task, scroll_to=True):
        super().select_task(task, scroll_to)
        self._hide_actions()

    def _tick(self):
        super()._tick()
        self._hide_actions()

    def _hide_actions(self):
        for button in (self.detail.run_button, self.detail.pause_button, self.detail.stop_button):
            button.setVisible(False)
