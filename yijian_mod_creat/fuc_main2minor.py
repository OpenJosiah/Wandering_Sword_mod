# -*- coding: utf-8 -*-
"""
功能（当前版本）：
1) 扫描主→次函数“次要函数结构块”(dict)
2) 功能等价去重（忽略 Value 等易变字段；策略：keep_first / keep_last / empty_value）
3) 学习“常用次序记忆”（统计相对先后），可选地累计到 fc_order_memory.json（由 ENABLE_MEMORY 控制）
4) 导出主→次“完整模板”：fc_main2minor.json
   - 在扫描过程中为每个主函数“自主拷贝”其遇到的第一个 NormalExport 作为模板
   - 仅替换该模板的 Data 为“记忆排序后的全部次要函数块”（其它字段原样保留）
5) 导出主函数对应的 Imports（含 Default 库）：fc_main_imports.json
"""

import os
import re
import json
import sys
import copy
from typing import Any, Dict, List, Set, Iterable, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# ======================================================================
#                                配置区（自定义优先，聚类排布）
# ======================================================================

# ——【交互/记忆 开关】——————————————————————————————————————
ENABLE_MEMORY       = False   # True：累计并保存记忆顺序；False：仅用本次扫描的顺序统计，不写入记忆文件
ENABLE_INTERACTIVE  = True   # True：运行结束后进入交互；False：不进入交互
INTERACTIVE_GUI     = True   # True：运行结束进入窗口交互（需要设置ENABLE_INTERACTIVE  = True）；False：命令行交互
DO_SCAN_AND_EXPORT  = False   # True：扫描+导出；False：直接进入交互环节。

# ——【输入源】———————————————————————————————————————————————
SEARCH_DIRS = [
    r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Skills",
    r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Core",
    r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH",
    r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_1\Wandering_Sword\Content\JH\Skills",
]
FILENAME_PREFIXES = ["GE"]     # 扫描文件名前缀（如 "GE*.json"）
FILE_EXT = ".json"             # 文件扩展名筛选
MAIN_FUNCTIONS_TXT = r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles\functions.txt"  # 主函数清单

# ——【输出与持久化】———————————————————————————————————————————
OUTPUT_TO_SPECIFIED_DIR = True # True：输出在指定目录；False：脚本目录
SPECIFIED_OUTPUT_DIR = r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles"
OUT_JSON_NAME      = "fc_main2minor.json"        # 主→次：完整模板（每主函数恰好一个）
OUT_CACHE_NAME     = "fc_scan_cache.json"        # 扫描缓存（可选）
ORDER_MEMORY_NAME  = "fc_order_memory.json"      # 顺序记忆（可选）
OUT_IMPORTS_NAME   = "fc_main_imports.json"      # 主/Default Imports

# ——【运行模式 / 性能】———————————————————————————————————————
USE_FILE_CACHE = False           # True: 启用文件级缓存（未变更文件复用）
MAX_WORKERS = None               # 并行线程数（None=自动）
DEDUP_STRATEGY = 'keep_first'    # keep_first / keep_last / empty_value

# ——【内部常量】———————————————————————————————————————————————
SOFT_OBJ_TYPE    = "UAssetAPI.PropertyTypes.Objects.SoftObjectPropertyData, UAssetAPI"
STRUCT_PROP_TYPE = "UAssetAPI.PropertyTypes.Structs.StructPropertyData, UAssetAPI"
_ID_KEYS = ("$type", "Name", "EnumType", "StructType", "ArrayType", "InnerType")
_SEP = "␟"

# ======================================================================
# 工具函数
# ======================================================================

def get_output_dir() -> str:
    if OUTPUT_TO_SPECIFIED_DIR:
        os.makedirs(SPECIFIED_OUTPUT_DIR, exist_ok=True)
        return SPECIFIED_OUTPUT_DIR
    return os.path.dirname(os.path.abspath(sys.argv[0]))

def read_main_functions(txt_path: str) -> List[str]:
    mains: List[str] = []
    with open(txt_path, "r", encoding="utf-8") as f:
        for line in f:
            s = sanitize(line.strip())
            if s and not s.startswith("#"):
                mains.append(purify_func_name(s))
    return mains

def file_matches_prefixes(filename: str, prefixes: Iterable[str]) -> bool:
    base = os.path.basename(filename)
    return any(base.startswith(pfx) for pfx in prefixes)

