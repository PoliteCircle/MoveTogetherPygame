from __future__ import annotations

"""
core.py
=======
负责：
1. 关卡数据结构与读写；
2. BFS 求解与状态空间分析；
3. 对外兼容的 move_level / is_victory 接口。

说明：
- JSON 关卡格式只保存静态信息：name / width / height / terrain / actors / goals / boundary / shock。
- 角色麻痹状态与已消耗电击格属于运行时状态，不写回 JSON，而是放在求解状态中。
- 为兼容旧版本关卡，load_level() 会尽力把旧格式转换为新格式。
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from game_rules import (
    ACTOR_EMPTY,
    ActorState,
    actor_state_from_level,
    is_victory_state,
    level_from_actor_state as rules_level_from_actor_state,
    move_actor_state,
)

BOUNDARY_CLOSED = "closed"
BOUNDARY_OPEN = "open"
VALID_BOUNDARIES = {BOUNDARY_CLOSED, BOUNDARY_OPEN}


@dataclass
class LevelData:
    name: str
    width: int
    height: int
    terrain: List[List[int]]
    actors: List[List[int]]
    goals: List[List[int]]
    boundary: str
    shock: List[List[int]]

    def clone(self) -> "LevelData":
        cloned = LevelData(
            name=self.name,
            width=self.width,
            height=self.height,
            terrain=[row[:] for row in self.terrain],
            actors=[row[:] for row in self.actors],
            goals=[row[:] for row in self.goals],
            boundary=self.boundary,
            shock=[row[:] for row in self.shock],
        )

        # 运行时附加状态不写入 JSON，但在 clone 时保留，方便求解器 / 预览器复用。
        actor_status = getattr(self, "actor_status", None)
        if actor_status is not None:
            cloned.actor_status = [row[:] for row in actor_status]

        shock_used = getattr(self, "shock_used", None)
        if shock_used is not None:
            cloned.shock_used = [row[:] for row in shock_used]

        if hasattr(self, "victory_mode"):
            cloned.victory_mode = getattr(self, "victory_mode")

        if hasattr(self, "_has_wrapping_edges_cache"):
            cloned._has_wrapping_edges_cache = getattr(self, "_has_wrapping_edges_cache")

        return cloned


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


def create_empty_level(width: int, height: int, name: str = "新关卡") -> LevelData:
    from game_rules import GOAL_EMPTY, TERRAIN_FLOOR

    terrain = [[TERRAIN_FLOOR for _ in range(width)] for _ in range(height)]
    actors = [[ACTOR_EMPTY for _ in range(width)] for _ in range(height)]
    goals = [[GOAL_EMPTY for _ in range(width)] for _ in range(height)]
    shock = [[0 for _ in range(width)] for _ in range(height)]
    return LevelData(
        name=name,
        width=width,
        height=height,
        terrain=terrain,
        actors=actors,
        goals=goals,
        boundary=BOUNDARY_CLOSED,
        shock=shock,
    )


def level_to_dict(level: LevelData) -> dict:
    return {
        "name": level.name,
        "width": level.width,
        "height": level.height,
        "terrain": level.terrain,
        "actors": level.actors,
        "goals": level.goals,
        "boundary": level.boundary,
        "shock": level.shock,
    }


def _validate_layer(data: dict, layer_name: str, width: int, height: int) -> None:
    layer = data[layer_name]
    if not isinstance(layer, list) or len(layer) != height:
        raise ValueError(f"{layer_name} 的行数必须等于 height")
    for row in layer:
        if not isinstance(row, list) or len(row) != width:
            raise ValueError(f"{layer_name} 的每一行长度必须等于 width")
        for item in row:
            if not isinstance(item, int):
                raise ValueError(f"{layer_name} 中必须全为整数")


def _normalize_old_level_dict(data: dict) -> dict:
    """
    兼容旧关卡：
    1. 旧版把电击区直接存进 terrain=3，这里迁移到 shock 数组；
    2. 旧版没有 boundary 时，沿用旧规则：地图中存在雪地/冰面则视为开放边界，否则封闭；
    3. 旧版 actor_status / shock_used / victory_mode 直接忽略，不再写回。
    """
    from game_rules import TERRAIN_FLOOR, TERRAIN_ICE, TERRAIN_SHOCK, TERRAIN_SNOW

    if "shock" not in data:
        width = int(data["width"])
        height = int(data["height"])
        shock = [[0 for _ in range(width)] for _ in range(height)]
        terrain = [[int(v) for v in row] for row in data["terrain"]]
        for y in range(height):
            for x in range(width):
                if terrain[y][x] == TERRAIN_SHOCK:
                    shock[y][x] = 1
                    terrain[y][x] = TERRAIN_FLOOR
        data["terrain"] = terrain
        data["shock"] = shock

    if "boundary" not in data:
        has_opening_terrain = any(
            tid in (TERRAIN_SNOW, TERRAIN_ICE)
            for row in data["terrain"]
            for tid in row
        )
        data["boundary"] = BOUNDARY_OPEN if has_opening_terrain else BOUNDARY_CLOSED

    return data


def validate_level_dict(data: dict) -> None:
    required = ["name", "width", "height", "terrain", "actors", "goals", "boundary", "shock"]
    for key in required:
        if key not in data:
            raise ValueError(f"关卡文件缺少必要字段: {key}")

    width = data["width"]
    height = data["height"]
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError("width 和 height 必须是正整数")

    for layer_name in ("terrain", "actors", "goals", "shock"):
        _validate_layer(data, layer_name, width, height)

    boundary = data["boundary"]
    if not isinstance(boundary, str) or boundary not in VALID_BOUNDARIES:
        raise ValueError("boundary 必须是 'closed' 或 'open'")


def load_level(path: str | Path) -> LevelData:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data = _normalize_old_level_dict(data)
    validate_level_dict(data)

    return LevelData(
        name=str(data["name"]),
        width=int(data["width"]),
        height=int(data["height"]),
        terrain=[[int(v) for v in row] for row in data["terrain"]],
        actors=[[int(v) for v in row] for row in data["actors"]],
        goals=[[int(v) for v in row] for row in data["goals"]],
        boundary=str(data["boundary"]),
        shock=[[int(v) for v in row] for row in data["shock"]],
    )


def save_level(level: LevelData, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(level_to_dict(level), f, ensure_ascii=False, indent=2)


def level_from_actor_state(level: LevelData, state: ActorState) -> LevelData:
    return rules_level_from_actor_state(level, state)


def move_level(level: LevelData, move_name: str) -> LevelData:
    old_state = actor_state_from_level(level)
    new_state = move_actor_state(level, old_state, move_name)
    return level_from_actor_state(level, new_state)


def is_victory(level: LevelData) -> bool:
    return is_victory_state(level, actor_state_from_level(level))


def _reconstruct_solution_from_indices(
    parents: List[Optional[int]],
    parent_moves: List[Optional[str]],
    solution_index: int,
) -> List[str]:
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


def analyze_level_state_graph(
    level: LevelData,
    max_states: int = 200000,
    max_depth: Optional[int] = None,
) -> StateGraphResult:
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


def solve_level_bfs(
    level: LevelData,
    max_states: int = 200000,
    max_depth: Optional[int] = None,
) -> Optional[List[str]]:
    graph = analyze_level_state_graph(level, max_states=max_states, max_depth=max_depth)
    return graph.solution_moves
