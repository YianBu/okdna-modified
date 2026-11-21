from qfluentwidgets import FluentIcon
import time
import cv2

from ok import Logger, TaskDisabledException
from src.tasks.BaseDNATask import BaseDNATask
from src.tasks.DNAOneTimeTask import DNAOneTimeTask

logger = Logger.get_logger(__name__)


class AutoFishTask_Leisure(DNAOneTimeTask, BaseDNATask):
    """AutoFishTask_Leisure
    悠闲全自动钓鱼
    """
    BAR_MIN_AREA = 1200
    ICON_MIN_AREA = 70
    ICON_MAX_AREA = 400
    CONTROL_ZONE_RATIO = 0.25

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动钓鱼（悠闲）"
        self.description = "悠闲全自动钓鱼 (原作者: B站无敌大蜜瓜)"
        self.icon = "icons/tasks/auto_fish_leisure.svg"
        self.group_name = "休闲"
        self.group_icon = FluentIcon.CAFE

        # 默认配置（会被 configs/AutoFishTask.json 覆盖）
        self.default_config.update({
            "MAX_ROUNDS": 100,
            "END_WAIT_SPACE": 1.0,
            "MAX_START_SEC": 20.0,
            "MAX_FIGHT_SEC": 60.0,
            "MAX_END_SEC": 20.0,
        })

        # 配置描述（便于GUI显示）
        self.config_description.update({
            "MAX_ROUNDS": "最大轮数，鱼塘每天上限为100次",
            "END_WAIT_SPACE": "每轮结束等待时间(秒)",
            "MAX_START_SEC": "开始阶段超时(秒)",
            "MAX_FIGHT_SEC": "溜鱼阶段超时(秒)",
            "MAX_END_SEC": "结束阶段超时(秒)",
        })

        # runtime
        self.stats = {
            "rounds_completed": 0,
            "total_time": 0.0,
            "start_time": None,
            "current_phase": "准备中",
            "chance_used": 0,  # 授渔以鱼使用次数
        }

    def run(self):
        DNAOneTimeTask.run(self)
        try:
            return self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error("AutoFishTask error", e)
            raise

    def init(self):
        self.stats = {
            "rounds_completed": 0,
            "total_time": 0.0,
            "start_time": None,
            "current_phase": "准备中",
            "chance_used": 0,  # 授渔以鱼使用次数
        }

    def find_fish_cast(self) -> tuple[bool, tuple]:
        """查找 fish_cast 图标（抛竿/收杆），返回 (found, center)"""
        CAST_THRESHOLD = 0.8  # fish_cast 匹配阈值
        fish_box = self.box_of_screen(0.854, 0.778, 0.910, 0.879, name="fish_bite")
        box = self.find_one("fish_cast", box=fish_box, threshold=CAST_THRESHOLD) or self.find_one("fish_ease",
                                                                                                  box=fish_box,
                                                                                                  threshold=CAST_THRESHOLD)
        if box:
            return True, (box.x + box.width // 2, box.y + box.height // 2)
        return False, (0, 0)

    def find_fish_bite(self) -> tuple[bool, tuple]:
        """查找 fish_bite 图标（等待鱼上钩），返回 (found, center)"""
        BITE_THRESHOLD = 0.8  # fish_bite 匹配阈值
        fish_box = self.box_of_screen(0.854, 0.778, 0.910, 0.879, name="fish_bite")
        box = self.find_one("fish_bite", box=fish_box, threshold=BITE_THRESHOLD)
        if box:
            return True, (box.x + box.width // 2, box.y + box.height // 2)
        return False, (0, 0)

    def find_fish_chance(self) -> tuple[bool, tuple]:
        """查找 fish_chance 图标（授渔以鱼），返回 (found, center)"""
        CHANCE_THRESHOLD = 0.8  # fish_chance 匹配阈值
        fish_chance_box = self.screen_box('FISH_CHANCE')
        box = self.find_one("fish_chance", box=fish_chance_box, threshold=CHANCE_THRESHOLD)
        if box:
            return True, (box.x + box.width // 2, box.y + box.height // 2)
        return False, (0, 0)

    def find_fish_prompt(self):
        """右下角提示图标：鱼竿图样按空格，耳机图样（自动钓鱼中）不按

        模板只取圆盘内的白色图案区（共用圆环/键帽不进模板，靠图案区分两种状态）。
        返回匹配到的 Box（name 为 fish_prompt_cast / fish_prompt_auto），未找到返回 None
        """
        PROMPT_THRESHOLD = 0.65  # 实测同图案跨时刻 ~0.84+，异图案 ~0.58
        roi = self.box_of_screen(0.82, 0.74, 0.96, 0.97, name="fish_prompt_roi")
        return self.find_best_match_in_box(roi, ["fish_prompt_cast", "fish_prompt_auto"], PROMPT_THRESHOLD)

    def find_fish_caught(self):
        """查找结算弹窗标题（钓到鱼了），返回标题 Box，未找到返回 None"""
        CAUGHT_THRESHOLD = 0.7  # 实测同图 ~0.96，异图 ~0.47
        roi = self.box_of_screen(0.38, 0.10, 0.62, 0.26, name="fish_caught_roi")
        return self.find_one("fish_caught", box=roi, threshold=CAUGHT_THRESHOLD)

    def close_caught_popup(self) -> bool:
        """钓到鱼结算弹窗：连续点击卡片下方“自动关闭”处直到弹窗关闭"""
        logger.info("检测到钓到鱼结算弹窗 -> 点击“自动关闭”关闭")
        close_deadline = time.monotonic() + 15.0
        while time.monotonic() < close_deadline:
            title = self.find_fish_caught()
            if title is None:
                logger.info("结算弹窗已关闭")
                return True
            # “自动关闭(Ns)”在卡片正下方、屏幕底部：标题中心 x，y 取帧高 ~0.944 处（按 1920 截图实测换算）
            x = title.x + title.width // 2
            y = int(self.height * 0.944)
            self.click(x, y)
            self.sleep(0.25)
        logger.info("结算弹窗关闭超时，继续主循环")
        return False

    def find_bar_and_fish_by_area(self):
        """基于 ROI 找到鱼条和鱼标的区域与面积

        返回：((has_bar, bar_center, bar_rect), (has_icon, icon_center, icon_rect))
        注意：bar_center 和 icon_center 是相对于 ROI 内部的坐标，bar_rect 和 icon_rect 也是
        """

        # 获取 ROI 区域
        box = self.box_of_screen(0.873, 0.302, 0.890, 0.674, name="fish_roi")
        self.draw_boxes(box.name, box, "blue")

        try:
            # frame = self.frame
            # Box 对象使用 x, y, width, height 属性
            # box_x1, box_y1 = box.x, box.y
            # box_x2, box_y2 = box.x + box.width, box.y + box.height
            # box_x1 = max(0, min(box_x1, frame_width - 1))
            # box_y1 = max(0, min(box_y1, frame_height - 1))
            # box_x2 = max(box_x1 + 1, min(box_x2, frame_width))
            # box_y2 = max(box_y1 + 1, min(box_y2, frame_height))
            # roi_img = frame[box_y1:box_y2, box_x1:box_x2]
            frame_height, _ = self.frame.shape[:2]
            res_ratio = frame_height / 1080
            roi_img = box.crop_frame(self.frame)

            # 转换为灰度图
            gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)

            # 二值化：提取亮色区域（鱼条和图标都是白色/亮色）
            _, scene_bin = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

            # 查找轮廓
            contours, _ = cv2.findContours(scene_bin, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

            # 收集所有符合最小面积的轮廓
            blobs = []
            for contour in contours:
                area = cv2.contourArea(contour)
                if area > self.ICON_MIN_AREA * res_ratio ** 2:
                    blobs.append({"contour": contour, "area": area})

            # 按面积降序排列
            blobs.sort(key=lambda b: b["area"], reverse=True)

            # Debug only
            # output_img = roi_img.copy()
            # colors = [
            #     (0, 0, 255),     # 红
            #     (0, 255, 0),     # 绿
            #     (255, 0, 0),     # 蓝
            #     (0, 255, 255),   # 黄
            #     (255, 0, 255),   # 紫
            #     (255, 255, 0),   # 青
            #     (255, 255, 255), # 白
            # ]
            # for i, blob in enumerate(blobs):
            #     color = colors[i % len(colors)]  # 超过列表长度循环使用
            #     cv2.drawContours(output_img, [blob["contour"]], -1, color, 2)
            # Debug only

            has_bar = has_icon = False
            bar_center = bar_rect = icon_center = icon_rect = None
            bar_area = icon_area = 0.0

            # 查找鱼条（最大的符合条件的轮廓）
            for blob in blobs:
                if blob["area"] > self.BAR_MIN_AREA * res_ratio ** 2:
                    contour = blob["contour"]
                    moments = cv2.moments(contour)
                    if moments["m00"] > 0:
                        has_bar = True
                        bar_area = blob["area"]
                        # 注意：这里是 ROI 内部坐标，不加 box_x1, box_y1
                        bar_center = (
                            int(moments["m10"] / moments["m00"]),
                            int(moments["m01"] / moments["m00"]),
                        )
                        x, y, w, h = cv2.boundingRect(contour)
                        # 矩形也是 ROI 内部坐标
                        bar_rect = (x, y, x + w, y + h)
                    break

            # 查找鱼标（第二大的符合条件的轮廓，排除鱼条）
            for blob in blobs:
                if blob["area"] == bar_area:
                    continue
                if self.ICON_MIN_AREA * res_ratio ** 2 < blob["area"] < self.ICON_MAX_AREA * res_ratio ** 2:
                    contour = blob["contour"]
                    moments = cv2.moments(contour)
                    if moments["m00"] > 0:
                        has_icon = True
                        icon_area = blob["area"]
                        # ROI 内部坐标
                        icon_center = (
                            int(moments["m10"] / moments["m00"]),
                            int(moments["m01"] / moments["m00"]),
                        )
                        x, y, w, h = cv2.boundingRect(contour)
                        icon_rect = (x, y, x + w, y + h)
                    break

            if has_bar:
                zone_ratio = bar_area / box.area()
                if self.CONTROL_ZONE_RATIO <= 0 or abs(
                        zone_ratio - self.CONTROL_ZONE_RATIO) / self.CONTROL_ZONE_RATIO > 0.1:
                    self.CONTROL_ZONE_RATIO = zone_ratio
                    self.log_info(f"set CONTROL_ZONE_RATIO {self.CONTROL_ZONE_RATIO}")

            # Debug only
            # cv2.imshow("Contours", output_img)
            # cv2.waitKey(1)
            # Debug only

            # 更新统计信息
            self.stats.update({
                "last_bar_found": has_bar,
                "last_bar_area": float(bar_area),
                "last_icon_found": has_icon,
                "last_icon_area": float(icon_area),
            })

            return (has_bar, bar_center, bar_rect), (has_icon, icon_center, icon_rect)
        except TaskDisabledException:
            # cv2.destroyAllWindows()
            raise
        except Exception as e:
            logger.error("find_bar_and_fish_by_area error", e)
            return (False, None, None), (False, None, None)

    # ---- phases ----
    def phase_start(self) -> bool:
        cfg = self.config
        self.stats["current_phase"] = "抛竿"
        self.info_set("当前阶段", "抛竿")

        # ensure foreground handled by framework interaction activation
        start_deadline = time.monotonic() + cfg.get("MAX_START_SEC", 20.0)

        # 检测是否有授渔以鱼机会 (优先执行且短路，减少不必要的对比开销)
        has_chance_icon, _ = self.find_fish_chance()
        if has_chance_icon:
            logger.info("检测到fish_chance（授渔以鱼）-> 按下E键使用授渔以鱼抛竿")
            self.stats["chance_used"] = self.stats.get("chance_used", 0) + 1
            self.info_set("授渔以鱼", self.stats["chance_used"])
            # 上一轮的鱼被用作鱼饵，不计入轮数
            if self.stats["rounds_completed"] > 0:
                self.stats["rounds_completed"] -= 1
                self.info_set("完成轮数", self.stats["rounds_completed"])
                logger.info(f"上一轮的鱼作为鱼饵，轮数调整为: {self.stats['rounds_completed']}")
            self.send_key("e", down_time=0.06)
        else:
            has_cast_icon, _ = self.find_fish_cast()
            self.stats["last_cast_icon_found"] = has_cast_icon
            if not has_cast_icon:
                logger.info("开始阶段未找到fish_cast，尝试按空格抛竿并等待fish_bite出现")
                # press space to cast
                self.send_key("space", down_time=0.06)
            else:
                logger.info("找到fish_cast -> 按下空格抛竿")
                self.send_key("space", down_time=0.06)

        logger.info("等待fish_bite出现...")
        ret = self.wait_until(lambda: self.find_fish_bite()[0], time_out=start_deadline, raise_if_not_found=False)
        self.stats["last_bite_icon_found"] = ret
        if ret:
            logger.info("找到fish_bite -> 等待鱼咬钩")
        else:
            logger.info("超时：等待fish_bite出现")
            return False

        # poll_interval = 0.01
        # while time.monotonic() < start_deadline:
        #     has_bite_icon, _ = self.find_fish_bite()
        #     self.stats["last_bite_icon_found"] = has_bite_icon
        #     if has_bite_icon:
        #         logger.info("找到fish_bite -> 等待鱼咬钩")
        #         break
        #     self.sleep(poll_interval)
        # else:
        #     logger.info("超时：等待fish_bite出现")
        #     return False

        # 等待 fish_bite 消失（鱼咬钩了）
        logger.info("等待鱼咬钩...")
        bite_gone_stable_time = 0.5  # 咬钩消失稳定时间
        ret = self.wait_until(lambda: not self.find_fish_bite()[0], time_out=start_deadline,
                              settle_time=bite_gone_stable_time)
        self.stats["last_bite_icon_found"] = not ret
        if not ret:
            logger.info("等待fish_bite消失超时")
            return False
        # absent_start = None
        # while time.monotonic() < start_deadline:
        #     has_bite_icon, _ = self.find_fish_bite()
        #     self.stats["last_bite_icon_found"] = has_bite_icon
        #     if not has_bite_icon:
        #         if absent_start is None:
        #             absent_start = time.monotonic()
        #         elif time.monotonic() - absent_start >= bite_gone_stable_time:
        #             logger.info("fish_bite已消失 -> 鱼咬钩了！")
        #             break
        #     else:
        #         absent_start = None
        #     self.sleep(poll_interval)
        # else:
        #     logger.info("等待fish_bite消失超时")
        #     return False

        # 等待 fish_cast 出现（收杆提示）
        logger.info("等待fish_cast出现（收杆提示）...")
        ret = self.wait_until(lambda: self.find_fish_cast()[0], time_out=start_deadline)
        self.stats["last_cast_icon_found"] = ret
        if ret:
            logger.info("找到fish_cast -> 按下空格收杆，进入溜鱼阶段")
            self.send_key("space", down_time=0.06)
            return True
        # while time.monotonic() < start_deadline:
        #     has_cast_icon, _ = self.find_fish_cast()
        #     self.stats["last_cast_icon_found"] = has_cast_icon
        #     if has_cast_icon:
        #         logger.info("找到fish_cast -> 按下空格收杆，进入溜鱼阶段")
        #         self.send_key("space", down_time=0.06)
        #         return True
        #     self.sleep(poll_interval)

        logger.info("超时：等待fish_cast出现")
        return False

    def phase_fight(self) -> bool:
        cfg = self.config
        self.stats["current_phase"] = "溜鱼"
        self.info_set("当前阶段", "溜鱼")
        logger.info("进入溜鱼阶段...")

        # 硬编码的常量
        BAR_MISSING_TIMEOUT = 2.5  # 鱼条丢失超时
        MERGE_GRACE_SECONDS = 0.20  # 合并宽限时间

        # 运行时状态
        is_holding_space = False
        icon_was_visible_prev = False
        last_known_icon_y_relative = 0.0

        bar_missing_start_time = None
        merge_start_time = None

        def set_hold(target_hold: bool):
            nonlocal is_holding_space
            if target_hold != is_holding_space:
                if target_hold:
                    self.send_key_down("space")
                else:
                    self.send_key_up("space")
                is_holding_space = target_hold
                self.stats["last_hold_state"] = is_holding_space

        fight_deadline = time.monotonic() + cfg.get("MAX_FIGHT_SEC", 60.0)
        try:
            while True:
                now = time.monotonic()
                if now >= fight_deadline:
                    logger.info("溜鱼超时")
                    return False

                (has_bar, bar_center, bar_rect), (has_icon, icon_center, icon_rect) = self.find_bar_and_fish_by_area()

                # 记录鱼标相对位置（用于合并处理）
                if has_bar and has_icon:
                    last_known_icon_y_relative = icon_center[1] - bar_center[1]

                # 检查鱼条是否丢失
                if not has_bar:
                    if bar_missing_start_time is None:
                        bar_missing_start_time = now
                    elif now - bar_missing_start_time >= BAR_MISSING_TIMEOUT:
                        logger.info(f"鱼条丢失超过 {BAR_MISSING_TIMEOUT}s -> 溜鱼结束")
                        return True
                else:
                    bar_missing_start_time = None

                # 主控制逻辑：两层控制系统
                if has_bar and bar_rect:
                    bar_top = bar_rect[1]
                    bar_bottom = bar_rect[3]
                    bar_height = bar_bottom - bar_top

                    if bar_height <= 0:
                        bar_height = 1

                    # 计算控制区域边界
                    control_zone_ratio = self.CONTROL_ZONE_RATIO
                    control_height = int(bar_height * control_zone_ratio)
                    control_top = bar_top + control_height
                    control_bottom = bar_bottom - control_height

                    is_merged = has_bar and (not has_icon) and icon_was_visible_prev

                    if has_icon:
                        merge_start_time = None
                        icon_y = icon_center[1]

                        # 简化的两层控制逻辑
                        if icon_y < control_top:
                            # 鱼标在上控制区 -> 按住空格
                            set_hold(True)
                        elif icon_y > control_bottom:
                            # 鱼标在下控制区 -> 松开空格
                            set_hold(False)
                        # else: 鱼标在中立区 -> 保持当前状态（滞回控制）

                    else:
                        # 处理鱼标与鱼条合并的情况
                        if is_merged:
                            if merge_start_time is None:
                                merge_start_time = now
                                self.stats["last_merge_event"] = (f"merged, last_rel={last_known_icon_y_relative:.1f}")
                                # logger.info("检测到合并，处理...")
                            elapsed = now - merge_start_time
                            if elapsed <= MERGE_GRACE_SECONDS:
                                # 根据上次已知的相对位置决定操作
                                if last_known_icon_y_relative < 0:
                                    set_hold(True)
                                else:
                                    set_hold(False)
                        else:
                            merge_start_time = None
                else:
                    set_hold(False)

                icon_was_visible_prev = has_icon

                self.next_frame()

        except TaskDisabledException:
            self.send_key_up("space")
            raise
        finally:
            self.send_key_up("space")

    def phase_end(self) -> bool:
        cfg = self.config
        self.stats["current_phase"] = "收线"
        self.info_set("当前阶段", "收线")

        # wait and press space to collect
        logger.info(f"等待 {cfg.get('END_WAIT_SPACE', 7.0)}s 结束鱼信息展示...")
        self.sleep(cfg.get("END_WAIT_SPACE", 7.0))

        # wait and verify
        confirm_deadline = time.monotonic() + cfg.get("MAX_END_SEC", 20.0)
        
        # 抛竿图标连续稳定确认机制
        stable_confirm_time = 0.5
        cast_appeared_time = None

        while time.monotonic() < confirm_deadline:
            has_chance = self.find_fish_chance()[0]
            if has_chance:
                logger.info("确认已回到挥杆界面（检测到授渔以鱼）")
                return True

            has_bite = self.find_fish_bite()[0]
            if has_bite:
                logger.info("确认已回到挥杆界面（检测到鱼咬钩被遗留）")
                return True

            has_cast = self.find_fish_cast()[0]
            self.stats["last_cast_icon_found"] = has_cast
            if has_cast:
                if cast_appeared_time is None:
                    # 记录第一次看见抛竿图标的时间
                    cast_appeared_time = time.monotonic()
                elif time.monotonic() - cast_appeared_time >= stable_confirm_time:
                    # 第二次确认：抛竿图标连续显示，非画面闪现
                    logger.info("界面稳定，确认已回到抛竿界面")
                    return True
            else:
                # 抛竿图标消失，重置判定计时
                cast_appeared_time = None

            # 继续保持点击屏幕左侧用来关闭那些可能无法单纯靠时间等待关闭的层叠UI
            self.click_relative_random(0.05, 0.3, 0.4, 0.7)
            self.sleep(0.5)
            
        logger.info("结束阶段确认失败")
        return False

    # main run
    def do_run(self):
        logger.info("=" * 50)
        logger.info("自动钓鱼（悠闲）启动：右下角提示按空格 / 授渔以鱼溜鱼 / 结算连点关闭")
        logger.info("=" * 50)

        self.stats["start_time"] = time.time()
        self.info_set("当前阶段", "等待抛竿")

        last_blank_click = 0.0
        while True:
            try:
                # 0) 钓到鱼结算弹窗 -> 连续点击屏幕边缘空白处直到关闭
                if self.find_fish_caught():
                    self.info_set("当前阶段", "关闭结算")
                    self.close_caught_popup()
                    continue

                # 1) 右下角提示图标：鱼竿图样 -> 按空格抛竿/收杆
                prompt = self.find_fish_prompt()
                if prompt:
                    if prompt.name == "fish_prompt_cast":
                        logger.info("检测到抛竿/收杆提示（鱼竿图标）-> 按空格")
                        self.info_set("当前阶段", "抛竿")
                        self.send_key("space", down_time=0.06)
                        self.sleep(0.5)
                        continue
                    # 耳机图样 = 自动钓鱼进行中，不按空格，等游戏自己钓
                    logger.info("检测到自动钓鱼提示（耳机图标）-> 不按空格")
                    self.info_set("当前阶段", "自动钓鱼中")

                # 2) 其它情况：等游戏自动钓鱼 / 咬钩等；定期点空白关闭鱼信息层
                # （授渔以鱼改版后不再出现鱼条，无需手动溜鱼）
                self.info_set("当前阶段", "等待")
                now = time.monotonic()
                if now - last_blank_click >= 1.0:
                    self.click_relative_random(0.05, 0.3, 0.4, 0.7)
                    last_blank_click = now
                self.sleep(0.2)
            except TaskDisabledException:
                raise
            except Exception as e:
                logger.error("AutoFishTask_Leisure fatal", e)
                break
