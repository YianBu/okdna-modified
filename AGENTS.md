# AGENTS.md

给在本仓库工作的 AI 助手的规则。

## 绝不触碰上游（硬性）

- `origin` = `https://github.com/BnanZ0/ok-duet-night-abyss.git` 是上游。**永远不要** push 到
  `origin`、不要向上游开 PR、不要改上游的分支或远程配置。
- 所有提交只推 `mine` = `https://github.com/YianBu/okdna_modified.git` 的 `master`：
  `git push mine master`。本地 `master` 仍跟踪 `origin/master`，只为 `git pull` 拉上游更新；
  仓库已设 `remote.pushDefault = mine`，所以不带参数的 `git push` 也只会打到 `mine`。
- 本地 `origin` 另设了 `remote.origin.tagOpt = --no-tags`：`git pull/fetch` 只拉上游的提交，
  不会把上游那一百多个 tag（`v0.0.x`/`v1.0.x`/`v1.1.x`…`v1.6.x`）抓回本地。这是刻意设的
  **本地**配置（不改上游任何东西、也不影响推送 tag），不要删。
- 永远不要 `git push mine --tags`：`git pull` 之后本地会重新带回上游的 `v1.6.x` 等标签，
  全推上去会让 Launcher 把 `v1.6.5` 当成「新版本」推给用户。推发布 tag 要指名道姓，
  一次只推要发的那一个。

## Git 提交、版本与发布

- 提交信息只写「这个版本增加了、改了哪些内容」，一两句（一到三行）说清就行。不要把实现细节、
  排查过程、踩过的坑、设计取舍写进提交信息；那些留在与用户的对话里，需要留档就写进代码注释
  或本文件。
- 本仓库的版本号（`v1.x`）与上游完全独立，不要拿上游的 tag 做比较或参考。本仓库自己的发布
  序列到目前是 `v1.0.1`…`v1.2.3`（另有 CI 用的 `launcher-base-v1.0.1`，在远端，不是版本号）。
  本地 tag 已清理过，只剩本仓库自己的 `v1.x`；万一又看到上游 tag（换了机器、重新克隆等），
  别照它们编号，本地删掉即可。
- 版本号**逢 10 进 1**：`v1.0.9` 之后是 `v1.1.0`（不是 `v1.0.10`），`v1.1.9` 之后是 `v1.2.0`，
  以此类推。`v1.1.3` 这个号之前打过一次又被删掉了（`v1.1.2` 第一次的 CI 挂在「Run tests」
  步骤，Release 被跳过），后来作为新版本正式发出，现在已经在用。
- **「传云」的含义**：用户说「传云」（或「传云 git」「推送更新」）时，默认理解为「提交改动 ->
  本仓库版本号 +1 打 annotated tag -> 推送」：即 `git push mine master` 加
  `git push mine <下一个版本号>`（当前下一个是 `v1.2.4`），让 CI 出 release 给 Launcher 用户。
  推完把下一个版本号记住（再次「传云」时就再 +1）。**只推这一个 tag，绝不 `--tags`。**
- 发布 = 打 `v*` tag 推到 `mine`：CI 按 tag 改写 `src/config.py` 的 version 并发布 release，
  Launcher 用户就是靠这个 tag 才拿得到更新的。
- 一次发布约 12 分钟，其中约 9 分钟是 PyAppify 最后 `makensis` 压缩 ~590MB 的离线 payload
  （Python 环境 + 依赖 + 源码快照）。这是已知且**已接受**的成本，不要再为了「省时间」把它改成
  只发 online 安装包、或省掉打包。
- `use_release` 复用已编译的 Launcher，依赖 `launcher-base-v1.0.1` 这个**已公开发布的预发布**
  release：action 是去下载它的资产，draft 的下载地址取不到（会 404）。改了 `icons/` 或
  `pyappify.yml` 之后这个 zip 就失效了，需要重新出一个包并更新里面的 tag。

## 文案与界面语言（i18n）

