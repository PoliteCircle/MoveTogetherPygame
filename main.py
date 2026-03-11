"""
main.py
=======
游戏启动入口（pygame 图形化选关版）。

职责：
1. 在 pygame 窗口中显示关卡列表，而不是在终端中输入编号。
2. 用户可在图形化菜单中选择关卡、进入编辑器、退出程序。
3. 启动选定关卡的 pygame 游戏界面。
4. 退出当前关卡后，再次回到图形化选关界面，方便连续测试多个关卡。

图形化菜单交互：
- ↑ / ↓：选择关卡
- Enter：进入当前选中的关卡
- E：打开地图编辑器
- R：刷新关卡列表
- Esc：退出程序

游戏内按键：
- ↑ ↓ ← →：移动
- R：重开当前关卡
- H：求解当前关卡并显示最短路径
- P：若存在最短路径，则自动播放
- ESC：退出当前关卡，返回选关菜单

说明：
- 这一版已经不再使用 input()。
- 整个程序的交互统一在 pygame 窗口内完成，更适合游戏项目。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

import pygame

from core import (
    BG_COLOR,
    CELL_SIZE,
    MOVE_TO_CHAR,
    draw_level,
    draw_text,
    is_victory,
    load_level,
    move_level,
    solve_level_bfs,
)
from mapedit import run_editor


BASE_DIR = Path(__file__).resolve().parent
LEVEL_DIR = BASE_DIR / "levels"

MENU_WIDTH = 900
MENU_HEIGHT = 700
WINDOW_EXTRA_HEIGHT = 150
ANIM_DURATION_MS = 140
AUTO_PLAY_DELAY_MS = 180

##################################################
##################################################
# 辅助函数
def list_subdirs(dir_path: Path) -> List[Path]:
    """
    列出某个目录下的所有子文件夹。
    只返回文件夹，不返回文件。
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    return sorted([p for p in dir_path.iterdir() if p.is_dir()], key=lambda p: p.name.lower())


