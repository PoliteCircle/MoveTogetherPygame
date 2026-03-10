"""
mapedit.py
==========
pygame 图形化地图编辑器（支持中文输入法 + 关卡名/文件名统一 + 30步内求解）。

本版本特点：
1. 右侧只保留“地形 / 目标位置 / 角色”三个资源类别按钮。
2. 点击资源类别按钮后，会弹出资源选择面板，显示该类别下所有资源。
3. 用户点击资源面板中的某一项后，即可选择当前画笔。
4. 资源选择面板和打开文件面板均为“模态”：
   - 面板打开时，点击不会再穿透到底下地图。
   - 面板打开时，不会显示地图高亮框。
   - 面板打开时，也不会拖拽绘制地图。
5. 关卡名 / 文件名合并为同一个名字：
   - 编辑时只输入一个“关卡名”
   - 保存文件名自动使用清洗后的关卡名并拼接 .json
6. 支持中文输入法：
   - 使用 pygame.TEXTINPUT 接收已确认文本
   - 使用 pygame.TEXTEDITING 显示预编辑串
   - 进入输入时启动 start_text_input()，退出时 stop_text_input()
7. 增加“求30步内最短解”按钮：
   - 调用 core.solve_level_bfs()
   - 若无解或最短解大于30步，则显示“30步内无解”
8. 三类资源均通过数组配置，方便后续扩展。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import pygame

from core import (
    ACTOR_EMPTY,
    ACTOR_SOIL,
    BG_COLOR,
    Button,
    CELL_SIZE,
    EDITOR_PANEL_WIDTH,
    GOAL_EMPTY,
    GOAL_SOIL,
    MOVE_TO_CHAR,
    PANEL_COLOR,
    SUB_TEXT_COLOR,
    TERRAIN_FLOOR,
    TERRAIN_STONE,
    TERRAIN_VOID,
    LevelData,
    create_empty_level,
    draw_cell_overlay,
    draw_level,
    draw_text,
    load_level,
    save_level,
    solve_level_bfs,
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LEVEL_DIR = BASE_DIR / "levels"
MAX_SOLUTION_STEPS = 30


# =============================================================================
# 可扩展资源配置
# =============================================================================

TERRAIN_RESOURCES = [
    {"id": TERRAIN_VOID, "name": "虚空"},
    {"id": TERRAIN_FLOOR, "name": "平地"},
    {"id": TERRAIN_STONE, "name": "石头"},
]

ACTOR_RESOURCES = [
    {"id": ACTOR_EMPTY, "name": "空"},
    {"id": ACTOR_SOIL, "name": "土人"},
]

GOAL_RESOURCES = [
    {"id": GOAL_EMPTY, "name": "空"},
    {"id": GOAL_SOIL, "name": "土人目标"},
]


# =============================================================================
# 基础辅助函数
# =============================================================================

def sanitize_filename(name: str) -> str:
    """
    粗略清洗用户输入的文件名。

    中文、英文、数字、下划线、减号、点号都允许。
    """
    name = name.strip().replace(" ", "_")
    result = []
    for ch in name:
        if ch.isalnum() or ch in "-_().[]{}":
            result.append(ch)
        elif "\u4e00" <= ch <= "\u9fff":
            result.append(ch)
    cleaned = "".join(result).strip("._")
    return cleaned or "new_level"


def list_level_files(level_dir: Path) -> List[Path]:
    """列出关卡目录中所有 json 文件。"""
    level_dir.mkdir(parents=True, exist_ok=True)
    return sorted(level_dir.glob("*.json"), key=lambda p: p.name.lower())


def resize_level_keep_data(level: LevelData, new_width: int, new_height: int) -> LevelData:
    """修改地图尺寸，同时尽可能保留原有内容。"""
    new_width = max(1, new_width)
    new_height = max(1, new_height)

    new_level = create_empty_level(new_width, new_height, level.name)
    new_level.victory_mode = level.victory_mode

    for y in range(min(level.height, new_height)):
        for x in range(min(level.width, new_width)):
            new_level.terrain[y][x] = level.terrain[y][x]
            new_level.actors[y][x] = level.actors[y][x]
            new_level.goals[y][x] = level.goals[y][x]

    return new_level


def get_resources_for_layer(layer: str) -> List[dict]:
    """根据层名返回对应的资源配置数组。"""
    if layer == "terrain":
        return TERRAIN_RESOURCES
    if layer == "actors":
        return ACTOR_RESOURCES
    return GOAL_RESOURCES


def screen_pos_to_grid(
    mx: int,
    my: int,
    offset_x: int,
    offset_y: int,
    cell_size: int,
    level: LevelData,
) -> Optional[Tuple[int, int]]:
    """将屏幕坐标转换为地图格子坐标。"""
    grid_w = level.width * cell_size
    grid_h = level.height * cell_size

    if not (offset_x <= mx < offset_x + grid_w and offset_y <= my < offset_y + grid_h):
        return None

    gx = (mx - offset_x) // cell_size
    gy = (my - offset_y) // cell_size

    if 0 <= gx < level.width and 0 <= gy < level.height:
        return int(gx), int(gy)
    return None


def unified_name_to_filename(name: str) -> str:
    """将统一名称转换为保存文件名（自动补 .json）。"""
    base = name.strip()
    if base.lower().endswith(".json"):
        base = base[:-5]
    return sanitize_filename(base) + ".json"


def format_solution(path_moves: List[str]) -> str:
    """把 ['up','right'] 这样的方向列表格式化成 'UR' 这样的紧凑字符串。"""
    return "".join(MOVE_TO_CHAR[m] for m in path_moves)


def solve_with_step_limit(level: LevelData, max_steps: int = MAX_SOLUTION_STEPS) -> Optional[List[str]]:
    """
    求解关卡，但只把 max_steps 步内的解视为有效。

    注意：由于当前未直接控制 core.solve_level_bfs() 的内部搜索深度，
    这里是对其返回结果再做一步长度限制。
    若返回结果长度 > max_steps，则视为“max_steps步内无解”。
    """
    solution = solve_level_bfs(level)
    if solution is None:
        return None
    if len(solution) > max_steps:
        return None
    return solution


# =============================================================================
# 编辑器状态类
# =============================================================================

class EditorState:
    """将编辑器运行中的变量集中管理。"""

    def __init__(self, level_dir: Path):
        self.level_dir = level_dir
        self.level_dir.mkdir(parents=True, exist_ok=True)

        self.level: LevelData = create_empty_level(8, 8, "新关卡")
        self.file_name: str = unified_name_to_filename(self.level.name)

        self.current_layer: str = "terrain"

        self.terrain_brush: int = TERRAIN_FLOOR
        self.actor_brush: int = ACTOR_SOIL
        self.goal_brush: int = GOAL_SOIL

        self.status_text: str = "欢迎使用地图编辑器"
        self.solution_text: str = "尚未计算"

        self.show_open_panel: bool = False
        self.resource_picker_layer: Optional[str] = None

        self.text_input_mode: Optional[str] = None
        self.text_buffer: str = ""

        # 输入法预编辑状态（例如拼音未上屏时）
        self.composition_text: str = ""
        self.composition_cursor: int = 0

    def current_brush_value(self) -> int:
        if self.current_layer == "terrain":
            return self.terrain_brush
        if self.current_layer == "actors":
            return self.actor_brush
        return self.goal_brush

    def set_current_brush_value(self, value: int) -> None:
        if self.current_layer == "terrain":
            self.terrain_brush = value
        elif self.current_layer == "actors":
            self.actor_brush = value
        else:
            self.goal_brush = value

    def cycle_layer(self) -> None:
        order = ["terrain", "actors", "goals"]
        i = order.index(self.current_layer)
        self.current_layer = order[(i + 1) % len(order)]
        self.status_text = f"已切换到 {self.current_layer} 层"

    def set_unified_name(self, name: str) -> None:
        """统一设置关卡名和文件名。"""
        cleaned_name = name.strip() or "未命名关卡"
        self.level.name = cleaned_name
        self.file_name = unified_name_to_filename(cleaned_name)


# =============================================================================
# 编辑器逻辑函数
# =============================================================================

def start_text_input(editor: EditorState, mode: str) -> None:
    """进入文本输入模式，并启用系统输入法文本输入。"""
    editor.text_input_mode = mode
    editor.resource_picker_layer = None
    editor.show_open_panel = False
    editor.composition_text = ""
    editor.composition_cursor = 0

    # 当前版本只有“统一名称”输入模式
    editor.text_buffer = editor.level.name
    editor.status_text = "请输入关卡名（文件名将自动同步），按回车确认"

    pygame.key.start_text_input()
    pygame.key.set_text_input_rect(pygame.Rect(40, 740, 600, 40))


def stop_text_input(editor: EditorState) -> None:
    """退出文本输入模式并关闭系统文本输入。"""
    editor.text_input_mode = None
    editor.text_buffer = ""
    editor.composition_text = ""
    editor.composition_cursor = 0
    pygame.key.stop_text_input()


def finish_text_input(editor: EditorState) -> None:
    """结束文本输入模式并提交修改。"""
    editor.set_unified_name(editor.text_buffer)
    editor.status_text = f"名称已更新为：{editor.level.name}，文件将保存为：{editor.file_name}"
    stop_text_input(editor)


def load_into_editor(editor: EditorState, path: Path) -> None:
    """加载关卡文件。"""
    editor.level = load_level(path)
    editor.file_name = path.name
    editor.status_text = f"已打开关卡：{editor.level.name}（{path.name}）"
    editor.show_open_panel = False
    editor.resource_picker_layer = None
    editor.solution_text = "尚未计算"


def save_current(editor: EditorState) -> None:
    """保存当前关卡到 levels 目录。"""
    # 保存前再次同步，保证名称和文件名一致
    editor.file_name = unified_name_to_filename(editor.level.name)
    save_path = editor.level_dir / editor.file_name
    save_level(editor.level, save_path)
    editor.status_text = f"已保存：{save_path.name}"


def compute_solution(editor: EditorState) -> None:
    """计算30步内最短解并显示结果。"""
    solution = solve_with_step_limit(editor.level, MAX_SOLUTION_STEPS)
    if solution is None:
        editor.solution_text = f"{MAX_SOLUTION_STEPS}步内无解"
        editor.status_text = f"求解完成：{MAX_SOLUTION_STEPS}步内无解"
        return

    if not solution:
        editor.solution_text = "初始状态已通关"
        editor.status_text = "求解完成：初始状态已通关"
        return

    compact = format_solution(solution)
    editor.solution_text = f"{len(solution)}步: {compact}"
    editor.status_text = f"求解完成：最短 {len(solution)} 步"


def apply_paint(editor: EditorState, gx: int, gy: int, erase: bool = False) -> None:
    """在指定网格位置应用当前画笔。"""
    if not (0 <= gx < editor.level.width and 0 <= gy < editor.level.height):
        return

    if editor.current_layer == "terrain":
        editor.level.terrain[gy][gx] = TERRAIN_FLOOR if erase else editor.terrain_brush
    elif editor.current_layer == "actors":
        editor.level.actors[gy][gx] = ACTOR_EMPTY if erase else editor.actor_brush
    else:
        editor.level.goals[gy][gx] = GOAL_EMPTY if erase else editor.goal_brush

    # 地图修改后，求解结果失效
    editor.solution_text = "地图已修改，请重新计算"


# =============================================================================
# 绘制侧边栏与面板
# =============================================================================

def build_sidebar_buttons(window_w: int) -> List[Tuple[str, Button]]:
    """构建右侧按钮列表。"""
    left = window_w - EDITOR_PANEL_WIDTH + 18
    top = 140
    width = EDITOR_PANEL_WIDTH - 36
    height = 34
    gap = 8

    items = [
        ("pick_terrain", "地形"),
        ("pick_goals", "目标位置"),
        ("pick_actors", "角色"),
        ("solve", f"求{MAX_SOLUTION_STEPS}步内最短解"),
        ("new", "新建关卡"),
        ("save", "保存"),
        ("open", "打开"),
        ("name", "修改名称"),
        ("w-", "宽度 -"),
        ("w+", "宽度 +"),
        ("h-", "高度 -"),
        ("h+", "高度 +"),
    ]

    out: List[Tuple[str, Button]] = []
    for i, (key, text) in enumerate(items):
        rect = pygame.Rect(left, top + i * (height + gap), width, height)
        out.append((key, Button(rect, text)))
    return out


def handle_button(editor: EditorState, key: str) -> None:
    """根据按钮 key 执行对应操作。"""
    if key == "pick_terrain":
        editor.current_layer = "terrain"
        editor.resource_picker_layer = "terrain"
        editor.show_open_panel = False
        editor.status_text = "请选择地形画笔"

    elif key == "pick_actors":
        editor.current_layer = "actors"
        editor.resource_picker_layer = "actors"
        editor.show_open_panel = False
        editor.status_text = "请选择角色画笔"

    elif key == "pick_goals":
        editor.current_layer = "goals"
        editor.resource_picker_layer = "goals"
        editor.show_open_panel = False
        editor.status_text = "请选择目标位置画笔"

    elif key == "solve":
        editor.resource_picker_layer = None
        editor.show_open_panel = False
        compute_solution(editor)

    elif key == "new":
        editor.level = create_empty_level(8, 8, "新关卡")
        editor.file_name = unified_name_to_filename(editor.level.name)
        editor.resource_picker_layer = None
        editor.show_open_panel = False
        editor.solution_text = "尚未计算"
        editor.status_text = "已新建空白关卡"

    elif key == "save":
        save_current(editor)

    elif key == "open":
        editor.show_open_panel = not editor.show_open_panel
        editor.resource_picker_layer = None
        editor.status_text = "已打开文件面板" if editor.show_open_panel else "已关闭文件面板"

    elif key == "name":
        start_text_input(editor, "name")

    elif key == "w-":
        editor.level = resize_level_keep_data(editor.level, editor.level.width - 1, editor.level.height)
        editor.solution_text = "地图已修改，请重新计算"
        editor.status_text = f"宽度改为 {editor.level.width}"

    elif key == "w+":
        editor.level = resize_level_keep_data(editor.level, editor.level.width + 1, editor.level.height)
        editor.solution_text = "地图已修改，请重新计算"
        editor.status_text = f"宽度改为 {editor.level.width}"

    elif key == "h-":
        editor.level = resize_level_keep_data(editor.level, editor.level.width, editor.level.height - 1)
        editor.solution_text = "地图已修改，请重新计算"
        editor.status_text = f"高度改为 {editor.level.height}"

    elif key == "h+":
        editor.level = resize_level_keep_data(editor.level, editor.level.width, editor.level.height + 1)
        editor.solution_text = "地图已修改，请重新计算"
        editor.status_text = f"高度改为 {editor.level.height}"


def draw_sidebar(
    screen: pygame.Surface,
    editor: EditorState,
    window_w: int,
    window_h: int,
    mouse_pos: Tuple[int, int],
) -> None:
    """绘制右侧边栏。"""
    panel_rect = pygame.Rect(window_w - EDITOR_PANEL_WIDTH, 0, EDITOR_PANEL_WIDTH, window_h)
    pygame.draw.rect(screen, PANEL_COLOR, panel_rect)
    pygame.draw.line(screen, (90, 94, 104), (panel_rect.left, 0), (panel_rect.left, window_h), 2)

    draw_text(screen, "地图编辑器", panel_rect.left + 18, 16, 28)
    draw_text(screen, f"名称：{editor.level.name}", panel_rect.left + 18, 50, 20)
    draw_text(screen, f"文件：{editor.file_name}", panel_rect.left + 18, 76, 20)
    draw_text(screen, f"尺寸：{editor.level.width} x {editor.level.height}", panel_rect.left + 18, 102, 20)

    buttons = build_sidebar_buttons(window_w)
    for _, btn in buttons:
        btn.draw(screen, mouse_pos)

    info_y = window_h - 220
    draw_text(screen, f"当前层：{editor.current_layer}", panel_rect.left + 18, info_y, 22)
    draw_text(screen, f"当前画笔编号：{editor.current_brush_value()}", panel_rect.left + 18, info_y + 28, 22)
    draw_text(screen, f"求解：{editor.solution_text}", panel_rect.left + 18, info_y + 56, 18, color=(210, 220, 240))
    draw_text(screen, "鼠标左键绘制，右键擦除", panel_rect.left + 18, info_y + 86, 18, SUB_TEXT_COLOR)
    draw_text(screen, "点击“地形/角色/目标位置”选择画笔", panel_rect.left + 18, info_y + 108, 18, SUB_TEXT_COLOR)
    draw_text(screen, f"求解按钮：只检查{MAX_SOLUTION_STEPS}步内", panel_rect.left + 18, info_y + 130, 18, SUB_TEXT_COLOR)
    draw_text(screen, "S保存 | O打开 | N改名称", panel_rect.left + 18, info_y + 152, 18, SUB_TEXT_COLOR)
    draw_text(screen, "+/-改宽高 | ESC退出/关闭弹窗", panel_rect.left + 18, info_y + 174, 18, SUB_TEXT_COLOR)


def draw_open_panel(
    screen: pygame.Surface,
    level_files: List[Path],
    mouse_pos: Tuple[int, int],
    max_width: int,
    max_height: int,
) -> List[Tuple[Path, pygame.Rect]]:
    """绘制文件列表弹窗，返回每个文件对应的可点击区域。"""
    rect = pygame.Rect(40, 40, max_width, max_height)
    pygame.draw.rect(screen, (30, 32, 38), rect, border_radius=10)
    pygame.draw.rect(screen, (140, 140, 150), rect, 2, border_radius=10)
    draw_text(screen, "打开关卡文件", rect.left + 16, rect.top + 14, 28)
    draw_text(screen, "点击任意条目即可加载，弹窗打开时不会绘制地图", rect.left + 16, rect.top + 46, 18, SUB_TEXT_COLOR)

    clickable: List[Tuple[Path, pygame.Rect]] = []
    y = rect.top + 80
    for path in level_files[:18]:
        item_rect = pygame.Rect(rect.left + 16, y, rect.width - 32, 32)
        hovered = item_rect.collidepoint(mouse_pos)
        color = (78, 82, 94) if hovered else (58, 62, 72)
        pygame.draw.rect(screen, color, item_rect, border_radius=6)
        pygame.draw.rect(screen, (130, 130, 142), item_rect, 1, border_radius=6)
        draw_text(screen, path.name, item_rect.left + 10, item_rect.top + 6, 20)
        clickable.append((path, item_rect))
        y += 38
        if y > rect.bottom - 40:
            break
    return clickable


def draw_resource_preview(
    screen: pygame.Surface,
    layer: str,
    resource_id: int,
    preview_rect: pygame.Rect,
) -> None:
    """在资源选择面板中绘制单个资源预览。"""
    preview_level = create_empty_level(1, 1, "preview")
    preview_level.terrain[0][0] = TERRAIN_FLOOR
    preview_level.actors[0][0] = ACTOR_EMPTY
    preview_level.goals[0][0] = GOAL_EMPTY

    if layer == "terrain":
        preview_level.terrain[0][0] = resource_id
    elif layer == "actors":
        preview_level.actors[0][0] = resource_id
    else:
        preview_level.goals[0][0] = resource_id

    pygame.draw.rect(screen, (120, 126, 140), preview_rect, 1)

    cell_size = preview_rect.width - 8
    inner_rect = pygame.Rect(0, 0, cell_size, cell_size)
    inner_rect.center = preview_rect.center

    draw_level(
        screen,
        preview_level,
        offset_x=inner_rect.x,
        offset_y=inner_rect.y,
        cell_size=cell_size,
    )


def draw_resource_picker_panel(
    screen: pygame.Surface,
    editor: EditorState,
    mouse_pos: Tuple[int, int],
    max_width: int,
    max_height: int,
) -> List[Tuple[int, pygame.Rect]]:
    """绘制资源选择面板。"""
    if editor.resource_picker_layer is None:
        return []

    resources = get_resources_for_layer(editor.resource_picker_layer)

    panel_rect = pygame.Rect(40, 40, max_width, max_height)
    pygame.draw.rect(screen, (30, 32, 38), panel_rect, border_radius=10)
    pygame.draw.rect(screen, (140, 140, 150), panel_rect, 2, border_radius=10)

    title_map = {
        "terrain": "选择地形画笔",
        "actors": "选择角色画笔",
        "goals": "选择目标位置画笔",
    }
    draw_text(screen, title_map.get(editor.resource_picker_layer, "选择画笔"), panel_rect.left + 16, panel_rect.top + 14, 28)
    draw_text(screen, "点击任意资源即可切换当前画笔，按 ESC 关闭", panel_rect.left + 16, panel_rect.top + 46, 18, SUB_TEXT_COLOR)

    clickable: List[Tuple[int, pygame.Rect]] = []

    item_x = panel_rect.left + 20
    item_y = panel_rect.top + 86
    item_w = panel_rect.width - 40
    item_h = 64
    gap = 12
    preview_size = 40

    current_brush = editor.current_brush_value()

    for res in resources:
        res_id = res["id"]
        res_name = res["name"]

        row_rect = pygame.Rect(item_x, item_y, item_w, item_h)
        hovered = row_rect.collidepoint(mouse_pos)
        selected = (res_id == current_brush)

        if selected:
            bg = (78, 105, 170)
            text_color = (255, 255, 255)
        elif hovered:
            bg = (78, 82, 94)
            text_color = (235, 235, 240)
        else:
            bg = (58, 62, 72)
            text_color = (225, 225, 230)

        pygame.draw.rect(screen, bg, row_rect, border_radius=8)
        pygame.draw.rect(screen, (130, 130, 142), row_rect, 1, border_radius=8)

        preview_rect = pygame.Rect(row_rect.left + 10, row_rect.top + 12, preview_size, preview_size)
        draw_resource_preview(screen, editor.resource_picker_layer, res_id, preview_rect)

        draw_text(
            screen,
            f"{res_name} (编号 {res_id})",
            row_rect.left + 84,
            row_rect.top + 18,
            22,
            color=text_color,
        )

        clickable.append((res_id, row_rect))
        item_y += item_h + gap

        if item_y > panel_rect.bottom - 70:
            break

    return clickable


# =============================================================================
# 主入口
# =============================================================================

def run_editor(level_dir: Optional[Path] = None, initial_file: Optional[Path] = None) -> None:
    """启动地图编辑器窗口。"""
    pygame.init()
    level_dir = level_dir or DEFAULT_LEVEL_DIR
    editor = EditorState(level_dir)

    if initial_file is not None and initial_file.exists():
        load_into_editor(editor, initial_file)

    window_w = 1200
    window_h = 840
    screen = pygame.display.set_mode((window_w, window_h))
    pygame.display.set_caption("一起移动！游戏 - 地图编辑器")
    clock = pygame.time.Clock()

    dragging_left = False
    dragging_right = False
    running = True

    while running:
        mouse_pos = pygame.mouse.get_pos()
        level_files = list_level_files(editor.level_dir)

        # 左侧工作区中，地图上方预留一块区域专门显示求解结果
        top_info_height = 80

        grid_w = editor.level.width * CELL_SIZE
        grid_h = editor.level.height * CELL_SIZE
        work_w = window_w - EDITOR_PANEL_WIDTH
        available_h = window_h - top_info_height

        # 地图显示区域位置：尽量在“预留标题区”下面居中
        offset_x = max(20, (work_w - grid_w) // 2)
        offset_y = max(top_info_height, top_info_height + (available_h - grid_h) // 2)

        if grid_w > work_w - 40:
            offset_x = 20
        if grid_h > available_h - 40:
            offset_y = top_info_height

        # 按钮命中区域必须在事件处理前构建
        buttons = build_sidebar_buttons(window_w)

        # 输入法候选框参考位置，尽量放到可见输入框附近
        if editor.text_input_mode is not None:
            pygame.key.set_text_input_rect(pygame.Rect(40, window_h - 100, work_w - 80, 54))

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break

            # -----------------------------
            # 文本输入模式下，优先处理输入法 / 文本输入
            # -----------------------------
            if editor.text_input_mode is not None:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        editor.status_text = "已取消输入"
                        stop_text_input(editor)

                    elif event.key == pygame.K_RETURN:
                        finish_text_input(editor)

                    elif event.key == pygame.K_BACKSPACE:
                        editor.text_buffer = editor.text_buffer[:-1]

                elif event.type == pygame.TEXTINPUT:
                    # 输入法确认上屏后的文本（中文输入的关键）
                    editor.text_buffer += event.text
                    editor.composition_text = ""
                    editor.composition_cursor = 0

                elif event.type == pygame.TEXTEDITING:
                    # 输入法预编辑串，例如拼音还未确认时
                    editor.composition_text = event.text
                    editor.composition_cursor = event.start

                continue

            # -----------------------------
            # 键盘快捷键
            # -----------------------------
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if editor.resource_picker_layer is not None:
                        editor.resource_picker_layer = None
                        editor.status_text = "已关闭资源选择面板"
                    elif editor.show_open_panel:
                        editor.show_open_panel = False
                        editor.status_text = "已关闭文件列表"
                    else:
                        running = False
                        break

                elif event.key == pygame.K_TAB:
                    editor.cycle_layer()
                    editor.resource_picker_layer = editor.current_layer
                    editor.show_open_panel = False

                elif event.key == pygame.K_s:
                    save_current(editor)

                elif event.key == pygame.K_o:
                    editor.show_open_panel = not editor.show_open_panel
                    editor.resource_picker_layer = None
                    editor.status_text = "已打开文件列表" if editor.show_open_panel else "已关闭文件列表"

                elif event.key == pygame.K_n:
                    start_text_input(editor, "name")

                elif event.key == pygame.K_f:
                    # 兼容旧快捷键，仍然进入统一名称输入
                    start_text_input(editor, "name")

                elif event.key == pygame.K_h:
                    compute_solution(editor)

                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                    if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                        editor.level = resize_level_keep_data(editor.level, editor.level.width, editor.level.height + 1)
                        editor.solution_text = "地图已修改，请重新计算"
                        editor.status_text = f"高度改为 {editor.level.height}"
                    else:
                        editor.level = resize_level_keep_data(editor.level, editor.level.width + 1, editor.level.height)
                        editor.solution_text = "地图已修改，请重新计算"
                        editor.status_text = f"宽度改为 {editor.level.width}"

                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                        editor.level = resize_level_keep_data(editor.level, editor.level.width, editor.level.height - 1)
                        editor.solution_text = "地图已修改，请重新计算"
                        editor.status_text = f"高度改为 {editor.level.height}"
                    else:
                        editor.level = resize_level_keep_data(editor.level, editor.level.width - 1, editor.level.height)
                        editor.solution_text = "地图已修改，请重新计算"
                        editor.status_text = f"宽度改为 {editor.level.width}"

            # -----------------------------
            # 鼠标按下/抬起
            # -----------------------------
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    # 1) 先处理资源选择面板点击（模态）
                    if editor.resource_picker_layer is not None:
                        picker_items = draw_resource_picker_panel(
                            screen,
                            editor,
                            event.pos,
                            min(560, work_w - 80),
                            window_h - 80,
                        )

                        for resource_id, rect in picker_items:
                            if rect.collidepoint(event.pos):
                                editor.set_current_brush_value(resource_id)
                                editor.status_text = f"已选择 {editor.resource_picker_layer} 画笔：{resource_id}"
                                editor.resource_picker_layer = None
                                break

                        continue

                    # 2) 再处理打开文件面板点击（模态）
                    if editor.show_open_panel:
                        panel_items = draw_open_panel(
                            screen,
                            level_files,
                            event.pos,
                            min(560, work_w - 80),
                            window_h - 80,
                        )

                        for path, rect in panel_items:
                            if rect.collidepoint(event.pos):
                                load_into_editor(editor, path)
                                break

                        continue

                    # 3) 再处理侧边栏按钮点击
                    clicked_button = False
                    for key, btn in buttons:
                        if btn.rect.collidepoint(event.pos):
                            handle_button(editor, key)
                            clicked_button = True
                            break
                    if clicked_button:
                        continue

                    # 4) 最后处理地图区域绘制
                    mx, my = event.pos
                    if mx < window_w - EDITOR_PANEL_WIDTH:
                        grid_pos = screen_pos_to_grid(mx, my, offset_x, offset_y, CELL_SIZE, editor.level)
                        if grid_pos is not None:
                            gx, gy = grid_pos
                            apply_paint(editor, gx, gy, erase=False)
                            dragging_left = True

                elif event.button == 3:
                    if editor.resource_picker_layer is not None or editor.show_open_panel or editor.text_input_mode is not None:
                        continue

                    mx, my = event.pos
                    if mx < window_w - EDITOR_PANEL_WIDTH:
                        grid_pos = screen_pos_to_grid(mx, my, offset_x, offset_y, CELL_SIZE, editor.level)
                        if grid_pos is not None:
                            gx, gy = grid_pos
                            apply_paint(editor, gx, gy, erase=True)
                            dragging_right = True

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    dragging_left = False
                elif event.button == 3:
                    dragging_right = False

            elif event.type == pygame.MOUSEMOTION:
                if editor.resource_picker_layer is not None or editor.show_open_panel or editor.text_input_mode is not None:
                    continue

                mx, my = event.pos
                if mx < window_w - EDITOR_PANEL_WIDTH:
                    grid_pos = screen_pos_to_grid(mx, my, offset_x, offset_y, CELL_SIZE, editor.level)
                    if grid_pos is not None:
                        gx, gy = grid_pos
                        if dragging_left:
                            apply_paint(editor, gx, gy, erase=False)
                        elif dragging_right:
                            apply_paint(editor, gx, gy, erase=True)

        # =============================
        # 绘制本帧
        # =============================
        screen.fill(BG_COLOR)

        # 将求解结果显示在地图区域上方，而不是右侧边栏，便于显示更长的答案
        draw_text(
            screen,
            f"求解结果：{editor.solution_text}",
            offset_x,
            max(16, offset_y - 48),
            24,
            color=(235, 235, 180),
        )

        draw_level(
            screen,
            editor.level,
            offset_x=offset_x,
            offset_y=offset_y,
            cell_size=CELL_SIZE,
        )

        # 只有在没有任何弹窗时，才显示地图高亮框
        if (
            editor.resource_picker_layer is None
            and not editor.show_open_panel
            and editor.text_input_mode is None
        ):
            mx, my = mouse_pos
            grid_pos = screen_pos_to_grid(mx, my, offset_x, offset_y, CELL_SIZE, editor.level)
            if grid_pos is not None:
                gx, gy = grid_pos
                cell_rect = pygame.Rect(
                    offset_x + gx * CELL_SIZE,
                    offset_y + gy * CELL_SIZE,
                    CELL_SIZE,
                    CELL_SIZE,
                )
                draw_cell_overlay(screen, cell_rect, True)

        draw_sidebar(screen, editor, window_w, window_h, mouse_pos)

        if editor.show_open_panel:
            draw_open_panel(screen, level_files, mouse_pos, min(560, work_w - 80), window_h - 80)

        if editor.resource_picker_layer is not None:
            draw_resource_picker_panel(
                screen,
                editor,
                mouse_pos,
                min(560, work_w - 80),
                window_h - 80,
            )

        # 文本输入框
        if editor.text_input_mode is not None:
            box = pygame.Rect(40, window_h - 100, work_w - 80, 54)
            pygame.draw.rect(screen, (245, 245, 248), box, border_radius=8)
            pygame.draw.rect(screen, (60, 60, 66), box, 2, border_radius=8)
            label = "名称："
            display_text = label + editor.text_buffer
            if editor.composition_text:
                display_text += f" [{editor.composition_text}]"
            draw_text(screen, display_text, box.left + 12, box.top + 12, 24, color=(20, 20, 20))
            draw_text(screen, "保存文件名会自动同步为：" + unified_name_to_filename(editor.text_buffer or editor.level.name), box.left + 12, box.top - 22, 18, color=(220, 220, 230))

        # 底部状态条
        pygame.draw.rect(screen, (20, 22, 26), (0, window_h - 28, window_w, 28))
        draw_text(screen, editor.status_text, 8, window_h - 24, 18)

        pygame.display.flip()
        clock.tick(60)

    pygame.key.stop_text_input()
    pygame.display.quit()


if __name__ == "__main__":
    run_editor()