def iter_target_json_files(root_dirs: List[str]) -> List[str]:
    """按目录顺序遍历，保持“遇到顺序”稳定。"""
    seen: Set[str] = set()
    files: List[str] = []
    for root in root_dirs:
        if not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if fn.lower().endswith(FILE_EXT) and file_matches_prefixes(fn, FILENAME_PREFIXES):
                    fp = os.path.normpath(os.path.join(dirpath, fn))
                    if fp not in seen:
                        seen.add(fp)
                        files.append(fp)
    return files

def final_segment(name: str) -> str:
    if not isinstance(name, str):
        return ""
    parts = name.split(".")
    return parts[-1] if parts else name

def purify_func_name(name: str) -> str:
    seg = final_segment(name)
    i = len(seg)
    while True:
        j = seg.rfind("_", 0, i)
        if j == -1:
            break
        tail = seg[j+1:i]
        if tail.isdigit():
            i = j
        else:
            break
    return seg[:i]

QUOTE_RE = re.compile(r'^[\s\'"\u201c\u201d]+|[\s\'"\u201c\u201d]+$')
def sanitize(s: str) -> str:
    if not isinstance(s, str):
        return ""
    return QUOTE_RE.sub("", s)

def load_json_loose(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return json.loads(f.read())
        except Exception:
            return None

def extract_exports(obj: Any) -> List[dict]:
    """提取 Exports 列表。"""
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict) and "ObjectName" in x]
    if isinstance(obj, dict):
        for key in ("Exports", "exports", "Export", "export"):
            v = obj.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict) and "ObjectName" in v[0]:
                return v
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "ObjectName" in v[0]:
                return v
    return []

def extract_imports(obj: Any) -> List[dict]:
    """提取 Imports 列表。"""
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict) and x.get("$type", "").endswith("UAssetAPI.Import, UAssetAPI")]
    if isinstance(obj, dict):
        for key in ("Imports", "imports", "Import", "import"):
            v = obj.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                if any("ClassName" in d or "ObjectName" in d for d in v):
                    return v
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                if any("ClassName" in d or "ObjectName" in d for d in v):
                    return v
    return []

def _functional_key(item: dict) -> tuple:
    if not isinstance(item, dict):
        return ("<non-dict>",)
    return tuple(item.get(k) for k in _ID_KEYS)

def fk_to_str(fk: tuple) -> str:
    return _SEP.join("" if x is None else str(x) for x in fk)

def str_to_fk(s: str) -> tuple:
    parts = s.split(_SEP)
    while len(parts) < len(_ID_KEYS):
        parts.append("")
    return tuple(None if p == "" else p for p in parts[:len(_ID_KEYS)])

def _empty_value_for(item: dict):
    t = (item.get("$type") or "")
    if "FloatPropertyData" in t: return 0.0
    if "IntPropertyData"   in t: return 0
    if "BoolPropertyData"  in t: return False
    if "EnumPropertyData"  in t: return ""
    return None

def _apply_empty_value(blk: dict) -> dict:
    b = blk.copy()
    if "Value" in b:
        b["Value"] = _empty_value_for(b)
    return b

# ======================================================================
# 层1：单个 Export.Data 内去重 + 记录首次出现顺序
# ======================================================================

def collect_minor_structs_from_data(data_list: Any) -> Tuple[List[dict], List[tuple]]:
    if not isinstance(data_list, list):
        return ([], [])
    seen = set()
    kept: List[dict] = []
    order_seq: List[tuple] = []
    pos_by_key: Dict[tuple, int] = {}
    for item in data_list:
        if not isinstance(item, dict):
            continue
        k = _functional_key(item)
        if k not in seen:
            seen.add(k)
            order_seq.append(k)
            new_item = item.copy()
            if DEDUP_STRATEGY == 'empty_value' and "Value" in new_item:
                new_item["Value"] = _empty_value_for(new_item)
            kept.append(new_item)
            pos_by_key[k] = len(kept) - 1
        else:
            if DEDUP_STRATEGY == 'keep_last':
                kept[pos_by_key[k]] = item.copy()
    return (kept, order_seq)

# ======================================================================
# 顺序记忆（可选）
# ======================================================================