- 文案**只维护中文**：新增用户可见配置/文案时，往 `i18n/zh_CN/LC_MESSAGES/ok.po` 加 `msgid`
  就行（该文件 `msgstr` 惯例留空 = 回落到中文原文）；其它五种语言不用再动。
- **界面显示的是 `.mo` 不是 `.po`**：App 运行时读编译后的 `ok.mo`，只改 `ok.po`，界面上的英文
  msgid（如 `Normal Attack Key`）不会变中文。仓库没装 polib：用 `gettext.GNUTranslations` 读出
  `_catalog`，手写 `.mo` 二进制（struct）合并新条目，再读回逐条比对。改完记得把 `ok.mo` 一起
  同步到 ok-dna（见「部署到本地」）。

## 测试

- **不必**跑测试：用户明确说过「这些测试没有跑的必要」。CI 在打 tag 之后会逐个执行
  `tests/test_*.py` 兜底。需要本地自查时命令是 `python -m unittest tests/test_ui_labels.py`、
  `tests/test_theatre_task.py`、`tests/test_heavy_attack.py`。本地自查多个测试文件要**逐个跑**：
  一起跑会因共享 ok 运行时互相踩而误报。

## 看图片（直接看，看不清再 OCR）

- 助手**能直接看到图片**（视觉通道可用），用户发的截图正常按图聊就行，不要凭文件名或描述
  猜内容。只有图太小、太糊，或需要逐字的精确坐标时才走下面的 OCR。
- 命令：`python tools/ocr_image.py <图片路径> --out 结果.txt`，输出每行
  `x1,y1,x2,y2 <TAB> 置信度 <TAB> 文本`（坐标是图片像素）。
- 引擎是本机 Python（`C:\Users\67400\AppData\Local\Programs\Python\Python313`，也就是 ok
  源码版用的那个）里随 `ok` 装好的 PP-OCRv5（`onnxocr` 包，模型随包离线可用）。默认走
  `use_openvino=True` 的 OpenVINO 后端（和 ok 源码版一致）；`onnxruntime` 和 `rapidocr` 也已
  装好，可用 `--backend onnxruntime` 或改用 rapidocr 对照。
- 终端是 GBK，中文直接打印会乱码：加 `--out` 写成 UTF-8，再用 `Get-Content -Encoding UTF8`
  读回来。
- **沙箱里跑 OCR 报 `UnicodeDecodeError`（`ov.Core().set_property('CPU', {'CACHE_DIR'...})`
  那一行）是 Codex 沙箱环境问题，不是代码 bug**：Windows 错误串是 GBK，pybind11 转 UTF-8
  失败把真实错误吞了。加沙箱免提权跑就全部正常（`cache\openvino` 有缓存产物），用户机器和
  CI 都没事，别为这个改代码；需要对照时用 `--backend onnxruntime`。

## 验证图像判据（截图当帧喂给仓库代码）

- 新写或改一个 OCR/找图判据，不要只靠目测推断：把用户给的截图当成一帧，直接在仓库代码上跑
  对应的任务方法（如 `find_target_wave()`、`is_in_combat()`、`in_team()`）。「判据该成立的图」
  和「不该成立的图」各跑一遍，一真一假才算判据成立。
- `tests/images/` 里的几十张现成帧是回归底片：新判据应在所有非局内帧上为 False、只在局内
  HUD 帧上为 True，全量过一遍再收工。
- 探针要复用仓库自己的类（import 仓库的 Task 来跑），不要另写一套识别逻辑，否则验证的不是
  将要发布的那份代码。一次性探针脚本写到 `C:\Users\67400\.codex\visualizations\...`
  （沙箱可写目录），别进仓库。
- **定框按 1600×900 基准**：用户发的截图常是 1920×1080，云游戏实际跑 1600×900，定框定坐标
  一律按 1600×900 换算，别直接抄截图像素。先用 `tools/ocr_image.py` 拿文字像素框，再按图片
  长边换算；`SCREEN_BOX` 元组最后一项 `True` 表示相对框。左侧任务面板这类会随窗口比例平移的
  区域，框要像 `FISH_CHANCE` 那样左锚定，不要用居中相对框。

