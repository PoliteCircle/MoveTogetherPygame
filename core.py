"""
core.py
=======
本文件负责“核心规则层 + 基础绘制层”。

设计目标：
1. 将“地图数据结构”和“游戏规则”集中放在一个文件里，方便以后扩展。
2. 将“绘制地形 / 角色 / 目标”的入口统一到一起，方便以后替换美术资源。
3. 将“移动计算”“胜利判定”“关卡读写”封装成函数，方便 main.py / solve.py / mapedit.py 共用。
4. 注释尽量详细，便于后续继续扩展新的角色、地形、目标类型。

当前第一版规则（按用户需求实现）：
- 地形：
    0 = 虚空（不能站立，也不属于有效地图）
    1 = 平地（可通行）
    2 = 石头（阻挡）
- 角色：
    0 = 空
    1 = 土人
- 目标：
    0 = 空
    1 = 土人目标

- 土人移动规则：
    * 每次按方向键后，所有土人都会尝试同时向该方向移动“一格”。
    * 若某一条移动线（横向/纵向）上，沿移动方向有一串连续土人，则这一整串要么一起移动，要么都不移动。
      例如向右移动时：
         [土][土][空] -> 两个都右移
         [土][土][石] -> 两个都不能动
    * 可移动的条件本质上只取决于“这整串最前端（运动方向上的最前端）”前方那一格是否可进入。
    * 可进入要求：
         - 不能越界
         - 不能进入虚空
         - 不能进入石头
         - 不能进入同一时刻未随其一起移动的其他角色占据的位置
      对于同一串中的前后土人，因为是一起移动，所以内部不会互相阻挡。

- 胜利条件：
    * 当前版本按用户最新描述，默认实现为：任意一个土人到达任意一个土人目标位置，即可通关。
    * 为了方便以后改规则，本文件保留了 victory_mode：
         "any"  -> 任意一个角色踩到任意一个目标即胜利（默认）
         "all_actors_on_goals" -> 所有角色必须都站在目标上

文件中最重要的几个入口：
- load_level / save_level：读写 JSON 关卡文件
- move_state：根据方向计算下一帧逻辑状态
- is_victory：判断是否达成过关条件
- draw_level：统一绘制地图、目标、角色
- solve_level_bfs：用 BFS 求最短解
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pygame

# =============================================================================
# 常量定义区
# =============================================================================
# 将各种编号集中写在这里，后续扩展时只改这一块即可。

# 地形编号
TERRAIN_VOID = 0       # 虚空：无效区域，不可进入
TERRAIN_FLOOR = 1      # 平地：可进入
TERRAIN_STONE = 2      # 石头：阻挡

# 角色编号
ACTOR_EMPTY = 0
ACTOR_SOIL = 1         # 土人

# 目标编号
GOAL_EMPTY = 0
GOAL_SOIL = 1          # 土人目标

# 方向定义
DIRS: Dict[str, Tuple[int, int]] = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}

# 为了让求解结果和按键更直观，这里约定方向字符。
MOVE_TO_CHAR = {
    "up": "↑",
    "down": "↓",
    "left": "←",
    "right": "→",
}
CHAR_TO_MOVE = {v: k for k, v in MOVE_TO_CHAR.items()}

# 默认尺寸与颜色。这里不使用外部图片，直接用 pygame 图元绘制，便于你后续替换。
CELL_SIZE = 56
EDITOR_PANEL_WIDTH = 260
GRID_LINE_COLOR = (40, 40, 40)
BG_COLOR = (24, 24, 28)
TEXT_COLOR = (235, 235, 235)
SUB_TEXT_COLOR = (180, 180, 180)
PANEL_COLOR = (34, 35, 40)
BUTTON_COLOR = (70, 72, 82)
BUTTON_HOVER_COLOR = (95, 98, 112)
SELECT_COLOR = (240, 212, 92)

# 地形颜色
COLOR_VOID = (18, 18, 22)
COLOR_FLOOR = (170, 139, 90)
COLOR_STONE = (110, 110, 116)

# 角色颜色
COLOR_SOIL = (140, 90, 48)

# 目标颜色
COLOR_GOAL_SOIL = (90, 220, 120)

DEFAULT_VICTORY_MODE = "all_actors_on_goals"


# =============================================================================
# 数据结构定义区
# =============================================================================

Position = Tuple[int, int]
ActorState = Tuple[Position, ...]  # 用排序后的坐标元组表示一个状态，便于哈希 / BFS


@dataclass
class LevelData:
    """
    关卡数据对象。

    之所以定义成 dataclass，而不是直接到处传 dict，是为了：
    1. 类型更清晰；
    2. 以后扩展字段时更安全；
    3. IDE 补全更方便。

    字段说明：
    - name: 关卡名字，显示用
    - width / height: 地图宽高
    - terrain: 地形二维数组，terrain[y][x]
    - actors: 角色二维数组，actors[y][x]
    - goals: 目标二维数组，goals[y][x]
    - victory_mode: 胜利模式，默认 all_actors_on_goals
    """

    name: str
    width: int
    height: int
    terrain: List[List[int]]
    actors: List[List[int]]
    goals: List[List[int]]
    victory_mode: str = DEFAULT_VICTORY_MODE

    def clone(self) -> "LevelData":
        """深拷贝一个关卡，避免修改原对象。"""
        return LevelData(
            name=self.name,
            width=self.width,
            height=self.height,
            terrain=[row[:] for row in self.terrain],
            actors=[row[:] for row in self.actors],
            goals=[row[:] for row in self.goals],
            victory_mode=self.victory_mode,
        )


# =============================================================================
# JSON 读写与校验
# =============================================================================

def create_empty_level(width: int, height: int, name: str = "新关卡") -> LevelData:
    """
    创建一个空白关卡。

    默认将所有格子初始化为“平地”，这样编辑器中比较好操作。
    若你更喜欢默认都是虚空，可把 terrain 初始化改成 TERRAIN_VOID。
    """
    terrain = [[TERRAIN_FLOOR for _ in range(width)] for _ in range(height)]
    actors = [[ACTOR_EMPTY for _ in range(width)] for _ in range(height)]
    goals = [[GOAL_EMPTY for _ in range(width)] for _ in range(height)]
    return LevelData(name=name, width=width, height=height, terrain=terrain, actors=actors, goals=goals)



def level_to_dict(level: LevelData) -> dict:
    """将 LevelData 转成可写入 JSON 的普通字典。"""
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
    """
    对从 JSON 读出来的原始字典做基础合法性检查。

    这里尽量把错误在加载时就报出来，而不是等游戏运行时才崩。
    """
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
    """
    从 JSON 文件加载关卡。

    注意：
    - 路径可以是字符串，也可以是 Path
    - 默认使用 UTF-8 编码
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
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
    """将关卡保存到 JSON 文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(level_to_dict(level), f, ensure_ascii=False, indent=2)


# =============================================================================
# 状态提取与回填
# =============================================================================

def get_actor_positions(level: LevelData, actor_type: int = ACTOR_SOIL) -> List[Position]:
    """从角色位图中提取某种角色的所有坐标。"""
    pos: List[Position] = []
    for y in range(level.height):
        for x in range(level.width):
            if level.actors[y][x] == actor_type:
                pos.append((x, y))
    return pos



def get_goal_positions(level: LevelData, goal_type: int = GOAL_SOIL) -> Set[Position]:
    """从目标位图中提取目标坐标集合。"""
    pos: Set[Position] = set()
    for y in range(level.height):
        for x in range(level.width):
            if level.goals[y][x] == goal_type:
                pos.add((x, y))
    return pos



def actors_layer_from_positions(width: int, height: int, positions: Iterable[Position], actor_type: int = ACTOR_SOIL) -> List[List[int]]:
    """由坐标列表重新生成角色二维数组。"""
    layer = [[ACTOR_EMPTY for _ in range(width)] for _ in range(height)]
    for x, y in positions:
        layer[y][x] = actor_type
    return layer



def actor_state_from_level(level: LevelData) -> ActorState:
    """
    将当前关卡中的所有土人位置转成一个可哈希的规范状态。

    规范化做法：排序后转 tuple。
    这样 BFS 中就可以把状态放进 set / dict 里。
    """
    return tuple(sorted(get_actor_positions(level, ACTOR_SOIL)))



def level_from_actor_state(base_level: LevelData, actor_state: ActorState) -> LevelData:
    """基于一个“静态关卡 + 动态角色坐标状态”重建完整关卡对象。"""
    new_level = base_level.clone()
    new_level.actors = actors_layer_from_positions(base_level.width, base_level.height, actor_state, ACTOR_SOIL)
    return new_level


# =============================================================================
# 地图与移动规则
# =============================================================================

def in_bounds(level: LevelData, x: int, y: int) -> bool:
    """是否在数组边界内。注意：边界内不代表可站立，因为虚空也不可站立。"""
    return 0 <= x < level.width and 0 <= y < level.height



def is_walkable_terrain(level: LevelData, x: int, y: int) -> bool:
    """
    判断一个格子的地形是否“允许进入”。

    第一版中：
    - 平地可进入
    - 石头不可进入
    - 虚空不可进入
    """
    if not in_bounds(level, x, y):
        return False
    return level.terrain[y][x] == TERRAIN_FLOOR



def build_occupied_set(actor_state: ActorState) -> Set[Position]:
    """将角色状态转成 set，便于快速判断占位。"""
    return set(actor_state)



def extract_movable_groups(actor_state: ActorState, move_name: str) -> List[List[Position]]:
    """
    按当前移动方向，将所有土人切分为“连续移动组”。

    为什么要做这个步骤？
    因为题目要求：一条线上连续的多个土人是“整体移动”的。
    例如向右时，同一行中如果出现连续土人块：[(2,1), (3,1), (4,1)]，
    就应该把它当成一个 group，而不是三个独立单位。

    分组规则：
    - 向左/向右：按“行”分组，每行内按 x 排序，把连续 x 的土人合并成一组。
    - 向上/向下：按“列”分组，每列内按 y 排序，把连续 y 的土人合并成一组。

    返回值：group 列表，每个 group 是若干坐标组成的列表。
    group 内的顺序不是任意的，而是按“该方向下从后到前”排序，便于取前端。
    """
    positions = list(actor_state)
    groups: List[List[Position]] = []

    if move_name in ("left", "right"):
        row_map: Dict[int, List[Position]] = {}
        for x, y in positions:
            row_map.setdefault(y, []).append((x, y))

        for y, row_positions in row_map.items():
            row_positions.sort(key=lambda p: p[0])  # 按 x 排序
            current_group = [row_positions[0]]
            for pos in row_positions[1:]:
                if pos[0] == current_group[-1][0] + 1:
                    current_group.append(pos)
                else:
                    groups.append(current_group)
                    current_group = [pos]
            groups.append(current_group)

        # 为了让“最前端”容易取得：
        # right -> x 大的是前端；left -> x 小的是前端
        for g in groups:
            g.sort(key=lambda p: p[0], reverse=(move_name == "right"))

    else:
        col_map: Dict[int, List[Position]] = {}
        for x, y in positions:
            col_map.setdefault(x, []).append((x, y))

        for x, col_positions in col_map.items():
            col_positions.sort(key=lambda p: p[1])  # 按 y 排序
            current_group = [col_positions[0]]
            for pos in col_positions[1:]:
                if pos[1] == current_group[-1][1] + 1:
                    current_group.append(pos)
                else:
                    groups.append(current_group)
                    current_group = [pos]
            groups.append(current_group)

        # down -> y 大的是前端；up -> y 小的是前端
        for g in groups:
            g.sort(key=lambda p: p[1], reverse=(move_name == "down"))

    return groups



def can_group_move(level: LevelData, actor_state: ActorState, group: List[Position], move_name: str) -> bool:
    """
    判断一整组连续土人是否能够移动。

    关键思想：
    - 一组连续土人整体移动时，只需检查“前端那一个”前面的格子是否可进入。
    - 因为组内其他土人移动后会自动接上前面那个人原来的位置，所以不会额外产生碰撞。

    但还要注意一个细节：
    - 目标格如果被“本组之外”的其他土人占着，则不能移动。
    - 如果目标格本来由本组成员占着，那没关系，因为本组会一起动，位置会整体平移。
      不过由于前端外面一格不可能还是本组成员，所以这个情况一般不会发生。
    """
    dx, dy = DIRS[move_name]
    occupied = build_occupied_set(actor_state)
    group_set = set(group)

    front_x, front_y = group[0]
    nx, ny = front_x + dx, front_y + dy

    # 先判断地形是否允许进入
    if not is_walkable_terrain(level, nx, ny):
        return False

    # 再判断是否被其他“非本组”的土人占着
    if (nx, ny) in occupied and (nx, ny) not in group_set:
        return False

    return True



def move_group(group: List[Position], move_name: str) -> List[Position]:
    """返回某个 group 移动后的新坐标列表。"""
    dx, dy = DIRS[move_name]
    return [(x + dx, y + dy) for x, y in group]



def move_actor_state(level: LevelData, actor_state: ActorState, move_name: str) -> ActorState:
    """
    计算给定状态在某个方向移动一次后的新状态。

    这里最重要的是“同时移动”的含义：
    - 所有 group 的能否移动，都是基于“移动前的状态”来判断；
    - 一旦可移动，则这些 group 一起移动；
    - 不可移动的 group 保持原位。

    这能避免出现“先移动一个，再影响另一个”的顺序偏差。
    """
    groups = extract_movable_groups(actor_state, move_name)
    movable_flags = [can_group_move(level, actor_state, g, move_name) for g in groups]

    new_positions: List[Position] = []
    for group, can_move in zip(groups, movable_flags):
        if can_move:
            new_positions.extend(move_group(group, move_name))
        else:
            new_positions.extend(group)

    return tuple(sorted(new_positions))



def move_level(level: LevelData, move_name: str) -> LevelData:
    """对一个完整关卡执行一次移动，返回移动后的新关卡。"""
    state = actor_state_from_level(level)
    new_state = move_actor_state(level, state, move_name)
    return level_from_actor_state(level, new_state)


# =============================================================================
# 胜利判定
# =============================================================================

def is_victory_state(base_level: LevelData, actor_state: ActorState) -> bool:
    """
    判断角色状态是否满足过关条件。

    当前默认模式：
    - any：任意一个土人踩到任意一个目标即可

    预留模式：
    - all_actors_on_goals：所有土人都必须站在目标上
    """
    goals = get_goal_positions(base_level, GOAL_SOIL)
    actor_positions = set(actor_state)

    if not goals or not actor_positions:
        return False

    mode = base_level.victory_mode
    if mode == "any":
        return any(pos in goals for pos in actor_positions)
    elif mode == "all_actors_on_goals":
        return actor_positions.issubset(goals)
    else:
        # 防御性兜底：未知模式时回退到默认行为
        return any(pos in goals for pos in actor_positions)



def is_victory(level: LevelData) -> bool:
    """对完整关卡对象做胜利判定。"""
    return is_victory_state(level, actor_state_from_level(level))


# =============================================================================
# BFS 最短路求解
# =============================================================================

def solve_level_bfs(level: LevelData, max_states: int = 200000) -> Optional[List[str]]:
    """
    使用 BFS 求解当前关卡，返回最短方向列表。

    为什么 BFS 可以给出最短步数？
    - 因为每次移动代价都相同，都是 1 步；
    - BFS 会按层扩展状态空间；
    - 第一次到达胜利状态时，路径就是最短路径。

    参数：
    - max_states: 状态数上限，防止极端地图导致搜索爆炸。
      若超过该值，会提前停止并返回 None。

    返回：
    - None：无解或超过上限
    - List[str]：例如 ["right", "down", "left"]
    """
    from collections import deque

    start = actor_state_from_level(level)
    if is_victory_state(level, start):
        return []

    queue = deque([start])
    visited: Set[ActorState] = {start}
    parent: Dict[ActorState, Tuple[Optional[ActorState], Optional[str]]] = {
        start: (None, None)
    }

    expanded = 0

    while queue:
        state = queue.popleft()
        expanded += 1
        if expanded > max_states:
            return None

        for move_name in ("up", "down", "left", "right"):
            new_state = move_actor_state(level, state, move_name)
            if new_state == state:
                # 不发生变化的动作可以跳过，减少搜索分支。
                continue
            if new_state in visited:
                continue

            visited.add(new_state)
            parent[new_state] = (state, move_name)

            if is_victory_state(level, new_state):
                # 逆向回溯出最短路径
                path: List[str] = []
                cur = new_state
                while True:
                    prev, move = parent[cur]
                    if prev is None:
                        break
                    path.append(move)  # 当前状态由 prev 经过 move 到达
                    cur = prev
                path.reverse()
                return path

            queue.append(new_state)

    return None


# =============================================================================
# 绘制相关
# =============================================================================

def _get_font(size: int) -> pygame.font.Font:
    """统一字体入口。SysFont 在大多数平台上足够稳定。"""
    return pygame.font.SysFont("microsoftyahei,simhei,arial", size)



def draw_text(surface: pygame.Surface, text: str, x: int, y: int, size: int = 24, color=TEXT_COLOR) -> None:
    """在指定位置绘制左上角对齐文字。"""
    font = _get_font(size)
    img = font.render(text, True, color)
    surface.blit(img, (x, y))



def draw_text_center(surface: pygame.Surface, text: str, center: Tuple[int, int], size: int = 24, color=TEXT_COLOR) -> None:
    """绘制中心对齐文字。"""
    font = _get_font(size)
    img = font.render(text, True, color)
    rect = img.get_rect(center=center)
    surface.blit(img, rect)



def terrain_color(terrain_id: int) -> Tuple[int, int, int]:
    """根据地形编号返回基础填充颜色。"""
    if terrain_id == TERRAIN_FLOOR:
        return COLOR_FLOOR
    if terrain_id == TERRAIN_STONE:
        return COLOR_STONE
    return COLOR_VOID

def goal_color(goal_id: int) -> Tuple[int, int, int]:
    if goal_id == GOAL_SOIL:
        return COLOR_SOIL
    return None


def draw_terrain(surface: pygame.Surface, rect: pygame.Rect, terrain_id: int) -> None:
    """
    绘制地形。

    目前使用简单图元：
    - 虚空：深色底
    - 平地：棕色块
    - 石头：灰色块 + 小纹理

    将来你若要替换成图片，只需在这里按 terrain_id 分发贴图即可。
    """
    pygame.draw.rect(surface, terrain_color(terrain_id), rect)

    if terrain_id == TERRAIN_STONE:
        # 画几条简化纹理线，增强辨识度
        margin = 8
        pygame.draw.rect(surface, (90, 90, 96), rect.inflate(-8, -8), border_radius=6)
        pygame.draw.line(surface, (140, 140, 148), (rect.left + margin, rect.centery), (rect.right - margin, rect.centery), 2)
        pygame.draw.line(surface, (140, 140, 148), (rect.centerx, rect.top + margin), (rect.centerx, rect.bottom - margin), 2)
    elif terrain_id == TERRAIN_FLOOR:
        # 平地简单做一点边缘明暗
        pygame.draw.rect(surface, (196, 163, 108), rect, 2)
    else:
        # 虚空加深边界
        pygame.draw.rect(surface, (30, 30, 35), rect, 1)



def draw_goal(surface: pygame.Surface, rect: pygame.Rect, goal_id: int) -> None:
    color = goal_color(goal_id)
    if color == None:
        return

    # 画一个“内缩的正方形边框”作为目标标记。
    # 这样当角色站到目标格上时，边框四周仍然能露出来，比画在中心的小圆更容易看清。
    margin = max(1, min(rect.width, rect.height) // 12)
    border_width = max(2, min(rect.width, rect.height) // 12)

    inner_rect = pygame.Rect(
        rect.x + margin,
        rect.y + margin,
        rect.width - 2 * margin,
        rect.height - 2 * margin,
    )

    pygame.draw.rect(surface, color, inner_rect, border_width)


def draw_actor(surface: pygame.Surface, rect: pygame.Rect, actor_id: int, bob_phase: float = 0.0) -> None:
    """
    绘制角色层。

    这里做了一个很轻量的“上下浮动”动画（bob），
    这样角色看起来不会完全静止。

    参数：
    - bob_phase: 一个随时间变化的相位，用于计算轻微浮动效果。
    """
    if actor_id != ACTOR_SOIL:
        return

    # 浮动偏移：幅度很小，避免影响格子判定，只是视觉效果。
    offset_y = int(math.sin(bob_phase) * 2)

    body = rect.inflate(-14, -12)
    body.move_ip(0, offset_y)

    # 身体
    pygame.draw.ellipse(surface, COLOR_SOIL, body)
    pygame.draw.ellipse(surface, (92, 58, 28), body, 2)

    # 眼睛
    eye_y = body.centery - 6
    pygame.draw.circle(surface, (245, 245, 245), (body.centerx - 8, eye_y), 3)
    pygame.draw.circle(surface, (245, 245, 245), (body.centerx + 8, eye_y), 3)
    pygame.draw.circle(surface, (20, 20, 20), (body.centerx - 8, eye_y), 1)
    pygame.draw.circle(surface, (20, 20, 20), (body.centerx + 8, eye_y), 1)

    # 脚
    foot_y = body.bottom - 2
    pygame.draw.line(surface, (85, 52, 25), (body.centerx - 8, foot_y - 4), (body.centerx - 8, foot_y + 4), 2)
    pygame.draw.line(surface, (85, 52, 25), (body.centerx + 8, foot_y - 4), (body.centerx + 8, foot_y + 4), 2)



def draw_cell_overlay(surface: pygame.Surface, rect: pygame.Rect, is_selected: bool = False, selection_color=SELECT_COLOR) -> None:
    """绘制格子选中框，主要给地图编辑器用。"""
    if is_selected:
        pygame.draw.rect(surface, selection_color, rect, 3)



def draw_level(
    surface: pygame.Surface,
    level: LevelData,
    offset_x: int = 0,
    offset_y: int = 0,
    cell_size: int = CELL_SIZE,
) -> None:
    """
    统一绘制整个关卡。

    这个函数是 core.py 的关键接口之一。
    main.py 和 mapedit.py 都可以直接调用它来画地图。
    """
    # 1) 先画地形与目标
    for y in range(level.height):
        for x in range(level.width):
            rect = pygame.Rect(offset_x + x * cell_size, offset_y + y * cell_size, cell_size, cell_size)
            draw_terrain(surface, rect, level.terrain[y][x])
            draw_goal(surface, rect, level.goals[y][x])
            pygame.draw.rect(surface, GRID_LINE_COLOR, rect, 1)

    # 2) 再画角色
    actor_positions = get_actor_positions(level, ACTOR_SOIL)

    for pos in actor_positions:
        x, y = pos
        px = offset_x + x * cell_size
        py = offset_y + y * cell_size

        rect = pygame.Rect(int(px), int(py), cell_size, cell_size)
        draw_actor(surface, rect, ACTOR_SOIL, bob_phase=x * 0.7 + y * 0.5)


# =============================================================================
# 动画辅助
# =============================================================================

def build_position_mapping_for_animation(old_state: ActorState, new_state: ActorState, move_name: str) -> Dict[Position, Position]:
    """
    生成动画映射：new_pos -> old_pos。

    由于第一版规则中，每个土人要么原地不动，要么沿某方向移动 1 格，
    因此我们可以根据 move_name 反推：
      new_pos 的旧位置就是 new_pos - dir
    若该旧位置在 old_state 中，则说明该角色发生了移动；
    否则 old_pos = new_pos，表示这个角色没动。

    这样做不需要给每个土人单独 ID，也能做出基本平滑动画。
    """
    dx, dy = DIRS[move_name]
    old_set = set(old_state)
    mapping: Dict[Position, Position] = {}
    for nx, ny in new_state:
        candidate = (nx - dx, ny - dy)
        if candidate in old_set:
            mapping[(nx, ny)] = candidate
        else:
            mapping[(nx, ny)] = (nx, ny)
    return mapping


# =============================================================================
# UI 小组件：按钮（供 mapedit.py 复用）
# =============================================================================

@dataclass
class Button:
    """一个非常轻量的按钮类，便于地图编辑器快速复用。"""
    rect: pygame.Rect
    text: str

    def draw(self, surface: pygame.Surface, mouse_pos: Tuple[int, int]) -> None:
        hovered = self.rect.collidepoint(mouse_pos)
        color = BUTTON_HOVER_COLOR if hovered else BUTTON_COLOR
        pygame.draw.rect(surface, color, self.rect, border_radius=8)
        pygame.draw.rect(surface, (140, 140, 150), self.rect, 2, border_radius=8)
        draw_text_center(surface, self.text, self.rect.center, 20)

    def is_clicked(self, event: pygame.event.Event) -> bool:
        return event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos)

