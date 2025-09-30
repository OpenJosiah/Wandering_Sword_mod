# -*- coding: utf-8 -*-
"""
功能：
1) 递归扫描主目录及可选补充目录的 .json 文件。
2) 从 Exports[2:] 提取 JH 函数；从 NameMap 或 Exports[起始索引] 提取 Tag/触发器。
3) 统计每个名称的来源文件（去重，最多保留 MAX_SOURCES_PER_NAME 条）。
4) 两种模式：
   - 快速模式：直接读取已保存来源表并进入查询；
   - 标准流程：扫描→导出 functions/tags/detectors→交互查询→可选择保存来源表。
5) 统一输出到 OUT_DIR，支持自定义目录。
"""

import os, json, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Set, Tuple

# =============== 仅用已保存来源表（新流程总开关）================
# True：只读 SAVED_SOURCES_PATH -> 直接进入查询循环 -> 退出
# False：按完整流程：扫描 -> 导出 -> （询问后）查询 -> 询问是否保存
USE_SAVED_SOURCES = True
# 保存/读取来源表的路径（建议用 .json，亦兼容 .txt（TSV））
SAVED_SOURCES_PATH = Path(r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles\name_sources.json")
# ============================================================

# ================= 扫描配置（完整流程时生效） =================
ROOT_DIR = Path(r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Skills")

SUPP_ENABLED = True
SUPP_DIRS = [
    Path(r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Core"),
    Path(r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH"),
    Path(r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_1\Wandering_Sword\Content\JH\Skills"),
]

MAX_WORKERS = min(32, (os.cpu_count() or 4) * 2)

# 开关：标签与触发器。True:搜索Export；False：搜索NameMap
TAGS_FROM_EXPORTS = True
# 从第几项 Export 开始提取 Tag/触发器（0 基索引）
START_EXPORT_INDEX_FOR_TAGS_DETS = 1

# =============== 输出目录控制（True 启用自定义目录）==============
USE_CUSTOM_OUT_DIR = True
CUSTOM_OUT_DIR = Path(r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles")

# 脚本所在目录（非工作目录）
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DIR = (CUSTOM_OUT_DIR if USE_CUSTOM_OUT_DIR else SCRIPT_DIR)
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 输出文件路径
OUT_FUNCS     = OUT_DIR / "functions.txt"
OUT_TAGS      = OUT_DIR / "tags.txt"
OUT_DETECTORS = OUT_DIR / "detectors.txt"
# 默认保存来源映射为 JSON（更易读/程序友好）；若想存 TSV，只需把后缀改成 .txt
OUT_SOURCES   = OUT_DIR / "name_sources.json"
# 同一名称最多保留多少条“来源文件路径”（按字典序最小优先）——可快速修改
MAX_SOURCES_PER_NAME = 3
# ============================================================

# 函数名前缀（认可的起始）
FUNCTION_PREFIXES = ("JHGEExtAct", "JHExecutionPhase", "JHGEExtReq")
SUFFIX_NUM_RE = re.compile(r"_(\d+)$")

# ---------- 查询净化辅助：去引号/空白、取末段、剥离尾部 _数字(可重复) ----------
QUOTE_TRIM_RE = re.compile(r'^[\s\'"\u201c\u201d]+|[\s\'"\u201c\u201d]+$')
MULTI_NUM_SUFFIX_RE = re.compile(r'(?:_\d+)+$')

def sanitize_quotes(s: str) -> str:
    if not isinstance(s, str):
        return ""
    return QUOTE_TRIM_RE.sub("", s)

def purify_function_query(raw: str) -> str:
    """仅用于函数名查询：去引号 -> 取链末段 -> 连续剥离结尾 _数字。"""
    s = sanitize_quotes(raw)
    if not s:
        return s
    seg = s.split(".")[-1]
    # 连续去掉结尾 _数字
    while True:
        m = SUFFIX_NUM_RE.search(seg)
        if m and m.end() == len(seg):
            seg = seg[:m.start()]
        else:
            break
    return seg

def normalize_for_lookup(raw: str) -> str:
    """
    查询名规范化：
    - 函数名：以 FUNCTION_PREFIXES 任一前缀开头 -> 函数链净化（按点取末段 + 去尾部_数字）
    - Tag：以 'JH.Ability.' 开头 -> 仅去引号
    - 触发器：包含 '::' -> 仅去引号
    - 其它：仅去引号（保留点号）
    """
    s = sanitize_quotes(raw)
    if not s:
        return s

    # 明确识别 Tag / 触发器：保留点号与原样
    if s.startswith("JH.Ability.") or "::" in s:
        return s

    # 识别为函数名：执行函数链净化
    if any(s.startswith(p) for p in FUNCTION_PREFIXES):
        return purify_function_query(s)

    # 其它情况：只去引号
    return s

# ======================= 通用 JSON 工具 ==========================
def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:
        return None

def _ci_eq(a: str, b: str) -> bool:
    return a.lower() == b.lower()

def _get_exports(data: dict) -> List[dict]:
    """从顶层取 Exports/exports 列表（宽松判断）"""
    if not isinstance(data, dict):
        return []
    key = next((k for k in data.keys() if str(k).lower() == "exports"), None)
    if key is None:
        return []
    exps = data.get(key)
    return exps if isinstance(exps, list) else []

def _gather_strings(node, out: List[str], max_per_node: int = None):
    """
    递归收集节点下的字符串。
    - dict: 遍历 values
    - list: 遍历元素
    - str : 收集
    - 其它：忽略
    max_per_node=None 表示不限制；给整数则为软上限
    """
    if isinstance(node, str):
        out.append(node)
        return
    if isinstance(node, dict):
        for v in node.values():
            if max_per_node is not None and len(out) >= max_per_node:
                break
            _gather_strings(v, out, max_per_node)
    elif isinstance(node, list):
        for v in node:
            if max_per_node is not None and len(out) >= max_per_node:
                break
            _gather_strings(v, out, max_per_node)

# ======================= 函数名提取（Exports[2:]） ==========================
def last_segment(name: str) -> str:
    """'A.B' -> 'B'；再去掉尾部 '_123' 数字后缀（单次）。"""
    base = name.split(".")[-1]
    return SUFFIX_NUM_RE.sub("", base)

def read_functions_from_exports(path: Path) -> Set[str]:
    """从 JSON.Exports[2:] 的 ObjectName 中提取函数名集合。"""
    data = load_json(path)
    if not isinstance(data, dict):
        return set()
    exps = _get_exports(data)
    if not exps:
        return set()

    funcs: Set[str] = set()
    for exp in exps[2:]:  # 从第3项开始
        if isinstance(exp, dict):
            on = exp.get("ObjectName")
            if isinstance(on, str) and on:
                name = last_segment(on)
                if any(name.startswith(p) for p in FUNCTION_PREFIXES):
                    funcs.add(name)
    return funcs

# ======================= Tag/触发器提取 ==========================
def read_namemap_strings(path: Path) -> List[str]:
    """只读 NameMap/Namemap（大小写容错），提取其中的字符串。"""
    data = load_json(path)
    if not isinstance(data, dict):
        return []
    key = next((k for k in data.keys() if str(k).lower() == "namemap"), None)
    if key is None:
        return []
    nm = data.get(key, [])
    out: List[str] = []
    if isinstance(nm, list):
        for item in nm:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                val = item.get("Name") or item.get("Value") or item.get("String") or item.get("Text")
                if isinstance(val, str):
                    out.append(val)
    return out

def read_strings_from_exports_datablock(path: Path, start_index: int = None) -> List[str]:
    """
    从 Exports[start_index:] 的每个 Export 的 Data 中尽量抽取字符串（Name/Value/String/Text 及其嵌套）。
    默认 start_index 取全局配置 START_EXPORT_INDEX_FOR_TAGS_DETS。
    """
    if start_index is None:
        start_index = START_EXPORT_INDEX_FOR_TAGS_DETS

    data = load_json(path)
    if not isinstance(data, dict):
        return []
    exps = _get_exports(data)
    if not exps:
        return []

    out: List[str] = []
    for exp in exps[start_index:]:
        if not isinstance(exp, dict):
            continue
        data_list = exp.get("Data")
        if not isinstance(data_list, list):
            continue
        for prop in data_list:
            if isinstance(prop, dict):
                for key in ("Name", "Value", "String", "Text"):
                    val = prop.get(key)
                    _gather_strings(val, out, max_per_node=None)
            elif isinstance(prop, str):
                out.append(prop)
    return sorted(set(out))

# ======================= 单文件处理 ==========================
def process_file(path: Path) -> Tuple[Set[str], Set[str], Set[str]]:
    funcs = read_functions_from_exports(path)  # 仍从 Export[2:] 提函数名

    if TAGS_FROM_EXPORTS:
        pool = read_strings_from_exports_datablock(path)  # 现在从 Export[1:]（可配）
    else:
        pool = read_namemap_strings(path)

    tags = {s for s in pool if isinstance(s, str) and s.startswith("JH.Ability.")}
    dets = {s for s in pool if isinstance(s, str) and s.startswith("EAbilitySystemEventType::")}
    return funcs, tags, dets

# ======================= 并行扫描与来源统计 ==========================
def scan_dir(json_dir: Path):
    """并行扫描一个目录，返回 (funcs, tags, dets, src_map)。
       src_map: 名称 -> 该目录内的**前 N 个**来源文件（按字典序最小，去重）。"""
    files = sorted({p.resolve() for p in json_dir.rglob("*.json")})
    funcs_all, tags_all, dets_all = set(), set(), set()
    src_map: Dict[str, List[Path]] = {}

    def record(names: Set[str], src: Path):
        for n in names:
            lst = src_map.get(n)
            if lst is None:
                lst = []
                src_map[n] = lst
            if src not in lst:
                lst.append(src)
            lst.sort(key=lambda p: str(p))
            if len(lst) > MAX_SOURCES_PER_NAME:
                del lst[MAX_SOURCES_PER_NAME:]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(process_file, p): p for p in files}
        for fut in as_completed(futs):
            try:
                fset, tset, dset = fut.result()
                src = futs[fut]
                funcs_all |= fset
                tags_all  |= tset
                dets_all  |= dset
                record(fset, src)
                record(tset, src)
                record(dset, src)
            except Exception:
                pass
    return funcs_all, tags_all, dets_all, src_map

# -------------------- 来源表：读取/保存（JSON/TSV 兼容） --------------------
def load_sources_json(path: Path) -> Dict[str, List[Path]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        if not isinstance(obj, dict):
            return {}
        m: Dict[str, List[Path]] = {}
        for name, arr in obj.items():
            if not isinstance(name, str) or not isinstance(arr, list):
                continue
            uniq = sorted({str(Path(p)) for p in arr if isinstance(p, str) and p}, key=lambda s: s)
            if not uniq:
                continue
            m[name] = [Path(p) for p in uniq[:MAX_SOURCES_PER_NAME]]
        return m
    except FileNotFoundError:
        print(f"未找到来源表：{path}")
        return {}
    except Exception:
        return {}

def load_sources_tsv(path: Path) -> Dict[str, List[Path]]:
    """兼容旧版 TSV：name \t path1 \t path2 ..."""
    m: Dict[str, List[Path]] = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or "\t" not in line:
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                name, *paths = parts
                if not name:
                    continue
                uniq = sorted({str(Path(p)) for p in paths if p}, key=lambda s: s)
                if not uniq:
                    continue
                m[name] = [Path(p) for p in uniq[:MAX_SOURCES_PER_NAME]]
    except FileNotFoundError:
        print(f"未找到来源表：{path}")
        return {}
    return m

def load_sources_file(path: Path) -> Dict[str, List[Path]]:
    if path.suffix.lower() == ".json":
        return load_sources_json(path)
    return load_sources_tsv(path)

def save_sources_json(path: Path, src_map: Dict[str, List[Path]]):
    obj = {name: [str(p) for p in paths] for name, paths in sorted(src_map.items(), key=lambda kv: kv[0])}
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def save_sources_tsv(path: Path, src_map: Dict[str, List[Path]]):
    with path.open("w", encoding="utf-8") as f:
        for name in sorted(src_map.keys()):
            paths = [str(p) for p in src_map[name]]
            f.write("\t".join([name] + paths) + "\n")

def save_sources_file(path: Path, src_map: Dict[str, List[Path]]):
    if path.suffix.lower() == ".json":
        save_sources_json(path, src_map)
    else:
        save_sources_tsv(path, src_map)

# -------------------------- 查询交互 --------------------------
def query_loop(src_map: Dict[str, List[Path]], *, auto_start: bool):
    """
    交互式查询名称来源（可显示多条）。
    auto_start=True  -> 直接进入查询（用于 USE_SAVED_SOURCES=True 的场景）
    auto_start=False -> 先询问是否进入查询（用于完整流程）
    """
    if not auto_start:
        try:
            choice = input("\n是否查询名称来源？输入 1 开启 / 0 结束：").strip()
        except EOFError:
            choice = "0"
        if choice != "1":
            print("跳过查询。")
            return

    # 直接开始查询循环
    while True:
        try:
            q_raw = input("请输入完整名称（回车结束）：").strip()
        except EOFError:
            break
        if not q_raw:
            break
        key = normalize_for_lookup(q_raw)  # 引号净化 + 函数链末段 + 后缀净化
        if not key:
            print("输入为空。")
            continue
        lst = src_map.get(key)
        if lst:
            print("来源（最多前 %d 个）：" % MAX_SOURCES_PER_NAME)
            for i, p in enumerate(lst, 1):
                print(f"  {i}. {p}")
        else:
            print(f"未找到该名称：{key}（请检查是否在 functions/tags/detectors 中）。")

# =========================== 主流程 ============================
def main():
    # ====== 快速模式：仅用已保存的来源表 ======
    if USE_SAVED_SOURCES:
        src_map = load_sources_file(SAVED_SOURCES_PATH)
        if not src_map:
            print("来源表为空或未找到，程序结束。")
            return
        print(f"已载入来源表：{SAVED_SOURCES_PATH}（共 {len(src_map)} 条名称）")
        # 直接进入查询（按你的需求跳过“是否查询”询问）
        query_loop(src_map, auto_start=True)
        print("完成（已保存来源表模式）。")
        return

    # ====== 正常完整流程 ======
    if not ROOT_DIR.exists():
        raise FileNotFoundError(f"找不到主目录：{ROOT_DIR}")
    f_main, t_main, d_main, src_main = scan_dir(ROOT_DIR)

    f_all, t_all, d_all = set(f_main), set(t_main), set(d_main)
    src_map: Dict[str, List[Path]] = dict(src_main)  # 主目录优先

    if SUPP_ENABLED and SUPP_DIRS:
        for sup in SUPP_DIRS:
            if not sup or not Path(sup).exists():
                continue
            f_sup, t_sup, d_sup, src_sup = scan_dir(Path(sup))
            f_all |= f_sup
            t_all |= t_sup
            d_all |= d_sup
            for name, sup_list in src_sup.items():
                base_list = src_map.get(name, [])
                merged = {str(p) for p in base_list}
                merged.update(str(p) for p in sup_list)
                merged = sorted(merged, key=lambda s: s)[:MAX_SOURCES_PER_NAME]
                src_map[name] = [Path(p) for p in merged]

    OUT_FUNCS.write_text("\n".join(sorted(f_all)), encoding="utf-8")
    OUT_TAGS.write_text("\n".join(sorted(t_all)), encoding="utf-8")
    OUT_DETECTORS.write_text("\n".join(sorted(d_all)), encoding="utf-8")

    print(f"完成：主目录函数{len(f_main)} / 标签{len(t_main)} / 检测器{len(d_main)}")
    if SUPP_ENABLED:
        print(f"补充目录合并后：函数{len(f_all)} / 标签{len(t_all)} / 检测器{len(d_all)}")
    print(f"输出目录：{OUT_DIR}")
    print(f"输出文件：\n  {OUT_FUNCS}\n  {OUT_TAGS}\n  {OUT_DETECTORS}")
    print(f"标签/触发器来源：{'Exports[2:]' if TAGS_FROM_EXPORTS else 'NameMap'}")

    # 完整流程下，按旧逻辑：先询问是否进入查询
    query_loop(src_map, auto_start=False)

    # 询问是否保存名称来源
    try:
        save_ans = input("\n保存本次名称来源文件？输入 yes 保存；回车或 no 放弃（不区分大小写）：").strip().lower()
    except EOFError:
        save_ans = ""
    if save_ans in ("yes", "y"):
        save_sources_file(OUT_SOURCES, src_map)
        print(f"已保存：{OUT_SOURCES}（每个名称最多 {MAX_SOURCES_PER_NAME} 条来源）")
    else:
        print("未保存名称来源文件。")

if __name__ == "__main__":
    main()
