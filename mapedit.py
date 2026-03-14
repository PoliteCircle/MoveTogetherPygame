
## mapedit.py
"""
mapedit.py
==========
pygame 图形化地图编辑器（支持中文输入法 + 关卡名/文件名统一 + BFS求解）。

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
7. 增加“求最短解”按钮：
   - 调用 core.solve_level_bfs()
   - 若无解或已搜索过大空间则显示“无解”
8. 三类资源均通过数组配置，方便后续扩展。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pygame
import shutil

from core import (
    LevelData,
    analyze_level_state_graph,
    create_empty_level,
    level_from_actor_state,
    level_to_dict,
    load_level,
    save_level,
    # solve_level_bfs,
)

from game_render import (
    BG_COLOR,
    Button,
    CELL_SIZE,
    EDITOR_PANEL_WIDTH,
    PANEL_COLOR,
    SUB_TEXT_COLOR,
    draw_actor,
    draw_cell_overlay,
    draw_goal,
    draw_level,
    draw_terrain,
    draw_text,
)

from game_rules import (
    ACTOR_EMPTY,
    GOAL_EMPTY,
    TERRAIN_FLOOR,
    TERRAIN_VOID,
    actor_name,
    can_place_actor,
    can_place_goal,
    get_base_brush_by_group,
    get_resource_groups, MOVE_TO_CHAR,
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LEVEL_DIR = BASE_DIR / "levels"
MAX_SOLUTION_STEPS = 100


# =============================================================================
# 可扩展资源配置 统一从 game_rules.py 读取
# =============================================================================



# =============================================================================
# 工具函数
# =============================================================================


def ensure_level_dir(level_dir: Optional[Path] = None) -> Path:
    path = Path(level_dir) if level_dir is not None else DEFAULT_LEVEL_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path

def list_level_entries(current_dir: Path, root_dir: Path) -> List[Path]:
    current_dir = ensure_level_dir(current_dir)
    root_dir = ensure_level_dir(root_dir)

    entries: List[Path] = []

    current_resolved = current_dir.resolve()
    root_resolved = root_dir.resolve()

    # 第一个条目：返回上级目录
    if current_resolved != root_resolved:
        entries.append(current_dir.parent)

    subdirs = sorted(
        [p for p in current_dir.iterdir() if p.is_dir()],
        key=lambda p: p.name.lower()
    )
    json_files = sorted(
        [p for p in current_dir.iterdir() if p.is_file() and p.suffix.lower() == ".json"],
        key=lambda p: p.name.lower()
    )

    entries.extend(subdirs)
    entries.extend(json_files)
    return entries

def list_level_files() -> List[Path]:
    ensure_level_dir()
    files = sorted(DEFAULT_LEVEL_DIR.glob("*.json"), key=lambda p: p.name.lower())
    return files



def sanitize_filename(name: str) -> str:
    """
    将关卡名清洗成适合当文件名的字符串。
    这里不显示 .json，保存时自动拼接。
    """
    forbidden = '<>:"/\\|?*'
    result = []
    for ch in name.strip():
        if ch in forbidden:
            result.append("_")
        else:
            result.append(ch)
    text = "".join(result).strip().strip(".")
    return text or "untitled"



def solution_moves_to_text(moves: Optional[List[str]]) -> str:
    if moves is None:
        return f"{MAX_SOLUTION_STEPS}步内无解"
    if len(moves) == 0:
        return "已在目标状态"
    chars = [MOVE_TO_CHAR.get(m, m) for m in moves]
    return f"共{len(moves)}步：" + " ".join(chars)



def format_solution(moves: Optional[List[str]]) -> str:
    return solution_moves_to_text(moves)



def apply_brush(level: LevelData, x: int, y: int, brush_group: str, brush_id: int) -> None:
    if not (0 <= x < level.width and 0 <= y < level.height):
        return

    if brush_group == "terrain":
        level.terrain[y][x] = brush_id
        if brush_id == TERRAIN_VOID:
            level.actors[y][x] = ACTOR_EMPTY
            level.actor_status[y][x] = 0
            level.goals[y][x] = GOAL_EMPTY

    elif brush_group == "goal":
        if can_place_goal(level, x, y):
            level.goals[y][x] = brush_id

    elif brush_group == "actor":
        if can_place_actor(level, x, y):
            level.actors[y][x] = brush_id
            level.actor_status[y][x] = 0



def resize_level(old_level: LevelData, new_width: int, new_height: int) -> LevelData:
    new_level = create_empty_level(new_width, new_height, name=old_level.name)
    new_level.victory_mode = old_level.victory_mode

    copy_w = min(old_level.width, new_width)
    copy_h = min(old_level.height, new_height)
    for y in range(copy_h):
        for x in range(copy_w):
            new_level.terrain[y][x] = old_level.terrain[y][x]
            new_level.actors[y][x] = old_level.actors[y][x]
            new_level.actor_status[y][x] = old_level.actor_status[y][x]
            new_level.goals[y][x] = old_level.goals[y][x]
    return new_level


def open_state_space_window(editor: "EditorState") -> None:
    if editor.last_state_graph is None:
        editor.status_text = "请先求解一次，再查看状态空间"
        return

    try:
        import json
        import tempfile

        payload = {
            "static_level": level_to_dict(editor.level),
            "states": [
                [
                    {
                        "x": int(x),
                        "y": int(y),
                        "actor_id": int(actor_id),
                        "stun_turns": int(stun_turns),
                    }
                    for x, y, actor_id, stun_turns in state
                ]
                for state in editor.last_state_graph.states
            ],
            "depths": [int(d) for d in editor.last_state_graph.depths],
            "edges": [
                {"src": int(src), "dst": int(dst), "move": move}
                for src, dst, move in editor.last_state_graph.edges
            ],
            "parents": [None if p is None else int(p) for p in editor.last_state_graph.parents],
            "parent_moves": list(editor.last_state_graph.parent_moves),
            "start_index": int(editor.last_state_graph.start_index),
            "solution_index": None if editor.last_state_graph.solution_index is None else int(editor.last_state_graph.solution_index),
            "solution_moves": editor.last_state_graph.solution_moves,
            "expanded_count": int(editor.last_state_graph.expanded_count),
            "truncated": bool(editor.last_state_graph.truncated),
            "max_steps": int(MAX_SOLUTION_STEPS),
        }

        temp_dir = Path(tempfile.mkdtemp(prefix="mapedit_state_space_"))
        json_path = temp_dir / "state_space.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        viewer_path = Path(__file__).resolve().parent / "state_space.py"
        subprocess.Popen([sys.executable, str(viewer_path), "--state-space-json", str(json_path)])
        editor.status_text = "已打开状态空间窗口"

    except Exception as e:
        editor.status_text = f"打开状态空间失败：{e}"

# =============================================================================
# 编辑器状态
# =============================================================================

class EditorState:
    def __init__(self) -> None:
        self.level: LevelData = create_empty_level(8, 8, name="新关卡")

        base_brushes = get_base_brush_by_group()
        self.selected_brush_by_group: Dict[str, int] = dict(base_brushes)
        self.current_brush_group: str = "terrain"
        self.current_brush_id: int = self.selected_brush_by_group["terrain"]

        self.status_text: str = "欢迎使用地图编辑器"
        self.solution_text: str = "尚未求解"
        self.last_solution_moves: Optional[List[str]] = None
        self.last_state_graph = None

        self.resource_panel_open: bool = False
        self.resource_panel_group: Optional[str] = None

        self.open_file_panel_open: bool = False
        self.open_file_paths: List[Path] = []

        self.root_level_dir: Path = DEFAULT_LEVEL_DIR
        self.current_level_dir: Path = DEFAULT_LEVEL_DIR
        self.open_panel_dir: Path = DEFAULT_LEVEL_DIR

        self.open_selected_path: Optional[Path] = None
        self.open_selected_is_back: bool = False
        self.open_last_click_path: Optional[Path] = None
        self.open_last_click_is_back: bool = False
        self.open_last_click_ms: int = 0

        self.open_dialog_mode: Optional[str] = None  # None / "mkdir" / "rename"
        self.open_dialog_text: str = ""
        self.open_dialog_composition: str = ""

        self.open_confirm_delete: bool = False
        self.open_confirm_target: Optional[Path] = None

        self.editing_name: bool = False
        self.name_input: str = self.level.name
        self.ime_composition: str = ""

        self.editing_width: bool = False
        self.width_input: str = str(self.level.width)
        self.editing_height: bool = False
        self.height_input: str = str(self.level.height)

        self.drag_painting: bool = False
        self.paint_mouse_button: int = 1
        self.last_painted_cell: Optional[Tuple[int, int]] = None


# =============================================================================
# UI 布局计算
# =============================================================================


def get_window_size(level: LevelData) -> Tuple[int, int]:
    map_w = level.width * CELL_SIZE
    map_h = level.height * CELL_SIZE

    extra_w = 120
    extra_h = 100

    # 给右下角更宽的“最短解输出区”预留高度
    solution_area_h = 130

    min_map_area_w = map_w + extra_w
    min_map_area_h = map_h + extra_h + solution_area_h

    w = EDITOR_PANEL_WIDTH + min_map_area_w
    h = max(720, min_map_area_h)
    return w, h


def get_rects(level: LevelData, screen_size: Optional[Tuple[int, int]] = None) -> Dict[str, pygame.Rect]:
    map_w = level.width * CELL_SIZE
    map_h = level.height * CELL_SIZE

    if screen_size is None:
        screen_w, screen_h = get_window_size(level)
    else:
        screen_w, screen_h = screen_size

    panel_rect = pygame.Rect(0, 0, EDITOR_PANEL_WIDTH, screen_h)

    right_area_rect = pygame.Rect(
        panel_rect.right,
        0,
        max(0, screen_w - panel_rect.width),
        screen_h,
    )

    solution_h = 120
    gap = 12

    solution_rect = pygame.Rect(
        right_area_rect.x + 16,
        right_area_rect.bottom - solution_h - 16,
        max(0, right_area_rect.width - 32),
        solution_h,
    )

    map_area_rect = pygame.Rect(
        right_area_rect.x,
        right_area_rect.y,
        right_area_rect.width,
        max(0, solution_rect.top - right_area_rect.top - gap),
    )

    map_rect = pygame.Rect(0, 0, map_w, map_h)
    map_rect.center = map_area_rect.center

    rects = {
        "right_area": right_area_rect,
        "map_area": map_area_rect,
        "map": map_rect,
        "solution_rect": solution_rect,
        "panel": panel_rect,
        "name_label": pygame.Rect(panel_rect.left + 16, 16, 100, 24),
        "name_input": pygame.Rect(panel_rect.left + 16, 44, panel_rect.width - 32, 34),
    }
    return rects


def build_buttons(level: LevelData) -> Dict[str, Button]:
    panel_left = 0
    panel_w = EDITOR_PANEL_WIDTH

    left_x = panel_left + 16
    gap = 8
    col_w = (panel_w - 32 - gap) // 2
    right_x = left_x + col_w + gap

    buttons: Dict[str, Button] = {}

    # 宽高调节按钮
    size_y = 96
    small_w = 34
    small_h = 34

    buttons["w_minus"] = Button(pygame.Rect(left_x, size_y, small_w, small_h), "-")
    buttons["w_plus"] = Button(pygame.Rect(left_x + col_w - small_w, size_y, small_w, small_h), "+")
    buttons["h_minus"] = Button(pygame.Rect(right_x, size_y, small_w, small_h), "-")
    buttons["h_plus"] = Button(pygame.Rect(right_x + col_w - small_w, size_y, small_w, small_h), "+")

    # 第一行：资源按钮
    y = 146
    buttons["terrain"] = Button(pygame.Rect(left_x, y, col_w, 68), "选择地形")
    buttons["goal"] = Button(pygame.Rect(right_x, y, col_w, 68), "选择目标位置")

    # 第二行：资源按钮 + 求解
    y += 76
    buttons["actor"] = Button(pygame.Rect(left_x, y, col_w, 68), "选择角色")
    buttons["solve"] = Button(pygame.Rect(right_x, y, col_w, 68), f"求{MAX_SOLUTION_STEPS}步内最短解")

    # 第三行：普通按钮
    y += 76
    buttons["new"] = Button(pygame.Rect(left_x, y, col_w, 36), "新建关卡")
    buttons["save"] = Button(pygame.Rect(right_x, y, col_w, 36), "保存关卡")

    # 第四行：普通按钮
    y += 44
    buttons["open"] = Button(pygame.Rect(left_x, y, col_w, 36), "打开关卡")
    buttons["state_space"] = Button(pygame.Rect(right_x, y, col_w, 36), "查看状态空间")

    return buttons


# =============================================================================
# 绘制输入框 / 面板
# =============================================================================

def _get_resource_modal_rect(panel_rect: pygame.Rect, group: str) -> pygame.Rect:
    resource_groups = get_resource_groups()
    item_count = len(resource_groups[group]["items"])
    modal_h = 78 + item_count * 50 + 18
    return pygame.Rect(panel_rect.left + 8, 150, panel_rect.width - 16, modal_h)


def _draw_resource_preview(
    screen: pygame.Surface,
    group: str,
    item_id: int,
    rect: pygame.Rect,
) -> None:
    pygame.draw.rect(screen, (28, 30, 36), rect, border_radius=6)

    if group == "terrain":
        draw_terrain(screen, rect, item_id)
    elif group == "goal":
        draw_terrain(screen, rect, TERRAIN_FLOOR)
        draw_goal(screen, rect, item_id)
    elif group == "actor":
        draw_terrain(screen, rect, TERRAIN_FLOOR)
        draw_actor(screen, rect, item_id)

    pygame.draw.rect(screen, (120, 124, 136), rect, 1, border_radius=6)


def _draw_resource_button(
    screen: pygame.Surface,
    rect: pygame.Rect,
    title: str,
    group: str,
    item_id: int,
    hovered: bool,
    selected: bool,
) -> None:
    resource_groups = get_resource_groups()
    base_brushes = get_base_brush_by_group()

    fill = (95, 98, 112) if hovered else (70, 72, 82)
    if selected:
        fill = (92, 98, 112)
    border = (240, 212, 92) if selected else (120, 124, 136)

    pygame.draw.rect(screen, fill, rect, border_radius=8)
    pygame.draw.rect(screen, border, rect, 2, border_radius=8)

    thumb = pygame.Rect(rect.x + 8, rect.y + 8, rect.height - 16, rect.height - 16)
    _draw_resource_preview(screen, group, item_id, thumb)

    item_name = next(
        item["name"]
        for item in resource_groups[group]["items"]
        if item["id"] == item_id
    )
    base_name = next(
        item["name"]
        for item in resource_groups[group]["items"]
        if item["id"] == base_brushes[group]
    )

    draw_text(screen, title, thumb.right + 10, rect.y + 5, 20)
    draw_text(screen, f"左键：{item_name}", thumb.right + 10, rect.y + 27, 16, SUB_TEXT_COLOR)
    draw_text(screen, f"右键：{base_name}", thumb.right + 10, rect.y + 44, 16, SUB_TEXT_COLOR)


def _get_paint_brush_id(editor: EditorState, mouse_button: int) -> int:
    if mouse_button == 3:
        return get_base_brush_by_group()[editor.current_brush_group]
    return editor.current_brush_id

def draw_input_box(
    screen: pygame.Surface,
    rect: pygame.Rect,
    text: str,
    active: bool,
    placeholder: str = "",
    composition: str = "",
) -> None:
    fill = (48, 50, 58) if active else (40, 42, 50)
    border = (235, 205, 88) if active else (90, 94, 106)
    pygame.draw.rect(screen, fill, rect, border_radius=6)
    pygame.draw.rect(screen, border, rect, 2, border_radius=6)

    font = pygame.font.SysFont("microsoftyahei,simhei,arial", 24)
    base_x = rect.x + 8
    base_y = rect.y + 6

    if text:
        img = font.render(text, True, (235, 235, 235))
        screen.blit(img, (base_x, base_y))
    else:
        img = None
        draw_text(screen, placeholder, base_x, base_y, 24, SUB_TEXT_COLOR)

    if active and composition:
        text_width = font.size(text)[0]
        comp_img = font.render(composition, True, (255, 210, 150))
        screen.blit(comp_img, (base_x + text_width, base_y))

    if active and _is_blink_cursor_visible():
        cursor_x = base_x + font.size(text + composition)[0]
        cursor_top = rect.y + 7
        cursor_bottom = rect.bottom - 7
        pygame.draw.line(screen, (245, 245, 245), (cursor_x, cursor_top), (cursor_x, cursor_bottom), 2)


def draw_resource_panel(screen: pygame.Surface, editor: EditorState, panel_rect: pygame.Rect) -> None:
    resource_groups = get_resource_groups()

    if not editor.resource_panel_open or not editor.resource_panel_group:
        return

    group = editor.resource_panel_group
    group_info = resource_groups[group]
    items = group_info["items"]

    bg = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    bg.fill((0, 0, 0, 120))
    screen.blit(bg, (0, 0))

    modal = _get_resource_modal_rect(panel_rect, group)
    pygame.draw.rect(screen, (42, 44, 52), modal, border_radius=10)
    pygame.draw.rect(screen, (108, 112, 125), modal, 2, border_radius=10)

    draw_text(screen, group_info["title"], modal.x + 16, modal.y + 12, 26)

    y = modal.y + 52
    for item in items:
        item_rect = pygame.Rect(modal.x + 16, y, modal.width - 32, 40)
        selected = (
            editor.current_brush_group == group
            and editor.current_brush_id == item["id"]
        )
        color = (92, 98, 112) if selected else (66, 70, 82)
        border = (240, 212, 92) if selected else (110, 114, 128)

        pygame.draw.rect(screen, color, item_rect, border_radius=6)
        pygame.draw.rect(screen, border, item_rect, 2, border_radius=6)

        thumb = pygame.Rect(item_rect.x + 6, item_rect.y + 4, 32, 32)
        _draw_resource_preview(screen, group, item["id"], thumb)

        draw_text(screen, item["name"], item_rect.x + 48, item_rect.y + 8, 20)
        y += 50

    tip_y = modal.bottom - 30
    draw_text(screen, "点击一项选择；点击空白处关闭", modal.x + 16, tip_y, 18, SUB_TEXT_COLOR)



def draw_open_panel(screen: pygame.Surface, editor: EditorState, panel_rect: pygame.Rect) -> None:
    if not editor.open_file_panel_open:
        return

    bg = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    bg.fill((0, 0, 0, 120))
    screen.blit(bg, (0, 0))

    modal, list_top, list_bottom, buttons = _get_open_panel_layout(screen.get_size())

    pygame.draw.rect(screen, (42, 44, 52), modal, border_radius=12)
    pygame.draw.rect(screen, (108, 112, 125), modal, 2, border_radius=12)

    draw_text(screen, "打开关卡", modal.x + 18, modal.y + 16, 28)

    try:
        rel_dir = editor.open_panel_dir.resolve().relative_to(editor.root_level_dir.resolve())
        rel_text = "." if str(rel_dir) in ("", ".") else str(rel_dir)
    except Exception:
        rel_text = str(editor.open_panel_dir)

    draw_text(screen, f"当前目录：{rel_text}", modal.x + 18, modal.y + 52, 18, SUB_TEXT_COLOR)
    draw_text(screen, "单击选择；双击打开目录或关卡；底部按钮可新建目录 / 重命名 / 删除", modal.x + 18, modal.y + 76, 18, SUB_TEXT_COLOR)

    y = list_top
    if not editor.open_file_paths:
        draw_text(screen, "当前目录下没有子目录或 json 关卡文件", modal.x + 18, y, 22, SUB_TEXT_COLOR)
    else:
        can_go_up = editor.open_panel_dir.resolve() != editor.root_level_dir.resolve()

        for idx, path in enumerate(editor.open_file_paths):
            item_rect = pygame.Rect(modal.x + 18, y, modal.width - 36, 36)

            is_back_item = can_go_up and idx == 0 and path.resolve() == editor.open_panel_dir.parent.resolve()
            is_dir = (not is_back_item) and path.is_dir()

            if is_back_item:
                label = "[返回上级目录] .."
                fill = (88, 86, 70)
            elif is_dir:
                label = f"[目录] {path.name}/"
                fill = (62, 76, 92)
            else:
                label = f"[关卡] {path.name}"
                fill = (66, 70, 82)

            selected = (
                editor.open_selected_path is not None
                and editor.open_selected_path.resolve() == path.resolve()
                and editor.open_selected_is_back == is_back_item
            )
            border = (240, 212, 92) if selected else (110, 114, 128)

            pygame.draw.rect(screen, fill, item_rect, border_radius=6)
            pygame.draw.rect(screen, border, item_rect, 2, border_radius=6)
            draw_text(screen, label, item_rect.x + 10, item_rect.y + 6, 22)

            y += 44
            if y + 40 > list_bottom:
                break

    for key, rect in buttons.items():
        fill = (72, 76, 88)
        if rect.collidepoint(pygame.mouse.get_pos()):
            fill = (92, 98, 112)
        pygame.draw.rect(screen, fill, rect, border_radius=6)
        pygame.draw.rect(screen, (120, 124, 136), rect, 2, border_radius=6)

    draw_text(screen, "新建目录", buttons["mkdir"].x + 16, buttons["mkdir"].y + 6, 20)
    draw_text(screen, "重命名", buttons["rename"].x + 20, buttons["rename"].y + 6, 20)
    draw_text(screen, "删除", buttons["delete"].x + 30, buttons["delete"].y + 6, 20)
    draw_text(screen, "关闭", buttons["close"].x + 30, buttons["close"].y + 6, 20)

    if editor.open_dialog_mode is not None:
        dim = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 90))
        screen.blit(dim, (0, 0))

        dialog, input_rect, ok_rect, cancel_rect = _get_open_dialog_layout(modal)
        pygame.draw.rect(screen, (48, 50, 58), dialog, border_radius=10)
        pygame.draw.rect(screen, (120, 124, 136), dialog, 2, border_radius=10)

        title = "新建目录" if editor.open_dialog_mode == "mkdir" else "重命名"
        draw_text(screen, title, dialog.x + 18, dialog.y + 16, 26)
        draw_input_box(
            screen,
            input_rect,
            editor.open_dialog_text,
            True,
            placeholder="请输入名称",
            composition=editor.open_dialog_composition,
        )

        for rect, text in [(ok_rect, "确定"), (cancel_rect, "取消")]:
            fill = (72, 76, 88)
            if rect.collidepoint(pygame.mouse.get_pos()):
                fill = (92, 98, 112)
            pygame.draw.rect(screen, fill, rect, border_radius=6)
            pygame.draw.rect(screen, (120, 124, 136), rect, 2, border_radius=6)
            draw_text(screen, text, rect.x + 30, rect.y + 6, 22)

    if editor.open_confirm_delete:
        dim = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 110))
        screen.blit(dim, (0, 0))

        dialog, ok_rect, cancel_rect = _get_confirm_dialog_layout(modal)
        pygame.draw.rect(screen, (48, 50, 58), dialog, border_radius=10)
        pygame.draw.rect(screen, (120, 124, 136), dialog, 2, border_radius=10)

        draw_text(screen, "确认删除", dialog.x + 18, dialog.y + 16, 26)

        target_name = editor.open_confirm_target.name if editor.open_confirm_target is not None else ""
        draw_text(screen, "确定要删除以下对象吗？", dialog.x + 18, dialog.y + 56, 22, SUB_TEXT_COLOR)
        draw_text(screen, target_name, dialog.x + 18, dialog.y + 90, 22, (255, 210, 140))

        for rect, text in [(ok_rect, "确认删除"), (cancel_rect, "取消")]:
            fill = (72, 76, 88)
            if rect.collidepoint(pygame.mouse.get_pos()):
                fill = (92, 98, 112)
            pygame.draw.rect(screen, fill, rect, border_radius=6)
            pygame.draw.rect(screen, (120, 124, 136), rect, 2, border_radius=6)
            draw_text(screen, text, rect.x + 16, rect.y + 6, 22)

def _get_open_panel_layout(screen_size: Tuple[int, int]):
    modal = pygame.Rect(40, 40, screen_size[0] - 80, screen_size[1] - 80)

    button_y = modal.bottom - 52
    gap = 10
    btn_w = (modal.width - 36 - gap * 3) // 4

    buttons = {
        "mkdir": pygame.Rect(modal.x + 18, button_y, btn_w, 34),
        "rename": pygame.Rect(modal.x + 18 + (btn_w + gap), button_y, btn_w, 34),
        "delete": pygame.Rect(modal.x + 18 + (btn_w + gap) * 2, button_y, btn_w, 34),
        "close": pygame.Rect(modal.x + 18 + (btn_w + gap) * 3, button_y, btn_w, 34),
    }

    list_top = modal.y + 112
    list_bottom = button_y - 12
    return modal, list_top, list_bottom, buttons


def _get_open_dialog_layout(modal: pygame.Rect):
    dialog = pygame.Rect(modal.centerx - 220, modal.centery - 90, 440, 180)
    input_rect = pygame.Rect(dialog.x + 20, dialog.y + 62, dialog.width - 40, 38)
    ok_rect = pygame.Rect(dialog.x + 78, dialog.bottom - 52, 110, 34)
    cancel_rect = pygame.Rect(dialog.right - 188, dialog.bottom - 52, 110, 34)
    return dialog, input_rect, ok_rect, cancel_rect

def _is_blink_cursor_visible() -> bool:
    return (pygame.time.get_ticks() // 500) % 2 == 0


def _get_confirm_dialog_layout(modal: pygame.Rect):
    dialog = pygame.Rect(modal.centerx - 220, modal.centery - 90, 440, 180)
    ok_rect = pygame.Rect(dialog.x + 78, dialog.bottom - 52, 110, 34)
    cancel_rect = pygame.Rect(dialog.right - 188, dialog.bottom - 52, 110, 34)
    return dialog, ok_rect, cancel_rect


def _begin_delete_confirm(editor: EditorState) -> None:
    if editor.open_selected_path is None or editor.open_selected_is_back:
        editor.status_text = "请先选择要删除的目录或关卡"
        return
    stop_all_text_edit(editor)
    editor.open_confirm_delete = True
    editor.open_confirm_target = editor.open_selected_path


def _close_delete_confirm(editor: EditorState) -> None:
    editor.open_confirm_delete = False
    editor.open_confirm_target = None


def _apply_delete_confirm(editor: EditorState) -> None:
    target = editor.open_confirm_target
    if target is None:
        _close_delete_confirm(editor)
        return

    try:
        if target.is_dir():
            shutil.rmtree(target)
            editor.status_text = f"已删除目录：{target.name}"
        else:
            target.unlink()
            editor.status_text = f"已删除文件：{target.name}"
    except Exception as e:
        editor.status_text = f"删除失败：{e}"
        _close_delete_confirm(editor)
        return

    editor.open_selected_path = None
    editor.open_selected_is_back = False
    editor.open_last_click_path = None
    editor.open_last_click_is_back = False
    _refresh_open_panel_entries(editor)
    _close_delete_confirm(editor)


def _refresh_open_panel_entries(editor: EditorState) -> None:
    editor.open_file_paths = list_level_entries(editor.open_panel_dir, editor.root_level_dir)

    if editor.open_selected_path is not None:
        if editor.open_selected_is_back:
            can_go_up = editor.open_panel_dir.resolve() != editor.root_level_dir.resolve()
            if not can_go_up or editor.open_selected_path.resolve() != editor.open_panel_dir.parent.resolve():
                editor.open_selected_path = None
                editor.open_selected_is_back = False
        else:
            if not editor.open_selected_path.exists():
                editor.open_selected_path = None
                editor.open_selected_is_back = False


def _sanitize_entry_name(name: str) -> str:
    forbidden = '<>:"/\\|?*'
    result = []
    for ch in name.strip():
        result.append("_" if ch in forbidden else ch)
    text = "".join(result).strip().strip(".")
    return text


def _begin_open_dialog(editor: EditorState, mode: str) -> None:
    stop_all_text_edit(editor)
    editor.open_dialog_mode = mode
    editor.open_dialog_composition = ""

    if mode == "rename" and editor.open_selected_path is not None and not editor.open_selected_is_back:
        if editor.open_selected_path.is_file():
            editor.open_dialog_text = editor.open_selected_path.stem
        else:
            editor.open_dialog_text = editor.open_selected_path.name
    else:
        editor.open_dialog_text = ""

    pygame.key.start_text_input()


def _close_open_dialog(editor: EditorState) -> None:
    editor.open_dialog_mode = None
    editor.open_dialog_text = ""
    editor.open_dialog_composition = ""
    pygame.key.stop_text_input()


def _apply_open_dialog(editor: EditorState) -> None:
    raw_name = editor.open_dialog_text.strip()
    name = _sanitize_entry_name(raw_name)

    if not name:
        editor.status_text = "名称不能为空"
        return

    if editor.open_dialog_mode == "mkdir":
        new_dir = editor.open_panel_dir / name
        if new_dir.exists():
            editor.status_text = "该目录已存在"
            return
        new_dir.mkdir(parents=False, exist_ok=False)
        editor.current_level_dir = editor.open_panel_dir
        editor.open_selected_path = new_dir
        editor.open_selected_is_back = False
        _refresh_open_panel_entries(editor)
        _close_open_dialog(editor)
        editor.status_text = f"已新建目录：{new_dir.name}"
        return

    if editor.open_dialog_mode == "rename":
        if editor.open_selected_path is None or editor.open_selected_is_back:
            editor.status_text = "请先选择要重命名的文件或目录"
            return

        src = editor.open_selected_path
        if src.is_file():
            new_name = name if name.lower().endswith(".json") else f"{name}.json"
        else:
            new_name = name

        dst = src.with_name(new_name)
        if dst.exists() and dst.resolve() != src.resolve():
            editor.status_text = "目标名称已存在"
            return

        src.rename(dst)

        if editor.current_level_dir.resolve() == src.resolve():
            editor.current_level_dir = dst
        if editor.open_panel_dir.resolve() == src.resolve():
            editor.open_panel_dir = dst

        editor.open_selected_path = dst
        editor.open_selected_is_back = False
        _refresh_open_panel_entries(editor)
        _close_open_dialog(editor)
        editor.status_text = f"已重命名为：{dst.name}"
        return

def _wrap_text_to_pixel_width(text: str, font: pygame.font.Font, max_width: int) -> List[str]:
    """
    按像素宽度换行，而不是按固定字符数换行。
    """
    if not text:
        return [""]

    lines: List[str] = []
    current = ""

    for ch in text:
        test = current + ch
        if font.size(test)[0] <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = ch

    if current:
        lines.append(current)

    return lines


def draw_ui(screen: pygame.Surface, editor: EditorState, mouse_pos: Tuple[int, int]) -> Dict[str, Button]:
    resource_groups = get_resource_groups()
    base_brushes = get_base_brush_by_group()

    rects = get_rects(editor.level, screen.get_size())
    panel_rect = rects["panel"]
    solution_rect = rects["solution_rect"]

    pygame.draw.rect(screen, PANEL_COLOR, panel_rect)
    pygame.draw.line(screen, (80, 82, 94), (panel_rect.left, 0), (panel_rect.left, panel_rect.height), 2)

    draw_text(screen, "关卡名", rects["name_label"].x, rects["name_label"].y, 22)
    draw_input_box(
        screen,
        rects["name_input"],
        editor.name_input,
        editor.editing_name,
        placeholder="请输入关卡名",
        composition=editor.ime_composition if editor.editing_name else "",
    )

    buttons = build_buttons(editor.level)

    w_minus_rect = buttons["w_minus"].rect
    w_plus_rect = buttons["w_plus"].rect
    h_minus_rect = buttons["h_minus"].rect
    h_plus_rect = buttons["h_plus"].rect

    w_value_rect = pygame.Rect(
        w_minus_rect.right + 6,
        w_minus_rect.y,
        w_plus_rect.left - w_minus_rect.right - 12,
        w_minus_rect.height,
    )
    h_value_rect = pygame.Rect(
        h_minus_rect.right + 6,
        h_minus_rect.y,
        h_plus_rect.left - h_minus_rect.right - 12,
        h_minus_rect.height,
    )

    draw_text(screen, "宽度", w_minus_rect.x, w_minus_rect.y - 22, 18, SUB_TEXT_COLOR)
    draw_text(screen, "高度", h_minus_rect.x, h_minus_rect.y - 22, 18, SUB_TEXT_COLOR)

    for value_rect, text in [
        (w_value_rect, str(editor.level.width)),
        (h_value_rect, str(editor.level.height)),
    ]:
        pygame.draw.rect(screen, (48, 50, 58), value_rect, border_radius=6)
        pygame.draw.rect(screen, (90, 94, 106), value_rect, 2, border_radius=6)
        font = pygame.font.SysFont("microsoftyahei,simhei,arial", 22)
        img = font.render(text, True, (235, 235, 235))
        img_rect = img.get_rect(center=value_rect.center)
        screen.blit(img, img_rect)

    for key in ("w_minus", "w_plus", "h_minus", "h_plus"):
        btn = buttons[key]
        btn.draw(screen, btn.rect.collidepoint(mouse_pos))

    for key in ("terrain", "goal", "actor"):
        btn = buttons[key]
        _draw_resource_button(
            screen=screen,
            rect=btn.rect,
            title=btn.text,
            group=key,
            item_id=editor.selected_brush_by_group[key],
            hovered=btn.rect.collidepoint(mouse_pos),
            selected=(editor.current_brush_group == key),
        )

    for key in ("solve", "new", "save", "open", "state_space"):
        btn = buttons[key]
        btn.draw(screen, btn.rect.collidepoint(mouse_pos))

    info_y = buttons["open"].rect.bottom + 14

    draw_text(screen, "当前画笔", panel_rect.left + 18, info_y, 22)

    current_name = next(
        item["name"]
        for item in resource_groups[editor.current_brush_group]["items"]
        if item["id"] == editor.current_brush_id
    )
    base_name = next(
        item["name"]
        for item in resource_groups[editor.current_brush_group]["items"]
        if item["id"] == base_brushes[editor.current_brush_group]
    )

    draw_text(screen, f"左键：{current_name}", panel_rect.left + 18, info_y + 28, 18, SUB_TEXT_COLOR)
    draw_text(screen, f"右键：{base_name}", panel_rect.left + 18, info_y + 52, 18, SUB_TEXT_COLOR)

    draw_text(screen, "状态", panel_rect.left + 18, info_y + 84, 22)
    draw_text(screen, editor.status_text, panel_rect.left + 18, info_y + 112, 18, SUB_TEXT_COLOR)
    draw_text(screen, "点击“查看状态空间”打开新窗口", panel_rect.left + 18, info_y + 138, 17, SUB_TEXT_COLOR)

    # ---------- 右侧更宽的最短解输出区 ----------
    pygame.draw.rect(screen, (28, 30, 36), solution_rect, border_radius=10)
    pygame.draw.rect(screen, (96, 102, 112), solution_rect, 2, border_radius=10)

    draw_text(screen, "最短解", solution_rect.x + 16, solution_rect.y + 12, 24)

    solution_font = pygame.font.SysFont("microsoftyahei,simhei,arial", 22)
    max_text_width = solution_rect.width - 32

    wrapped_lines = _wrap_text_to_pixel_width(editor.solution_text, solution_font, max_text_width)

    line_y = solution_rect.y + 46
    for line in wrapped_lines[:3]:
        img = solution_font.render(line, True, (220, 224, 232))
        screen.blit(img, (solution_rect.x + 16, line_y))
        line_y += 28

    return buttons


# =============================================================================
# 事件辅助
# =============================================================================


def stop_all_text_edit(editor: EditorState) -> None:
    editor.editing_name = False
    editor.editing_width = False
    editor.editing_height = False
    editor.ime_composition = ""
    pygame.key.stop_text_input()



def begin_name_edit(editor: EditorState) -> None:
    stop_all_text_edit(editor)
    editor.editing_name = True
    pygame.key.start_text_input()



def begin_width_edit(editor: EditorState) -> None:
    stop_all_text_edit(editor)
    editor.editing_width = True
    editor.ime_composition = ""
    pygame.key.start_text_input()


def begin_height_edit(editor: EditorState) -> None:
    stop_all_text_edit(editor)
    editor.editing_height = True
    editor.ime_composition = ""
    pygame.key.start_text_input()



def do_resize(editor: EditorState) -> None:
    try:
        new_w = max(1, int(editor.width_input))
        new_h = max(1, int(editor.height_input))
    except ValueError:
        editor.status_text = "宽高必须是整数"
        return

    editor.level = resize_level(editor.level, new_w, new_h)
    editor.status_text = f"地图尺寸已调整为 {new_w} x {new_h}"



def do_new_level(editor: EditorState) -> None:
    editor.level = create_empty_level(8, 8, name="新关卡")
    editor.name_input = editor.level.name
    editor.width_input = str(editor.level.width)
    editor.height_input = str(editor.level.height)
    editor.solution_text = "尚未求解"
    editor.last_solution_moves = None
    editor.last_state_graph = None
    editor.status_text = "已新建空白关卡"



def do_save_level(editor: EditorState) -> None:
    editor.level.name = editor.name_input.strip() or "未命名关卡"
    safe_name = sanitize_filename(editor.level.name)

    # 如果文件浏览器当前停留在某目录，就优先保存到那个目录
    save_dir = editor.open_panel_dir if editor.open_file_panel_open else editor.current_level_dir
    save_dir = ensure_level_dir(save_dir)

    path = save_dir / f"{safe_name}.json"
    save_level(editor.level, path)

    editor.current_level_dir = save_dir
    editor.status_text = f"已保存：{path.name}"



def do_open_panel(editor: EditorState) -> None:
    editor.open_panel_dir = ensure_level_dir(editor.current_level_dir)
    editor.open_selected_path = None
    editor.open_selected_is_back = False
    editor.open_last_click_path = None
    editor.open_last_click_is_back = False
    editor.open_last_click_ms = 0
    _refresh_open_panel_entries(editor)
    editor.open_file_panel_open = True
    editor.resource_panel_open = False



def do_load_level(editor: EditorState, path: Path) -> None:
    level = load_level(path)
    editor.level = level
    editor.name_input = level.name
    editor.width_input = str(level.width)
    editor.height_input = str(level.height)
    editor.solution_text = "尚未求解"
    editor.last_solution_moves = None
    editor.last_state_graph = None

    editor.current_level_dir = path.parent
    editor.open_panel_dir = path.parent
    editor.open_selected_path = path
    editor.open_selected_is_back = False

    editor.status_text = f"已打开：{path.name}"



def do_solve(editor: EditorState) -> None:
    level = editor.level.clone()
    graph = analyze_level_state_graph(level, max_depth=MAX_SOLUTION_STEPS)
    editor.last_state_graph = graph
    editor.last_solution_moves = graph.solution_moves
    editor.solution_text = solution_moves_to_text(graph.solution_moves)

    if graph.solution_moves is None:
        editor.status_text = f"搜索完成：{MAX_SOLUTION_STEPS}步内无解"
    else:
        editor.status_text = f"搜索完成：最短解 {len(graph.solution_moves)} 步，状态数 {len(graph.states)}"



def click_resource_panel(editor: EditorState, pos: Tuple[int, int], panel_rect: pygame.Rect) -> bool:
    resource_groups = get_resource_groups()

    if not editor.resource_panel_open or not editor.resource_panel_group:
        return False

    group = editor.resource_panel_group
    modal = _get_resource_modal_rect(panel_rect, group)

    if not modal.collidepoint(pos):
        editor.resource_panel_open = False
        editor.resource_panel_group = None
        return True

    y = modal.y + 52
    for item in resource_groups[group]["items"]:
        item_rect = pygame.Rect(modal.x + 16, y, modal.width - 32, 40)
        if item_rect.collidepoint(pos):
            editor.selected_brush_by_group[group] = item["id"]
            editor.current_brush_group = group
            editor.current_brush_id = item["id"]
            editor.resource_panel_open = False
            editor.resource_panel_group = None
            editor.status_text = f"已选择：{item['name']}"
            return True
        y += 50

    return True



def click_open_panel(editor: EditorState, pos: Tuple[int, int], screen_size: Tuple[int, int]) -> bool:
    if not editor.open_file_panel_open:
        return False

    modal, list_top, list_bottom, buttons = _get_open_panel_layout(screen_size)

    # ---------- 输入对话框优先 ----------
    if editor.open_dialog_mode is not None:
        dialog, input_rect, ok_rect, cancel_rect = _get_open_dialog_layout(modal)

        if ok_rect.collidepoint(pos):
            _apply_open_dialog(editor)
            return True

        if cancel_rect.collidepoint(pos):
            _close_open_dialog(editor)
            return True

        if input_rect.collidepoint(pos):
            return True

        if dialog.collidepoint(pos):
            return True

        return True

    # ---------- 点击面板外部 ----------
    if not modal.collidepoint(pos):
        editor.open_file_panel_open = False
        editor.open_selected_path = None
        editor.open_selected_is_back = False
        return True

    # ---------- 底部按钮 ----------
    if buttons["mkdir"].collidepoint(pos):
        _begin_open_dialog(editor, "mkdir")
        return True

    if buttons["rename"].collidepoint(pos):
        if editor.open_selected_path is None or editor.open_selected_is_back:
            editor.status_text = "请先选择一个目录或关卡"
            return True
        _begin_open_dialog(editor, "rename")
        return True

    if buttons["delete"].collidepoint(pos):
        if editor.open_selected_path is None or editor.open_selected_is_back:
            editor.status_text = "请先选择要删除的目录或关卡"
            return True

        target = editor.open_selected_path
        try:
            if target.is_dir():
                shutil.rmtree(target)
                editor.status_text = f"已删除目录：{target.name}"
            else:
                target.unlink()
                editor.status_text = f"已删除文件：{target.name}"
        except Exception as e:
            editor.status_text = f"删除失败：{e}"
            return True

        editor.open_selected_path = None
        editor.open_selected_is_back = False
        editor.open_last_click_path = None
        editor.open_last_click_is_back = False
        _refresh_open_panel_entries(editor)
        return True

    if buttons["close"].collidepoint(pos):
        editor.open_file_panel_open = False
        return True

    # ---------- 列表项：单击选择，双击打开 ----------
    y = list_top
    can_go_up = editor.open_panel_dir.resolve() != editor.root_level_dir.resolve()

    for idx, path in enumerate(editor.open_file_paths):
        item_rect = pygame.Rect(modal.x + 18, y, modal.width - 36, 36)
        if item_rect.collidepoint(pos):
            is_back_item = can_go_up and idx == 0 and path.resolve() == editor.open_panel_dir.parent.resolve()

            now_ms = pygame.time.get_ticks()
            is_same_as_last = (
                editor.open_last_click_path is not None
                and editor.open_last_click_path.resolve() == path.resolve()
                and editor.open_last_click_is_back == is_back_item
            )
            is_double_click = is_same_as_last and (now_ms - editor.open_last_click_ms <= 350)

            editor.open_selected_path = path
            editor.open_selected_is_back = is_back_item
            editor.open_last_click_path = path
            editor.open_last_click_is_back = is_back_item
            editor.open_last_click_ms = now_ms

            if is_double_click:
                if is_back_item:
                    editor.open_panel_dir = editor.open_panel_dir.parent
                    editor.current_level_dir = editor.open_panel_dir
                    editor.open_selected_path = None
                    editor.open_selected_is_back = False
                    _refresh_open_panel_entries(editor)
                    editor.status_text = f"已进入：{editor.open_panel_dir.name or str(editor.open_panel_dir)}"
                    return True

                if path.is_dir():
                    editor.open_panel_dir = path
                    editor.current_level_dir = path
                    editor.open_selected_path = None
                    editor.open_selected_is_back = False
                    _refresh_open_panel_entries(editor)
                    editor.status_text = f"已进入目录：{path.name}"
                    return True

                do_load_level(editor, path)
                editor.open_file_panel_open = False
                return True

            editor.status_text = f"已选择：{path.name if not is_back_item else '..'}"
            return True

        y += 44
        if y + 40 > list_bottom:
            break

    return True


def handle_button_action(editor: EditorState, key: str) -> None:
    if key in ("terrain", "goal", "actor"):
        editor.resource_panel_open = True
        editor.resource_panel_group = key
        editor.open_file_panel_open = False

    elif key == "w_minus":
        new_w = max(1, editor.level.width - 1)
        editor.level = resize_level(editor.level, new_w, editor.level.height)
        editor.width_input = str(editor.level.width)
        editor.height_input = str(editor.level.height)
        editor.status_text = f"地图宽度已调整为 {editor.level.width}"

    elif key == "w_plus":
        new_w = editor.level.width + 1
        editor.level = resize_level(editor.level, new_w, editor.level.height)
        editor.width_input = str(editor.level.width)
        editor.height_input = str(editor.level.height)
        editor.status_text = f"地图宽度已调整为 {editor.level.width}"

    elif key == "h_minus":
        new_h = max(1, editor.level.height - 1)
        editor.level = resize_level(editor.level, editor.level.width, new_h)
        editor.width_input = str(editor.level.width)
        editor.height_input = str(editor.level.height)
        editor.status_text = f"地图高度已调整为 {editor.level.height}"

    elif key == "h_plus":
        new_h = editor.level.height + 1
        editor.level = resize_level(editor.level, editor.level.width, new_h)
        editor.width_input = str(editor.level.width)
        editor.height_input = str(editor.level.height)
        editor.status_text = f"地图高度已调整为 {editor.level.height}"

    elif key == "new":
        do_new_level(editor)
    elif key == "save":
        do_save_level(editor)
    elif key == "open":
        do_open_panel(editor)
    elif key == "solve":
        do_solve(editor)
    elif key == "state_space":
        open_state_space_window(editor)



# =============================================================================
# 状态空间查看器辅助
# =============================================================================


def _level_from_payload(data: dict) -> LevelData:
    return LevelData(
        name=data.get("name", "状态预览"),
        width=int(data["width"]),
        height=int(data["height"]),
        terrain=[[int(v) for v in row] for row in data["terrain"]],
        actors=[[int(v) for v in row] for row in data["actors"]],
        goals=[[int(v) for v in row] for row in data["goals"]],
        victory_mode=data.get("victory_mode", "all_actors_on_goals"),
    )



def _compute_solution_path_indices(solution_index, parents) -> Set[int]:
    result: Set[int] = set()
    cur = solution_index
    while cur is not None:
        result.add(int(cur))
        cur = parents[cur] if 0 <= cur < len(parents) else None
    return result



def _build_initial_node_positions(depths: List[int]) -> Dict[int, Tuple[float, float]]:
    from collections import defaultdict

    layers = defaultdict(list)
    for idx, depth in enumerate(depths):
        layers[int(depth)].append(idx)

    positions: Dict[int, Tuple[float, float]] = {}
    x_gap = 180
    y_gap = 110
    for depth in sorted(layers.keys()):
        nodes = layers[depth]
        total = len(nodes)
        for i, node_index in enumerate(nodes):
            x = depth * x_gap
            y = (i - (total - 1) / 2.0) * y_gap
            positions[node_index] = (float(x), float(y))
    return positions



def _world_to_screen(pos, graph_rect: pygame.Rect, camera, zoom: float) -> Tuple[int, int]:
    x = graph_rect.left + int(pos[0] * zoom + camera[0])
    y = graph_rect.centery + int(pos[1] * zoom + camera[1])
    return x, y



def _screen_to_world(pos, graph_rect: pygame.Rect, camera, zoom: float) -> Tuple[float, float]:
    x = (pos[0] - graph_rect.left - camera[0]) / zoom
    y = (pos[1] - graph_rect.centery - camera[1]) / zoom
    return x, y


def _zoom_camera_at_screen_pos(
    graph_rect: pygame.Rect,
    camera: List[float],
    zoom: float,
    screen_pos: Tuple[int, int],
    zoom_factor: float,
    min_zoom: float = 0.35,
    max_zoom: float = 3.0,
) -> float:
    """
    以 screen_pos（通常就是鼠标位置）为锚点进行缩放。
    缩放前后，让该屏幕位置对应的世界坐标保持不变。
    """
    old_zoom = zoom
    new_zoom = max(min_zoom, min(max_zoom, old_zoom * zoom_factor))
    if abs(new_zoom - old_zoom) < 1e-9:
        return old_zoom

    world_x, world_y = _screen_to_world(screen_pos, graph_rect, (camera[0], camera[1]), old_zoom)

    camera[0] = screen_pos[0] - graph_rect.left - world_x * new_zoom
    camera[1] = screen_pos[1] - graph_rect.centery - world_y * new_zoom

    return new_zoom


def _find_node_at_screen_pos(screen_pos, graph_rect, positions, camera, zoom, base_radius):
    mx, my = screen_pos
    hit_index = None
    hit_dist2 = None
    radius = max(10, int(base_radius * zoom)) + 4
    for index, pos in positions.items():
        sx, sy = _world_to_screen(pos, graph_rect, camera, zoom)
        dx = mx - sx
        dy = my - sy
        d2 = dx * dx + dy * dy
        if d2 <= radius * radius:
            if hit_dist2 is None or d2 < hit_dist2:
                hit_index = index
                hit_dist2 = d2
    return hit_index



def _draw_arrow(screen, start, end, color, radius_px: int, width: int = 2) -> None:
    import math

    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    dist = math.hypot(dx, dy)
    if dist <= 1:
        return

    ux = dx / dist
    uy = dy / dist

    head_len = max(10, 8 + width * 2)
    head_w = max(6, 4 + width * 2)

    line_start = (sx + ux * radius_px, sy + uy * radius_px)
    line_end = (ex - ux * (radius_px + head_len), ey - uy * (radius_px + head_len))
    pygame.draw.line(screen, color, line_start, line_end, width)

    arrow_tip = (int(ex - ux * radius_px), int(ey - uy * radius_px))
    left = (
        int(arrow_tip[0] - ux * head_len - uy * head_w),
        int(arrow_tip[1] - uy * head_len + ux * head_w),
    )
    right = (
        int(arrow_tip[0] - ux * head_len + uy * head_w),
        int(arrow_tip[1] - uy * head_len - ux * head_w),
    )
    pygame.draw.polygon(screen, color, [arrow_tip, left, right])



def run_state_space_viewer(json_path: Path) -> None:
    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    static_level = _level_from_payload(payload["static_level"])
    states = [
        tuple((int(item["x"]), int(item["y"]), int(item["actor_id"])) for item in state)
        for state in payload["states"]
    ]
    depths = [int(x) for x in payload["depths"]]
    edges = [(int(item["src"]), int(item["dst"]), item["move"]) for item in payload["edges"]]
    parents = payload.get("parents", [None] * len(states))
    parent_moves = payload.get("parent_moves", [None] * len(states))
    solution_index = payload.get("solution_index")
    solution_moves = payload.get("solution_moves")
    expanded_count = int(payload.get("expanded_count", len(states)))
    truncated = bool(payload.get("truncated", False))
    max_steps = int(payload.get("max_steps", MAX_SOLUTION_STEPS))

    solution_path_indices = _compute_solution_path_indices(solution_index, parents)

    solution_path_pairs = set()
    if solution_index is not None:
        cur = solution_index
        while cur is not None and 0 <= cur < len(parents):
            prev = parents[cur]
            if prev is None:
                break
            solution_path_pairs.add(frozenset((prev, cur)))
            cur = prev

    # 当前状态下，按上下左右可到达的下一个状态
    next_state_by_move: Dict[Tuple[int, str], int] = {}
    for src, dst, move in edges:
        next_state_by_move[(src, move)] = dst

    pygame.init()
    window_w = 1580
    window_h = 920
    screen = pygame.display.set_mode((window_w, window_h))
    pygame.display.set_caption("状态空间查看器")
    clock = pygame.time.Clock()

    side_w = 430
    divider_w = 18
    graph_rect = pygame.Rect(0, 0, window_w - side_w - divider_w, window_h)
    divider_rect = pygame.Rect(graph_rect.right, 0, divider_w, window_h)
    side_rect = pygame.Rect(divider_rect.right, 0, side_w, window_h)

    positions = _build_initial_node_positions(depths)
    camera = [60.0, 40.0]
    zoom = 1.0
    base_radius = 15.0

    selected_index = 0 if states else None
    dragging_node: Optional[int] = None
    node_drag_offset = (0.0, 0.0)
    panning = False
    pan_last = (0, 0)

    edge_lookup = {(src, dst) for src, dst, _ in edges}

    running = True
    while running:
        mouse_pos = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                    break

                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                    anchor = mouse_pos if graph_rect.collidepoint(mouse_pos) else graph_rect.center
                    zoom = _zoom_camera_at_screen_pos(graph_rect, camera, zoom, anchor, 1.12)

                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    anchor = mouse_pos if graph_rect.collidepoint(mouse_pos) else graph_rect.center
                    zoom = _zoom_camera_at_screen_pos(graph_rect, camera, zoom, anchor, 1.0 / 1.12)

                # 方向键：等价于点击当前状态沿对应方向可达的状态
                elif selected_index is not None:
                    move_name = None
                    if event.key == pygame.K_UP:
                        move_name = "up"
                    elif event.key == pygame.K_DOWN:
                        move_name = "down"
                    elif event.key == pygame.K_LEFT:
                        move_name = "left"
                    elif event.key == pygame.K_RIGHT:
                        move_name = "right"

                    if move_name is not None:
                        next_index = next_state_by_move.get((selected_index, move_name))
                        if next_index is not None:
                            selected_index = next_index

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if not graph_rect.collidepoint(event.pos):
                    continue

                if event.button == 1:
                    hit = _find_node_at_screen_pos(
                        event.pos,
                        graph_rect,
                        positions,
                        (camera[0], camera[1]),
                        zoom,
                        base_radius,
                    )
                    if hit is not None:
                        selected_index = hit
                        dragging_node = hit
                        wx, wy = _screen_to_world(event.pos, graph_rect, (camera[0], camera[1]), zoom)
                        px, py = positions[hit]
                        node_drag_offset = (wx - px, wy - py)
                elif event.button in (2, 3):
                    panning = True
                    pan_last = event.pos
                elif event.button == 4:
                    zoom = _zoom_camera_at_screen_pos(graph_rect, camera, zoom, event.pos, 1.12)
                elif event.button == 5:
                    zoom = _zoom_camera_at_screen_pos(graph_rect, camera, zoom, event.pos, 1.0 / 1.12)

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    dragging_node = None
                elif event.button in (2, 3):
                    panning = False

            elif event.type == pygame.MOUSEMOTION:
                if dragging_node is not None:
                    wx, wy = _screen_to_world(event.pos, graph_rect, (camera[0], camera[1]), zoom)
                    positions[dragging_node] = (wx - node_drag_offset[0], wy - node_drag_offset[1])
                elif panning:
                    dx = event.pos[0] - pan_last[0]
                    dy = event.pos[1] - pan_last[1]
                    camera[0] += dx
                    camera[1] += dy
                    pan_last = event.pos

            elif event.type == pygame.MOUSEWHEEL:
                if graph_rect.collidepoint(mouse_pos):
                    if event.y > 0:
                        zoom = _zoom_camera_at_screen_pos(graph_rect, camera, zoom, mouse_pos, 1.12)
                    elif event.y < 0:
                        zoom = _zoom_camera_at_screen_pos(graph_rect, camera, zoom, mouse_pos, 1.0 / 1.12)

        connected_indices: Set[int] = set()
        incident_pairs = set()
        if selected_index is not None:
            for src, dst, _ in edges:
                if src == selected_index or dst == selected_index:
                    connected_indices.add(src)
                    connected_indices.add(dst)
                    incident_pairs.add(frozenset((src, dst)))
            connected_indices.discard(selected_index)

        screen.fill((18, 20, 26))
        pygame.draw.rect(screen, (24, 26, 33), graph_rect)
        pygame.draw.rect(screen, (44, 47, 58), divider_rect)
        pygame.draw.rect(screen, (32, 35, 44), side_rect)
        pygame.draw.line(screen, (95, 100, 115), (side_rect.left, 0), (side_rect.left, window_h), 2)

        screen.set_clip(graph_rect)

        draw_text(screen, "状态空间图", graph_rect.left + 22, 14, 30)
        draw_text(
            screen,
            "左键拖拽节点；中键/右键拖动画布；滚轮缩放；↑↓←→切换相邻状态",
            graph_rect.left + 22,
            48,
            18,
            SUB_TEXT_COLOR,
        )

        drawn_bidirectional_pairs = set()
        for src, dst, move in edges:
            if src == dst:
                continue

            pair = frozenset((src, dst))
            is_bidirectional = (dst, src) in edge_lookup
            if is_bidirectional:
                if pair in drawn_bidirectional_pairs:
                    continue
                drawn_bidirectional_pairs.add(pair)

            src_pos = _world_to_screen(positions[src], graph_rect, (camera[0], camera[1]), zoom)
            dst_pos = _world_to_screen(positions[dst], graph_rect, (camera[0], camera[1]), zoom)
            radius_px = max(10, int(base_radius * zoom))

            in_solution = pair in solution_path_pairs
            is_incident = pair in incident_pairs

            if in_solution and is_incident:
                edge_color = (236, 120, 255)
                edge_width = 5
            elif is_incident:
                edge_color = (255, 176, 80)
                edge_width = 4
            elif in_solution:
                edge_color = (88, 182, 255)
                edge_width = 4
            else:
                edge_color = (110, 118, 132)
                edge_width = 2

            if is_bidirectional:
                pygame.draw.line(screen, edge_color, src_pos, dst_pos, edge_width)
            else:
                _draw_arrow(screen, src_pos, dst_pos, edge_color, radius_px, width=edge_width)

        for index, pos in positions.items():
            sx, sy = _world_to_screen(pos, graph_rect, (camera[0], camera[1]), zoom)
            radius = max(10, int(base_radius * zoom))

            if index == 0:
                fill_color = (238, 204, 84)
            elif solution_index is not None and index == solution_index:
                fill_color = (104, 226, 132)
            elif index in solution_path_indices:
                fill_color = (120, 170, 255)
            else:
                fill_color = (200, 205, 214)

            if index in connected_indices:
                pygame.draw.circle(screen, (255, 176, 80), (sx, sy), radius + 5)

            if selected_index == index:
                pygame.draw.circle(screen, (255, 0, 0), (sx, sy), radius + 7)
                pygame.draw.circle(screen, (255, 0, 0), (sx, sy), radius + 4)

            pygame.draw.circle(screen, fill_color, (sx, sy), radius)
            pygame.draw.circle(screen, (35, 38, 46), (sx, sy), radius, 2)

        screen.set_clip(None)

        draw_text(screen, "选中状态", side_rect.left + 18, 18, 28)
        draw_text(screen, f"总状态数：{len(states)}", side_rect.left + 18, 56, 20)
        draw_text(screen, f"总边数：{len(edges)}", side_rect.left + 18, 82, 20)
        draw_text(screen, f"搜索深度上限：{max_steps}", side_rect.left + 18, 108, 20)
        draw_text(screen, f"扩展状态数：{expanded_count}", side_rect.left + 18, 134, 20)

        legend_y = 164
        draw_text(screen, "图例：蓝=最短路径，橙=当前相连，紫=两者同时满足", side_rect.left + 18, legend_y, 16, SUB_TEXT_COLOR)

        if truncated:
            draw_text(screen, "提示：状态空间达到上限，结果已截断", side_rect.left + 18, legend_y + 24, 18, color=(240, 190, 120))

        preview_top = 232
        preview_margin = 18
        preview_w = side_rect.width - preview_margin * 2
        preview_h = 380
        preview_rect = pygame.Rect(side_rect.left + preview_margin, preview_top, preview_w, preview_h)
        pygame.draw.rect(screen, (24, 27, 33), preview_rect, border_radius=10)
        pygame.draw.rect(screen, (96, 102, 112), preview_rect, 2, border_radius=10)

        if selected_index is not None:
            draw_text(screen, f"状态编号：{selected_index}", side_rect.left + 18, 190, 20)
            draw_text(screen, f"BFS 深度：{depths[selected_index]}", side_rect.left + 190, 190, 20)

            if selected_index < len(parents) and parents[selected_index] is not None:
                parent_move = parent_moves[selected_index]
                draw_text(screen, f"由状态 {parents[selected_index]} 经 {parent_move} 到达", side_rect.left + 18, 210, 18, SUB_TEXT_COLOR)
            elif selected_index == 0:
                draw_text(screen, "这是初始状态", side_rect.left + 18, 210, 18, SUB_TEXT_COLOR)

            state_level = level_from_actor_state(static_level, states[selected_index])
            cell_size = max(
                18,
                min(
                    (preview_rect.width - 24) // max(1, state_level.width),
                    (preview_rect.height - 24) // max(1, state_level.height),
                ),
            )
            draw_level(
                screen,
                state_level,
                offset_x=preview_rect.left + 12,
                offset_y=preview_rect.top + 12,
                cell_size=cell_size,
            )

            actor_text = "角色状态：" + ", ".join(
                f"{actor_name(actor_id)}@({x},{y})" + (f"[麻痹{stun_turns}]" if stun_turns > 0 else "")
                for x, y, actor_id, stun_turns in states[selected_index]
            )
            draw_text(screen, actor_text[:36], side_rect.left + 18, preview_rect.bottom + 18, 18, SUB_TEXT_COLOR)
            if len(actor_text) > 36:
                draw_text(screen, actor_text[36:72], side_rect.left + 18, preview_rect.bottom + 40, 18, SUB_TEXT_COLOR)

            draw_text(screen, f"直接相连状态数：{len(connected_indices)}", side_rect.left + 18, preview_rect.bottom + 72, 18, color=(255, 176, 80))

            available_moves = []
            for move_name, arrow_char in [("up", "↑"), ("down", "↓"), ("left", "←"), ("right", "→")]:
                if (selected_index, move_name) in next_state_by_move:
                    available_moves.append(arrow_char)
            if available_moves:
                draw_text(
                    screen,
                    "可用方向键：" + " ".join(available_moves),
                    side_rect.left + 18,
                    preview_rect.bottom + 98,
                    18,
                    color=(180, 220, 255),
                )

            if solution_index is not None:
                if selected_index == solution_index:
                    draw_text(screen, "该状态是一个最短解终点", side_rect.left + 18, preview_rect.bottom + 124, 18, color=(120, 230, 140))
                elif selected_index in solution_path_indices:
                    draw_text(screen, "该状态位于最短解路径上", side_rect.left + 18, preview_rect.bottom + 124, 18, color=(140, 200, 255))

        if solution_moves is None:
            draw_text(screen, f"求解结果：{max_steps}步内无解", side_rect.left + 18, window_h - 78, 20, color=(238, 210, 150))
        elif len(solution_moves) == 0:
            draw_text(screen, "求解结果：初始状态已通关", side_rect.left + 18, window_h - 78, 20, color=(140, 230, 150))
        else:
            compact = format_solution(solution_moves)
            draw_text(screen, f"求解结果：{len(solution_moves)} 步", side_rect.left + 18, window_h - 100, 20, color=(140, 230, 150))
            draw_text(screen, compact[:28], side_rect.left + 18, window_h - 74, 18, color=(220, 230, 240))
            if len(compact) > 28:
                draw_text(screen, compact[28:56], side_rect.left + 18, window_h - 50, 18, color=(220, 230, 240))

        pygame.display.flip()
        clock.tick(60)

    pygame.display.quit()


# =============================================================================
# 主循环
# =============================================================================


def run_editor(level_dir=None) -> None:
    pygame.init()

    resource_groups = get_resource_groups()

    start_dir = ensure_level_dir(Path(level_dir) if level_dir is not None else DEFAULT_LEVEL_DIR)

    editor = EditorState()
    editor.root_level_dir = start_dir
    editor.current_level_dir = start_dir
    editor.open_panel_dir = start_dir

    screen = pygame.display.set_mode(get_window_size(editor.level), pygame.RESIZABLE)
    pygame.display.set_caption("一起移动！地图编辑器")
    clock = pygame.time.Clock()

    running = True
    while running:
        mouse_pos = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break

            if event.type == pygame.TEXTINPUT:
                if editor.open_dialog_mode is not None:
                    editor.open_dialog_text += event.text
                elif editor.editing_name:
                    editor.name_input += event.text
                    editor.level.name = editor.name_input or editor.level.name

            elif event.type == pygame.TEXTEDITING:
                if editor.open_dialog_mode is not None:
                    editor.open_dialog_composition = event.text
                elif editor.editing_name:
                    editor.ime_composition = event.text

            elif event.type == pygame.KEYDOWN:
                if editor.open_dialog_mode is not None:
                    if event.key == pygame.K_ESCAPE:
                        _close_open_dialog(editor)
                    elif event.key == pygame.K_BACKSPACE:
                        if editor.open_dialog_text:
                            editor.open_dialog_text = editor.open_dialog_text[:-1]
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        _apply_open_dialog(editor)
                    continue

                if event.key == pygame.K_ESCAPE:
                    if editor.resource_panel_open:
                        editor.resource_panel_open = False
                        editor.resource_panel_group = None
                    elif editor.open_file_panel_open:
                        editor.open_file_panel_open = False
                        editor.open_selected_path = None
                        editor.open_selected_is_back = False
                    else:
                        stop_all_text_edit(editor)

                elif event.key == pygame.K_BACKSPACE:
                    if editor.editing_name and editor.name_input:
                        editor.name_input = editor.name_input[:-1]

                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if editor.editing_name:
                        editor.level.name = editor.name_input.strip() or "未命名关卡"
                        stop_all_text_edit(editor)

                elif event.key == pygame.K_h:
                    do_solve(editor)
                elif event.key == pygame.K_v:
                    open_state_space_window(editor)

            elif event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
                rects = get_rects(editor.level, screen.get_size())
                panel_rect = rects["panel"]
                map_rect = rects["map"]

                if event.button == 1:
                    if click_resource_panel(editor, event.pos, panel_rect):
                        continue
                    if click_open_panel(editor, event.pos, screen.get_size()):
                        continue

                    if rects["name_input"].collidepoint(event.pos):
                        begin_name_edit(editor)
                        continue
                    else:
                        stop_all_text_edit(editor)

                    buttons = build_buttons(editor.level)

                    handled_resource_thumb = False
                    for key in ("terrain", "goal", "actor"):
                        btn = buttons[key]
                        thumb_rect = pygame.Rect(
                            btn.rect.x + 8,
                            btn.rect.y + 8,
                            btn.rect.height - 16,
                            btn.rect.height - 16,
                        )
                        if thumb_rect.collidepoint(event.pos):
                            editor.current_brush_group = key
                            editor.current_brush_id = editor.selected_brush_by_group[key]
                            editor.resource_panel_open = False
                            editor.resource_panel_group = None
                            editor.open_file_panel_open = False

                            item_name = next(
                                item["name"]
                                for item in resource_groups[key]["items"]
                                if item["id"] == editor.current_brush_id
                            )
                            editor.status_text = f"已切换到：{item_name}"
                            handled_resource_thumb = True
                            break

                    if handled_resource_thumb:
                        continue

                    clicked_button = None
                    for key, btn in buttons.items():
                        if btn.rect.collidepoint(event.pos):
                            clicked_button = key
                            break
                    if clicked_button is not None:
                        handle_button_action(editor, clicked_button)
                        continue

                if (
                    map_rect.collidepoint(event.pos)
                    and not editor.resource_panel_open
                    and not editor.open_file_panel_open
                ):
                    gx = (event.pos[0] - map_rect.left) // CELL_SIZE
                    gy = (event.pos[1] - map_rect.top) // CELL_SIZE
                    brush_id = _get_paint_brush_id(editor, event.button)
                    apply_brush(editor.level, gx, gy, editor.current_brush_group, brush_id)
                    editor.drag_painting = True
                    editor.paint_mouse_button = event.button
                    editor.last_painted_cell = (gx, gy)
                    editor.status_text = f"已绘制到 ({gx}, {gy})"

            elif event.type == pygame.MOUSEBUTTONUP and event.button in (1, 3):
                if editor.drag_painting and editor.paint_mouse_button == event.button:
                    editor.drag_painting = False
                    editor.last_painted_cell = None

            elif event.type == pygame.MOUSEMOTION:
                if editor.drag_painting and not editor.resource_panel_open and not editor.open_file_panel_open:
                    rects = get_rects(editor.level, screen.get_size())
                    map_rect = rects["map"]
                    if map_rect.collidepoint(event.pos):
                        gx = (event.pos[0] - map_rect.left) // CELL_SIZE
                        gy = (event.pos[1] - map_rect.top) // CELL_SIZE
                        if editor.last_painted_cell != (gx, gy):
                            brush_id = _get_paint_brush_id(editor, editor.paint_mouse_button)
                            apply_brush(editor.level, gx, gy, editor.current_brush_group, brush_id)
                            editor.last_painted_cell = (gx, gy)

        if screen.get_size() != get_window_size(editor.level):
            screen = pygame.display.set_mode(get_window_size(editor.level), pygame.RESIZABLE)

        rects = get_rects(editor.level, screen.get_size())
        map_rect = rects["map"]

        screen.fill(BG_COLOR)
        draw_level(screen, editor.level, map_rect.left, map_rect.top, CELL_SIZE)

        if not editor.resource_panel_open and not editor.open_file_panel_open:
            mx, my = mouse_pos
            if map_rect.collidepoint(mouse_pos):
                gx = (mx - map_rect.left) // CELL_SIZE
                gy = (my - map_rect.top) // CELL_SIZE
                draw_cell_overlay(
                    screen,
                    map_rect.left + gx * CELL_SIZE,
                    map_rect.top + gy * CELL_SIZE,
                    CELL_SIZE,
                )

        draw_ui(screen, editor, mouse_pos)
        draw_resource_panel(screen, editor, rects["panel"])
        draw_open_panel(screen, editor, rects["panel"])

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    run_editor()