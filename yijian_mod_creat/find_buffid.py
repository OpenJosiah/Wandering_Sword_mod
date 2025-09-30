# -*- coding: utf-8 -*-
"""
功能：
在所有文件夹及其子文件夹搜索指定的BuffID。
"""
import os
import sys
import json
from pathlib import Path
from typing import Any, Iterable, List, Set, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========= 顶部配置（你主要改这里） =========
TARGET_BUFF_ID: int = 100500          # 目标 buffid（命令行第1参可覆盖）
TOP_N_PRINT: int = 3                # 控制台仅打印前 N 条（命令行第2参可覆盖）
SAVE_OUTPUT: bool = False            # ←← 开关：是否把“全部命中列表”保存成 JSON 文件

# 并行线程数（I/O 密集）
MAX_WORKERS = min(32, (os.cpu_count() or 4) * 2)

# 搜索目录（递归）
SEARCH_DIRS: List[Path] = [
    Path(r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Skills"),
    Path(r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Core"),
    Path(r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH"),
    Path(r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_1\Wandering_Sword\Content\JH\Skills"),
]

# 多前缀（例：["GE","BP"]）；留空 [] 表示不限前缀，匹配所有 .json
FILENAME_PREFIXES: List[str] = ["GE","GA"]
FILE_EXT = ".json"

# 输出目录（仅当 SAVE_OUTPUT=True 且有命中时才会写文件）
OUT_DIR = Path(r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles")
# ==========================================


# ---------- 参数解析 ----------
def parse_args(argv: List[str]) -> None:
    global TARGET_BUFF_ID, TOP_N_PRINT
    if len(argv) >= 2:
        try:
            TARGET_BUFF_ID = int(argv[1])
        except ValueError:
            pass
    if len(argv) >= 3:
        try:
            TOP_N_PRINT = max(1, int(argv[2]))
        except ValueError:
            pass


# ---------- 文件枚举 ----------
def file_matches_prefixes(p: Path) -> bool:
    if not FILENAME_PREFIXES:
        return True
    name = p.name
    return any(name.startswith(pfx) for pfx in FILENAME_PREFIXES)

def iter_target_json_files(dirs: Iterable[Path]) -> List[Path]:
    seen: Set[Path] = set()
    files: List[Path] = []
    for root in dirs:
        if not root or not root.exists():
            continue
        for p in root.rglob(f"*{FILE_EXT}"):
            if not file_matches_prefixes(p):
                continue
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                files.append(rp)
    return files


# ---------- JSON 加载 ----------
def load_json_loose(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                return json.loads(f.read())
        except Exception:
            return None


# ---------- BuffId/BuffIds 提取（仅凭这两个键） ----------
def _ci_eq(a: str, b: str) -> bool:
    return a.lower() == b.lower()

def _ints_from_buffids_array_node(node: Any) -> List[int]:
    """
    尝试从一个可能代表 BuffIds 的节点中读取整型数组：
      - { "Name":"BuffIds", "Value":[ {"Value":123}, ... ] }
      - { "BuffIds":[123, ...] } 或 { "BuffIds":[ {"Value":123}, ... ] }
    """
    out: List[int] = []
    if isinstance(node, dict):
        # UAsset 风格：Name=BuffIds
        name = node.get("Name")
        if isinstance(name, str) and _ci_eq(name, "BuffIds"):
            arr = node.get("Value")
            if isinstance(arr, list):
                for it in arr:
                    if isinstance(it, dict):
                        v = it.get("Value")
                        if isinstance(v, int):
                            out.append(v)
                    elif isinstance(it, int):
                        out.append(it)
            return out
        # 直接键 BuffIds
        arr2 = node.get("BuffIds")
        if isinstance(arr2, list):
            for it in arr2:
                if isinstance(it, dict):
                    v = it.get("Value")
                    if isinstance(v, int):
                        out.append(v)
                elif isinstance(it, int):
                    out.append(it)
    return out

def _int_from_buffid_node(node: Any) -> List[int]:
    """
    尝试从一个可能代表 BuffId 的节点中读取单个整型：
      - { "Name":"BuffId", "Value":123 }
      - { "BuffId":123 }
    """
    if isinstance(node, dict):
        name = node.get("Name")
        if isinstance(name, str) and _ci_eq(name, "BuffId"):
            v = node.get("Value")
            return [v] if isinstance(v, int) else []
        v2 = node.get("BuffId")
        return [v2] if isinstance(v2, int) else []
    return []

def node_contains_target_buff(node: Any, target: int) -> bool:
    # 当前节点直接命中？
    if target in _int_from_buffid_node(node):
        return True
    if target in _ints_from_buffids_array_node(node):
        return True
    # 递归向下
    if isinstance(node, dict):
        for v in node.values():
            if node_contains_target_buff(v, target):
                return True
    elif isinstance(node, list):
        for v in node:
            if node_contains_target_buff(v, target):
                return True
    return False


# ---------- 优先 Exports[2:]，否则深度遍历 ----------
def exports_from_root(obj: Any) -> List[dict]:
    if isinstance(obj, dict):
        for key in ("Exports", "exports"):
            v = obj.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        # 兜底：找看起来像 exports 的第一个列表
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    elif isinstance(obj, list):
        if obj and isinstance(obj[0], dict):
            return obj
    return []

def file_contains_buffid(path: Path, target: int) -> bool:
    obj = load_json_loose(path)
    if obj is None:
        return False
    exps = exports_from_root(obj)
    if exps:
        for exp in exps[2:]:  # 从第三项开始
            if node_contains_target_buff(exp, target):
                return True
    # 未命中则深度遍历整棵 JSON
    return node_contains_target_buff(obj, target)


# ---------- 主流程 ----------
def main():
    parse_args(sys.argv)

    files = iter_target_json_files(SEARCH_DIRS)
    if not files:
        print("未找到匹配的 JSON 文件。")
        return

    matches: List[Path] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fut_map = {ex.submit(file_contains_buffid, fp, TARGET_BUFF_ID): fp for fp in files}
        for fut in as_completed(fut_map):
            fp = fut_map[fut]
            ok = False
            try:
                ok = fut.result()
            except Exception:
                ok = False
            if ok:
                matches.append(fp)

    matches_sorted = sorted(matches, key=lambda p: str(p))

    # 没有命中：直接提示并结束（不保存文件）
    if not matches_sorted:
        print(f"未找到包含 buffid {TARGET_BUFF_ID} 的文件。")
        return

    # 有命中：展示前 N 条
    print(f"目标 buffid: {TARGET_BUFF_ID}")
    print(f"共命中 {len(matches_sorted)} 个文件。前 {TOP_N_PRINT} 个示例：")
    for i, p in enumerate(matches_sorted[:TOP_N_PRINT], 1):
        print(f"{i}. {p}")

    # 可选保存：仅当 SAVE_OUTPUT=True
    if SAVE_OUTPUT:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUT_DIR / f"buffid_{TARGET_BUFF_ID}_matches.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump([str(p) for p in matches_sorted], f, ensure_ascii=False, indent=2)
        print(f"\n已写出全部命中路径到：{out_path}")

if __name__ == "__main__":
    main()