## 部署到本地（默认自动做）

- 用户本地跑的是**源码方式**：`C:\Users\Administrator\Desktop\ok-dna` 里放了一份
  `main.py` + `src`，和现成的 `assets`/`i18n`/`mod`/`configs` 共用；启动器是目录里的
  `start-source.bat`（用本机 Python 的 `pythonw` 跑源码）。目录里那个 `ok-dna.exe`
  是旧的冻结包，只在需要冻结版时才用。
- **改完代码就自动同步过去**，不用等用户说「部署」：整份替换该目录下的 `src`，再覆盖
  `main.py`；动了中文文案就把 `i18n/zh_CN/LC_MESSAGES/ok.po`（和重编译的 `ok.mo`，见
  「文案与界面语言」）也覆盖过去。只动这几处，别碰 `configs`（用户配置）、`logs`、以及
  `mod` 里用户自己加的东西。
- 同步是秒级的文件拷贝；Python 不会热加载，**要重启那个源码版程序**新代码才生效，
  同步完在回复里提醒用户重启（只改任务配置的话，重新开始任务即可）。
- 同步脚本**别写成带中文的 .ps1**：apply_patch + GBK 终端写含中文的 ps1 会编码报错。用纯 ASCII
  的 Python 脚本（中文 key 用 \u 转义，shutil.rmtree + copytree + copy2），跑完把临时脚本删掉，
  别留在仓库里。
- 本地打包（PyInstaller，约 3~5 分钟）只在用户明确要求、或要出冻结版/发布时做；
  打包脚本是仓库里的 `build_exe.spec`。

## 各任务留档（踩过的坑）

### 委托/防御任务的状态机

- **状态复位靠 `Mission.START` 交还**：`CommissionsTask.handle_mission_interface` 的
  「开始任务」分支必须 `return Mission.START if self.in_team() else None`。游戏内开
  自动确认时弹窗被跳过、没有后续界面把状态交回去；返回 None 则 `do_run` 里的
  `init_all()` 不执行，`current_round`/`skill_tick`/`_mission_started` 不复位。
  症状：打到目标轮次结算后，新一轮开局立刻被判定「已到轮次」直接撤离、脚本卡住
  （99 波结算不重开的根因）。
- **局内 ESC 菜单不是「可重开/已完成界面」**：`give_up_mission` 判断是否已到可重开界面
  （含「已完成」判据）时别把 `find_esc_menu()` 算进去。菜单盖住 HUD 时 `in_team()` 为假，
  会被当成「已到能重开的界面」提前返回，永远不去点「放弃挑战」。
- **波次判据别用老的 `get_wave_info()` 框**：那个相对框在新 HUD 上只能 OCR 出「0/」，
  `\d/\d` 永远匹配不上。现在的开战判据是左侧任务面板整行匹配 `TARGET_WAVE_PATTERN`
  （`波次\s*\d+\s*/\s*\d+`，框是 `SCREEN_BOX.DEFENCE_TARGET_WAVE`）：只认「波次 x/y」
  这一行的存在，不写死总波次（不同防御本的波次上限不同）。
- **开局走位先判图、再走对应路线**：`Auto65ArtifactTask_Fast` 继承 `DungeonActionMixin`，
  判图和走位跟「自动开密函」的扼守共用 `DungeonActionLogic.DUNGEON_MAPS`（扼守斜走 /
  扼守直走；直走不设框、当兜底）。配置「地图选择」默认全勾，判出来的图不在勾选里就抛
  `MapDetectionError` 重开一轮。直走路线是按住 W 轮询开战判据
  （`hold_w_until_combat`，判据委托 `AutoDefence.is_in_combat`），判到开战后再多走
  `HOLD_W_EXTRA_TIME`（1 秒），20 秒没判到就松手，交给已有的「等待战斗开始超时→重开」
  流程处理。
