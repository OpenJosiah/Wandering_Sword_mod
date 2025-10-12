# -*- coding: utf-8 -*-
"""
功能：
输出NameMap总表，便于补充新文件缺失的NameMap。
"""

import os
import re
import json
from pathlib import Path
from typing import Iterable, Set, Union, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============== 配置（按需修改） ==============
# 主文件夹（必遍历）
MAIN_FOLDER = Path(r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_1\Wandering_Sword\Content\JH\Skills")

ENABLE_SUBFOLDERS = True  # True 启用副文件夹；False 只扫主文件夹
# 副文件夹（统一开关）
SUB_FOLDERS = [
    Path(r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Core"),
    Path(r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Skills"),
    Path(r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH\Wandering_Sword\Content\JH\Skills"),
]

# 只搜指定前缀文件（启用时，仅遍历以这些前缀开头的 .json）
ENABLE_PREFIX_FILTER = True
FILE_PREFIXES = ["GE"]          # 例：["GE", "ABC"]
PREFIX_CASE_SENSITIVE = False   # True大小写敏感；False不敏感

# 输出目录：False=脚本目录；True=使用自定义目录 OUTPUT_DIR
USE_CUSTOM_OUTPUT_DIR = True
OUTPUT_DIR = Path(r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles")
OUTPUT_FILENAME = "namemap_all_GA.txt"  # 统一输出到一个文件

# 并行线程数（I/O密集，适当偏大）
MAX_WORKERS = max(8, (os.cpu_count() or 8) * 4)
# ===========================================


def is_numeric_only(s: str) -> bool:
    """整串仅由【整数】组成（允许+/-号；包括0）则返回 True。"""
    return bool(re.fullmatch(r"[+-]?\d+", (s or "").strip()))


def normalize_name(name: str) -> Optional[str]:
    """
    仅当链头形如  <something>_<digits>.<...>  时：
      - 视为“函数链”，只保留链头并去掉末尾 _digits
    其他情况（包括带点但链头不带 _digits 的命名空间，如 JH.Ability.State.NoEnemyBlocking）原样保留；
    无点名称也原样保留。
    """
    if not isinstance(name, str):
        return None
    s = name.strip()
    if not s:
        return None

    if '.' in s:
        head, _ = s.split('.', 1)
        if re.search(r'_\d+$', head):                  # 链头以 _数字 结尾
            return re.sub(r'_\d+$', '', head) or None # 去掉索引，仅保留基础名
        else:
            return s                                   # 非链式“命名空间”风格，原样保留
    else:
        return s                                       # 无点，原样保留


def find_namemap_in_obj(obj: Union[dict, list, str, int, float, None]) -> Iterable[str]:
    """递归查找键名为 NameMap/Namemap（大小写不敏感）的值，产出其中的字符串项。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() == "namemap":
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            yield item
                elif isinstance(v, (dict, list)):
                    yield from find_namemap_in_obj(v)
            else:
                yield from find_namemap_in_obj(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from find_namemap_in_obj(x)


def read_json_safely(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except UnicodeDecodeError:
        for enc in ("utf-8-sig", "gb18030"):
            try:
                with path.open("r", encoding=enc) as f:
                    return json.load(f)
            except Exception:
                pass
        return None
    except Exception:
        return None


def matches_prefix(filename: str) -> bool:
    """仅当启用前缀过滤时检查主名是否以任一前缀开头。"""
    if not ENABLE_PREFIX_FILTER or not FILE_PREFIXES:
        return True
    stem = Path(filename).stem
    if PREFIX_CASE_SENSITIVE:
        return any(stem.startswith(p) for p in FILE_PREFIXES)
    s = stem.lower()
    return any(s.startswith(p.lower()) for p in FILE_PREFIXES)


def collect_json_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".json") and matches_prefix(fn):
                files.append(Path(dirpath) / fn)
    return files


def process_file(file_path: Path) -> Set[str]:
    """读取并提取该 JSON 文件中的 NameMap（按 normalize_name 处理），并过滤纯数字项。"""
    out: Set[str] = set()
    data = read_json_safely(file_path)
    if data is None:
        return out
    for raw in find_namemap_in_obj(data):
        norm = normalize_name(raw)
        if norm and not is_numeric_only(norm):  # 过滤整行仅数字（含正负号）
            out.add(norm)
    return out


def write_txt(lines: Iterable[str], out_path: Path):
    out_path.write_text("\n".join(sorted(lines)), encoding="utf-8")


def resolve_path(p: Path, script_dir: Path) -> Path:
    """绝对路径直接用；相对路径相对脚本目录解析。"""
    return p if p.is_absolute() else (script_dir / p).resolve()


def main():
    script_dir = Path(__file__).resolve().parent
    out_dir = resolve_path(OUTPUT_DIR, script_dir) if USE_CUSTOM_OUTPUT_DIR else script_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILENAME

    # 组织根目录：主（必扫）+ 副（总开关控制）
    roots: List[Tuple[str, Path]] = []
    main_root = resolve_path(MAIN_FOLDER, script_dir)
    roots.append(("MAIN", main_root))
    if ENABLE_SUBFOLDERS:
        for sub in SUB_FOLDERS:
            roots.append(("SUB", resolve_path(sub, script_dir)))

    # 收集所有 JSON 文件
    json_files: List[Path] = []
    for _, root_path in roots:
        if not root_path.exists() or not root_path.is_dir():
            print(f"[跳过] 找不到目录：{root_path}")
            continue
        jfs = collect_json_files(root_path)
        json_files.extend(jfs)
        print(f"[扫描] {root_path} -> JSON {len(jfs)} 个（前缀过滤={'开' if ENABLE_PREFIX_FILTER else '关'}）")

    # 并行处理所有文件
    final_set: Set[str] = set()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(process_file, fp): fp for fp in json_files}
        for fut in as_completed(futures):
            fp = futures[fut]
            try:
                names = fut.result()
            except Exception as e:
                print(f"[错误] 处理失败：{fp} -> {e}")
                continue
            final_set.update(names)

    # 统一输出到一个文件
    write_txt(final_set, out_path)
    print(f"[完成] 总汇去重 {len(final_set)} 项 -> {out_path}")

    # 摘要
    print("\n=== 配置摘要 ===")
    print(f"主文件夹：{main_root}")
    print(f"副文件夹开关：{ENABLE_SUBFOLDERS}；数量：{len(SUB_FOLDERS)}")
    print(f"文件前缀过滤：{ENABLE_PREFIX_FILTER}；前缀={FILE_PREFIXES}；大小写敏感={PREFIX_CASE_SENSITIVE}")
    print(f"输出文件：{out_path}")

if __name__ == "__main__":
    main()
