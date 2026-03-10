## core.py

"""
core.py
=======
本文件负责“核心规则层 + 基础绘制层”。

设计目标：
1. 将“地图数据结构”和“游戏规则”集中放在一个文件里，方便以后扩展。
2. 将“绘制地形 / 角色 / 目标”的入口统一到一起，方便以后替换美术资源。
3. 将“移动计算”“胜利判定”“关卡读写”封装成函数，方便 main.py / solve.py / mapedit.py 共用。
4. 注释尽量详细，便于后续继续扩展新的角色、地形、目标类型。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pygame

TERRAIN_VOID = 0
TERRAIN_FLOOR = 1
TERRAIN_STONE = 2

ACTOR_EMPTY = 0
ACTOR_SOIL = 1

GOAL_EMPTY = 0
GOAL_SOIL = 1

DIRS: Dict[str, Tuple[int, int]] = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}

MOVE_TO_CHAR = {
    "up": "↑",
    "down": "↓",
    "left": "←",
    "right": "→",
}
CHAR_TO_MOVE = {v: k for k, v in MOVE_TO_CHAR.items()}

CELL_SIZE = 56
EDITOR_PANEL_WIDTH = 430
GRID_LINE_COLOR = (40, 40, 40)
BG_COLOR = (24, 24, 28)
TEXT_COLOR = (235, 235, 235)
SUB_TEXT_COLOR = (180, 180, 180)
PANEL_COLOR = (34, 35, 40)
BUTTON_COLOR = (70, 72, 82)
BUTTON_HOVER_COLOR = (95, 98, 112)
SELECT_COLOR = (240, 212, 92)

COLOR_VOID = (18, 18, 22)
COLOR_FLOOR = (170, 139, 90)
COLOR_STONE = (110, 110, 116)
COLOR_SOIL = (140, 90, 48)
COLOR_GOAL_SOIL = (90, 220, 120)

DEFAULT_VICTORY_MODE = "all_actors_on_goals"
ActorState = Tuple[Tuple[int, int], ...]


@dataclass
class LevelData:
    name: str
    width: int
    height: int
    terrain: List[List[int]]
    actors: List[List[int]]
    goals: List[List[int]]
    victory_mode: str = DEFAULT_VICTORY_MODE

    def clone(self) -> "LevelData":
        return LevelData(
            name=self.name,
            width=self.width,
            height=self.height,
            terrain=[row[:] for row in self.terrain],
            actors=[row[:] for row in self.actors],
            goals=[row[:] for row in self.goals],
            victory_mode=self.victory_mode,
        )


@dataclass
class StateGraphResult:
    states: List[ActorState]
    depths: List[int]
    edges: List[Tuple[int, int, str]]
    parents: List[Optional[int]]
    parent_moves: List[Optional[str]]
    start_index: int = 0
    solution_index: Optional[int] = None
    solution_moves: Optional[List[str]] = None
    expanded_count: int = 0
    truncated: bool = False


@dataclass
class Button:
    rect: pygame.Rect
    text: str

    def draw(self, surface: pygame.Surface, hovered: bool = False) -> None:
        color = BUTTON_HOVER_COLOR if hovered else BUTTON_COLOR
        pygame.draw.rect(surface, color, self.rect, border_radius=8)
        pygame.draw.rect(surface, (120, 124, 136), self.rect, 2, border_radius=8)
        draw_text_center(surface, self.text, self.rect.center, 22)



def create_empty_level(width: int, height: int, name: str = "新关卡") -> LevelData:
    terrain = [[TERRAIN_FLOOR for _ in range(width)] for _ in range(height)]
    actors = [[ACTOR_EMPTY for _ in range(width)] for _ in range(height)]
    goals = [[GOAL_EMPTY for _ in range(width)] for _ in range(height)]
    return LevelData(name=name, width=width, height=height, terrain=terrain, actors=actors, goals=goals)



def level_to_dict(level: LevelData) -> dict:
    return {
        "name": level.name,
        "width": level.width,
        "height": level.height,
        "terrain": level.terrain,
        "actors": level.actors,
        "goals": level.goals,
        "victory_mode": level.victory_mode,
    }



def validate_level_dict(data: dict) -> None:
    required = ["name", "width", "height", "terrain", "actors", "goals"]
    for key in required:
        if key not in data:
            raise ValueError(f"关卡文件缺少必要字段: {key}")

    width = data["width"]
    height = data["height"]
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError("width 和 height 必须是正整数")

    for layer_name in ["terrain", "actors", "goals"]:
        layer = data[layer_name]
        if not isinstance(layer, list) or len(layer) != height:
            raise ValueError(f"{layer_name} 的行数必须等于 height")
        for row in layer:
            if not isinstance(row, list) or len(row) != width:
                raise ValueError(f"{layer_name} 的每一行长度必须等于 width")
            for v in row:
                if not isinstance(v, int):
                    raise ValueError(f"{layer_name} 中必须全为整数")



def load_level(path: str | Path) -> LevelData:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    validate_level_dict(data)
    return LevelData(
        name=data["name"],
        width=data["width"],
        height=data["height"],
        terrain=data["terrain"],
        actors=data["actors"],
        goals=data["goals"],
        victory_mode=data.get("victory_mode", DEFAULT_VICTORY_MODE),
    )



def save_level(level: LevelData, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(level_to_dict(level), f, ensure_ascii=False, indent=2)



def actor_state_from_level(level: LevelData) -> ActorState:
    result = []
    for y in range(level.height):
        for x in range(level.width):
            if level.actors[y][x] != ACTOR_EMPTY:
                result.append((x, y))
    result.sort()
    return tuple(result)



def level_from_actor_state(level: LevelData, state: ActorState) -> LevelData:
    new_level = level.clone()
    for y in range(new_level.height):
        for x in range(new_level.width):
            new_level.actors[y][x] = ACTOR_EMPTY
    for x, y in state:
        if 0 <= x < new_level.width and 0 <= y < new_level.height:
            new_level.actors[y][x] = ACTOR_SOIL
    return new_level



def is_inside(level: LevelData, x: int, y: int) -> bool:
    return 0 <= x < level.width and 0 <= y < level.height



def is_walkable_terrain(level: LevelData, x: int, y: int) -> bool:
    if not is_inside(level, x, y):
        return False
    return level.terrain[y][x] == TERRAIN_FLOOR



def is_victory_state(level: LevelData, state: ActorState) -> bool:
    actor_set = set(state)
    goal_cells = {
        (x, y)
        for y in range(level.height)
        for x in range(level.width)
        if level.goals[y][x] == GOAL_SOIL
    }

    if level.victory_mode == "any":
        return len(actor_set & goal_cells) > 0
    return goal_cells.issubset(actor_set) if goal_cells else False



def _group_actors_for_move(state: ActorState, move_name: str) -> List[List[Tuple[int, int]]]:
    dx, dy = DIRS[move_name]
    actor_set = set(state)
    visited: Set[Tuple[int, int]] = set()
    groups: List[List[Tuple[int, int]]] = []

    if dx != 0:
        order = sorted(state, key=lambda p: (p[1], p[0]))
        for x, y in order:
            if (x, y) in visited:
                continue
            left = x
            while (left - 1, y) in actor_set:
                left -= 1
            chain = []
            cur = left
            while (cur, y) in actor_set:
                chain.append((cur, y))
                visited.add((cur, y))
                cur += 1
            groups.append(chain)
    else:
        order = sorted(state, key=lambda p: (p[0], p[1]))
        for x, y in order:
            if (x, y) in visited:
                continue
            top = y
            while (x, top - 1) in actor_set:
                top -= 1
            chain = []
            cur = top
            while (x, cur) in actor_set:
                chain.append((x, cur))
                visited.add((x, cur))
                cur += 1
            groups.append(chain)

    if dx > 0:
        groups.sort(key=lambda g: (g[0][1], g[-1][0]))
    elif dx < 0:
        groups.sort(key=lambda g: (g[0][1], g[0][0]))
    elif dy > 0:
        groups.sort(key=lambda g: (g[0][0], g[-1][1]))
    else:
        groups.sort(key=lambda g: (g[0][0], g[0][1]))

    return groups



def move_actor_state(level: LevelData, state: ActorState, move_name: str) -> ActorState:
    if move_name not in DIRS:
        return state

    dx, dy = DIRS[move_name]
    actor_set = set(state)
    moving_set: Set[Tuple[int, int]] = set()

    groups = _group_actors_for_move(state, move_name)
    group_can_move: List[bool] = []

    for group in groups:
        front_x, front_y = max(group, key=lambda p: p[0] * dx + p[1] * dy)
        nx, ny = front_x + dx, front_y + dy
        can_move = is_walkable_terrain(level, nx, ny) and ((nx, ny) not in actor_set)
        group_can_move.append(can_move)
        if can_move:
            moving_set.update(group)

    new_positions = []
    for group, can_move in zip(groups, group_can_move):
        for x, y in group:
            if can_move:
                new_positions.append((x + dx, y + dy))
            else:
                new_positions.append((x, y))

    new_positions.sort()
    return tuple(new_positions)



def _reconstruct_solution_from_indices(parents, parent_moves, solution_index: int) -> List[str]:
    path: List[str] = []
    cur = solution_index
    while cur is not None:
        prev = parents[cur]
        move = parent_moves[cur]
        if prev is None or move is None:
            break
        path.append(move)
        cur = prev
    path.reverse()
    return path



def analyze_level_state_graph(level: LevelData, max_states: int = 200000, max_depth: Optional[int] = None) -> StateGraphResult:
    from collections import deque

    start = actor_state_from_level(level)
    states: List[ActorState] = [start]
    depths: List[int] = [0]
    parents: List[Optional[int]] = [None]
    parent_moves: List[Optional[str]] = [None]
    edges: List[Tuple[int, int, str]] = []

    state_to_index: Dict[ActorState, int] = {start: 0}
    queue = deque([0])

    solution_index: Optional[int] = 0 if is_victory_state(level, start) else None
    truncated = False
    expanded_count = 0

    while queue:
        src_index = queue.popleft()
        state = states[src_index]
        depth = depths[src_index]
        expanded_count += 1

        if max_depth is not None and depth >= max_depth:
            continue

        for move_name in ("up", "down", "left", "right"):
            new_state = move_actor_state(level, state, move_name)
            if new_state == state:
                continue

            dst_index = state_to_index.get(new_state)
            if dst_index is None:
                if len(states) >= max_states:
                    truncated = True
                    continue

                dst_index = len(states)
                state_to_index[new_state] = dst_index
                states.append(new_state)
                depths.append(depth + 1)
                parents.append(src_index)
                parent_moves.append(move_name)
                queue.append(dst_index)

                if solution_index is None and is_victory_state(level, new_state):
                    solution_index = dst_index

            edges.append((src_index, dst_index, move_name))

    solution_moves = None if solution_index is None else _reconstruct_solution_from_indices(parents, parent_moves, solution_index)

    return StateGraphResult(
        states=states,
        depths=depths,
        edges=edges,
        parents=parents,
        parent_moves=parent_moves,
        start_index=0,
        solution_index=solution_index,
        solution_moves=solution_moves,
        expanded_count=expanded_count,
        truncated=truncated,
    )



def solve_level_bfs(level: LevelData, max_states: int = 200000) -> Optional[List[str]]:
    result = analyze_level_state_graph(level, max_states=max_states, max_depth=None)
    return result.solution_moves



def _get_font(size: int) -> pygame.font.Font:
    return pygame.font.SysFont("microsoftyahei,simhei,arial", size)



def draw_text(surface: pygame.Surface, text: str, x: int, y: int, size: int = 24, color=TEXT_COLOR) -> None:
    font = _get_font(size)
    img = font.render(text, True, color)
    surface.blit(img, (x, y))



def draw_text_center(surface: pygame.Surface, text: str, center: Tuple[int, int], size: int = 24, color=TEXT_COLOR) -> None:
    font = _get_font(size)
    img = font.render(text, True, color)
    rect = img.get_rect(center=center)
    surface.blit(img, rect)



def terrain_color(terrain_id: int) -> Tuple[int, int, int]:
    if terrain_id == TERRAIN_FLOOR:
        return COLOR_FLOOR
    if terrain_id == TERRAIN_STONE:
        return COLOR_STONE
    return COLOR_VOID



def goal_color(goal_id: int):
    if goal_id == GOAL_SOIL:
        return COLOR_SOIL
    return None



def draw_terrain(surface: pygame.Surface, rect: pygame.Rect, terrain_id: int) -> None:
    pygame.draw.rect(surface, terrain_color(terrain_id), rect)
    if terrain_id == TERRAIN_STONE:
        margin = 8
        pygame.draw.rect(surface, (90, 90, 96), rect.inflate(-8, -8), border_radius=6)
        pygame.draw.line(surface, (140, 140, 148), (rect.left + margin, rect.centery), (rect.right - margin, rect.centery), 2)
        pygame.draw.line(surface, (140, 140, 148), (rect.centerx, rect.top + margin), (rect.centerx, rect.bottom - margin), 2)
    elif terrain_id == TERRAIN_FLOOR:
        pygame.draw.rect(surface, (196, 163, 108), rect, 2)
    else:
        pygame.draw.rect(surface, (30, 30, 35), rect, 1)



def draw_goal(surface: pygame.Surface, rect: pygame.Rect, goal_id: int) -> None:
    color = goal_color(goal_id)
    if color is None:
        return
    margin = max(1, min(rect.width, rect.height) // 12)
    border_width = max(2, min(rect.width, rect.height) // 12)
    inner_rect = pygame.Rect(rect.x + margin, rect.y + margin, rect.width - 2 * margin, rect.height - 2 * margin)
    pygame.draw.rect(surface, color, inner_rect, border_width)



def draw_actor(surface: pygame.Surface, rect: pygame.Rect, actor_id: int, bob_phase: float = 0.0) -> None:
    if actor_id == ACTOR_EMPTY:
        return
    if actor_id == ACTOR_SOIL:
        cx, cy = rect.center
        body_rect = pygame.Rect(0, 0, int(rect.width * 0.58), int(rect.height * 0.58))
        body_rect.center = (cx, cy + int(math.sin(bob_phase) * 2))
        pygame.draw.ellipse(surface, COLOR_SOIL, body_rect)
        pygame.draw.ellipse(surface, (90, 58, 28), body_rect, 2)
        eye_y = body_rect.y + body_rect.height * 0.4
        eye_dx = body_rect.width * 0.18
        pygame.draw.circle(surface, (22, 22, 22), (int(cx - eye_dx), int(eye_y)), max(2, rect.width // 18))
        pygame.draw.circle(surface, (22, 22, 22), (int(cx + eye_dx), int(eye_y)), max(2, rect.width // 18))



def draw_cell_overlay(surface: pygame.Surface, x: int, y: int, size: int) -> None:
    r = pygame.Rect(x, y, size, size)
    pygame.draw.rect(surface, SELECT_COLOR, r, 3)



def draw_level(surface: pygame.Surface, level: LevelData, offset_x: int = 0, offset_y: int = 0, cell_size: int = CELL_SIZE) -> None:
    for y in range(level.height):
        for x in range(level.width):
            rect = pygame.Rect(offset_x + x * cell_size, offset_y + y * cell_size, cell_size, cell_size)
            terrain_id = level.terrain[y][x]
            goal_id = level.goals[y][x]
            actor_id = level.actors[y][x]
            draw_terrain(surface, rect, terrain_id)
            draw_goal(surface, rect, goal_id)
            draw_actor(surface, rect, actor_id)
            pygame.draw.rect(surface, GRID_LINE_COLOR, rect, 1)


# =============================================================================
# 兼容旧版 main.py 的接口
# =============================================================================

def is_victory(level: LevelData) -> bool:
    """
    兼容旧接口：
    直接对当前 level 的 actors 布局判断是否胜利。
    """
    state = actor_state_from_level(level)
    return is_victory_state(level, state)


def move_level(level: LevelData, move_name: str) -> LevelData:
    """
    兼容旧接口：
    输入一个关卡对象和方向，返回移动后的新关卡对象。
    不修改原 level。
    """
    old_state = actor_state_from_level(level)
    new_state = move_actor_state(level, old_state, move_name)
    return level_from_actor_state(level, new_state)