- **放技能的 in_combat 和波次计时是耦合的，别单独换**：`handle_in_mission` 里放技能仍用
  `current_wave != -1` 当 in_combat，且 `wave_start_time` 只在 `current_wave` 变化时
  刷新。想把放技能也换成 `find_target_wave()` 判据时，必须连同波次计时一起改，否则
  `time.time() - wave_start_time` 会立刻超过「超时时间」，误判超时撤退。
- 已知小缺口：`i18n/zh_CN/LC_MESSAGES/ok.po` 还没有任务名「自动防御」
  （`Auto65ArtifactTask_Fast`）的 msgid（「自动扼守」「自动探险」已有），下次动文案时补上。

### 迷津任务（AutoMijinTask：整屏 OCR 判界面）

- **界面判据全部用整屏 OCR 文案**（TEXT_* 常量 + 主循环节流缓存），不用找图模板：用户跑的是
  云二重螺旋（1600×900），实拍帧糊、模板分低，假阴性很多。判据文字挑各页面唯一、互不重叠的
  短句（「坠入深渊」「开始探索」「获得烛芯」「复苏」「时之纺线」…）。
- **点击优先点 OCR 到的文字位置**，固定坐标只做兜底（`click_text(fallback_coord, name, *needles)`）：
  「点击空白处关闭」点空白区域坐标时常没反应，点这几个字本身才稳；这套文案会连续出现在
  道具弹窗、二次确定后的过场、结算页，规则是「见到就点」。
- **COORD 放点击坐标、SCREEN_BOX 放 OCR/搜索框，别放错类**（都在 `src/dna_ui/Defs.py`）：
  把框错放进 COORD 会直接崩任务（`type object 'SCREEN_BOX' has no attribute ...`）。
- **放技能直连「游戏快捷键设置」**：`send_key(get_combat_key()/get_ultimate_key()/get_geniemon_key())`。
  不要走角色对象 —— 角色对象拿不到会整段静默 return，症状就是「技能一个都不放」。用户在
  游戏里改键后，只要 App 里的快捷键设置跟着改，技能序列不用动。
- **循环技能手法：每进一次主循环只走一步**（`run_character_skill` 的 loop 分支），不要
  for 循环整串阻塞 —— 阻塞期间整屏 OCR 判不了界面，打完一关的弹窗就漏了；一次型角色才整串放完。
- **打完一关的判据要加闸门**：进本画面上也会出现「前往下一层深渊」，只看它会把刚进本误判成
  打完。现在的闸门是 `sequence_done`（已放过技能序列）+ 进本满 `WAVE_DONE_MIN_ROUND_SECONDS`。
- **阵亡退本**：局内 OCR 到「复苏」即死亡，延迟 `REVIVE_EXIT_DELAY`（1 秒）后按 ESC，走和
  打完一关相同的退出流程（菜单「退出结算」-> 确认「确定」-> 点「点击空白处关闭」）。
- **结算收益**：结算页 OCR「时之纺线」读其上方数字累加（框 `SCREEN_BOX.MIJIN_SPINLINE`），
  `info_set("累计时之纺线")` 显示在信息栏，任务停止时清零；每局用 `settlement_counted`
  保证只计一次。
