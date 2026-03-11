from __future__ import annotations

"""
game_rules.py
=============
统一管理：
1. 地形 / 角色 / 目标的定义与资源配置；
2. 角色响应方向键、推动小球、胜利判定等规则；
3. 供 core.py / main.py / mapedit.py 复用的元数据。

以后想扩展新的角色、目标、被推动物体，只需要优先改这里。
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# =============================================================================
# 基础常量
# =============================================================================

TERRAIN_VOID = 0
TERRAIN_FLOOR = 1
TERRAIN_STONE = 2

ACTOR_EMPTY = 0
ACTOR_RED = 1
ACTOR_YELLOW = 2
ACTOR_BLUE = 3
ACTOR_GREEN = 4
ACTOR_BALL = 5

# 兼容旧命名：旧关卡里的“土人”现在视为红色角色
ACTOR_SOIL = ACTOR_RED

GOAL_EMPTY = 0
GOAL_RED = 1
GOAL_YELLOW = 2
GOAL_BLUE = 3
GOAL_GREEN = 4
GOAL_BALL = 5

# 兼容旧命名：旧关卡里的“土人目标”现在视为红色目标
GOAL_SOIL = GOAL_RED

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

DEFAULT_VICTORY_MODE = "all_matching_goals"

# ActorState: (x, y, actor_id)
ActorState = Tuple[Tuple[int, int, int], ...]


# =============================================================================
# 元数据定义
# =============================================================================

@dataclass(frozen=True)
class TerrainDef:
    id: int
    name: str
    walkable: bool
    base_color: Tuple[int, int, int]
    style: str = "solid"


@dataclass(frozen=True)
class ActorDef:
    id: int
    name: str
    color: Tuple[int, int, int]
    responds_to_input: bool
    pushable: bool
    goal_id: Optional[int]
    style: str = "blob"


@dataclass(frozen=True)
class GoalDef:
    id: int
    name: str
    actor_id: Optional[int]
    color: Tuple[int, int, int]
    shape: str = "square"


TERRAIN_DEFS: Dict[int, TerrainDef] = {
    TERRAIN_VOID: TerrainDef(TERRAIN_VOID, "虚空", False, (18, 18, 22), "void"),
    TERRAIN_FLOOR: TerrainDef(TERRAIN_FLOOR, "平地", True, (170, 139, 90), "floor"),
    TERRAIN_STONE: TerrainDef(TERRAIN_STONE, "石头", False, (110, 110, 116), "stone"),
}

ACTOR_DEFS: Dict[int, ActorDef] = {
    ACTOR_RED: ActorDef(ACTOR_RED, "红色角色", (220, 74, 74), True, False, GOAL_RED, "blob"),
    ACTOR_YELLOW: ActorDef(ACTOR_YELLOW, "黄色角色", (236, 202, 70), True, False, GOAL_YELLOW, "blob"),
    ACTOR_BLUE: ActorDef(ACTOR_BLUE, "蓝色角色", (74, 136, 236), True, False, GOAL_BLUE, "blob"),
    ACTOR_GREEN: ActorDef(ACTOR_GREEN, "绿色角色", (72, 190, 116), True, False, GOAL_GREEN, "blob"),
    ACTOR_BALL: ActorDef(ACTOR_BALL, "白色小球", (240, 240, 240), False, True, GOAL_BALL, "ball"),
}

GOAL_DEFS: Dict[int, GoalDef] = {
    GOAL_RED: GoalDef(GOAL_RED, "红色目标", ACTOR_RED, (220, 74, 74), "square"),
    GOAL_YELLOW: GoalDef(GOAL_YELLOW, "黄色目标", ACTOR_YELLOW, (236, 202, 70), "square"),
    GOAL_BLUE: GoalDef(GOAL_BLUE, "蓝色目标", ACTOR_BLUE, (74, 136, 236), "square"),
    GOAL_GREEN: GoalDef(GOAL_GREEN, "绿色目标", ACTOR_GREEN, (72, 190, 116), "square"),
    GOAL_BALL: GoalDef(GOAL_BALL, "小球目标", ACTOR_BALL, (240, 240, 240), "circle"),
}

TERRAIN_RESOURCES = [
    {"id": terrain_id, "name": TERRAIN_DEFS[terrain_id].name}
    for terrain_id in sorted(TERRAIN_DEFS)
]

GOAL_RESOURCES = [
    {"id": GOAL_EMPTY, "name": "无目标"},
    *[
        {"id": goal_id, "name": GOAL_DEFS[goal_id].name}
        for goal_id in sorted(GOAL_DEFS)
    ],
]

ACTOR_RESOURCES = [
    {"id": ACTOR_EMPTY, "name": "无角色"},
    *[
        {"id": actor_id, "name": ACTOR_DEFS[actor_id].name}
        for actor_id in sorted(ACTOR_DEFS)
    ],
]

RESOURCE_GROUPS = {
    "terrain": {"title": "选择地形", "items": TERRAIN_RESOURCES},
    "goal": {"title": "选择目标位置", "items": GOAL_RESOURCES},
    "actor": {"title": "选择角色", "items": ACTOR_RESOURCES},
}

BASE_BRUSH_BY_GROUP = {
    "terrain": TERRAIN_FLOOR,
    "goal": GOAL_EMPTY,
    "actor": ACTOR_EMPTY,
}


# =============================================================================
# 元数据辅助函数
# =============================================================================

def terrain_def(terrain_id: int) -> TerrainDef:
    return TERRAIN_DEFS.get(terrain_id, TERRAIN_DEFS[TERRAIN_VOID])


def actor_def(actor_id: int) -> Optional[ActorDef]:
    return ACTOR_DEFS.get(actor_id)


def goal_def(goal_id: int) -> Optional[GoalDef]:
    return GOAL_DEFS.get(goal_id)


def actor_name(actor_id: int) -> str:
    if actor_id == ACTOR_EMPTY:
        return "无角色"
    info = actor_def(actor_id)
    return info.name if info else f"未知角色({actor_id})"


def goal_name(goal_id: int) -> str:
    if goal_id == GOAL_EMPTY:
        return "无目标"
    info = goal_def(goal_id)
    return info.name if info else f"未知目标({goal_id})"


def actor_goal_id(actor_id: int) -> Optional[int]:
    info = actor_def(actor_id)
    return info.goal_id if info else None


def goal_required_actor(goal_id: int) -> Optional[int]:
    info = goal_def(goal_id)
    return info.actor_id if info else None


def actor_responds_to_input(actor_id: int) -> bool:
    info = actor_def(actor_id)
    return bool(info and info.responds_to_input)


def actor_is_pushable(actor_id: int) -> bool:
    info = actor_def(actor_id)
    return bool(info and info.pushable)


# =============================================================================
# 状态 / 规则
# =============================================================================

def actor_state_from_level(level) -> ActorState:
    result: List[Tuple[int, int, int]] = []
    for y in range(level.height):
        for x in range(level.width):
            actor_id = level.actors[y][x]
            if actor_id != ACTOR_EMPTY:
                result.append((x, y, actor_id))
    result.sort(key=lambda item: (item[1], item[0], item[2]))
    return tuple(result)


def is_inside(level, x: int, y: int) -> bool:
    return 0 <= x < level.width and 0 <= y < level.height


def is_walkable_terrain(level, x: int, y: int) -> bool:
    if not is_inside(level, x, y):
        return False
    return terrain_def(level.terrain[y][x]).walkable


def is_victory_state(level, state: ActorState) -> bool:
    actor_map = {(x, y): actor_id for x, y, actor_id in state}

    if level.victory_mode == "any":
        for y in range(level.height):
            for x in range(level.width):
                goal_id = level.goals[y][x]
                if goal_id == GOAL_EMPTY:
                    continue
                if actor_map.get((x, y)) == goal_required_actor(goal_id):
                    return True
        return False

    has_goal = False
    for y in range(level.height):
        for x in range(level.width):
            goal_id = level.goals[y][x]
            if goal_id == GOAL_EMPTY:
                continue
            has_goal = True
            if actor_map.get((x, y)) != goal_required_actor(goal_id):
                return False
    return has_goal


def _sorted_positions_for_move(state: ActorState, move_name: str) -> List[Tuple[int, int]]:
    dx, dy = DIRS[move_name]
    positions = [(x, y) for x, y, _ in state]
    if dx > 0:
        positions.sort(key=lambda p: (-p[0], p[1]))
    elif dx < 0:
        positions.sort(key=lambda p: (p[0], p[1]))
    elif dy > 0:
        positions.sort(key=lambda p: (-p[1], p[0]))
    else:
        positions.sort(key=lambda p: (p[1], p[0]))
    return positions


def move_actor_state(level, state: ActorState, move_name: str) -> ActorState:
    if move_name not in DIRS:
        return state

    dx, dy = DIRS[move_name]
    occupied: Dict[Tuple[int, int], int] = {(x, y): actor_id for x, y, actor_id in state}

    for x, y in _sorted_positions_for_move(state, move_name):
        actor_id = occupied.get((x, y))
        if actor_id is None:
            continue
        if not actor_responds_to_input(actor_id):
            continue

        nx, ny = x + dx, y + dy
        if not is_walkable_terrain(level, nx, ny):
            continue

        front_cell = occupied.get((nx, ny))
        if front_cell is None:
            occupied[(nx, ny)] = actor_id
            del occupied[(x, y)]
            continue

        if not actor_is_pushable(front_cell):
            continue

        push_chain: List[Tuple[int, int, int]] = []
        cx, cy = nx, ny
        while True:
            blocking_actor = occupied.get((cx, cy))
            if blocking_actor is None:
                break
            if not actor_is_pushable(blocking_actor):
                push_chain = []
                break
            push_chain.append((cx, cy, blocking_actor))
            cx += dx
            cy += dy

        if not push_chain:
            continue
        if not is_walkable_terrain(level, cx, cy):
            continue
        if (cx, cy) in occupied:
            continue

        for bx, by, ball_id in reversed(push_chain):
            occupied[(bx + dx, by + dy)] = ball_id
            del occupied[(bx, by)]

        occupied[(nx, ny)] = actor_id
        del occupied[(x, y)]

    result = [(x, y, actor_id) for (x, y), actor_id in occupied.items()]
    result.sort(key=lambda item: (item[1], item[0], item[2]))
    return tuple(result)


def level_from_actor_state(level, state: ActorState):
    new_level = level.clone()
    new_level.actors = [[ACTOR_EMPTY for _ in range(level.width)] for _ in range(level.height)]
    for x, y, actor_id in state:
        if is_inside(new_level, x, y):
            new_level.actors[y][x] = actor_id
    return new_level


def move_level(level, move_name: str):
    state = actor_state_from_level(level)
    new_state = move_actor_state(level, state, move_name)
    return level_from_actor_state(level, new_state)


def is_victory(level) -> bool:
    return is_victory_state(level, actor_state_from_level(level))


# =============================================================================
# 编辑器 / UI 可用的统一入口
# =============================================================================

def get_resource_groups():
    return RESOURCE_GROUPS


def get_base_brush_by_group():
    return BASE_BRUSH_BY_GROUP.copy()