def update_order_stats(stats: Dict[str, Dict[str, int]], seq: List[tuple]) -> None:
    sseq = [fk_to_str(k) for k in seq]
    n = len(sseq)
    for i in range(n):
        ki = sseq[i]
        row = stats.setdefault(ki, {})
        for j in range(i + 1, n):
            kj = sseq[j]
            row[kj] = row.get(kj, 0) + 1

def derive_order_from_stats(stats: Dict[str, Dict[str, int]]) -> List[str]:
    keys = list(stats.keys())
    for a in keys:
        for b in keys:
            if a == b: continue
            stats.setdefault(a, {}).setdefault(b, 0)
            stats.setdefault(b, {}).setdefault(a, 0)
    copeland: Dict[str, int] = {}
    avg_rank: Dict[str, float] = {}
    for a in keys:
        wins = losses = 0
        rank_sum = total = 0
        for b in keys:
            if a == b: continue
            wa = stats[a].get(b, 0)
            wb = stats[b].get(a, 0)
            if wa > wb: wins += 1
            elif wa < wb: losses += 1
            if wa + wb > 0:
                rank_sum += (wb / (wa + wb))
                total += 1
        copeland[a] = wins - losses
        avg_rank[a] = (rank_sum / total) if total > 0 else 0.5
    keys.sort(key=lambda k: (-copeland[k], avg_rank[k], k))
    return keys

def load_json(path: str) -> Dict[str, Any]:
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ======================================================================
# 单文件解析（返回：去重块、首次顺序、以及“首个模板”）
# ======================================================================

def parse_file_build_index(path: str) -> Dict[str, Any]:
    """
    返回：{ pure_fn: { "blocks": {key_str: block},
                      "orders": [ [key_str,...], ... ],
                      "first_template": dict or None } }
    - first_template：该文件内该主函数“遇到的第一个 NormalExport”（深拷贝）
    """
    obj = load_json_loose(path)
    if obj is None:
        return {}
    exports = extract_exports(obj)
    if not exports:
        return {}

    per_fn_blocks: Dict[str, Dict[str, dict]] = {}
    per_fn_orders: Dict[str, List[List[str]]] = {}
    per_fn_first_tpl: Dict[str, dict] = {}

    for ex in exports:
        pure = purify_func_name(ex.get("ObjectName", ""))
        if not pure:
            continue

        # 先记录首个模板（只要纯净名匹配、且还没存过）
        if pure not in per_fn_first_tpl:
            per_fn_first_tpl[pure] = copy.deepcopy(ex)

        # 采集 Data 的“次函数块”
        blocks, order_seq = collect_minor_structs_from_data(ex.get("Data"))
        if blocks:
            sseq = [fk_to_str(k) for k in order_seq]
            if sseq:
                per_fn_orders.setdefault(pure, []).append(sseq)
            bucket = per_fn_blocks.setdefault(pure, {})
            for blk in blocks:
                k = fk_to_str(_functional_key(blk))
                if k in bucket:
                    if DEDUP_STRATEGY == 'keep_last':
                        bucket[k] = blk
                else:
                    bucket[k] = blk if DEDUP_STRATEGY != 'empty_value' else _apply_empty_value(blk)

    out = {}
    for pure_fn in set(list(per_fn_blocks.keys()) + list(per_fn_orders.keys()) + list(per_fn_first_tpl.keys())):
        out[pure_fn] = {
            "blocks": per_fn_blocks.get(pure_fn, {}),
            "orders": per_fn_orders.get(pure_fn, []),
            "first_template": per_fn_first_tpl.get(pure_fn)  # 可能为 None
        }
    return out

# ======================================================================
# Imports 聚合
# ======================================================================

def collect_main_imports(files: List[str], main_set: Set[str]) -> Dict[str, List[dict]]:
    result: Dict[str, List[dict]] = {m: [] for m in main_set}
    seen_by_main: Dict[str, Set[str]] = {m: set() for m in main_set}
    for fp in files:
        obj = load_json_loose(fp)
        if obj is None:
            continue
        imports = extract_imports(obj)
        if not imports:
            continue
        idx: Dict[str, dict] = {}
        for imp in imports:
            if isinstance(imp, dict) and "ObjectName" in imp:
                idx.setdefault(imp["ObjectName"], imp)
        for m in main_set:
            for want in (m, f"Default__{m}"):
                imp = idx.get(want)
                if not imp:
                    continue
                seen = seen_by_main[m]
                if want in seen:
                    continue
                result[m].append(imp)
                seen.add(want)
    return result

