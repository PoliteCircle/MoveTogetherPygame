from __future__ import annotations

"""
game_render.py
==============
所有绘图逻辑统一放这里。

设计目标：
- 以后要改角色外观 / 目标形状 / 地形画法，只改这一个文件；
- 若 game_rules.py 中新增对象仍使用已有 render_style / render_shape，
  则这里不用改。
"""

import math
from dataclasses import dataclass
from typing import Tuple

import pygame

from game_rules import ACTOR_EMPTY, GOAL_EMPTY, TERRAIN_SHOCK, actor_def, goal_def, terrain_def

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
class Button:
    rect: pygame.Rect
    text: str

    def draw(self, surface: pygame.Surface, hovered: bool = False) -> None:
        color = BUTTON_HOVER_COLOR if hovered else BUTTON_COLOR
        pygame.draw.rect(surface, color, self.rect, border_radius=8)
        pygame.draw.rect(surface, (120, 124, 136), self.rect, 2, border_radius=8)
        draw_text_center(surface, self.text, self.rect.center, 22)


def _get_font(size: int) -> pygame.font.Font:
    return pygame.font.SysFont("microsoftyahei, simhei, arial", size)


def draw_text(surface: pygame.Surface, text: str, x: int, y: int, size: int = 24, color=TEXT_COLOR) -> None:
    font = _get_font(size)
    img = font.render(text, True, color)
    surface.blit(img, (x, y))


def draw_text_center(surface: pygame.Surface, text: str, center: Tuple[int, int], size: int = 24, color=TEXT_COLOR) -> None:
    font = _get_font(size)
    img = font.render(text, True, color)
    rect = img.get_rect(center=center)
    surface.blit(img, rect)


def draw_cell_overlay(surface: pygame.Surface, x: int, y: int, size: int) -> None:
    rect = pygame.Rect(x, y, size, size)
    pygame.draw.rect(surface, SELECT_COLOR, rect, 3)


# =============================================================================
# 地形绘制
# =============================================================================

def _draw_shock_terrain(surface: pygame.Surface, rect: pygame.Rect) -> None:
    pygame.draw.rect(surface, (88, 68, 24), rect)
    pygame.draw.rect(surface, (230, 198, 76), rect, 2)

    inner = rect.inflate(-8, -8)
    if inner.width <= 0 or inner.height <= 0:
        return

    pygame.draw.rect(surface, (122, 92, 32), inner, border_radius=6)
    points = [
        (inner.left + inner.width * 0.58, inner.top + inner.height * 0.05),
        (inner.left + inner.width * 0.34, inner.top + inner.height * 0.42),
        (inner.left + inner.width * 0.54, inner.top + inner.height * 0.42),
        (inner.left + inner.width * 0.28, inner.bottom - inner.height * 0.05),
        (inner.left + inner.width * 0.68, inner.top + inner.height * 0.54),
        (inner.left + inner.width * 0.46, inner.top + inner.height * 0.54),
    ]
    pygame.draw.polygon(surface, (255, 226, 92), [(int(x), int(y)) for x, y in points])




def _draw_snow_terrain(surface: pygame.Surface, rect: pygame.Rect) -> None:
    pygame.draw.rect(surface, (210, 226, 240), rect)
    pygame.draw.rect(surface, (248, 252, 255), rect, 2)

    # 使用很轻的雪纹来提示：该地形会启用“联通边界”。
    inner = rect.inflate(-8, -8)
    if inner.width <= 0 or inner.height <= 0:
        return

    pygame.draw.line(surface, (245, 250, 255), (inner.left, inner.centery), (inner.right, inner.centery), 2)
    pygame.draw.line(surface, (245, 250, 255), (inner.centerx, inner.top), (inner.centerx, inner.bottom), 2)
    pygame.draw.line(surface, (232, 242, 252), (inner.left + 4, inner.top + 4), (inner.right - 4, inner.bottom - 4), 2)
    pygame.draw.line(surface, (232, 242, 252), (inner.right - 4, inner.top + 4), (inner.left + 4, inner.bottom - 4), 2)


def _draw_ice_terrain(surface: pygame.Surface, rect: pygame.Rect) -> None:
    pygame.draw.rect(surface, (145, 206, 236), rect)
    pygame.draw.rect(surface, (224, 248, 255), rect, 2)

    inner = rect.inflate(-8, -8)
    if inner.width <= 0 or inner.height <= 0:
        return

    pygame.draw.rect(surface, (176, 226, 247), inner, border_radius=6)
    pygame.draw.line(surface, (235, 250, 255), (inner.left + 6, inner.top + 8), (inner.right - 6, inner.top + 8), 2)
    pygame.draw.line(surface, (235, 250, 255), (inner.left + 10, inner.centery), (inner.right - 8, inner.centery - 4), 2)
    pygame.draw.line(surface, (235, 250, 255), (inner.left + 8, inner.bottom - 10), (inner.right - 10, inner.bottom - 14), 2)

