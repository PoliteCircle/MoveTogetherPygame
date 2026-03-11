"""
core.py
=======
负责：
1. 关卡数据结构与读写；
2. 基础绘制；
3. BFS 求解与状态空间分析；
4. 对外兼容的 move_level / is_victory 等接口。

地形 / 角色 / 目标的具体定义，以及它们的移动与胜利逻辑，
已经统一迁移到 game_rules.py 中，方便后续集中扩展。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygame

from game_rules import (
    ACTOR_BALL,
    ACTOR_BLUE,
    ACTOR_DEFS,
    ACTOR_EMPTY,
    ACTOR_GREEN,
    ACTOR_RED,
    ACTOR_RESOURCES,
    ACTOR_SOIL,
    ACTOR_YELLOW,
    ActorState,
    BASE_BRUSH_BY_GROUP,
    CHAR_TO_MOVE,
    DEFAULT_VICTORY_MODE,
    DIRS,
    GOAL_BALL,
    GOAL_BLUE,
    GOAL_DEFS,
    GOAL_EMPTY,
    GOAL_GREEN,
    GOAL_RED,
    GOAL_RESOURCES,
    GOAL_SOIL,
    GOAL_YELLOW,
    MOVE_TO_CHAR,
    RESOURCE_GROUPS,
    TERRAIN_DEFS,
    TERRAIN_FLOOR,
    TERRAIN_RESOURCES,
    TERRAIN_STONE,
    TERRAIN_VOID,
    actor_def,
    actor_name,
    actor_state_from_level,
    goal_def,
    is_inside,
    is_victory_state,
    is_walkable_terrain,
    move_actor_state,
    terrain_def,
)

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


def level_from_actor_state(level: LevelData, state: ActorState) -> LevelData:
    new_level = level.clone()
    for y in range(new_level.height):
        for x in range(new_level.width):
            new_level.actors[y][x] = ACTOR_EMPTY
    for x, y, actor_id in state:
        if 0 <= x < new_level.width and 0 <= y < new_level.height:
            new_level.actors[y][x] = actor_id
    return new_level


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


def solve_level_bfs(level: LevelData, max_states: int = 200000, max_depth: Optional[int] = None) -> Optional[List[str]]:
    result = analyze_level_state_graph(level, max_states=max_states, max_depth=max_depth)
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
    return terrain_def(terrain_id).base_color


def goal_color(goal_id: int):
    info = goal_def(goal_id)
    return None if info is None else info.color


def draw_terrain(surface: pygame.Surface, rect: pygame.Rect, terrain_id: int) -> None:
    info = terrain_def(terrain_id)
    pygame.draw.rect(surface, info.base_color, rect)

    if info.style == "stone":
        margin = 8
        pygame.draw.rect(surface, (90, 90, 96), rect.inflate(-8, -8), border_radius=6)
        pygame.draw.line(surface, (140, 140, 148), (rect.left + margin, rect.centery), (rect.right - margin, rect.centery), 2)
        pygame.draw.line(surface, (140, 140, 148), (rect.centerx, rect.top + margin), (rect.centerx, rect.bottom - margin), 2)
    elif info.style == "floor":
        pygame.draw.rect(surface, (196, 163, 108), rect, 2)
    else:
        pygame.draw.rect(surface, (30, 30, 35), rect, 1)


def draw_goal(surface: pygame.Surface, rect: pygame.Rect, goal_id: int) -> None:
    info = goal_def(goal_id)
    if info is None:
        return

    margin = max(2, min(rect.width, rect.height) // 10)
    border_width = max(2, min(rect.width, rect.height) // 10)
    inner_rect = pygame.Rect(rect.x + margin, rect.y + margin, rect.width - 2 * margin, rect.height - 2 * margin)

    if info.shape == "circle":
        pygame.draw.ellipse(surface, info.color, inner_rect, border_width)
    else:
        pygame.draw.rect(surface, info.color, inner_rect, border_width)


def _draw_blob_actor(surface: pygame.Surface, rect: pygame.Rect, color: Tuple[int, int, int], bob_phase: float = 0.0) -> None:
    cx, cy = rect.center
    body_rect = pygame.Rect(0, 0, int(rect.width * 0.58), int(rect.height * 0.58))
    body_rect.center = (cx, cy + int(math.sin(bob_phase) * 2))
    pygame.draw.ellipse(surface, color, body_rect)
    outline = tuple(max(0, c - 55) for c in color)
    pygame.draw.ellipse(surface, outline, body_rect, 2)
    eye_y = body_rect.y + body_rect.height * 0.4
    eye_dx = body_rect.width * 0.18
    pygame.draw.circle(surface, (22, 22, 22), (int(cx - eye_dx), int(eye_y)), max(2, rect.width // 18))
    pygame.draw.circle(surface, (22, 22, 22), (int(cx + eye_dx), int(eye_y)), max(2, rect.width // 18))


def _draw_ball_actor(surface: pygame.Surface, rect: pygame.Rect, color: Tuple[int, int, int]) -> None:
    margin = rect.width // 2
    circle_rect = rect.inflate(-margin, -margin)
    pygame.draw.ellipse(surface, color, circle_rect)
    # pygame.draw.ellipse(surface, (120, 120, 120), circle_rect, 2)
    shine = pygame.Rect(circle_rect.x + circle_rect.width // 5, circle_rect.y + circle_rect.height // 6, circle_rect.width // 4, circle_rect.height // 4)
    pygame.draw.ellipse(surface, (255, 255, 255), shine)


def draw_actor(surface: pygame.Surface, rect: pygame.Rect, actor_id: int, bob_phase: float = 0.0) -> None:
    if actor_id == ACTOR_EMPTY:
        return
    info = actor_def(actor_id)
    if info is None:
        return
    if info.style == "ball":
        _draw_ball_actor(surface, rect, info.color)
    else:
        _draw_blob_actor(surface, rect, info.color, bob_phase)


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
# 兼容旧版接口
# =============================================================================

def is_victory(level: LevelData) -> bool:
    return is_victory_state(level, actor_state_from_level(level))


def move_level(level: LevelData, move_name: str) -> LevelData:
    old_state = actor_state_from_level(level)
    new_state = move_actor_state(level, old_state, move_name)
    return level_from_actor_state(level, new_state)