# ======================================================================
# 交互（命令行 / GUI）
# ======================================================================

def interactive_cli(mapping: Dict[str, Any]):
    """命令行交互：打印模板本体（不带外层主函数键）。"""
    print("【交互模式-命令行】回车退出。")
    while True:
        try:
            q = input("主函数：").strip()
        except EOFError:
            break
        if not q:
            break
        key = purify_func_name(sanitize(q))
        vals = mapping.get(key)
        if isinstance(vals, dict):
            print(json.dumps(vals, ensure_ascii=False, indent=2))
        else:
            print("未找到。")

def interactive_gui(mapping: Dict[str, Any]):
    """Tkinter 窗口：可下拉选择/模糊搜索主函数，显示模板，清空。"""
    import tkinter as tk
    from tkinter import scrolledtext, ttk

    # ——— 读取主函数清单（作为候选） ———
    try:
        candidates = read_main_functions(MAIN_FUNCTIONS_TXT)
    except Exception:
        candidates = []
    # 兜底：把当前映射里的键也加入候选
    if isinstance(mapping, dict):
        for k in mapping.keys():
            if k not in candidates:
                candidates.append(k)
    candidates = sorted(set(candidates), key=str.lower)

    # ——— 窗口与样式 ———
    root = tk.Tk()
    root.title("主→次 模板查询")
    root.geometry("1100x720")  # 更大一点
    try:
        root.iconbitmap(default='')  # 可按需设置图标
    except Exception:
        pass

    # ttk 样式简单美化
    style = ttk.Style()
    try:
        style.theme_use('clam')
    except Exception:
        pass
    style.configure("TLabel",  font=("Microsoft YaHei UI", 10))
    style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=4)
    style.configure("TCombobox", font=("Consolas", 11))
    style.configure("TEntry", font=("Consolas", 11))

    frm_top = ttk.Frame(root)
    frm_top.pack(fill="x", padx=10, pady=8)

    ttk.Label(frm_top, text="主函数：").pack(side="left")

    var_fn = tk.StringVar()

    # ——— 可下拉 + 可输入的组合框（带右侧“>”下拉箭头） ———
    combo = ttk.Combobox(frm_top, textvariable=var_fn, values=candidates, width=60)  # 更宽
    combo.pack(side="left", padx=8)
    # combo.state(["!disabled", "readonly"])  # 只读下拉；若想可自由输入，注释此行

    # 若你想“既能自由输入又能选择”，用下面两行替换上面的 state 设置：
    combo.configure(state="normal")               # 允许输入
    combo['values'] = candidates

    # 搜索按钮 / 清空按钮
    def do_query():
        key = purify_func_name(sanitize(var_fn.get()))
        vals = mapping.get(key)
        txt.config(state="normal")
        txt.delete("1.0", tk.END)
        if isinstance(vals, dict):
            txt.insert(tk.END, json.dumps(vals, ensure_ascii=False, indent=2))
        else:
            txt.insert(tk.END, "未找到。")
        txt.config(state="normal")  # 保持可复制

    def do_clear():
        var_fn.set("")
        # 恢复全量候选
        if combo.cget("state") != "readonly":
            combo['values'] = candidates
        txt.config(state="normal")
        txt.delete("1.0", tk.END)
        txt.config(state="normal")

    ttk.Button(frm_top, text="查询", command=do_query).pack(side="left", padx=6)
    ttk.Button(frm_top, text="清空", command=do_clear).pack(side="left", padx=6)

    # ——— 模糊过滤：在可输入模式下启用（默认 readonly 不会触发过滤） ———
    def on_key_release(event=None):
        # 只有在可输入模式下才做动态过滤
        if combo.cget("state") == "readonly":
            return
        text = var_fn.get().strip().lower()
        if not text:
            combo['values'] = candidates
            return
        # 包含式模糊匹配
        filtered = [c for c in candidates if text in c.lower()]
        combo['values'] = filtered if filtered else candidates

    combo.bind("<KeyRelease>", on_key_release)
    combo.bind("<Return>", lambda e: do_query())

    # 文本展示区（等宽字体、可滚动）
    txt = scrolledtext.ScrolledText(root, wrap="none", font=("Consolas", 11))
    txt.pack(expand=True, fill="both", padx=10, pady=10)

    # 初始焦点
    combo.focus_set()
    root.mainloop()

