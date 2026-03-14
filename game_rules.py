from __future__ import annotations

"""
game_rules.py
=============
统一管理：
1. 地形 / 角色 / 目标的定义；
2. 编辑器资源面板数据；
3. 地图可放置规则；
4. 角色移动、推动、胜利判定等核心规则。

本版本新增：
- 电击区：角色刚进入后，下一次输入会跳过行动（stun_turns=1）。
- 雪地：普通可行走地形，但只要地图中存在雪地或冰面，边界就会首尾相连。
- 冰面：角色/被推动物体如果在本次输入中落到冰面，会沿当前方向继续滑行，直到离开冰面或无法继续。

设计目标：
- 以后新增普通角色 / 目标 / 地形时，优先只改这里；
- main.py / mapedit.py / core.py 不再维护自己的资源表；
- 若新对象仍使用已有绘图风格，则无需修改其他文件。
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

# =============================================================================
# 基础常量
# =============================================================================

TERRAIN_VOID = 0
TERRAIN_FLOOR = 1
TERRAIN_STONE = 2
TERRAIN_SHOCK = 3
TERRAIN_SNOW = 4
TERRAIN_ICE = 5

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

# ActorState item: (x, y, actor_id, stun_turns)
ActorItem = Tuple[int, int, int, int]
ActorState = Tuple[ActorItem, ...]


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
    TERRAIN_SHOCK: TerrainDef(
        id=TERRAIN_SHOCK,
        name="电击区",
        walkable=True,
        accepts_actor=True,
        accepts_goal=True,
        base_color=(92, 72, 24),
        render_style="shock",
    ),
    TERRAIN_SNOW: TerrainDef(
        id=TERRAIN_SNOW,
        name="雪地",
        walkable=True,
        accepts_actor=True,
        accepts_goal=True,
        base_color=(210, 226, 240),
        render_style="snow",
    ),
    TERRAIN_ICE: TerrainDef(
        id=TERRAIN_ICE,
        name="冰面",
        walkable=True,
        accepts_actor=True,
        accepts_goal=True,
        base_color=(145, 206, 236),
        render_style="ice",
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


def terrain_is_shock(terrain_id: int) -> bool:
    return terrain_id == TERRAIN_SHOCK


def terrain_is_snow(terrain_id: int) -> bool:
    return terrain_id == TERRAIN_SNOW


def terrain_is_ice(terrain_id: int) -> bool:
    return terrain_id == TERRAIN_ICE


def terrain_enables_wrapping(terrain_id: int) -> bool:
    return terrain_id in (TERRAIN_SNOW, TERRAIN_ICE)


def can_place_actor_on_terrain_id(terrain_id: int) -> bool:
    return terrain_def(terrain_id).accepts_actor


def can_place_goal_on_terrain_id(terrain_id: int) -> bool:
    return terrain_def(terrain_id).accepts_goal


# =============================================================================
# 编辑器资源配置
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

def _coerce_state_item(item: Tuple[int, ...]) -> ActorItem:
    if len(item) == 4:
        x, y, actor_id, stun_turns = item
        return int(x), int(y), int(actor_id), max(0, int(stun_turns))
    if len(item) == 3:
        x, y, actor_id = item
        return int(x), int(y), int(actor_id), 0
    raise ValueError(f"非法状态项: {item!r}")


def _sort_actor_items(items: List[ActorItem]) -> None:
    items.sort(key=lambda item: (item[1], item[0], item[2], item[3]))


def actor_state_from_level(level) -> ActorState:
    result: List[ActorItem] = []
    actor_status = getattr(level, "actor_status", None)

    for y in range(level.height):
        for x in range(level.width):
            actor_id = level.actors[y][x]
            if actor_id == ACTOR_EMPTY:
                continue
            stun_turns = 0
            if actor_status is not None and 0 <= y < len(actor_status) and 0 <= x < len(actor_status[y]):
                stun_turns = max(0, int(actor_status[y][x]))
            result.append((x, y, actor_id, stun_turns))

    _sort_actor_items(result)
    return tuple(result)


def is_inside(level, x: int, y: int) -> bool:
    return 0 <= x < level.width and 0 <= y < level.height


def level_has_wrapping_edges(level) -> bool:
    """
    只要整张地图中存在“雪地”或“冰面”，就启用首尾相连的联通边界。
    由于关卡地形在求解过程中不会变化，这里做一个轻量缓存，避免 BFS 时重复扫描整张图。
    """
    cached = getattr(level, "_has_wrapping_edges_cache", None)
    if cached is not None:
        return bool(cached)

    has_wrap = any(terrain_enables_wrapping(tid) for row in level.terrain for tid in row)
    setattr(level, "_has_wrapping_edges_cache", has_wrap)
    return has_wrap


def _step_forward(level, x: int, y: int, dx: int, dy: int, wrap_enabled: bool) -> Optional[Tuple[int, int]]:
    """
    计算从 (x, y) 朝 (dx, dy) 迈出一步后的坐标。

    - 普通地图：走出边界会返回 None，表示该方向不可前进。
    - 联通边界地图：走出边界会从对侧重新出现。
    """
    nx = x + dx
    ny = y + dy

    if wrap_enabled:
        if level.width <= 0 or level.height <= 0:
            return None
        return nx % level.width, ny % level.height

    if not is_inside(level, nx, ny):
        return None
    return nx, ny


def is_walkable_terrain(level, x: int, y: int) -> bool:
    return is_inside(level, x, y) and terrain_is_walkable(level.terrain[y][x])


def is_shock_terrain(level, x: int, y: int) -> bool:
    return is_inside(level, x, y) and terrain_is_shock(level.terrain[y][x])


def is_ice_terrain(level, x: int, y: int) -> bool:
    return is_inside(level, x, y) and terrain_is_ice(level.terrain[y][x])


def can_place_actor(level, x: int, y: int) -> bool:
    return is_inside(level, x, y) and can_place_actor_on_terrain_id(level.terrain[y][x])


def can_place_goal(level, x: int, y: int) -> bool:
    return is_inside(level, x, y) and can_place_goal_on_terrain_id(level.terrain[y][x])


def level_from_actor_state(level, state: ActorState):
    new_level = level.clone()
    new_level.actors = [[ACTOR_EMPTY for _ in range(level.width)] for _ in range(level.height)]
    new_level.actor_status = [[0 for _ in range(level.width)] for _ in range(level.height)]

    for raw_item in state:
        x, y, actor_id, stun_turns = _coerce_state_item(raw_item)
        if is_inside(new_level, x, y):
            new_level.actors[y][x] = actor_id
            new_level.actor_status[y][x] = max(0, int(stun_turns))
    return new_level


# =============================================================================
# 胜利规则
# =============================================================================

def is_victory_state(level, state: ActorState) -> bool:
    actor_map = {(x, y): actor_id for x, y, actor_id, _ in (_coerce_state_item(item) for item in state)}

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

def _sorted_state_for_move(state: ActorState, move_name: str) -> List[ActorItem]:
    dx, dy = DIRS[move_name]
    items = [_coerce_state_item(item) for item in state]

    if dx > 0:
        items.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    elif dx < 0:
        items.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    elif dy > 0:
        items.sort(key=lambda item: (-item[1], item[0], item[2], item[3]))
    else:
        items.sort(key=lambda item: (item[1], item[0], item[2], item[3]))

    return items


def _sorted_entity_ids_for_move(
    entity_ids: Set[int],
    entities: Dict[int, Dict[str, int]],
    move_name: str,
) -> List[int]:
    dx, dy = DIRS[move_name]
    ids = list(entity_ids)

    if dx > 0:
        ids.sort(key=lambda eid: (-entities[eid]["x"], entities[eid]["y"], entities[eid]["actor_id"], eid))
    elif dx < 0:
        ids.sort(key=lambda eid: (entities[eid]["x"], entities[eid]["y"], entities[eid]["actor_id"], eid))
    elif dy > 0:
        ids.sort(key=lambda eid: (-entities[eid]["y"], entities[eid]["x"], entities[eid]["actor_id"], eid))
    else:
        ids.sort(key=lambda eid: (entities[eid]["y"], entities[eid]["x"], entities[eid]["actor_id"], eid))

    return ids


def _collect_push_chain(
    level,
    occupied: Dict[Tuple[int, int], int],
    entities: Dict[int, Dict[str, int]],
    start_x: int,
    start_y: int,
    dx: int,
    dy: int,
    wrap_enabled: bool,
) -> Optional[List[int]]:
    """
    从 front cell 开始收集一整条可被推动的链。

    返回：
    - None：无法推动。
    - List[int]：需要被整体向前推一格的 entity_id 链。

    在联通边界地图里，这里会额外做“环检测”：
    如果一整圈都被物体占满而找不到空位，就不能推动，避免无限循环。
    """
    chain: List[int] = []
    visited_positions: Set[Tuple[int, int]] = set()
    cx, cy = start_x, start_y

    while True:
        if (cx, cy) in visited_positions:
            return None
        visited_positions.add((cx, cy))

        eid = occupied.get((cx, cy))
        if eid is None:
            if not is_walkable_terrain(level, cx, cy):
                return None
            return chain

        actor_id = entities[eid]["actor_id"]
        if not actor_is_pushable(actor_id):
            return None
        chain.append(eid)

        next_pos = _step_forward(level, cx, cy, dx, dy, wrap_enabled)
        if next_pos is None:
            return None
        cx, cy = next_pos


def _move_entity_to(
    occupied: Dict[Tuple[int, int], int],
    entities: Dict[int, Dict[str, int]],
    entity_id: int,
    new_x: int,
    new_y: int,
) -> None:
    old_x = entities[entity_id]["x"]
    old_y = entities[entity_id]["y"]
    occupied.pop((old_x, old_y), None)
    entities[entity_id]["x"] = new_x
    entities[entity_id]["y"] = new_y
    occupied[(new_x, new_y)] = entity_id


def _attempt_single_step(
    level,
    occupied: Dict[Tuple[int, int], int],
    entities: Dict[int, Dict[str, int]],
    entity_id: int,
    dx: int,
    dy: int,
    wrap_enabled: bool,
) -> Optional[List[int]]:
    """
    让某个实体尝试向当前方向移动一小步（必要时带着整条可推动链一起动）。

    返回：
    - None：这一步完全走不动。
    - List[int]：本次真实发生位移的所有 entity_id（包含主动移动者和被推动者）。
    """
    x = entities[entity_id]["x"]
    y = entities[entity_id]["y"]

    next_pos = _step_forward(level, x, y, dx, dy, wrap_enabled)
    if next_pos is None:
        return None

    nx, ny = next_pos
    if not is_walkable_terrain(level, nx, ny):
        return None

    blocker_id = occupied.get((nx, ny))
    moved_ids: List[int] = []

    if blocker_id is not None:
        chain = _collect_push_chain(level, occupied, entities, nx, ny, dx, dy, wrap_enabled)
        if chain is None:
            return None

        for pushed_id in reversed(chain):
            px = entities[pushed_id]["x"]
            py = entities[pushed_id]["y"]
            pushed_next = _step_forward(level, px, py, dx, dy, wrap_enabled)
            if pushed_next is None:
                return None
            pnx, pny = pushed_next
            _move_entity_to(occupied, entities, pushed_id, pnx, pny)
            moved_ids.append(pushed_id)

    _move_entity_to(occupied, entities, entity_id, nx, ny)
    moved_ids.append(entity_id)
    return moved_ids


def move_actor_state(level, state: ActorState, move_name: str) -> ActorState:
    """
    单次输入的完整状态转移。

    本函数同时处理：
    1. 正常移动 / 推动；
    2. 电击区导致的“下一回合跳过”；
    3. 雪地/冰面触发的全图联通边界；
    4. 冰面上的持续滑行。

    关键实现思路：
    - 先把状态转换成带 entity_id 的内部结构，方便跟踪“同一个物体”在同一回合内多次滑行；
    - 初始 active 集合只放“会响应输入”的角色；
    - 如果某个实体在本回合落到了冰面，就把它加入下一轮 active，继续沿原方向滑；
    - 被推动的小球如果被推到冰面，也会继续滑；
    - 如果某个实体在冰面环上反复回到同一冰格，则停止继续滑，避免无限循环。
    """
    if move_name not in DIRS:
        return tuple(_coerce_state_item(item) for item in state)

    dx, dy = DIRS[move_name]
    wrap_enabled = level_has_wrapping_edges(level)

    # entity_id -> {x, y, actor_id, stun_turns}
    entities: Dict[int, Dict[str, int]] = {}
    occupied: Dict[Tuple[int, int], int] = {}
    for entity_id, raw_item in enumerate(_coerce_state_item(item) for item in state):
        x, y, actor_id, stun_turns = raw_item
        entities[entity_id] = {
            "x": x,
            "y": y,
            "actor_id": actor_id,
            "stun_turns": stun_turns,
        }
        occupied[(x, y)] = entity_id

    # 第一轮只有“会响应输入”的角色会尝试行动。
    active_ids: Set[int] = {
        entity_id
        for entity_id, info in entities.items()
        if actor_responds_to_input(info["actor_id"])
    }

    # 记录本回合哪些实体进入过电击区；回合结算时给它们挂 1 层麻痹。
    entered_shock_ids: Set[int] = set()

    # 记录每个实体在本回合滑冰时已经到过哪些冰格，用来防止环形冰道无限滑动。
    ice_visited: Dict[int, Set[Tuple[int, int]]] = {entity_id: set() for entity_id in entities}

    while active_ids:
        next_active_ids: Set[int] = set()

        for entity_id in _sorted_entity_ids_for_move(active_ids, entities, move_name):
            info = entities.get(entity_id)
            if info is None:
                continue

            current_stun_turns = info["stun_turns"]
            if current_stun_turns > 0:
                # 电击效果：下一次输入直接跳过行动，然后层数减 1。
                info["stun_turns"] = current_stun_turns - 1
                continue

            moved_ids = _attempt_single_step(
                level=level,
                occupied=occupied,
                entities=entities,
                entity_id=entity_id,
                dx=dx,
                dy=dy,
                wrap_enabled=wrap_enabled,
            )
            if not moved_ids:
                continue

            for moved_id in moved_ids:
                mx = entities[moved_id]["x"]
                my = entities[moved_id]["y"]

                if is_shock_terrain(level, mx, my):
                    entered_shock_ids.add(moved_id)

                if is_ice_terrain(level, mx, my):
                    # 本回合落在冰面上的实体，下一个微步会继续沿同方向滑动。
                    # 若回到已经到过的冰格，说明出现了环，不再继续滑。
                    if (mx, my) not in ice_visited[moved_id]:
                        ice_visited[moved_id].add((mx, my))
                        next_active_ids.add(moved_id)

        active_ids = next_active_ids

    for entity_id in entered_shock_ids:
        entities[entity_id]["stun_turns"] = max(entities[entity_id]["stun_turns"], 1)

    result: List[ActorItem] = []
    for info in entities.values():
        result.append((
            info["x"],
            info["y"],
            info["actor_id"],
            max(0, info["stun_turns"]),
        ))

    _sort_actor_items(result)
    return tuple(result)


def move_level(level, move_name: str):
    return level_from_actor_state(level, move_actor_state(level, actor_state_from_level(level), move_name))


def is_victory(level) -> bool:
    return is_victory_state(level, actor_state_from_level(level))