def list_level_files_in(dir_path: Path) -> List[Path]:
    """
    列出某个目录下的所有 json 关卡文件。
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    return sorted(dir_path.glob("*.json"), key=lambda p: p.name.lower())


def build_menu_items(current_dir: Path) -> List[Dict[str, Any]]:
    """
    根据当前目录构建菜单项列表。

    菜单顺序固定为：
    1. 进入编辑器
    2. 返回上一级（若当前目录不是根目录）
    3. 所有子文件夹
    4. 所有关卡文件
    """
    items: List[Dict[str, Any]] = []

    items.append({
        "type": "edit",
        "label": "[编辑器] 打开当前目录地图编辑器",
        "path": current_dir,
    })

    if current_dir.resolve() != LEVEL_DIR.resolve():
        items.append({
            "type": "back",
            "label": "[返回] ..",
            "path": current_dir.parent,
        })

    for subdir in list_subdirs(current_dir):
        items.append({
            "type": "dir",
            "label": f"[文件夹] {subdir.name}",
            "path": subdir,
        })

    for level_file in list_level_files_in(current_dir):
        items.append({
            "type": "level",
            "label": f"[关卡] {level_file.name}",
            "path": level_file,
        })

    return items
##################################################
##################################################


def list_level_files() -> List[Path]:
    LEVEL_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(LEVEL_DIR.glob("*.json"))


def format_solution(solution: Optional[List[str]]) -> str:
    if solution is None:
        return "无解 / 超出搜索上限"
    if not solution:
        return "初始状态已通关"
    return "".join(MOVE_TO_CHAR[m] for m in solution)


def run_menu(start_dir: Optional[Path] = None) -> Optional[dict]:
    pygame.init()
    pygame.display.set_caption("一起移动！游戏 - 关卡浏览")
    screen = pygame.display.set_mode((MENU_WIDTH, MENU_HEIGHT))
    clock = pygame.time.Clock()

    current_dir = start_dir if start_dir is not None else LEVEL_DIR
    if not current_dir.exists():
        current_dir = LEVEL_DIR
    menu_items = build_menu_items(current_dir)
    selected_index = 0

    last_click_index = -1
    last_click_ms = 0
    double_click_threshold = 350

    def activate_selected() -> Optional[dict]:
        nonlocal current_dir, menu_items, selected_index, menu_changed

        if not menu_items:
            return None

        item = menu_items[selected_index]
        item_type = item["type"]
        item_path = item["path"]

        if item_type == "edit":
            return {
                "action": "edit",
                "dir": current_dir,
                "menu_dir": current_dir,
            }

        elif item_type == "back":
            current_dir = item_path
            menu_items = build_menu_items(current_dir)
            selected_index = 0
            menu_changed = True
            return None

        elif item_type == "dir":
            current_dir = item_path
            menu_items = build_menu_items(current_dir)
            selected_index = 0
            menu_changed = True
            return None

        elif item_type == "level":
            return {
                "action": "play",
                "path": item_path,
                "menu_dir": current_dir,
            }

        return None

    while True:
        screen.fill((22, 24, 30))
        menu_changed = False

        list_left = 40
        list_top = 190
        list_width = MENU_WIDTH - 80
        list_height = 390

        item_height = 38
        start_y = list_top + 52
        visible_count = max(1, (list_height - 76) // item_height)

        if menu_items:
            selected_index = max(0, min(selected_index, len(menu_items) - 1))
            half = visible_count // 2
            start_index = max(0, selected_index - half)
            end_index = min(len(menu_items), start_index + visible_count)
            start_index = max(0, end_index - visible_count)
        else:
            selected_index = 0
            start_index = 0
            end_index = 0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return None

                elif event.key == pygame.K_r:
                    menu_items = build_menu_items(current_dir)
                    if menu_items:
                        selected_index = max(0, min(selected_index, len(menu_items) - 1))
                    else:
                        selected_index = 0

                elif event.key == pygame.K_BACKSPACE:
                    if current_dir.resolve() != LEVEL_DIR.resolve():
                        current_dir = current_dir.parent
                        menu_items = build_menu_items(current_dir)
                        selected_index = 0
                        menu_changed = True

                elif event.key == pygame.K_UP:
                    if menu_items:
                        selected_index = (selected_index - 1) % len(menu_items)

                elif event.key == pygame.K_DOWN:
                    if menu_items:
                        selected_index = (selected_index + 1) % len(menu_items)

                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    result = activate_selected()
                    if result is not None:
                        return result

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos

                if menu_items:
                    clicked_index = None

                    for draw_i, item_index in enumerate(range(start_index, end_index)):
                        y = start_y + draw_i * item_height
                        item_rect = pygame.Rect(
                            list_left + 12,
                            y - 3,
                            list_width - 24,
                            item_height - 2,
                        )
                        if item_rect.collidepoint(mx, my):
                            clicked_index = item_index
                            break

                    if clicked_index is not None:
                        now_ms = pygame.time.get_ticks()
                        is_double_click = (
                            clicked_index == last_click_index
                            and now_ms - last_click_ms <= double_click_threshold
                        )

                        selected_index = clicked_index
                        last_click_index = clicked_index
                        last_click_ms = now_ms

                        if is_double_click:
                            result = activate_selected()
                            if result is not None:
                                return result

        if menu_changed:
            continue
        draw_text(screen, "一起移动！游戏", 40, 26, 40, color=(235, 235, 240))
        draw_text(screen, "关卡浏览器 / 图形化选关菜单", 42, 74, 24, color=(170, 185, 210))

        draw_text(
            screen,
            "操作：单击选择，双击确认，↑/↓选择，Enter确认，Backspace返回上级，R刷新，Esc退出",
            40,
            120,
            24,
            color=(200, 210, 220),
        )

        try:
            relative_dir = current_dir.relative_to(LEVEL_DIR)
            dir_text = "." if str(relative_dir) == "." else f"./{relative_dir.as_posix()}"
        except ValueError:
            dir_text = str(current_dir)

        draw_text(screen, f"当前目录：{dir_text}", 40, 154, 24, color=(220, 210, 150))

        pygame.draw.rect(
            screen,
            (34, 38, 46),
            (list_left, list_top, list_width, list_height),
            border_radius=12,
        )
        pygame.draw.rect(
            screen,
            (70, 78, 95),
            (list_left, list_top, list_width, list_height),
            width=2,
            border_radius=12,
        )

        if not menu_items:
            draw_text(
                screen,
                "当前目录为空。你可以在此目录打开编辑器创建关卡。",
                list_left + 20,
                list_top + 30,
                28,
                color=(220, 220, 220),
            )
        else:
            draw_text(
                screen,
                f"当前可选项：{len(menu_items)} 个",
                list_left + 20,
                list_top + 16,
                24,
                color=(230, 230, 235),
            )

            for draw_i, item_index in enumerate(range(start_index, end_index)):
                y = start_y + draw_i * item_height
                item = menu_items[item_index]
                is_selected = (item_index == selected_index)

                item_type = item["type"]
                if item_type == "edit":
                    normal_color = (210, 235, 210)
                elif item_type == "back":
                    normal_color = (230, 220, 170)
                elif item_type == "dir":
                    normal_color = (180, 220, 255)
                else:
                    normal_color = (215, 220, 228)

                if is_selected:
                    pygame.draw.rect(
                        screen,
                        (78, 105, 170),
                        (list_left + 12, y - 3, list_width - 24, item_height - 2),
                        border_radius=8,
                    )
                    text_color = (255, 255, 255)
                else:
                    text_color = normal_color

                draw_text(
                    screen,
                    f"{item_index + 1:>3}.",
                    list_left + 24,
                    y,
                    23,
                    color=text_color,
                )
                draw_text(
                    screen,
                    item["label"],
                    list_left + 90,
                    y,
                    23,
                    color=text_color,
                )

            draw_text(
                screen,
                f"当前选中：{menu_items[selected_index]['label']}",
                list_left + 20,
                list_top + list_height - 32,
                22,
                color=(180, 220, 180),
            )

        draw_text(screen, f"根关卡目录：{LEVEL_DIR}", 40, 605, 20, color=(145, 155, 170))
        draw_text(screen, "菜单顺序：编辑器 -> 返回上级 -> 文件夹 -> 关卡", 40, 632, 20, color=(145, 155, 170))

        pygame.display.flip()
        clock.tick(60)


def run_level(level_path: Path) -> None:
    pygame.init()
    pygame.display.set_caption(f"一起移动！ - {level_path.name}")

    original_level = load_level(level_path)
    level = original_level.clone()

    win_w = level.width * CELL_SIZE + 200
    win_h = level.height * CELL_SIZE + 150
    screen = pygame.display.set_mode((win_w, win_h))
    clock = pygame.time.Clock()

    cached_solution: Optional[List[str]] = None
    last_solution_text = "尚未求解"

    auto_play_queue: List[str] = []
    auto_play_next_ms = 0

    running = True
    won = is_victory(level)

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                    break

                if event.key == pygame.K_r:
                    level = original_level.clone()
                    won = is_victory(level)
                    auto_play_queue.clear()
                    continue

                if event.key == pygame.K_h:
                    cached_solution = solve_level_bfs(level)
                    last_solution_text = format_solution(cached_solution)
                    continue

                key_to_move = {
                    pygame.K_UP: "up",
                    pygame.K_DOWN: "down",
                    pygame.K_LEFT: "left",
                    pygame.K_RIGHT: "right",
                }

                if event.key in key_to_move and not won:
                    move_name = key_to_move[event.key]
                    new_level = move_level(level, move_name)
                    if new_level.actors != level.actors:
                        level = new_level
                        won = is_victory(level)

        screen.fill(BG_COLOR)

        draw_level(screen, level, 100, 0, CELL_SIZE)

        panel_y = level.height * CELL_SIZE
        pygame.draw.rect(screen, (28, 30, 36), (0, panel_y, win_w, WINDOW_EXTRA_HEIGHT))
        draw_text(screen, f"关卡: {level.name}", 14, panel_y + 10, 26)
        draw_text(screen, "方向键移动,R重开,H求解,ESC返回(用英文输入法)", 14, panel_y + 45, 22)
        draw_text(screen, f"求解结果: {last_solution_text}", 14, panel_y + 78, 22)

        if won:
            draw_text(screen, "已通关！按 ESC 返回选关，或按 R 重开。", 14, panel_y + 108, 24, color=(120, 230, 140))
        else:
            draw_text(
                screen,
                "过关规则：所有目标都必须由对应角色占据",
                14,
                panel_y + 108,
                22,
                color=(200, 210, 220),
            )

        pygame.display.flip()
        clock.tick(60)

    pygame.display.quit()


def main() -> None:
    last_menu_dir = LEVEL_DIR

    while True:
        choice = run_menu(start_dir=last_menu_dir)

        if choice is None:
            pygame.quit()
            print("已退出。")
            return

        action = choice.get("action")
        last_menu_dir = choice.get("menu_dir", last_menu_dir)

        if action == "edit":
            run_editor(level_dir=choice["dir"])
            continue

        if action == "play":
            run_level(choice["path"])
            continue


if __name__ == "__main__":
    main()