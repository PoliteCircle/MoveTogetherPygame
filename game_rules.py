from __future__ import annotations

"""
game_rules.py
=============
统一管理：
1. 地形 / 角色 / 目标的定义；
2. 编辑器资源面板数据；
3. 地图可放置规则；
4. 角色移动、推动、胜利判定等核心规则。

设计目标：
- 以后新增普通角色 / 目标 / 地形时，优先只改这里；
- main.py / mapedit.py / core.py 不再维护自己的资源表；
- 若新对象仍使用已有绘图风格，则无需修改其他文件。
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

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

GOAL_EMPTY = 0
GOAL_RED = 1
GOAL_YELLOW = 2
GOAL_BLUE = 3
GOAL_GREEN = 4
GOAL_BALL = 5

# 兼容旧命名
ACTOR_SOIL = ACTOR_RED
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
# 定义类
# =============================================================================

@dataclass(frozen=True)
class TerrainDef:
    id: int
    name: str
    walkable: bool
    accepts_actor: bool
    accepts_goal: bool
    base_color: Tuple[int, int, int]
    render_style: str = "solid"


@dataclass(frozen=True)
class ActorDef:
    id: int
    name: str
    color: Tuple[int, int, int]
    responds_to_input: bool
    pushable: bool
    goal_id: Optional[int]
    render_style: str = "blob"


@dataclass(frozen=True)
class GoalDef:
    id: int
    name: str
    actor_id: Optional[int]
    color: Tuple[int, int, int]
    render_shape: str = "square"


# =============================================================================
# 可扩展注册表
# 以后新增普通对象，主要改这里
# =============================================================================

TERRAIN_DEFS: Dict[int, TerrainDef] = {
    TERRAIN_VOID: TerrainDef(
        id=TERRAIN_VOID,
        name="虚空",
        walkable=False,
        accepts_actor=False,
        accepts_goal=False,
        base_color=(18, 18, 22),
        render_style="void",
    ),
    TERRAIN_FLOOR: TerrainDef(
        id=TERRAIN_FLOOR,
        name="平地",
        walkable=True,
        accepts_actor=True,
        accepts_goal=True,
        base_color=(170, 139, 90),
        render_style="floor",
    ),
    TERRAIN_STONE: TerrainDef(
        id=TERRAIN_STONE,
        name="石头",
        walkable=False,
        accepts_actor=False,
        accepts_goal=False,
        base_color=(110, 110, 116),
        render_style="stone",
    ),
}

ACTOR_DEFS: Dict[int, ActorDef] = {
    ACTOR_RED: ActorDef(
        id=ACTOR_RED,
        name="红色角色",
        color=(220, 74, 74),
        responds_to_input=True,
        pushable=False,
        goal_id=GOAL_RED,
        render_style="blob",
    ),
    ACTOR_YELLOW: ActorDef(
        id=ACTOR_YELLOW,
        name="黄色角色",
        color=(236, 202, 70),
        responds_to_input=True,
        pushable=False,
        goal_id=GOAL_YELLOW,
        render_style="blob",
    ),
    ACTOR_BLUE: ActorDef(
        id=ACTOR_BLUE,
        name="蓝色角色",
        color=(74, 136, 236),
        responds_to_input=True,
        pushable=False,
        goal_id=GOAL_BLUE,
        render_style="blob",
    ),
    ACTOR_GREEN: ActorDef(
        id=ACTOR_GREEN,
        name="绿色角色",
        color=(72, 190, 116),
        responds_to_input=True,
        pushable=False,
        goal_id=GOAL_GREEN,
        render_style="blob",
    ),
    ACTOR_BALL: ActorDef(
        id=ACTOR_BALL,
        name="白色小球",
        color=(240, 240, 240),
        responds_to_input=False,
        pushable=True,
        goal_id=GOAL_BALL,
        render_style="ball",
    ),
}

GOAL_DEFS: Dict[int, GoalDef] = {
    GOAL_RED: GoalDef(
        id=GOAL_RED,
        name="红色目标",
        actor_id=ACTOR_RED,
        color=(220, 74, 74),
        render_shape="square",
    ),
    GOAL_YELLOW: GoalDef(
        id=GOAL_YELLOW,
        name="黄色目标",
        actor_id=ACTOR_YELLOW,
        color=(236, 202, 70),
        render_shape="square",
    ),
    GOAL_BLUE: GoalDef(
        id=GOAL_BLUE,
        name="蓝色目标",
        actor_id=ACTOR_BLUE,
        color=(74, 136, 236),
        render_shape="square",
    ),
    GOAL_GREEN: GoalDef(
        id=GOAL_GREEN,
        name="绿色目标",
        actor_id=ACTOR_GREEN,
        color=(72, 190, 116),
        render_shape="square",
    ),
    GOAL_BALL: GoalDef(
        id=GOAL_BALL,
        name="小球目标",
        actor_id=ACTOR_BALL,
        color=(240, 240, 240),
        render_shape="circle",
    ),
}


# =============================================================================
# 元数据查询
# =============================================================================

def terrain_def(terrain_id: int) -> TerrainDef:
    return TERRAIN_DEFS.get(terrain_id, TERRAIN_DEFS[TERRAIN_VOID])


def actor_def(actor_id: int) -> Optional[ActorDef]:
    return ACTOR_DEFS.get(actor_id)


def goal_def(goal_id: int) -> Optional[GoalDef]:
    return GOAL_DEFS.get(goal_id)


def terrain_name(terrain_id: int) -> str:
    return terrain_def(terrain_id).name


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


def terrain_is_walkable(terrain_id: int) -> bool:
    return terrain_def(terrain_id).walkable


def can_place_actor_on_terrain_id(terrain_id: int) -> bool:
    return terrain_def(terrain_id).accepts_actor


def can_place_goal_on_terrain_id(terrain_id: int) -> bool:
    return terrain_def(terrain_id).accepts_goal


# =============================================================================
# 编辑器资源配置
# mapedit.py 只需要调用这些函数
# =============================================================================

def build_terrain_resources() -> List[dict]:
    return [{"id": tid, "name": info.name} for tid, info in sorted(TERRAIN_DEFS.items(), key=lambda x: x[0])]


def build_goal_resources() -> List[dict]:
    return [{"id": GOAL_EMPTY, "name": "无目标"}] + [
        {"id": gid, "name": info.name}
        for gid, info in sorted(GOAL_DEFS.items(), key=lambda x: x[0])
    ]


def build_actor_resources() -> List[dict]:
    return [{"id": ACTOR_EMPTY, "name": "无角色"}] + [
        {"id": aid, "name": info.name}
        for aid, info in sorted(ACTOR_DEFS.items(), key=lambda x: x[0])
    ]


def get_resource_groups() -> Dict[str, dict]:
    return {
        "terrain": {"title": "选择地形", "items": build_terrain_resources()},
        "goal": {"title": "选择目标位置", "items": build_goal_resources()},
        "actor": {"title": "选择角色", "items": build_actor_resources()},
    }


def get_base_brush_by_group() -> Dict[str, int]:
    return {
        "terrain": TERRAIN_FLOOR,
        "goal": GOAL_EMPTY,
        "actor": ACTOR_EMPTY,
    }


# =============================================================================
# 规则层辅助
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
    return is_inside(level, x, y) and terrain_is_walkable(level.terrain[y][x])


def can_place_actor(level, x: int, y: int) -> bool:
    return is_inside(level, x, y) and can_place_actor_on_terrain_id(level.terrain[y][x])


def can_place_goal(level, x: int, y: int) -> bool:
    return is_inside(level, x, y) and can_place_goal_on_terrain_id(level.terrain[y][x])


def level_from_actor_state(level, state: ActorState):
    new_level = level.clone()
    new_level.actors = [[ACTOR_EMPTY for _ in range(level.width)] for _ in range(level.height)]
    for x, y, actor_id in state:
        if is_inside(new_level, x, y):
            new_level.actors[y][x] = actor_id
    return new_level


# =============================================================================
# 胜利规则
# =============================================================================

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


# =============================================================================
# 移动 / 推动规则
# =============================================================================

def _sorted_state_for_move(state: ActorState, move_name: str) -> List[Tuple[int, int, int]]:
    dx, dy = DIRS[move_name]
    items = list(state)

    if dx > 0:
        items.sort(key=lambda item: (-item[0], item[1], item[2]))
    elif dx < 0:
        items.sort(key=lambda item: (item[0], item[1], item[2]))
    elif dy > 0:
        items.sort(key=lambda item: (-item[1], item[0], item[2]))
    else:
        items.sort(key=lambda item: (item[1], item[0], item[2]))

    return items


def _collect_push_chain(
    level,
    occupied: Dict[Tuple[int, int], int],
    start_x: int,
    start_y: int,
    dx: int,
    dy: int,
) -> Optional[List[Tuple[int, int, int]]]:
    """
    从 front cell 开始收集一整条可被推动的链。
    返回:
    - None: 无法推动
    - List[(x, y, actor_id)]: 可以推动的链
    """
    chain: List[Tuple[int, int, int]] = []
    cx, cy = start_x, start_y

    while True:
        actor_id = occupied.get((cx, cy))
        if actor_id is None:
            break
        if not actor_is_pushable(actor_id):
            return None
        chain.append((cx, cy, actor_id))
        cx += dx
        cy += dy

    if not is_walkable_terrain(level, cx, cy):
        return None
    if (cx, cy) in occupied:
        return None

    return chain


def move_actor_state(level, state: ActorState, move_name: str) -> ActorState:
    if move_name not in DIRS:
        return state

    dx, dy = DIRS[move_name]
    occupied: Dict[Tuple[int, int], int] = {(x, y): actor_id for x, y, actor_id in state}

    for x, y, actor_id in _sorted_state_for_move(state, move_name):
        current_actor = occupied.get((x, y))
        if current_actor is None:
            continue
        if current_actor != actor_id:
            continue
        if not actor_responds_to_input(actor_id):
            continue

        nx, ny = x + dx, y + dy
        if not is_walkable_terrain(level, nx, ny):
            continue

        blocker = occupied.get((nx, ny))
        if blocker is None:
            occupied[(nx, ny)] = actor_id
            del occupied[(x, y)]
            continue

        chain = _collect_push_chain(level, occupied, nx, ny, dx, dy)
        if chain is None:
            continue

        for bx, by, bid in reversed(chain):
            occupied[(bx + dx, by + dy)] = bid
            del occupied[(bx, by)]

        occupied[(nx, ny)] = actor_id
        del occupied[(x, y)]

    result = [(x, y, actor_id) for (x, y), actor_id in occupied.items()]
    result.sort(key=lambda item: (item[1], item[0], item[2]))
    return tuple(result)


def move_level(level, move_name: str):
    return level_from_actor_state(level, move_actor_state(level, actor_state_from_level(level), move_name))


def is_victory(level) -> bool:
    return is_victory_state(level, actor_state_from_level(level))