- **改默认配置要连本地 configs/*.json 一起改**：用户配置项会盖住 `default_config` 的默认值
  （改了「进本等待(秒)」默认值，本地 json 里的旧值仍优先生效）。只改用户明确要改的那一项，
  别动其它（configs 目录原则上不碰，见「部署到本地」）。
- **整屏 OCR 要节流**（`OCR_INTERVAL=0.5`，缓存 boxes/texts 复用）：每帧都跑整屏 OCR 会把
  主循环拖到秒级。
- log 里不要刷「认不出当前界面」这类兜底日志（用户嫌吵，已删）。

### 狩月人之阶任务（AutoHuntMoonTask）

- **进本后的固定流程**：认 `syr_start_btn`（开始挑战按钮里的 ◯）开局 -> `in_team()`/
  菱形判进本（30 秒）-> 稳 `RUN_SETTLE` 1 秒 -> 走位 `WALK_SCHEDULE` -> 主控角色手法
  （opening 起手序列放一遍 -> 循环序列，菱形变红才放技能）-> 结算认 `syr_hud_restart`
  「重新开始」。**「等开战」那一步已删掉**：开战判据试过血条和 `x30` 都不稳，走位完直接
  靠菱形变红开打。
- **走位时间轴来自录制回放**（`mod\示例-脚本工具\回放和录制软件`，录制器 F9，教程
  `emt自录方法.pdf`）：录制 JSON 是 `key_down/key_up` + 绝对秒，转成相对等待写进
  `WALK_SCHEDULE`。走位/回放期间不能动鼠标视角，所以全程按住 `lalt`。
- **主控角色 = 两段式手法表**：`opening`（走位后放一遍）+ 循环序列（`spam` 连打 +
  `timed` 按真实秒数插入，或 `steps`+`loop` 定序循环）。`spam` 写字符串 = 不加
  额外间隔，节奏由主循环 ~0.3s/次决定，别再叠冷却（用户实测「普攻之前间隔太长」就是
  叠出来的）。手法里写了「锁定」动作（按 Lock Key）时，`plan_has_lock()` 会跳过走位后
  的自动锁定。
- **技能按太快会被游戏整串吃掉**：锁定后 88ms 就按终结技，一次都没放出来；起手序列里
  每个动作之间留 0.1~0.5 秒、进循环前留 1 秒才稳。排障看 `ok-dna\logs\ok-script.log`
  的时间戳最直接（日志中文是 GBK，读时 `errors='ignore'`）。
- **认不出的画面别立刻放弃**：`wait_screen_back` 每 30 秒警告一次、第一次警告时存
  `hunt_moon_unknown_screen` 截图、连续 `UNKNOWN_SCREEN_GIVE_UP`（180 秒）才报错停。
  曾经「log 一直卡在等待界面切换」就是这个自愈逻辑在跑，不是卡死。注意 `screenshots`
  目录每次重启程序会清空，诊断截图要在重启前看。
- **鼠标键热键**（BaseDNATask）：`MOUSE_HOTKEY_BUTTONS` 认中英文鼠标键名，配
  `press_hotkey/hotkey_down/hotkey_up`；游戏快捷键设置里有 `Normal Attack Key=鼠标左键`、
  `Shoot Key=鼠标右键`、`Lock Key=鼠标中键`。热键值要 strip —— 配置里带空格的
  `" e"` 曾抛 `HotkeyConfigException` 把任务打死；现在 `_hotkey_ok` 把非法键降级成
  「提示一次 + 跳过」，不再崩任务。
- **判据素材优先用上游的**：合并上游同类任务时，上游模板是原生 1600×900，比用户截图
  缩放版准；自己的重复素材直接删（本次删了 `hunt_moon_start_icon`/
  `hunt_moon_restart_icon`/`boss_hp_bar` 和对应 png），`coco_annotations.json` 只追加、
  不挪旧条目。

### 自动开密函任务（AutoLetterOpenTask：驱离/探险/扼守三合一）

- **结构**：`AutoLetterOpenTask(DungeonActionMixin, AutoExpulsion)`。原来独立的「扼守探险
  开密函」已并入，**没有「模式」配置**：到密函任务列表界面（三栏：驱离/探险/扼守）按
  **优先级 驱离>探险>扼守** 自动挑还剩下的类型。地图登记表在
  `DungeonActionLogic.DUNGEON_MAPS`（地图名 -> mode / track_point 检测框 / 行动函数），
  行动序列的执行器在 `DungeonActionMixin`（`execute_exploration_ground`/
  `execute_exploration_high`/`execute_defence_diagonal`/`execute_defence_straight`）。
- **判地图跟原版同款**：进本第一帧看 track_point（追踪点）图标落在哪个固定比例框
  （探险平地/探险高台/扼守斜走各一个框；**扼守直走不设框、当扼守的兜底**）。框是拿原版
  `track_point` 模板定的。
- **走位每局一次，不是每波一次**：`_walked_this_mission` 标志控制；波次间「继续挑战」
  不能复位它，只有真正开新局才复位。
- **探险机关 = F 交互后反复按 F 破解到开战**（`solve_exploration_mechanism`，参考自动
  沉浸式戏剧的做法）；「前进到开战」是按住 W 轮询开战判据、判到后再走 1 秒
  （`hold_w_until_combat`，和自动防御共用）。
- **游戏内「自动轮次」开关会干扰轮次计算**：进难度选择界面后、点「选择密函」前必须关掉
  （`ensure_auto_rounds_off`）。判据是开启时多出的「轮次x/99」行
  （`LETTER_AUTO_ROUNDS_STATE` 框）加标题行上移约 95px；开关在标题行**右侧**的滑块
  （标题左边 +543px）；每 2 秒复检直到确认关掉。
- **轮次体系是两层**：配置轮次（探险轮次/扼守轮次，默认 20）= 每局打几轮；任务列表各栏
  的「持有数」= 总上限，进列表挑任务时读最新的。每局打完在结算界面累加
  （`account_mission_rounds`）；**驱离单独按「进一次结算界面 = 一轮」计**
  （`account_drive_away_round`），它没有波次概念。信息栏「轮次计算」显示 已打/上限，
  回列表重挑时归零并重读最新持有数（`update_rounds_info`）。
- **密函开完判据（`letter_exhausted`）要防抖**：读密函卡行的持有数角标
  （`LETTER_CARD_ROW`，已放宽到 y370-470），角色密函的立绘格角标单帧可能读不到 ——
  连续 `LETTER_EXHAUSTED_CONFIRM_SECONDS`（2 秒）读不到才算开完，防止单帧误判提前撤离。
- **刷新时间到点**：探险/扼守要把**当前局**打完再回列表（`_leave_after_rounds` 标志，
  半路丢下副本会丢奖励）；驱离照旧直接回。
- **撤离走统一状态机 `CommissionsTask.leave_mission_once()`**（`quit_mission`/
  `give_up_mission` 共用，都不抛异常；`give_up_mission` 的 ESC 菜单坑见「委托/防御任务的
  状态机」）：按顺序判 行动抉择弹窗 -> 点「撤离」（`COORD.ACTION_RETREAT`）；二次确认
  弹窗 -> 点「确定」（判据失效兜底固定坐标 `COORD.RESET_TRANSPORT_OK`）；局内 ESC 菜单
  -> 点「放弃挑战」（`COORD.ESC_GIVEUP`）；都不在 -> 局内按 ESC 等菜单。密函副本和委托
  副本的撤离是同一套。
  - **行动抉择弹窗就是每一小波打完的那个弹窗**（左侧已完成轮次列表 + 底部「撤离」），
    不是特殊界面。它的「撤离」绿色门形图标判据（`DISCRIMINATORS` 里的
    `ACTION_DIALOG_RETREAT`）在实拍上偶发匹配不上 —— 所以加了文字兜底
    `find_retreat_button()`：认说明行「选择撤离则直接结算当前奖励」，再点它下面
    「撤/撒+离」按钮 OCR 到的实际位置。
  - **OCR 常把「撤」认成「撒」**：`RETREAT_BUTTON_RE = [撤撒]离`。
- **测试模块两个，分工不同**（都在左栏「半自动」下方的「测试」板块）：
  - 「行动逻辑测试」（`AutoDungeonActionTestTask`）：判地图 -> 跑 `DUNGEON_MAPS` 里
    登记的行动序列，用来验证正式逻辑；配置里也可以指定地图。
  - 「行动逻辑脚本测试」（`AutoActionLogicScriptTask`，默认热键 F8）：原样跑
    `mod/行动逻辑/*.json` 里自由填的 steps，用来**试新序列**；试好的序列再固化进
    `DungeonActionMixin` 的 `execute_*` 方法。正式逻辑**不读 json**，别把两者搞混。
- **挂机模式在自动开密函里是死配置**：`move_on_begin` 被注入 external_movement
  （`walk_to_aim`）时整段跳过挂机模式。自动防御（`Auto65ArtifactTask_Fast`）的
  「挂机模式」同理失效，但自动扼守直接跑时仍生效，所以共享定义没删。
