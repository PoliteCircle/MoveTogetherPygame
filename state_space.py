from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pygame

from core import LevelData, create_empty_level
from game_render import BG_COLOR, CELL_SIZE, PANEL_COLOR, SUB_TEXT_COLOR, draw_level, draw_text
from game_rules import MOVE_TO_CHAR, is_victory_state


# =============================================================================
# 统一颜色配置（只改这里即可影响全局）
# =============================================================================

STATE_COLORS = {
    "red": {
        "main": (225, 72, 72),      # 当前状态主色
        "light": (255, 188, 188),   # 当前状态浅色/边框色
    },
    "orange": {
        "main": (255, 164, 68),     # 双向可达主色
        "light": (255, 214, 170),   # 双向可达浅色/边框色
    },
    "yellow": {
        "main": (245, 210, 90),     # 当前状态可到达主色
        "light": (255, 238, 182),   # 当前状态可到达浅色/边框色
    },
    "blue": {
        "main": (90, 160, 255),     # 可到达当前状态主色
        "light": (196, 222, 255),   # 可到达当前状态浅色/边框色
    },
    "green": {
        "main": (90, 205, 120),     # 终点/最短路径主色
        "light": (186, 242, 194),   # 终点/最短路径浅色
    },
}


def _c(name: str) -> Tuple[int, int, int]:
    return STATE_COLORS[name]["main"]


def _cl(name: str) -> Tuple[int, int, int]:
    return STATE_COLORS[name]["light"]

# =============================================================================
# 数据恢复
# =============================================================================


def level_from_dict(data: dict) -> LevelData:
    width = int(data["width"])
    height = int(data["height"])
    name = data.get("name", "状态空间预览")
    level = create_empty_level(width, height, name=name)

    level.terrain = [list(row) for row in data["terrain"]]
    level.actors = [list(row) for row in data["actors"]]
    level.goals = [list(row) for row in data["goals"]]
    actor_status = data.get("actor_status")
    if actor_status is not None:
        level.actor_status = [list(row) for row in actor_status]

    if "victory_mode" in data:
        level.victory_mode = data["victory_mode"]

    return level


def build_level_from_state(static_level: LevelData, state_items: List[dict]) -> LevelData:
    level = static_level.clone()
    level.actors = [[0 for _ in range(level.width)] for _ in range(level.height)]
    level.actor_status = [[0 for _ in range(level.width)] for _ in range(level.height)]

    for item in state_items:
        x = int(item["x"])
        y = int(item["y"])
        actor_id = int(item["actor_id"])
        stun_turns = int(item.get("stun_turns", 0))
        if 0 <= x < level.width and 0 <= y < level.height:
            level.actors[y][x] = actor_id
            level.actor_status[y][x] = stun_turns

    return level


# =============================================================================
# 图布局
# =============================================================================


def _compute_depth_groups(depths: List[int]) -> Dict[int, List[int]]:
    groups: Dict[int, List[int]] = {}
    for idx, depth in enumerate(depths):
        groups.setdefault(int(depth), []).append(idx)
    return groups


def build_initial_positions(depths: List[int]) -> Dict[int, Tuple[float, float]]:
    groups = _compute_depth_groups(depths)
    positions: Dict[int, Tuple[float, float]] = {}

    x_gap = 180.0
    y_gap = 92.0
    top_margin = 80.0
    left_margin = 80.0

    for depth in sorted(groups.keys()):
        items = groups[depth]
        count = len(items)
        total_h = (count - 1) * y_gap
        start_y = top_margin - total_h / 2.0

        for row, idx in enumerate(items):
            x = left_margin + depth * x_gap
            y = start_y + row * y_gap + 260
            positions[idx] = (x, y)

    return positions


# =============================================================================
# 坐标变换
# =============================================================================


def _world_to_screen(
    world: Tuple[float, float],
    graph_rect: pygame.Rect,
    camera: Tuple[float, float],
    zoom: float,
) -> Tuple[int, int]:
    wx, wy = world
    sx = int(graph_rect.x + (wx + camera[0]) * zoom)
    sy = int(graph_rect.y + (wy + camera[1]) * zoom)
    return sx, sy


def _screen_to_world(
    screen_pos: Tuple[int, int],
    graph_rect: pygame.Rect,
    camera: Tuple[float, float],
    zoom: float,
) -> Tuple[float, float]:
    sx, sy = screen_pos
    wx = (sx - graph_rect.x) / zoom - camera[0]
    wy = (sy - graph_rect.y) / zoom - camera[1]
    return wx, wy


