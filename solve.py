"""
solve.py
========
命令行求解器。

用途：
- 读取指定关卡 JSON
- 使用 core.solve_level_bfs() 求最短解
- 输出最短步数与方向序列

使用示例：
    python solve.py levels/demo_easy.json

若不传路径，则会列出 levels 目录下的所有关卡，供用户输入编号选择。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from core import load_level, solve_level_bfs
from game_rules import MOVE_TO_CHAR

BASE_DIR = Path(__file__).resolve().parent
LEVEL_DIR = BASE_DIR / "levels"



def list_levels() -> List[Path]:
    """列出 levels 目录下所有 json 关卡文件。"""
    LEVEL_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(LEVEL_DIR.glob("*.json"))



def choose_level_interactively() -> Path | None:
    """在终端中让用户选择一个关卡文件。"""
    files = list_levels()
    if not files:
        print("levels 目录中还没有任何 json 关卡文件。")
        return None

    print("可求解的关卡：")
    for i, f in enumerate(files, 1):
        print(f"  {i}. {f.name}")

    while True:
        s = input("请输入关卡编号（直接回车退出）：").strip()
        if not s:
            return None
        if s.isdigit() and 1 <= int(s) <= len(files):
            return files[int(s) - 1]
        print("输入无效，请重新输入。")



def format_solution(path_moves: List[str]) -> str:
    """把 ['up','right'] 这样的方向列表格式化成 'UR' 这样的紧凑字符串。"""
    return "".join(MOVE_TO_CHAR[m] for m in path_moves)



def main() -> None:
    if len(sys.argv) >= 2:
        level_path = Path(sys.argv[1])
    else:
        level_path = choose_level_interactively()
        if level_path is None:
            return

    level = load_level(level_path)
    print(f"正在求解关卡: {level.name} ({level_path.name})")

    solution = solve_level_bfs(level)
    if solution is None:
        print("结果：未找到解，或者状态空间超过限制。")
        return

    print(f"最短步数: {len(solution)}")
    print(f"最短路径(简写): {format_solution(solution)}")
    if solution:
        print("最短路径(详细):")
        print(" -> ".join(solution))
    else:
        print("该关卡初始状态已满足过关条件。")


if __name__ == "__main__":
    main()