def draw_terrain(
    surface: pygame.Surface,
    rect: pygame.Rect,
    terrain_id: int,
    shock_used: bool = False,
    used_shock_as_snow: bool = False,
) -> None:
    if terrain_id == 3 and shock_used:
        if used_shock_as_snow:
            _draw_snow_terrain(surface, rect)
        else:
            draw_terrain(surface, rect, 1, shock_used=False, used_shock_as_snow=False)
        return

    info = terrain_def(terrain_id)
    pygame.draw.rect(surface, info.base_color, rect)

    if info.render_style == "void":
        pygame.draw.rect(surface, (30, 30, 35), rect, 1)

    elif info.render_style == "floor":
        pygame.draw.rect(surface, (196, 163, 108), rect, 2)

    elif info.render_style == "stone":
        margin = 8
        pygame.draw.rect(surface, (90, 90, 96), rect.inflate(-8, -8), border_radius=6)
        pygame.draw.line(
            surface,
            (140, 140, 148),
            (rect.left + margin, rect.centery),
            (rect.right - margin, rect.centery),
            2,
        )
        pygame.draw.line(
            surface,
            (140, 140, 148),
            (rect.centerx, rect.top + margin),
            (rect.centerx, rect.bottom - margin),
            2,
        )

    elif info.render_style == "shock":
        _draw_shock_terrain(surface, rect)

    elif info.render_style == "snow":
        _draw_snow_terrain(surface, rect)

    elif info.render_style == "ice":
        _draw_ice_terrain(surface, rect)

    else:
        pygame.draw.rect(surface, info.base_color, rect)
        pygame.draw.rect(surface, (60, 60, 70), rect, 1)


# =============================================================================
# 目标绘制
# =============================================================================

