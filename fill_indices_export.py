# -*- coding: utf-8 -*-
"""
功能：
1) 规范 Name 序号：把三类结构、BuffIds与 JHExtendSettings内部的 Name 顺序重排为 "0","1","2"...（始终在最前执行）。
2) export[1] 用到的索引写进最后的引用CBSD[]
3) 从 export[2] 起，扫描三类引用结构（ExecutionPhases / If_Req|Then_Act|Else_Act / Requirements）得到：
   - 函数内部引用序号
   - 函数被引用序号
   回写阶段对以下字段均执行“先清空再填”：
     a) 对“引用者”：引用者修改索引
     b) 对“被引用者”修改索引
        OuterIndex：若两依赖并集唯一值=1 → 设为该值；若≥2或0或同时被JH、三类结构之一引用 → 设为 2
4) 仅打印处理报告；最终 JSON 根据开关输出到源文件或 OUTPUT_DIR。
5) 开启索引平移后，先进行索引平移，再执行上述程序。
    索引平移：插入或删除代码段后，填入插入(正数)/删除(负数)的位置，程序自动平移受影响的引用和JHExtendSettings项。
6) 终态修正：
    a) 同时在 JHExtendSettings 且被三类之一引用：确保 SBS/CBC 包含 [2]（追加，不清空），Outindex = 2
    b) 仅在 JHExtendSettings 出现、未被三类之一引用：SBS/CBC 直接置为 [2] ，Outindex = 2；UIData项独立处理。
"""

import json, os, bisect, datetime
from typing import Any, Dict, List, Set, DefaultDict, Tuple, Optional
from collections import defaultdict

# ======== 路径与输出策略 ========
INPUT_JSON = r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH\Wandering_Sword\Content\JH\Skills\JH_D_ZhiRen\JH_D_ZhiRen3\GE_ZhiRen3_BD.json"
REPLACE_SOURCE = True   # True: 覆盖源文件；False: 写到 OUTPUT_DIR
OUTPUT_DIR = r"D:\\Python\\pythonProject1\\Files\\yijian_mod_creat\\outputfiles"
# ===============================

# ======== 目录扫描（默认关闭） ========
SCAN_RECURSIVE = False  # True 时递归目录及子目录；False 只扫单文件
INPUT_DIRS = [
    r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH\Wandering_Sword\Content\JH\Skills\JH_A_ZhongSheng",
]
# ===============================

# ======== 文件名前缀过滤 ========
# 仅处理文件名以这些前缀之一开头的 .json；留空元组 () 表示不过滤
PREFIX_CASE_SENSITIVE = True # True时区分前缀大小写，False时不区分
FILENAME_PREFIXES: Tuple[str, ...] = ("GE")  # 例：("GE",) 或 ("GE","JH")；() 表示全部允许
# ===============================

# ======== 索引平移（默认关闭） ========
ENABLE_SHIFT = True                 # True 开启平移；False 按原逻辑执行
# 正数 p 表示“在第 p 块前插入一块”；负数 -p 表示“删除第 p 块”
# 例：在 1、5、7 前插入且删除第 3 块 -> [1, 5, 7, -3]
SHIFT_POSITIONS: List[int] = []
# =====================================================

# ======== 报告控制 ========
WRITE_FULL_REPORT = False   # 新增：True 时自动写完整报告 TXT；False 时仅控制台预览前 5 条，不再询问 input()
# ==========================

REF_ARRAY_NAMES = {"ExecutionPhases", "If_Req", "Then_Act", "Else_Act", "Requirements"}