def _zoom_camera_at_screen_pos(
    graph_rect: pygame.Rect,
    camera: List[float],
    zoom: float,
    screen_pos: Tuple[int, int],
    factor: float,
) -> float:
    old_zoom = zoom
    new_zoom = max(0.2, min(3.5, zoom * factor))
    if abs(new_zoom - old_zoom) < 1e-9:
        return zoom

    world_before = _screen_to_world(screen_pos, graph_rect, (camera[0], camera[1]), old_zoom)
    world_after = _screen_to_world(screen_pos, graph_rect, (camera[0], camera[1]), new_zoom)

    camera[0] += world_after[0] - world_before[0]
    camera[1] += world_after[1] - world_before[1]
    return new_zoom


def _find_node_at_screen_pos(
    pos: Tuple[int, int],
    graph_rect: pygame.Rect,
    positions: Dict[int, Tuple[float, float]],
    camera: Tuple[float, float],
    zoom: float,
    base_radius: float,
) -> Optional[int]:
    px, py = pos
    hit_index = None
    hit_dist2 = 10**18

    r = max(10.0, base_radius * zoom)
    r2 = r * r

    for idx, world in positions.items():
        sx, sy = _world_to_screen(world, graph_rect, camera, zoom)
        dx = px - sx
        dy = py - sy
        d2 = dx * dx + dy * dy
        if d2 <= r2 and d2 < hit_dist2:
            hit_dist2 = d2
            hit_index = idx

    return hit_index


# =============================================================================
# 状态关系 / 最短路径
# =============================================================================


def _build_next_state_by_move(edges: List[Tuple[int, int, str]]) -> Dict[Tuple[int, str], int]:
    result: Dict[Tuple[int, str], int] = {}
    for src, dst, move in edges:
        result[(src, move)] = dst
    return result


def _build_adjacency(edges: List[Tuple[int, int, str]]) -> Dict[int, List[Tuple[int, str]]]:
    adjacency: Dict[int, List[Tuple[int, str]]] = {}
    for src, dst, move in edges:
        adjacency.setdefault(src, []).append((dst, move))
    return adjacency


def _build_solution_path(
    parents: List[Optional[int]],
    solution_index: Optional[int],
) -> Tuple[Set[int], Set[Tuple[int, int]]]:
    path_nodes: Set[int] = set()
    path_edges: Set[Tuple[int, int]] = set()

    if solution_index is None:
        return path_nodes, path_edges

    if not (0 <= solution_index < len(parents)):
        return path_nodes, path_edges

    cur = solution_index
    visited: Set[int] = set()

    while cur is not None:
        if cur in visited:
            break
        visited.add(cur)

        if not (0 <= cur < len(parents)):
            break

        path_nodes.add(cur)
        parent = parents[cur]

        if parent is not None:
            if not (0 <= parent < len(parents)):
                break
            path_edges.add((parent, cur))

        cur = parent

    return path_nodes, path_edges


def _extract_moves_from_parents(
    parents: List[Optional[int]],
    parent_moves: List[Optional[str]],
    solution_index: Optional[int],
) -> List[str]:
    if solution_index is None:
        return []

    moves_rev: List[str] = []
    cur = solution_index
    while cur is not None:
        move = parent_moves[cur]
        if move is not None:
            moves_rev.append(move)
        cur = parents[cur]
    moves_rev.reverse()
    return moves_rev


def _solve_shortest_path_from_source(
    source_index: Optional[int],
    goal_nodes: Set[int],
    edges: List[Tuple[int, int, str]],
    node_count: int,
) -> Tuple[Optional[int], List[Optional[int]], List[Optional[str]], List[str]]:
    if source_index is None or not (0 <= source_index < node_count):
        return None, [None] * node_count, [None] * node_count, []

    parents: List[Optional[int]] = [None] * node_count
    parent_moves: List[Optional[str]] = [None] * node_count
    visited: Set[int] = {source_index}
    queue: List[int] = [source_index]
    head = 0

    if source_index in goal_nodes:
        return source_index, parents, parent_moves, []

    adjacency = _build_adjacency(edges)

    found: Optional[int] = None
    while head < len(queue):
        cur = queue[head]
        head += 1

        for nxt, move in adjacency.get(cur, []):
            if nxt in visited:
                continue
            visited.add(nxt)
            parents[nxt] = cur
            parent_moves[nxt] = move
            if nxt in goal_nodes:
                found = nxt
                queue = []
                break
            queue.append(nxt)

    moves = _extract_moves_from_parents(parents, parent_moves, found)
    return found, parents, parent_moves, moves



def _is_goal_state(static_level: LevelData, state_items: List[dict]) -> bool:
    """
    直接复用 game_rules.is_victory_state 的正式胜利判定逻辑。
    这样会正确考虑：
    1. 目标格上是否有角色
    2. 角色是否与该目标类型匹配
    3. victory_mode（如 any / all_matching_goals）
    """
    actor_state = tuple(
        sorted(
            (
                int(item["x"]),
                int(item["y"]),
                int(item["actor_id"]),
                int(item.get("stun_turns", 0)),
            )
            for item in state_items
        )
    )
    return is_victory_state(static_level, actor_state)