def draw_goal(surface: pygame.Surface, rect: pygame.Rect, goal_id: int) -> None:
    if goal_id == GOAL_EMPTY:
        return

    info = goal_def(goal_id)
    if info is None:
        return

    margin = max(2, min(rect.width, rect.height) // 10)
    border_width = max(2, min(rect.width, rect.height) // 10)
    inner = pygame.Rect(
        rect.x + margin,
        rect.y + margin,
        rect.width - 2 * margin,
        rect.height - 2 * margin,
    )

    if info.render_shape == "circle":
        pygame.draw.ellipse(surface, info.color, inner, border_width)

    elif info.render_shape == "diamond":
        points = [
            (inner.centerx, inner.top),
            (inner.right, inner.centery),
            (inner.centerx, inner.bottom),
            (inner.left, inner.centery),
        ]
        pygame.draw.polygon(surface, info.color, points, border_width)

    else:
        pygame.draw.rect(surface, info.color, inner, border_width)


# =============================================================================
# 角色绘制
# =============================================================================

def _draw_character_actor(
    surface: pygame.Surface,
    rect: pygame.Rect,
    color: Tuple[int, int, int],
    scale: float,
    bob_phase: float = 0.0,
) -> None:
    cx, cy = rect.center
    size = max(10, int(min(rect.width, rect.height) * scale))
    body = pygame.Rect(0, 0, size, size)
    body.center = (cx, cy + int(math.sin(bob_phase) * 2))

    pygame.draw.ellipse(surface, color, body)
    outline = tuple(max(0, c - 55) for c in color)
    pygame.draw.ellipse(surface, outline, body, 2)

    eye_y = body.y + body.height * 0.40
    eye_dx = body.width * 0.18
    eye_r = max(2, body.width // 10)

    pygame.draw.circle(surface, (22, 22, 22), (int(cx - eye_dx), int(eye_y)), eye_r)
    pygame.draw.circle(surface, (22, 22, 22), (int(cx + eye_dx), int(eye_y)), eye_r)

    mouth_y = body.y + body.height * 0.64
    pygame.draw.arc(
        surface,
        (28, 28, 28),
        pygame.Rect(int(cx - body.width * 0.16), int(mouth_y - body.height * 0.08), int(body.width * 0.32), int(body.height * 0.20)),
        math.radians(15),
        math.radians(165),
        2,
    )


def _draw_ball_actor(surface: pygame.Surface, rect: pygame.Rect, color: Tuple[int, int, int], scale: float = 0.5) -> None:
    size = max(8, int(min(rect.width, rect.height) * scale))
    circle_rect = pygame.Rect(0, 0, size, size)
    circle_rect.center = rect.center

    pygame.draw.ellipse(surface, color, circle_rect)
    outline = tuple(max(0, c - 45) for c in color)
    pygame.draw.ellipse(surface, outline, circle_rect, 2)

    shine = pygame.Rect(
        circle_rect.x + circle_rect.width // 5,
        circle_rect.y + circle_rect.height // 6,
        max(3, circle_rect.width // 4),
        max(3, circle_rect.height // 4),
    )
    pygame.draw.ellipse(surface, (255, 255, 255), shine)


def _draw_box_actor(surface: pygame.Surface, rect: pygame.Rect, color: Tuple[int, int, int]) -> None:
    inner = rect.inflate(-rect.width // 5, -rect.height // 5)
    pygame.draw.rect(surface, color, inner, border_radius=6)
    pygame.draw.rect(surface, (30, 30, 30), inner, 2, border_radius=6)


def _draw_stunned_indicator(surface: pygame.Surface, rect: pygame.Rect, stunned_turns: int) -> None:
    if stunned_turns <= 0:
        return

    ring = rect.inflate(-rect.width // 5, -rect.height // 5)
    pygame.draw.ellipse(surface, (255, 220, 90), ring, 2)

    cx = rect.centerx
    top = rect.y + max(4, rect.height // 10)
    points = [
        (cx + rect.width * 0.08, top),
        (cx - rect.width * 0.08, top + rect.height * 0.18),
        (cx + rect.width * 0.02, top + rect.height * 0.18),
        (cx - rect.width * 0.12, top + rect.height * 0.40),
        (cx + rect.width * 0.16, top + rect.height * 0.14),
        (cx, top + rect.height * 0.14),
    ]
    pygame.draw.polygon(surface, (255, 234, 120), [(int(x), int(y)) for x, y in points])


def draw_actor(
    surface: pygame.Surface,
    rect: pygame.Rect,
    actor_id: int,
    bob_phase: float = 0.0,
    stunned_turns: int = 0,
) -> None:
    if actor_id == ACTOR_EMPTY:
        return

    info = actor_def(actor_id)
    if info is None:
        return

    style = info.render_style
    color = info.color
    scale = getattr(info, "render_scale", 0.66)

    if style == "ball":
        _draw_ball_actor(surface, rect, color, scale=scale)
    elif style == "box":
        _draw_box_actor(surface, rect, color)
    else:
        _draw_character_actor(surface, rect, color, scale=scale, bob_phase=bob_phase)

    _draw_stunned_indicator(surface, rect, stunned_turns)


# =============================================================================
# 整图绘制
# =============================================================================

def draw_level(
    surface: pygame.Surface,
    level,
    offset_x: int = 0,
    offset_y: int = 0,
    cell_size: int = CELL_SIZE,
) -> None:
    actor_status = getattr(level, "actor_status", None)
    shock_used = getattr(level, "shock_used", None)
    shock_grid = getattr(level, "shock", None)

    for y in range(level.height):
        for x in range(level.width):
            rect = pygame.Rect(
                offset_x + x * cell_size,
                offset_y + y * cell_size,
                cell_size,
                cell_size,
            )

            draw_terrain(surface, rect, level.terrain[y][x])

            cell_has_shock = False
            if shock_grid is not None and 0 <= y < len(shock_grid) and 0 <= x < len(shock_grid[y]):
                cell_has_shock = int(shock_grid[y][x]) != 0
            elif level.terrain[y][x] == TERRAIN_SHOCK:
                # 兼容旧关卡：电击区仍直接写在 terrain 中。
                cell_has_shock = True

            cell_shock_used = False
            if shock_used is not None and 0 <= y < len(shock_used) and 0 <= x < len(shock_used[y]):
                cell_shock_used = int(shock_used[y][x]) != 0

            if cell_has_shock and not cell_shock_used:
                draw_terrain(surface, rect, TERRAIN_SHOCK)

            draw_goal(surface, rect, level.goals[y][x])

            stunned_turns = 0
            if actor_status is not None and 0 <= y < len(actor_status) and 0 <= x < len(actor_status[y]):
                stunned_turns = max(0, int(actor_status[y][x]))
            draw_actor(surface, rect, level.actors[y][x], stunned_turns=stunned_turns)
            pygame.draw.rect(surface, GRID_LINE_COLOR, rect, 1)