# 全局警告收集
WARNINGS: List[str] = []

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def dump_json(obj: Dict[str, Any], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def _has_allowed_prefix(path: str) -> bool:
    if not FILENAME_PREFIXES:
        return True
    name = os.path.basename(path)
    if PREFIX_CASE_SENSITIVE:
        return any(name.startswith(p) for p in FILENAME_PREFIXES)
    else:
        lower = name.lower()
        return any(lower.startswith(p.lower()) for p in FILENAME_PREFIXES)

def _gather_input_files(file_path: str, dir_paths: List[str], recursive: bool) -> List[str]:
    """
    新语义：
      - recursive == False -> 仅处理 file_path（必须为 .json 且满足前缀）
      - recursive == True  -> 忽略 file_path，递归处理 dir_paths 中的所有目录（.json 且满足前缀）
    """
    out: List[str] = []
    seen = set()

    if not recursive:
        # 只跑单文件
        if os.path.isfile(file_path) and file_path.lower().endswith(".json"):
            if _has_allowed_prefix(file_path):
                out.append(file_path)
            else:
                WARNINGS.append(f"[过滤] 文件名不匹配前缀 {FILENAME_PREFIXES}: {file_path}")
        else:
            WARNINGS.append(f"[输入] 单文件无效或不是 .json：{file_path}")
        return out

    # recursive == True：只跑目录（含子目录）
    if not dir_paths:
        WARNINGS.append("[输入] SCAN_RECURSIVE=True 但 INPUT_DIRS 为空，未找到可扫描目录。")
        return out

    for d in dir_paths:
        if not os.path.isdir(d):
            WARNINGS.append(f"[输入] 目录不存在：{d}")
            continue
        for root, _, files in os.walk(d):
            for fn in files:
                if not fn.lower().endswith(".json"):
                    continue
                full = os.path.abspath(os.path.join(root, fn))
                if not _has_allowed_prefix(full):
                    # 不符合前缀过滤，跳过但不报错
                    continue
                if full not in seen:
                    out.append(full); seen.add(full)
    return out

def is_positive_int_no_bool(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x > 0

def dedup_keep_order(nums: List[int]) -> List[int]:
    seen: Set[int] = set(); out: List[int] = []
    for n in nums:
        if n not in seen:
            seen.add(n); out.append(n)
    return out

def ensure_list_field(obj: Dict[str, Any], key: str) -> List[Any]:
    if key not in obj or not isinstance(obj[key], list):
        obj[key] = []
    return obj[key]

# ---------- 文本格式化 ----------
def _fmt_list_brackets(nums: List[int]) -> str:
    return "[" + ", ".join(str(n) for n in nums) + "]" if nums else "[]"

def _center_arrow_line(old_line: str, new_line: str, left_pad: int = 2) -> str:
    width = max(len(old_line), len(new_line))
    pad = " " * left_pad
    arrow_pos = max(0, (width // 2) - 1)
    return pad + (" " * arrow_pos) + "↓"

# ---------- Name 重排（最前置执行） ----------
def _renumber_object_array_names(entry: Dict[str, Any]) -> int:
    """
    若 entry 是 ArrayProperty(ObjectProperty) 且值为对象数组，则把每个元素的 Name 依次重排为 "0","1",...
    返回本数组中发生改名的次数。
    """
    if not (isinstance(entry, dict) and entry.get("$type","").endswith("ArrayPropertyData, UAssetAPI")):
        return 0
    if entry.get("ArrayType") != "ObjectProperty":
        return 0
    vals = entry.get("Value")
    if not isinstance(vals, list):
        return 0
    changed = 0
    for i, objp in enumerate(vals):
        if isinstance(objp, dict):
            old = objp.get("Name")
            new = str(i)
            if old != new:
                objp["Name"] = new
                changed += 1
    return changed

def _renumber_in_jhextend(exp1: Dict[str, Any]) -> Tuple[int, int]:
    """
    在 export[1] 的 JHExtendSettings 下，对内部的 Requirements / Actions（ObjectProperty 数组）执行 Name 重排。
    返回：(被处理数组个数, 改名条数)
    """
    data = exp1.get("Data", [])
    if not isinstance(data, list):
        return 0, 0
    arrs = 0; changed = 0
    for entry in data:
        if not (isinstance(entry, dict)
                and entry.get("$type","").endswith("ArrayPropertyData, UAssetAPI")
                and entry.get("ArrayType") == "StructProperty"
                and entry.get("Name") == "JHExtendSettings"):
            continue
        structs = entry.get("Value", [])
        if not isinstance(structs, list):
            continue
        for s in structs:
            if not (isinstance(s, dict) and s.get("$type","").endswith("StructPropertyData, UAssetAPI")):
                continue
            inner_vals = s.get("Value", [])
            if not isinstance(inner_vals, list):
                continue
            for inner in inner_vals:
                if not (isinstance(inner, dict)
                        and inner.get("$type","").endswith("ArrayPropertyData, UAssetAPI")
                        and inner.get("ArrayType") == "ObjectProperty"
                        and inner.get("Name") in {"Requirements", "Actions"}):
                    continue
                arrs += 1
                changed += _renumber_object_array_names(inner)
    return arrs, changed

def _renumber_in_three_structs(exports: List[Any], start_idx: int = 1) -> Tuple[int, int]:
    """
    对 Exports[start_idx..] 的三类结构（ExecutionPhases / If_Req / Then_Act / Else_Act / Requirements）
    进行 Name 重排。注意 start_idx 默认从 1（即 export[2]）起；若希望包含 export[1] 的三类结构可改成 0。
    返回：(被处理数组个数, 改名条数)
    """
    total = len(exports)
    arrs = 0; changed = 0
    for idx in range(start_idx, total):
        exp = exports[idx]
        data = exp.get("Data", [])
        if not isinstance(data, list):
            continue
        for entry in data:
            if not (isinstance(entry, dict)
                    and entry.get("$type","").endswith("ArrayPropertyData, UAssetAPI")
                    and entry.get("ArrayType") == "ObjectProperty"
                    and entry.get("Name") in REF_ARRAY_NAMES):
                continue
            arrs += 1
            changed += _renumber_object_array_names(entry)
    return arrs, changed

def _renumber_buffids_anywhere(exports: List[Any]) -> Tuple[int, int]:
    """
    在所有 Exports[*].Data[*] 中查找：
      ArrayPropertyData(ArrayType="IntProperty", Name="BuffIds")
    将其 Value 数组内各 IntPropertyData 的 Name 重排为 "0","1","2",...
    返回：(被处理数组个数, 改名条数)
    """
    arrs = 0
    changed = 0
    for exp in exports:
        data = exp.get("Data", [])
        if not isinstance(data, list):
            continue
        for entry in data:
            if not (isinstance(entry, dict)
                    and isinstance(entry.get("$type", ""), str)
                    and entry.get("$type").endswith("ArrayPropertyData, UAssetAPI")
                    and entry.get("ArrayType") == "IntProperty"
                    and entry.get("Name") == "BuffIds"):
                continue
            vals = entry.get("Value")
            if not isinstance(vals, list):
                continue
            arrs += 1
            for i, intp in enumerate(vals):
                if isinstance(intp, dict):
                    old = intp.get("Name")
                    new = str(i)
                    if old != new:
                        intp["Name"] = new
                        changed += 1
    return arrs, changed

# ---------- 平移工具 ----------
def _normalize_shift_positions(raw: List[int]) -> Tuple[List[int], List[int]]:
    inserts = sorted({p for p in raw if isinstance(p, int) and p > 0 and p >= 1})
    deletes = sorted({-p for p in raw if isinstance(p, int) and p < 0 and -p >= 1})
    return inserts, deletes

def _build_shift_func(raw_positions: List[int]):
    if not raw_positions:
        return (lambda v: v, lambda v: False)
    inserts, deletes = _normalize_shift_positions(raw_positions)
    def count_le(arr, x): return bisect.bisect_right(arr, x)
    def count_lt(arr, x): return bisect.bisect_left(arr, x)
    deleted_set = set(deletes)
    def shift(v: int) -> int:
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            return v
        inc = count_le(inserts, v)     # p <= v
        dec = count_lt(deletes, v)     # d <  v（v==d 不减）
        return v + inc - dec
    def hit_deleted(v: int) -> bool:
        return isinstance(v, int) and not isinstance(v, bool) and v in deleted_set
    return shift, hit_deleted

# ---------- export[1]：仅按两类结构收集 ----------
def collect_export1_numbers(exp1: Dict[str, Any]) -> List[int]:
    nums: List[int] = []
    data = exp1.get("Data", [])
    if not isinstance(data, list): return nums
    for entry in data:
        if not isinstance(entry, dict): continue
        t = entry.get("$type", "")
        if t.endswith("ObjectPropertyData, UAssetAPI") and entry.get("Name") == "UIData":
            v = entry.get("Value");
            if is_positive_int_no_bool(v): nums.append(v)
            continue
        if t.endswith("ArrayPropertyData, UAssetAPI") and entry.get("ArrayType")=="StructProperty" and entry.get("Name")=="JHExtendSettings":
            structs = entry.get("Value", []);
            if not isinstance(structs, list): continue
            for s in structs:
                if not (isinstance(s, dict) and s.get("$type","").endswith("StructPropertyData, UAssetAPI")): continue
                inner_vals = s.get("Value", []);
                if not isinstance(inner_vals, list): continue
                for inner in inner_vals:
                    if not isinstance(inner, dict): continue
                    t2 = inner.get("$type","")
                    if t2.endswith("ArrayPropertyData, UAssetAPI") and inner.get("ArrayType")=="ObjectProperty" and inner.get("Name") in {"Requirements","Actions"}:
                        objs = inner.get("Value", [])
                        if not isinstance(objs, list): continue
                        for objp in objs:
                            if isinstance(objp, dict):
                                v2 = objp.get("Value")
                                if is_positive_int_no_bool(v2): nums.append(v2)
    return dedup_keep_order(nums)

def collect_jhext_numbers_only(exp1: Dict[str, Any]) -> List[int]:
    nums: List[int] = []
    data = exp1.get("Data", [])
    if not isinstance(data, list):
        return nums
    for entry in data:
        if not (isinstance(entry, dict)
                and entry.get("$type","").endswith("ArrayPropertyData, UAssetAPI")
                and entry.get("ArrayType") == "StructProperty"
                and entry.get("Name") == "JHExtendSettings"):
            continue
        structs = entry.get("Value", [])
        if not isinstance(structs, list):
            continue
        for s in structs:
            if not (isinstance(s, dict) and s.get("$type","").endswith("StructPropertyData, UAssetAPI")):
                continue
            inner_vals = s.get("Value", [])
            if not isinstance(inner_vals, list):
                continue
            for inner in inner_vals:
                if not (isinstance(inner, dict)
                        and inner.get("$type","").endswith("ArrayPropertyData, UAssetAPI")
                        and inner.get("ArrayType") == "ObjectProperty"
                        and inner.get("Name") in {"Requirements","Actions"}):
                    continue
                objs = inner.get("Value", [])
                if not isinstance(objs, list):
                    continue
                for objp in objs:
                    if isinstance(objp, dict):
                        v = objp.get("Value")
                        if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                            nums.append(v)
    return dedup_keep_order(nums)

def collect_ui_data_target(exp1: Dict[str, Any]) -> Optional[int]:
    """
    从 export[2]（变量名 exp1）读取 UIData 的正整数 Value；没有则返回 None。
    """
    data = exp1.get("Data", [])
    if not isinstance(data, list):
        return None
    for entry in data:
        if not isinstance(entry, dict):
            continue
        t = entry.get("$type", "")
        if t.endswith("ObjectPropertyData, UAssetAPI") and entry.get("Name") == "UIData":
            v = entry.get("Value")
            if is_positive_int_no_bool(v):
                return v
            return None
    return None

# ---------- 三类引用结构提取 ----------
def find_ref_indices_in_export(export_obj: Dict[str, Any]) -> List[int]:
    refs: List[int] = []
    data = export_obj.get("Data", [])
    if not isinstance(data, list): return refs
    for entry in data:
        if not isinstance(entry, dict): continue
        t = entry.get("$type", "")
        if not (isinstance(t, str) and t.endswith("ArrayPropertyData, UAssetAPI")): continue
        if entry.get("ArrayType") != "ObjectProperty": continue
        if entry.get("Name") not in REF_ARRAY_NAMES: continue
        values = entry.get("Value", [])
        if not isinstance(values, list): continue
        for obj_prop in values:
            if isinstance(obj_prop, dict):
                v = obj_prop.get("Value")
                if is_positive_int_no_bool(v): refs.append(v)
    return dedup_keep_order(refs)

# ---------- 平移具体应用 ----------
def _apply_shift_in_jhextend(exp1: Dict[str, Any], shift, hit_deleted) -> Tuple[int, List[int]]:
    data = exp1.get("Data", [])
    if not isinstance(data, list): return 0, []
    changed = 0; dangling: List[int] = []
    for entry in data:
        if not (isinstance(entry, dict) and entry.get("$type","").endswith("ArrayPropertyData, UAssetAPI")): continue
        if entry.get("ArrayType")!="StructProperty" or entry.get("Name")!="JHExtendSettings": continue
        structs = entry.get("Value", []);
        if not isinstance(structs, list): continue
        for s in structs:
            if not (isinstance(s, dict) and s.get("$type","").endswith("StructPropertyData, UAssetAPI")): continue
            inner_vals = s.get("Value", []);
            if not isinstance(inner_vals, list): continue
            for inner in inner_vals:
                if not (isinstance(inner, dict) and inner.get("$type","").endswith("ArrayPropertyData, UAssetAPI")): continue
                if inner.get("ArrayType")!="ObjectProperty" or inner.get("Name") not in {"Requirements","Actions"}: continue
                objs = inner.get("Value", []);
                if not isinstance(objs, list): continue
                for objp in objs:
                    if isinstance(objp, dict) and is_positive_int_no_bool(objp.get("Value")):
                        old = objp["Value"]
                        if hit_deleted(old):
                            # 命中删除：置 0 并警告
                            objp["Value"] = 0
                            dangling.append(old)
                            WARNINGS.append(f"[平移] JHExtendSettings 引用命中已删除位置 {old} → 置0")
                        else:
                            newv = shift(old)
                            if newv != old:
                                objp["Value"] = newv; changed += 1
    return changed, dangling

def _apply_shift_in_ui_data(exp1: Dict[str, Any], shift, hit_deleted) -> Tuple[bool, Optional[int]]:
    """对 exp1.UIData 应用平移；若命中删除则置0并告警。返回(是否改动, 命中删除的旧值或None)"""
    data = exp1.get("Data", [])
    if not isinstance(data, list): return False, None
    for entry in data:
        if not (isinstance(entry, dict) and entry.get("$type","").endswith("ObjectPropertyData, UAssetAPI") and entry.get("Name")=="UIData"):
            continue
        v = entry.get("Value")
        if not is_positive_int_no_bool(v):
            return False, None
        if hit_deleted(v):
            WARNINGS.append(f"[平移] UIData 引用命中已删除位置 {v} → 置0")
            entry["Value"] = 0
            return True, v
        newv = shift(v)
        if newv != v:
            entry["Value"] = newv
            return True, None
        return False, None
    return False, None

def _apply_shift_in_three_structs(exports: List[Any], shift, hit_deleted, start_idx: int = 2) -> Tuple[int, List[Tuple[int,int]]]:
    changed = 0; hits: List[Tuple[int,int]] = []
    total = len(exports)
    for idx in range(start_idx, total):
        exp = exports[idx]; exp_no = idx + 1
        data = exp.get("Data", []);
        if not isinstance(data, list): continue
        for entry in data:
            if not (isinstance(entry, dict) and entry.get("$type","").endswith("ArrayPropertyData, UAssetAPI")): continue
            if entry.get("ArrayType")!="ObjectProperty" or entry.get("Name") not in REF_ARRAY_NAMES: continue
            vals = entry.get("Value", []);
            if not isinstance(vals, list): continue
            for objp in vals:
                if isinstance(objp, dict) and is_positive_int_no_bool(objp.get("Value")):
                    old = objp["Value"]
                    if hit_deleted(old):
                        # 命中删除：置 0 并警告
                        objp["Value"] = 0
                        hits.append((exp_no, old))
                        WARNINGS.append(f"[平移] export#{exp_no} 的三类结构引用命中已删除位置 {old} → 置0")
                    else:
                        newv = shift(old)
                        if newv != old:
                            objp["Value"] = newv; changed += 1
    return changed, hits

# ---------- 主处理 ----------
def process(doc: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """
    返回： (普通日志 lines, 回填块 backfill_blocks)
    """
    lines: List[str] = []
    backfill_blocks: List[str] = []

    exports = doc.get("Exports") or doc.get("exports")
    if not isinstance(exports, list) or len(exports) < 2:
        lines.append("警告：Exports 不足 2 项，未处理。")
        return lines, backfill_blocks

    total = len(exports)

    # === 0) Name 重排（放在一切之前执行，无开关） ===
    jh_cnt, jh_changes = _renumber_in_jhextend(exports[1])
    tri_cnt, tri_changes = _renumber_in_three_structs(exports, start_idx=1)
    lines.append(f"[重排] 规范 Name 序号：JHExtendSettings 数组数={jh_cnt}，改名={jh_changes}；三类结构数组数={tri_cnt}，改名={tri_changes}")
    buf_cnt, buf_changes = _renumber_buffids_anywhere(exports)
    lines.append(f"[重排] BuffIds 数组数={buf_cnt}，改名={buf_changes}")

    # === 1) 可选：索引平移阶段（在重排之后、其他逻辑之前） ===
    if ENABLE_SHIFT and SHIFT_POSITIONS:
        shift, hit_deleted = _build_shift_func(SHIFT_POSITIONS)
        c_ui, _ = _apply_shift_in_ui_data(exports[1], shift, hit_deleted)
        c1, d1 = _apply_shift_in_jhextend(exports[1], shift, hit_deleted)
        c2, d2 = _apply_shift_in_three_structs(exports, shift, hit_deleted, 2)
        inserts, deletes = _normalize_shift_positions(SHIFT_POSITIONS)
        lines.append(f"[平移] 启用。插入位点={inserts}；删除位点={deletes}；UIData改动={int(c_ui)}；JHExtendSettings改动={c1}；三类结构改动={c2}")
        if d1 or d2:
            preview = d2[:10]
            lines.append(f"[提示] 有引用命中被删除位置：JHExt命中={d1}；三类命中前10={preview}（总计{len(d2)}）")
    else:
        lines.append("[平移] 关闭。按原逻辑执行")

    # === 2) 第一遍：汇总 outgoing 与 referenced_by ===
    outgoing_refs: Dict[int, List[int]] = {}
    referenced_by: DefaultDict[int, List[int]] = defaultdict(list)

    for idx in range(2, total):
        export_no = idx + 1
        refs = find_ref_indices_in_export(exports[idx])
        if refs:
            outgoing_refs[export_no] = refs
            for r in refs:
                lst = referenced_by[r]
                if export_no not in lst:
                    lst.append(export_no)

    # === 3) export[1]：先清理正数，再填升序正数（方括号 + 箭头） ===
    exp1 = exports[1]
    jhext_only_set = set(collect_jhext_numbers_only(exp1))  # 仅统计 JHExtendSettings 里的正数
    collected = collect_export1_numbers(exp1)
    collected_sorted = sorted(collected)
    cbsd = ensure_list_field(exp1, "CreateBeforeSerializationDependencies")
    before_cbsd = list(cbsd)
    tail_non_pos = [x for x in cbsd if not is_positive_int_no_bool(x)]
    exp1["CreateBeforeSerializationDependencies"] = list(collected_sorted) + tail_non_pos

    lines.append(f"[export#2] JHExtendSettings 正数(升序)：{_fmt_list_brackets(collected_sorted)}")
    old_line = f"旧: {_fmt_list_brackets(before_cbsd)}"
    new_line = f"新: {_fmt_list_brackets(exp1['CreateBeforeSerializationDependencies'])}"
    lines.append("[export#2] CBSD 清理并覆盖:")
    lines.append("  " + old_line)
    lines.append(_center_arrow_line(old_line, new_line, left_pad=2))
    lines.append("  " + new_line)

    # === 4) 第二遍：按汇总结果覆盖写入 ===
    # 4a) 覆盖所有“引用者”的 CBSD（与回填相同块样式）
    for export_no, refs in outgoing_refs.items():
        exp = exports[export_no - 1]
        before = list(exp.get("CreateBeforeSerializationDependencies", [])) if isinstance(exp.get("CreateBeforeSerializationDependencies"), list) else []
        exp["CreateBeforeSerializationDependencies"] = list(refs)

        block = []
        block.append(f" - 修改引用者 export#{export_no}:")
        block.append(f"     CBSD      {_fmt_list_brackets(before)} -> {_fmt_list_brackets(refs)}")
        lines.append("\n".join(block))

    # 4b) 覆盖所有“被引用者”的 SBS / CBC，并设置 OuterIndex
    for target_no, referrers in referenced_by.items():
        if not (1 <= target_no <= total):
            lines.append(f"  - 警告：被引用目标越界 target_no={target_no}/{total}")
            continue
        tgt = exports[target_no - 1]

        s_before = list(tgt.get("SerializationBeforeSerializationDependencies", [])) if isinstance(
            tgt.get("SerializationBeforeSerializationDependencies"), list) else []
        c_before = list(tgt.get("CreateBeforeCreateDependencies", [])) if isinstance(
            tgt.get("CreateBeforeCreateDependencies"), list) else []
        oi_before = tgt.get("OuterIndex", None)

        ref_after = list(referrers)  # 原始引用者列表（保序去重已在上游完成）

        tgt["SerializationBeforeSerializationDependencies"] = ref_after
        tgt["CreateBeforeCreateDependencies"] = ref_after
        uniq = dedup_keep_order(ref_after)
        tgt["OuterIndex"] = uniq[0] if len(uniq) == 1 else 2

        oi_before_str = f"[{oi_before}]" if oi_before is not None else "[]"
        oi_after_str = f"[{tgt.get('OuterIndex')}]"

        block = []
        block.append(f" - 回填到被引用 export#{target_no}:")
        block.append(
            f"     SBS        {_fmt_list_brackets(s_before)} -> {_fmt_list_brackets(tgt['SerializationBeforeSerializationDependencies'])}")
        block.append(
            f"     CBC        {_fmt_list_brackets(c_before)} -> {_fmt_list_brackets(tgt['CreateBeforeCreateDependencies'])}")
        block.append(f"     OuterIndex {oi_before_str} -> {oi_after_str}")
        backfill_blocks.append('\n'.join(block))

    # 5) 终态修正：若某 export 同时“出现在 JHExtendSettings”且“被三类结构引用” → 确保含2 & OI=2
    hits = sorted(set(referenced_by.keys()) & set(jhext_only_set))
    for tno in hits:
        if not (1 <= tno <= total):
            lines.append(f"  - 警告：命中JHExt但目标越界 target_no={tno}/{total}")
            continue

        tgt = exports[tno - 1]
        s_before = tgt.get("SerializationBeforeSerializationDependencies", [])
        c_before = tgt.get("CreateBeforeCreateDependencies", [])
        s_before = list(s_before) if isinstance(s_before, list) else []
        c_before = list(c_before) if isinstance(c_before, list) else []
        oi_before = tgt.get("OuterIndex", None)

        s_after = list(s_before)
        c_after = list(c_before)
        if 2 not in s_after:
            s_after.append(2)
        if 2 not in c_after:
            c_after.append(2)

        tgt["SerializationBeforeSerializationDependencies"] = s_after
        tgt["CreateBeforeCreateDependencies"] = c_after
        tgt["OuterIndex"] = 2

        if s_after != s_before or c_after != c_before or oi_before != 2:
            oi_before_str = f"[{oi_before}]" if oi_before is not None else "[]"
            block = []
            block.append(f" - 终态修正 export#{tno}（命中JHExt，强制含2 & OI=2）:")
            block.append(f"     SBS        {_fmt_list_brackets(s_before)} -> {_fmt_list_brackets(s_after)}")
            block.append(f"     CBC        {_fmt_list_brackets(c_before)} -> {_fmt_list_brackets(c_after)}")
            block.append(f"     OuterIndex {oi_before_str} -> [2]")
            backfill_blocks.append('\n'.join(block))

    # 5B) 终态修正 UIData：若 UIData 指向的 export 其 SBS/CBC/OuterIndex 不是“只等于2” → 设为[2]/[2]/2
    ui_target = collect_ui_data_target(exp1)  # 可能为 None
    if ui_target is not None and 1 <= ui_target <= total:
        tgt = exports[ui_target - 1]
        s_before = tgt.get("SerializationBeforeSerializationDependencies", [])
        c_before = tgt.get("CreateBeforeCreateDependencies", [])
        s_before = list(s_before) if isinstance(s_before, list) else []
        c_before = list(c_before) if isinstance(c_before, list) else []
        oi_before = tgt.get("OuterIndex", None)

        need_fix = (s_before != [2]) or (c_before != [2]) or (oi_before != 2)
        if need_fix:
            tgt["SerializationBeforeSerializationDependencies"] = [2]
            tgt["CreateBeforeCreateDependencies"] = [2]
            tgt["OuterIndex"] = 2

            oi_before_str = f"[{oi_before}]" if oi_before is not None else "[]"
            block = []
            block.append(f" - 终态修正 export#{ui_target}（UIData 引用，设为[2] & OI=2）:")
            block.append(f"     SBS        {_fmt_list_brackets(s_before)} -> [2]")
            block.append(f"     CBC        {_fmt_list_brackets(c_before)} -> [2]")
            block.append(f"     OuterIndex {oi_before_str} -> [2]")
            backfill_blocks.append('\n'.join(block))

    # 6) JHEx-Only：仅在 JHEx 出现、且未被三类结构引用（并排除已被 UIData 引用的序号）
    refed_set = set(referenced_by.keys())
    ui_exclude = {ui_target} if (ui_target is not None) else set()
    jhex_only_targets = sorted((set(jhext_only_set) - refed_set) - ui_exclude)
    for tno in jhex_only_targets:
        if not (2 <= tno <= total):
            continue
        tgt = exports[tno - 1]

        s_before = tgt.get("SerializationBeforeSerializationDependencies", [])
        c_before = tgt.get("CreateBeforeCreateDependencies", [])
        s_before = list(s_before) if isinstance(s_before, list) else []
        c_before = list(c_before) if isinstance(c_before, list) else []
        oi_before = tgt.get("OuterIndex", None)

        s_after = [2]
        c_after = [2]
        tgt["SerializationBeforeSerializationDependencies"] = s_after
        tgt["CreateBeforeCreateDependencies"] = c_after
        tgt["OuterIndex"] = 2

        oi_before_str = f"[{oi_before}]" if oi_before is not None else "[]"
        block = []
        block.append(f" - 终态修正 export#{tno}（仅JHExt，设为[2] & OI=2）:")
        block.append(f"     SBS        {_fmt_list_brackets(s_before)} -> {_fmt_list_brackets(s_after)}")
        block.append(f"     CBC        {_fmt_list_brackets(c_before)} -> {_fmt_list_brackets(c_after)}")
        block.append(f"     OuterIndex {oi_before_str} -> [2]")
        backfill_blocks.append('\n'.join(block))

    # 7) 弃用统计：从 export#3 起，既不被三类引用、也不在 JHEx、也不是 UIData 指向 → 仅打印
    all_candidates = set(range(3, total + 1))  # 从 export#3 起统计
    deprecated = sorted(all_candidates - refed_set - set(jhext_only_set) - ui_exclude)
    if deprecated:
        lines.append(f"[弃用] 未被三类引用且不在JHExt（从export#3起）：{deprecated}")

    return lines, backfill_blocks

def _maybe_write_full_report(all_lines: List[str], out_dir: str) -> str:
    """把完整报告写到指定目录 TXT（与打印同格式），返回文件路径；失败返回空串。"""
    try:
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(out_dir, f"report_{ts}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(all_lines))
        return path
    except Exception as e:
        print(f"[写报告失败] {e}")
        return ""

def main():
    inputs = _gather_input_files(INPUT_JSON, INPUT_DIRS, SCAN_RECURSIVE)
    if not inputs:
        print(f"[错误] 未找到可处理的 JSON。"
              f"{'请检查 INPUT_DIRS（递归目录模式）' if SCAN_RECURSIVE else '请检查 INPUT_JSON（单文件模式）'}")
        return

    total_files = len(inputs)
    print(f"[提示] 模式={'目录递归' if SCAN_RECURSIVE else '单文件'}，本次处理 {total_files} 个文件。")

    for i, in_path in enumerate(inputs, 1):
        WARNINGS.clear()  # 每个文件独立告警
        print("\n" + "=" * 80)
        print(f"[{i}/{total_files}] 处理：{in_path}")

        doc = load_json(in_path)
        lines, backfills = process(doc)

        # 预组合完整报告文本（用于可选落盘；格式与打印一致）
        full_report = []
        full_report.append("=== 处理报告 ===")
        full_report.extend(lines)
        if backfills:
            full_report.append(f"[回填统计] 共 {len(backfills)} 个")
            full_report.extend(backfills)

        # 控制台打印（与 full_report 同格式）
        print("=== 处理报告 ===")
        for ln in lines:
            print(ln)

        if backfills:
            print(f"[回填统计] 共 {len(backfills)} 个（仅显示前 5 个）")
            preview = backfills[:5]
            for blk in preview:
                print(blk)
        else:
            print("[回填统计] 0 个")

        # 警告汇总
        print("\n=== 警告汇总 ===")
        if WARNINGS:
            for w in WARNINGS:
                print(w)
        else:
            print("无警告")

        # 写入完整报告（如果开启） —— 一文件一报告
        if WRITE_FULL_REPORT:
            all_lines = []
            all_lines.extend(full_report)
            all_lines.append("\n=== 警告汇总 ===")
            if WARNINGS:
                all_lines.extend(WARNINGS)
            else:
                all_lines.append("无警告")
            path = _maybe_write_full_report(all_lines, OUTPUT_DIR)
            if path:
                print(f"\n[已写入完整报告] {path}")
            else:
                print("\n[写入失败] 未生成完整报告文件")

        # 输出 JSON：由开关控制路径（对每个输入分别落盘）
        out_path = in_path if REPLACE_SOURCE else os.path.join(OUTPUT_DIR, os.path.basename(in_path))
        dump_json(doc, out_path)
        print(f"\n已写入：{out_path}")

    print("\n[完成] 所有文件已处理。")

if __name__ == "__main__":
    main()