# ======================================================================
# 主流程
# ======================================================================

def main():
    out_dir = get_output_dir()
    cache_path = os.path.join(out_dir, OUT_CACHE_NAME)
    order_mem_path = os.path.join(out_dir, ORDER_MEMORY_NAME)

    final_full_templates: Dict[str, dict] = {}

    if DO_SCAN_AND_EXPORT:
        # ——加载主函数清单——
        if not os.path.isfile(MAIN_FUNCTIONS_TXT):
            print(f"未找到主函数清单：{MAIN_FUNCTIONS_TXT}")
            sys.exit(1)
        mains = read_main_functions(MAIN_FUNCTIONS_TXT)
        if not mains:
            print("主函数清单为空。")
            sys.exit(1)
        main_set: Set[str] = set(mains)

        # ——收集文件（保持遇到顺序）——
        files = iter_target_json_files(SEARCH_DIRS)
        if not files:
            print("未找到匹配的 JSON 文件。")
            sys.exit(0)

        # ——缓存与签名（可选）——
        cache = load_json(cache_path) if USE_FILE_CACHE else {}
        cache_index: Dict[str, Any] = cache.get("index", {}) if isinstance(cache, dict) else {}
        cache_sig: Dict[str, Any] = cache.get("signatures", {}) if isinstance(cache, dict) else {}

        to_parse: List[str] = []
        new_signatures: Dict[str, List[float]] = {}
        for fp in files:
            st = os.stat(fp); sig = [st.st_size, st.st_mtime]
            new_signatures[fp] = sig
            if not USE_FILE_CACHE or cache_sig.get(fp) != sig:
                to_parse.append(fp)

        # ——解析（并行）——
        perfile_index: Dict[str, Dict[str, Any]] = {}
        if to_parse:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                futs = {ex.submit(parse_file_build_index, fp): fp for fp in to_parse}
                for fut in as_completed(futs):
                    fp = futs[fut]
                    try:
                        perfile_index[fp] = fut.result() or {}
                    except Exception:
                        perfile_index[fp] = {}
        if USE_FILE_CACHE:
            for fp in files:
                if fp not in perfile_index:
                    old = cache_index.get(fp)
                    if isinstance(old, dict):
                        perfile_index[fp] = old

        # ——顺序统计：本次与历史（由 ENABLE_MEMORY 控制是否累计保存）——
        order_memory = load_json(order_mem_path) if ENABLE_MEMORY else {}
        total_pairs_before = sum(sum(row.values()) for v in order_memory.values() for row in v.get("pairwise", {}).values()) if ENABLE_MEMORY else 0

        global_key2blk: Dict[str, Dict[str, dict]] = {m: {} for m in main_set}
        pairwise_stats_now: Dict[str, Dict[str, Dict[str, int]]] = {}
        global_first_template: Dict[str, dict] = {}

        for fp in files:
            idx = perfile_index.get(fp, {})
            if not isinstance(idx, dict):
                continue
            for pure_fn, obj in idx.items():
                if pure_fn not in main_set:
                    continue

                # 1) 记录首个模板
                tpl = obj.get("first_template")
                if tpl and (pure_fn not in global_first_template):
                    global_first_template[pure_fn] = copy.deepcopy(tpl)

                # 2) 合并去重块
                blocks_dict = obj.get("blocks", {})
                bucket = global_key2blk[pure_fn]
                for k_str, blk in blocks_dict.items():
                    if k_str in bucket:
                        if DEDUP_STRATEGY == 'keep_last':
                            bucket[k_str] = blk
                    else:
                        bucket[k_str] = blk

                # 3) 本次顺序统计
                orders_list = obj.get("orders", [])
                stats = pairwise_stats_now.setdefault(pure_fn, {})
                for sseq in orders_list:
                    filtered = [k for k in sseq if k in bucket]
                    if len(filtered) >= 2:
                        update_order_stats(stats, [str_to_fk(k) for k in filtered])

        # ——合并历史记忆（可选）——
        pairwise_stats_final: Dict[str, Dict[str, int]] = {}
        for pure_fn, stats_now in pairwise_stats_now.items():
            if ENABLE_MEMORY:
                mem_entry = order_memory.get(pure_fn, {})
                stats_mem = mem_entry.get("pairwise", {})
                # 累计保存
                for a_str, row in stats_now.items():
                    grow = stats_mem.setdefault(a_str, {})
                    for b_str, cnt in row.items():
                        grow[b_str] = grow.get(b_str, 0) + cnt
                order_memory[pure_fn] = {"pairwise": stats_mem}
                pairwise_stats_final[pure_fn] = stats_mem
            else:
                # 不保存到文件，只使用“本次”的统计排序
                merged: Dict[str, Dict[str, int]] = {}
                for a_str, row in stats_now.items():
                    merged[a_str] = dict(row)
                pairwise_stats_final[pure_fn] = merged

        # ——推导记忆顺序并产出“仅结构块”的映射（中间产物）——
        final_map_blocks: Dict[str, List[dict]] = {}
        applied_items = 0
        for pure_fn, bucket in global_key2blk.items():
            if not bucket:
                final_map_blocks[pure_fn] = []
                continue
            stats_final = pairwise_stats_final.get(pure_fn, {})
            # 确保当前键都在统计里
            for k in bucket.keys():
                stats_final.setdefault(k, {})
            order_list = derive_order_from_stats(stats_final) if stats_final else []
            if ENABLE_MEMORY:
                # 仅在记忆开启时记录模板信息（非必要）
                order_memory.setdefault(pure_fn, {})["order"] = order_list
            order_pos = {k: i for i, k in enumerate(order_list)}
            def sort_key(k: str) -> Tuple[int, str]:
                return (order_pos.get(k, 10**9), k)
            sorted_keys = sorted(bucket.keys(), key=sort_key)
            final_map_blocks[pure_fn] = [bucket[k] for k in sorted_keys]
            applied_items += len(sorted_keys)

        # ——导出 Imports——
        imports_map = collect_main_imports(files, main_set)
        out_imports_path = os.path.join(get_output_dir(), OUT_IMPORTS_NAME)
        save_json(out_imports_path, imports_map)

        # ——导出：完整模板（每主函数一个；仅改 Data）——
        for pure_fn, minors in final_map_blocks.items():
            tpl = global_first_template.get(pure_fn)
            if not tpl:
                continue
            tpl_copy = copy.deepcopy(tpl)
            tpl_copy["Data"] = minors[:]   # 仅替换 Data；其它字段保持不变
            final_full_templates[pure_fn] = tpl_copy

        full_out_path = os.path.join(get_output_dir(), OUT_JSON_NAME)
        save_json(full_out_path, final_full_templates)

        # ——缓存与记忆落盘（记忆可选）——
        if USE_FILE_CACHE:
            save_json(cache_path, {"index": perfile_index, "signatures": new_signatures, "version": 7})
        if ENABLE_MEMORY:
            save_json(order_mem_path, order_memory)
            total_pairs_after = sum(sum(row.values()) for v in order_memory.values() for row in v.get("pairwise", {}).values())
        else:
            total_pairs_after = 0

        print(f"[FULL] 已导出完整模板：{full_out_path}")
        print(f"[Imports] 已导出主/Default库：{out_imports_path}")
        if ENABLE_MEMORY:
            print(f"[记忆] 历史对偶计数变化：{total_pairs_after}")

    # 交互：从最新内存结果或磁盘文件读取
    if ENABLE_INTERACTIVE:
        if not final_full_templates:
            # 没有本次扫描结果，则尝试读磁盘
            full_out_path = os.path.join(get_output_dir(), OUT_JSON_NAME)
            if os.path.isfile(full_out_path):
                final_full_templates = load_json(full_out_path)
            else:
                print(f"[交互] 未找到：{full_out_path}，无法进入交互。")
                return
        if INTERACTIVE_GUI:
            interactive_gui(final_full_templates)
        else:
            interactive_cli(final_full_templates)

# ——与上方一致的 save/load（保持风格）———————————

def load_json(path: str) -> Dict[str, Any]:
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 兼容性的正则编译
import os as _os, re as _re
if 'QUOTE_RE' not in globals():
    QUOTE_RE = _re.compile(r'^[\s\'"\u201c\u201d]+|[\s\'"\u201c\u201d]+$')

if __name__ == "__main__":
    main()