def _compute_goal_nodes(static_level: LevelData, states: List[List[dict]]) -> Set[int]:
    return {idx for idx, state_items in enumerate(states) if _is_goal_state(static_level, state_items)}


def _analyze_selected_connections(
    edges: List[Tuple[int, int, str]],
    selected_index: Optional[int],
) -> Tuple[
    Set[int],
    Set[int],
    Set[int],
    Set[Tuple[int, int]],
    Set[Tuple[int, int]],
    Set[Tuple[int, int]],
]:
    """
    返回:
    - mutual_nodes: 与当前状态互相到达的状态节点（橙）
    - outgoing_only_nodes: 当前状态能到达，但不能回到当前状态的节点（黄）
    - incoming_only_nodes: 仅能到达当前状态的节点（蓝）
    - mutual_edges / outgoing_only_edges / incoming_only_edges: 对应高亮边集合
    """
    if selected_index is None:
        return set(), set(), set(), set(), set(), set()

    outgoing_nodes = {dst for src, dst, _ in edges if src == selected_index and dst != selected_index}
    incoming_nodes = {src for src, dst, _ in edges if dst == selected_index and src != selected_index}

    mutual_nodes = outgoing_nodes & incoming_nodes
    outgoing_only_nodes = outgoing_nodes - incoming_nodes
    incoming_only_nodes = incoming_nodes - outgoing_nodes

    mutual_edges: Set[Tuple[int, int]] = set()
    outgoing_only_edges: Set[Tuple[int, int]] = set()
    incoming_only_edges: Set[Tuple[int, int]] = set()

    for src, dst, _ in edges:
        if src == selected_index and dst in mutual_nodes:
            mutual_edges.add((src, dst))
        elif dst == selected_index and src in mutual_nodes:
            mutual_edges.add((src, dst))
        elif src == selected_index and dst in outgoing_only_nodes:
            outgoing_only_edges.add((src, dst))
        elif dst == selected_index and src in incoming_only_nodes:
            incoming_only_edges.add((src, dst))

    return (
        mutual_nodes,
        outgoing_only_nodes,
        incoming_only_nodes,
        mutual_edges,
        outgoing_only_edges,
        incoming_only_edges,
    )


# =============================================================================
# 绘制
# =============================================================================


def _draw_arrow(
    surface: pygame.Surface,
    color: Tuple[int, int, int],
    start: Tuple[int, int],
    end: Tuple[int, int],
    width: int = 2,
) -> None:
    pygame.draw.line(surface, color, start, end, width)

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1:
        return

    ux = dx / length
    uy = dy / length

    arrow_len = 10
    arrow_w = 5
    left = (
        int(end[0] - ux * arrow_len - uy * arrow_w),
        int(end[1] - uy * arrow_len + ux * arrow_w),
    )
    right = (
        int(end[0] - ux * arrow_len + uy * arrow_w),
        int(end[1] - uy * arrow_len - ux * arrow_w),
    )
    pygame.draw.polygon(surface, color, [end, left, right])


def _draw_button(
    screen: pygame.Surface,
    rect: pygame.Rect,
    text: str,
    mouse_pos: Tuple[int, int],
    enabled: bool = True,
    fill_color: Optional[Tuple[int, int, int]] = None,
    border_color: Optional[Tuple[int, int, int]] = None,
) -> None:
    hovered = enabled and rect.collidepoint(mouse_pos)
    if enabled:
        base_fill = fill_color if fill_color is not None else (60, 105, 70)
        base_border = border_color if border_color is not None else (170, 232, 182)
        if hovered:
            fill = tuple(min(255, c + 16) for c in base_fill)
        else:
            fill = base_fill
        border = base_border
        text_color = (240, 248, 240)
    else:
        fill = (82, 84, 90)
        border = (128, 132, 140)
        text_color = (170, 174, 182)

    pygame.draw.rect(screen, fill, rect, border_radius=8)
    pygame.draw.rect(screen, border, rect, width=2, border_radius=8)
    draw_text(screen, text, rect.x + 14, rect.y + 8, 18, text_color)


