from __future__ import annotations

"""
core.py
=======
负责：
1. 关卡数据结构与读写；
2. BFS 求解与状态空间分析；
3. 对外兼容的 move_level / is_victory 接口。

注意：
- 可扩展定义与规则在 game_rules.py
- 绘图在 game_render.py
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from game_rules import (
    ACTOR_EMPTY,
    DEFAULT_VICTORY_MODE,
    ActorState,
    actor_state_from_level,
    is_victory_state,
    level_from_actor_state as rules_level_from_actor_state,
    move_actor_state,
)


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


def create_empty_level(width: int, height: int, name: str = "新关卡") -> LevelData:
    from game_rules import GOAL_EMPTY, TERRAIN_FLOOR

    terrain = [[TERRAIN_FLOOR for _ in range(width)] for _ in range(height)]
    actors = [[ACTOR_EMPTY for _ in range(width)] for _ in range(height)]
    goals = [[GOAL_EMPTY for _ in range(width)] for _ in range(height)]
    return LevelData(
        name=name,
        width=width,
        height=height,
        terrain=terrain,
        actors=actors,
        goals=goals,
    )


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

    for layer_name in ("terrain", "actors", "goals"):
        layer = data[layer_name]
        if not isinstance(layer, list) or len(layer) != height:
            raise ValueError(f"{layer_name} 的行数必须等于 height")
        for row in layer:
            if not isinstance(row, list) or len(row) != width:
                raise ValueError(f"{layer_name} 的每一行长度必须等于 width")
            for item in row:
                if not isinstance(item, int):
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

    solution_moves = None
    if solution_index is not None:
        solution_moves = _reconstruct_solution_from_indices(parents, parent_moves, solution_index)

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
    return analyze_level_state_graph(level, max_states=max_states, max_depth=max_depth).solution_moves