def _fit_cell_size(level: LevelData, max_inner_width: int, preferred: int = CELL_SIZE) -> int:
    if level.width <= 0:
        return max(10, min(preferred, CELL_SIZE))
    return max(10, min(preferred, CELL_SIZE, max_inner_width // max(1, level.width)))


def _draw_scrollbar(
    screen: pygame.Surface,
    track_rect: pygame.Rect,
    scroll: int,
    view_height: int,
    content_height: int,
) -> None:
    if content_height <= view_height or track_rect.height <= 0:
        return

    pygame.draw.rect(screen, (58, 62, 72), track_rect, border_radius=6)
    thumb_h = max(36, int(track_rect.height * view_height / content_height))
    max_scroll = max(1, content_height - view_height)
    thumb_y = track_rect.y + int((track_rect.height - thumb_h) * scroll / max_scroll)
    thumb_rect = pygame.Rect(track_rect.x + 2, thumb_y, max(6, track_rect.width - 4), thumb_h)
    pygame.draw.rect(screen, (150, 156, 170), thumb_rect, border_radius=6)

def _wrap_text_to_width(text: str, max_width: int, font_size: int = 20) -> List[str]:
    if max_width <= 10:
        return [text]

    font = pygame.font.Font(None, font_size)
    lines: List[str] = []
    current = ""

    for ch in text:
        test = current + ch
        if current and font.size(test)[0] > max_width:
            lines.append(current)
            current = ch
        else:
            current = test

    if current or not lines:
        lines.append(current if current else "")

    return lines


def _measure_info_panel_height(
    solution_index: Optional[int],
    solution_moves: List[str],
    info_width: int,
) -> int:
    if solution_index is None:
        return 70

    inner_w = max(60, info_width - 24)
    step_text = "".join(MOVE_TO_CHAR.get(m, m) for m in solution_moves) or "-"
    path_lines = _wrap_text_to_width(step_text, inner_w, 20)

    return 12 + 24 + 24 + 24 + len(path_lines) * 22 + 10


def _draw_graph_legend(screen: pygame.Surface, graph_rect: pygame.Rect) -> None:
    legend_rect = pygame.Rect(graph_rect.x + 12, graph_rect.bottom - 106, 230, 94)
    pygame.draw.rect(screen, (34, 37, 44), legend_rect, border_radius=8)
    pygame.draw.rect(screen, (92, 96, 108), legend_rect, width=1, border_radius=8)

    items = [
        ("红 当前状态", _c("red")),
        ("橙 双向可达", _c("orange")),
        ("黄 单向可达", _c("yellow")),
        ("蓝 反单向可达", _c("blue")),
        ("绿 终点/最短路径", _c("green")),
    ]

    x = legend_rect.x + 10
    y = legend_rect.y + 8
    for label, color in items:
        pygame.draw.circle(screen, color, (x + 6, y + 10), 5)
        draw_text(screen, label, x + 18, y, 16, (220, 224, 232))
        y += 17


def _build_preview_items(
    selected_index: Optional[int],
    mutual_nodes: Set[int],
    outgoing_only_nodes: Set[int],
    incoming_only_nodes: Set[int],
) -> List[Tuple[int, Tuple[int, int, int]]]:
    items: List[Tuple[int, Tuple[int, int, int]]] = []

    if selected_index is not None:
        items.append((selected_index, _c("red")))

    for idx in sorted(mutual_nodes):
        items.append((idx, _c("orange")))

    for idx in sorted(outgoing_only_nodes):
        items.append((idx, _c("yellow")))

    for idx in sorted(incoming_only_nodes):
        items.append((idx, _c("blue")))

    return items


def _get_grid_metrics(area_width: int, level: LevelData) -> Tuple[int, int, int, int]:
    gap = 10
    columns = 3
    card_width = (area_width - gap * (columns - 1)) // columns
    card_height = _measure_card_height(level, card_width)
    return columns, card_width, card_height, gap


def _draw_graph(
    screen: pygame.Surface,
    graph_rect: pygame.Rect,
    positions: Dict[int, Tuple[float, float]],
    edges: List[Tuple[int, int, str]],
    selected_index: Optional[int],
    mutual_nodes: Set[int],
    outgoing_only_nodes: Set[int],
    incoming_only_nodes: Set[int],
    mutual_edges: Set[Tuple[int, int]],
    outgoing_only_edges: Set[Tuple[int, int]],
    incoming_only_edges: Set[Tuple[int, int]],
    goal_nodes: Set[int],
    camera: Tuple[float, float],
    zoom: float,
    base_radius: float,
    start_index: int,
    solution_path_nodes: Set[int],
    solution_path_edges: Set[Tuple[int, int]],
) -> None:
    pygame.draw.rect(screen, (28, 30, 36), graph_rect)
    pygame.draw.rect(screen, (90, 94, 108), graph_rect, 1)

    clip_old = screen.get_clip()
    screen.set_clip(graph_rect)

    for src, dst, _move in edges:
        if src not in positions or dst not in positions:
            continue
        p1 = _world_to_screen(positions[src], graph_rect, camera, zoom)
        p2 = _world_to_screen(positions[dst], graph_rect, camera, zoom)

        color = (105, 112, 126)
        width = 2

        if (src, dst) in solution_path_edges:
            color = _c("green")
            width = 4

        if (src, dst) in mutual_edges:
            color = _c("orange")
            width = 4
        elif (src, dst) in outgoing_only_edges:
            color = _c("yellow")
            width = 4
        elif (src, dst) in incoming_only_edges:
            color = _c("blue")
            width = 4

        _draw_arrow(screen, color, p1, p2, width)

    for idx, world in positions.items():
        sx, sy = _world_to_screen(world, graph_rect, camera, zoom)
        radius = int(max(12, base_radius * zoom))

        fill = (72, 76, 88)
        border = (150, 156, 170)
        border_width = 3

        if idx == start_index:
            fill = (70, 110, 170)

        if idx in goal_nodes:
            fill = _c("green")
            border = _cl("green")
            border_width = 4

        if idx in incoming_only_nodes:
            fill = _c("blue")
            border = _cl("blue")
            border_width = 4

        if idx in outgoing_only_nodes:
            fill = _c("yellow")
            border = _cl("yellow")
            border_width = 4

        if idx in mutual_nodes:
            fill = _c("orange")
            border = _cl("orange")
            border_width = 4

        if selected_index == idx:
            fill = _c("red")
            border = _cl("red")
            border_width = 4

        if idx in solution_path_nodes:
            border = _c("green")
            border_width = 4

        pygame.draw.circle(screen, fill, (sx, sy), radius)
        pygame.draw.circle(screen, border, (sx, sy), radius, border_width)

    screen.set_clip(clip_old)
    _draw_graph_legend(screen, graph_rect)


def _draw_state_card(
    surface: pygame.Surface,
    rect: pygame.Rect,
    border_color: Tuple[int, int, int],
    level: LevelData,
    mouse_pos: Tuple[int, int],
) -> pygame.Rect:
    pygame.draw.rect(surface, (44, 47, 56), rect, border_radius=10)
    pygame.draw.rect(surface, border_color, rect, width=2, border_radius=10)

    inner_margin_x = 8
    inner_top = rect.y + 8
    inner_w = max(80, rect.width - inner_margin_x * 2)
    cell_size = _fit_cell_size(level, inner_w, preferred=CELL_SIZE)

    map_w = level.width * cell_size
    map_h = level.height * cell_size
    map_x = rect.x + max(inner_margin_x, (rect.width - map_w) // 2)
    map_y = inner_top
    draw_level(surface, level, map_x, map_y, cell_size)

    # 底部：左侧颜色圆点 + 右侧跳转按钮
    button_w = 82
    button_h = 28
    button_y = rect.bottom - button_h - 8

    # 按钮稍微右移
    button_x = rect.centerx - button_w // 2 + 18
    button_rect = pygame.Rect(button_x, button_y, button_w, button_h)

    # 按钮左边的颜色圆点
    dot_radius = 9
    dot_cx = button_rect.x - 24
    dot_cy = button_rect.centery

    pygame.draw.circle(surface, border_color, (dot_cx, dot_cy), dot_radius)

    _draw_button(
        surface,
        button_rect,
        "跳转",
        mouse_pos,
        enabled=True,
        fill_color=(72, 88, 120),
        border_color=(188, 208, 255),
    )
    return button_rect


def _measure_card_height(level: LevelData, card_width: int) -> int:
    inner_w = max(80, card_width - 16)
    cell_size = _fit_cell_size(level, inner_w, preferred=CELL_SIZE)
    map_h = level.height * cell_size
    return 8 + map_h + 40


def _draw_state_cards_grid(
    surface: pygame.Surface,
    area_rect: pygame.Rect,
    static_level: LevelData,
    states: List[List[dict]],
    items: List[Tuple[int, Tuple[int, int, int]]],
    start_y: int,
) -> Tuple[int, List[Tuple[pygame.Rect, int]]]:
    if not items:
        return start_y, []

    sample_level = build_level_from_state(static_level, states[items[0][0]])
    columns, card_width, card_h, gap = _get_grid_metrics(area_rect.width, sample_level)
    jump_buttons: List[Tuple[pygame.Rect, int]] = []

    for i, (idx, border_color) in enumerate(items):
        col = i % columns
        row = i // columns
        x = area_rect.x + col * (card_width + gap)
        y = start_y + row * (card_h + gap)
        rect = pygame.Rect(x, y, card_width, card_h)

        level = build_level_from_state(static_level, states[idx])
        button_rect = _draw_state_card(surface, rect, border_color, level, (-10000, -10000))
        jump_buttons.append((button_rect, idx))

    rows = (len(items) + columns - 1) // columns
    end_y = start_y + rows * card_h + max(0, rows - 1) * gap
    return end_y, jump_buttons


def _build_preview_content_height(
    area_width: int,
    static_level: LevelData,
    states: List[List[dict]],
    selected_index: Optional[int],
    mutual_nodes: Set[int],
    outgoing_only_nodes: Set[int],
    incoming_only_nodes: Set[int],
) -> int:
    items = _build_preview_items(
        selected_index=selected_index,
        mutual_nodes=mutual_nodes,
        outgoing_only_nodes=outgoing_only_nodes,
        incoming_only_nodes=incoming_only_nodes,
    )
    if not items:
        return 80

    pad = 12
    inner_width = max(120, area_width - pad * 2)
    sample_level = build_level_from_state(static_level, states[items[0][0]])
    columns, _card_width, card_h, gap = _get_grid_metrics(inner_width, sample_level)
    rows = (len(items) + columns - 1) // columns

    return pad + rows * card_h + max(0, rows - 1) * gap + pad


def _draw_preview_maps(
    screen: pygame.Surface,
    area_rect: pygame.Rect,
    static_level: LevelData,
    states: List[List[dict]],
    selected_index: Optional[int],
    mutual_nodes: Set[int],
    outgoing_only_nodes: Set[int],
    incoming_only_nodes: Set[int],
    scroll_y: int,
) -> Tuple[int, List[Tuple[pygame.Rect, int]]]:
    items = _build_preview_items(
        selected_index=selected_index,
        mutual_nodes=mutual_nodes,
        outgoing_only_nodes=outgoing_only_nodes,
        incoming_only_nodes=incoming_only_nodes,
    )

    content_h = _build_preview_content_height(
        area_width=area_rect.width,
        static_level=static_level,
        states=states,
        selected_index=selected_index,
        mutual_nodes=mutual_nodes,
        outgoing_only_nodes=outgoing_only_nodes,
        incoming_only_nodes=incoming_only_nodes,
    )

    content_surface = pygame.Surface((max(10, area_rect.width), content_h))
    content_surface.fill(PANEL_COLOR)

    jump_buttons_on_screen: List[Tuple[pygame.Rect, int]] = []

    if items:
        pad = 12
        content_inner_rect = pygame.Rect(
            pad,
            0,
            max(120, content_surface.get_width() - pad * 2),
            10,
        )
        _end_y, buttons = _draw_state_cards_grid(
            content_surface,
            content_inner_rect,
            static_level,
            states,
            items,
            pad,
        )
        jump_buttons_on_screen.extend(buttons)
    else:
        draw_text(content_surface, "左侧点击一个状态节点进行预览", 16, 16, 22, SUB_TEXT_COLOR)

    max_scroll = max(0, content_h - area_rect.height)
    scroll_y = max(0, min(scroll_y, max_scroll))

    clip_old = screen.get_clip()
    screen.set_clip(area_rect)
    screen.blit(content_surface, (area_rect.x, area_rect.y - scroll_y))
    screen.set_clip(clip_old)

    scrollbar_rect = pygame.Rect(area_rect.right - 10, area_rect.y, 8, area_rect.height)
    _draw_scrollbar(screen, scrollbar_rect, scroll_y, area_rect.height, content_h)

    jump_buttons_transformed: List[Tuple[pygame.Rect, int]] = []
    for rect, idx in jump_buttons_on_screen:
        screen_rect = rect.move(area_rect.x, area_rect.y - scroll_y)
        if screen_rect.bottom >= area_rect.y and screen_rect.top <= area_rect.bottom:
            jump_buttons_transformed.append((screen_rect, idx))

    return max_scroll, jump_buttons_transformed


def _draw_state_preview(
    screen: pygame.Surface,
    preview_rect: pygame.Rect,
    info_rect: pygame.Rect,
    button_rect: pygame.Rect,
    maps_rect: pygame.Rect,
    mouse_pos: Tuple[int, int],
    static_level: LevelData,
    states: List[List[dict]],
    selected_index: Optional[int],
    path_source_index: Optional[int],
    solution_index: Optional[int],
    solution_moves: List[str],
    mutual_nodes: Set[int],
    outgoing_only_nodes: Set[int],
    incoming_only_nodes: Set[int],
    preview_scroll_y: int,
) -> Tuple[int, List[Tuple[pygame.Rect, int]]]:
    del path_source_index  # 右侧不再显示“当前最短路起点”

    pygame.draw.rect(screen, PANEL_COLOR, preview_rect)
    pygame.draw.rect(screen, (100, 104, 116), preview_rect, 1)

    draw_text(screen, "状态空间查看", preview_rect.x + 16, preview_rect.y + 14, 28)

    _draw_button(screen, button_rect, "求解当前状态最短路径", mouse_pos, enabled=(selected_index is not None))

    pygame.draw.rect(screen, (38, 41, 49), info_rect, border_radius=10)
    pygame.draw.rect(screen, (100, 104, 116), info_rect, width=1, border_radius=10)

    info_x = info_rect.x + 12
    info_y = info_rect.y + 10
    draw_text(screen, f"总状态数: {len(states)}", info_x, info_y, 20, SUB_TEXT_COLOR)

    if solution_index is not None:
        draw_text(screen, f"最短路径长度: {len(solution_moves)}", info_x, info_y + 24, 20, (170, 230, 170))
        draw_text(screen, "最短路径:", info_x, info_y + 48, 20, (170, 230, 170))

        step_text = "".join(MOVE_TO_CHAR.get(m, m) for m in solution_moves) or "-"
        path_lines = _wrap_text_to_width(step_text, max(60, info_rect.width - 24), 20)

        line_y = info_y + 72
        for line in path_lines:
            draw_text(screen, line, info_x, line_y, 20, (170, 230, 170))
            line_y += 22
    else:
        draw_text(screen, "当前无可达解", info_x, info_y + 24, 20, (255, 200, 140))

    pygame.draw.rect(screen, (33, 36, 43), maps_rect, border_radius=10)
    pygame.draw.rect(screen, (92, 96, 108), maps_rect, width=1, border_radius=10)

    return _draw_preview_maps(
        screen=screen,
        area_rect=maps_rect,
        static_level=static_level,
        states=states,
        selected_index=selected_index,
        mutual_nodes=mutual_nodes,
        outgoing_only_nodes=outgoing_only_nodes,
        incoming_only_nodes=incoming_only_nodes,
        scroll_y=preview_scroll_y,
    )


# =============================================================================
# 窗口
# =============================================================================


def _create_viewer_window() -> pygame.Surface:
    info = pygame.display.Info()

    w = max(1400, info.current_w - 80)
    h = max(900, info.current_h - 120)
    flags = pygame.RESIZABLE

    maximized_flag = getattr(pygame, "WINDOWMAXIMIZED", 0)
    if maximized_flag == 0:
        maximized_flag = getattr(pygame, "MAXIMIZED", 0)

    try:
        screen = pygame.display.set_mode((w, h), flags | maximized_flag)
    except Exception:
        screen = pygame.display.set_mode((w, h), flags)

    try:
        from pygame._sdl2.video import Window

        Window.from_display_module().maximize()
    except Exception:
        pass

    return screen


# =============================================================================
# 主查看器
# =============================================================================


def run_state_space_viewer(json_path: Path) -> None:
    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))

    static_level = level_from_dict(payload["static_level"])
    states: List[List[dict]] = payload.get("states") or []
    depths: List[int] = [int(x) for x in (payload.get("depths") or [])]
    edges: List[Tuple[int, int, str]] = [
        (int(e["src"]), int(e["dst"]), str(e["move"]))
        for e in (payload.get("edges") or [])
    ]
    parents_from_start: List[Optional[int]] = [
        None if p is None else int(p)
        for p in (payload.get("parents") or [])
    ]
    parent_moves_from_start: List[Optional[str]] = [
        None if x is None else str(x)
        for x in (payload.get("parent_moves") or [])
    ]

    raw_solution_moves = payload.get("solution_moves") or []
    solution_moves_from_start: List[str] = [str(x) for x in raw_solution_moves]

    start_index = int(payload.get("start_index", 0))
    solution_index_raw = payload.get("solution_index")
    solution_index_from_start = None if solution_index_raw is None else int(solution_index_raw)

    pygame.init()
    screen = _create_viewer_window()
    pygame.display.set_caption("状态空间查看器")
    clock = pygame.time.Clock()

    positions = build_initial_positions(depths)
    next_state_by_move = _build_next_state_by_move(edges)
    goal_nodes = _compute_goal_nodes(static_level, states)

    path_source_index: Optional[int] = start_index
    current_path_parents: List[Optional[int]] = parents_from_start[:]
    current_path_parent_moves: List[Optional[str]] = parent_moves_from_start[:]
    current_solution_index: Optional[int] = solution_index_from_start
    current_solution_moves: List[str] = solution_moves_from_start[:]
    solution_path_nodes, solution_path_edges = _build_solution_path(current_path_parents, current_solution_index)

    selected_index: Optional[int] = start_index if states else None
    dragging_node: Optional[int] = None
    node_drag_offset = (0.0, 0.0)

    panning = False
    pan_last = (0, 0)

    camera = [40.0, 0.0]
    zoom = 1.0
    base_radius = 22.0
    preview_scroll_y = 0
    preview_max_scroll = 0
    preview_jump_buttons: List[Tuple[pygame.Rect, int]] = []

    running = True
    while running:
        w, h = screen.get_size()

        help_y = 12
        content_top = 42

        total_content_w = w - 16 - 12 - 16
        graph_w = int(total_content_w * 3 / 5)
        preview_w = total_content_w - graph_w

        graph_rect = pygame.Rect(16, content_top, graph_w, h - content_top - 16)
        preview_rect = pygame.Rect(graph_rect.right + 12, content_top, preview_w, h - content_top - 16)

        top_row_y = preview_rect.y + 48
        button_w = min(220, max(180, preview_rect.width // 3))
        button_h = 40
        button_rect = pygame.Rect(preview_rect.x + 16, top_row_y, button_w, button_h)

        info_x = button_rect.right + 12
        info_w = preview_rect.right - 16 - info_x
        info_h = _measure_info_panel_height(current_solution_index, current_solution_moves, info_w)
        top_row_h = max(button_h, info_h)

        info_rect = pygame.Rect(info_x, top_row_y, info_w, info_h)

        maps_rect = pygame.Rect(
            preview_rect.x + 12,
            top_row_y + top_row_h + 12,
            preview_rect.width - 24,
            preview_rect.bottom - (top_row_y + top_row_h + 24),
        )

        mouse_pos = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                    anchor = mouse_pos if graph_rect.collidepoint(mouse_pos) else graph_rect.center
                    zoom = _zoom_camera_at_screen_pos(graph_rect, camera, zoom, anchor, 1.12)

                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    anchor = mouse_pos if graph_rect.collidepoint(mouse_pos) else graph_rect.center
                    zoom = _zoom_camera_at_screen_pos(graph_rect, camera, zoom, anchor, 1.0 / 1.12)

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
                            preview_scroll_y = 0

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1 and button_rect.collidepoint(event.pos):
                    if selected_index is not None:
                        path_source_index = selected_index
                        (
                            current_solution_index,
                            current_path_parents,
                            current_path_parent_moves,
                            current_solution_moves,
                        ) = _solve_shortest_path_from_source(
                            source_index=selected_index,
                            goal_nodes=goal_nodes,
                            edges=edges,
                            node_count=len(states),
                        )
                        solution_path_nodes, solution_path_edges = _build_solution_path(
                            current_path_parents,
                            current_solution_index,
                        )
                    continue

                if event.button == 1:
                    jumped = False
                    for rect, idx in preview_jump_buttons:
                        if rect.collidepoint(event.pos):
                            selected_index = idx
                            preview_scroll_y = 0
                            jumped = True
                            break
                    if jumped:
                        continue

                if maps_rect.collidepoint(event.pos):
                    if event.button == 4:
                        preview_scroll_y = max(0, preview_scroll_y - 64)
                        continue
                    if event.button == 5:
                        preview_scroll_y = min(preview_max_scroll, preview_scroll_y + 64)
                        continue

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
                        preview_scroll_y = 0
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
                if maps_rect.collidepoint(mouse_pos):
                    preview_scroll_y = max(0, min(preview_max_scroll, preview_scroll_y - event.y * 64))
                elif graph_rect.collidepoint(mouse_pos):
                    if event.y > 0:
                        zoom = _zoom_camera_at_screen_pos(graph_rect, camera, zoom, mouse_pos, 1.12)
                    elif event.y < 0:
                        zoom = _zoom_camera_at_screen_pos(graph_rect, camera, zoom, mouse_pos, 1.0 / 1.12)

        (
            mutual_nodes,
            outgoing_only_nodes,
            incoming_only_nodes,
            mutual_edges,
            outgoing_only_edges,
            incoming_only_edges,
        ) = _analyze_selected_connections(edges, selected_index)

        screen.fill(BG_COLOR)

        draw_text(
            screen,
            "操作：左键选中/拖拽节点，中键/右键平移，左侧滚轮缩放，右侧滚轮滚动，方向键沿边跳转，Esc关闭",
            20,
            help_y,
            18,
            SUB_TEXT_COLOR,
        )

        _draw_graph(
            screen=screen,
            graph_rect=graph_rect,
            positions=positions,
            edges=edges,
            selected_index=selected_index,
            mutual_nodes=mutual_nodes,
            outgoing_only_nodes=outgoing_only_nodes,
            incoming_only_nodes=incoming_only_nodes,
            mutual_edges=mutual_edges,
            outgoing_only_edges=outgoing_only_edges,
            incoming_only_edges=incoming_only_edges,
            goal_nodes=goal_nodes,
            camera=(camera[0], camera[1]),
            zoom=zoom,
            base_radius=base_radius,
            start_index=start_index,
            solution_path_nodes=solution_path_nodes,
            solution_path_edges=solution_path_edges,
        )

        preview_max_scroll, preview_jump_buttons = _draw_state_preview(
            screen=screen,
            preview_rect=preview_rect,
            info_rect=info_rect,
            button_rect=button_rect,
            maps_rect=maps_rect,
            mouse_pos=mouse_pos,
            static_level=static_level,
            states=states,
            selected_index=selected_index,
            path_source_index=path_source_index,
            solution_index=current_solution_index,
            solution_moves=current_solution_moves,
            mutual_nodes=mutual_nodes,
            outgoing_only_nodes=outgoing_only_nodes,
            incoming_only_nodes=incoming_only_nodes,
            preview_scroll_y=preview_scroll_y,
        )
        preview_scroll_y = max(0, min(preview_scroll_y, preview_max_scroll))

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


# =============================================================================
# 命令行入口
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-space-json", type=str, required=True)
    args = parser.parse_args()

    run_state_space_viewer(Path(args.state_space_json))


if __name__ == "__main__":
    main()