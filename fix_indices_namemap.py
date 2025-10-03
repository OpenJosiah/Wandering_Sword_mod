# -*- coding: utf-8 -*-
"""
功能：
1) 扫描并补齐 Imports：依据当前文件 Exports[3:] 用到的主函数，
   从 fc_main_imports.json 追加缺失的“主库→Default 库”（按顺序）。
2) 统一“目标函数 Import”的 OuterIndex 指向 /Script/JH 包（若存在）。
3) 对 Exports[3:] 做同名标准化重命名（base_0..n-1）。
4) 修正 Exports[3:]：ClassIndex、TemplateIndex、SerializationBeforeCreateDependencies 指向正确的 Import 负索引。
5) 最后一步再补齐 NameMap：
   - 追加所有 Import 的 (ObjectName / ClassPackage / ClassName)；
   - 同时对照 namemap_all.txt，将“总表里有、文件中出现但 NameMap 没有”的条目补到末尾。
6) 若选择写回源文件且启用备份，则在写回前生成原文件 .bak。
7) 文件夹功能：
    A) 目录遍历（可配多个根目录，递归子目录）。
    B) 仅处理指定前缀的 .json 文件（可配多个前缀；空则不限制）。
    C) 开关：ENABLE_DIR_TRAVERSAL=True 时仅目录模式；False 时保持原单文件模式。
"""

import json
import os
import re
from copy import deepcopy
from typing import Any, Dict, List, Tuple, Optional, Set, Union, Iterable
from pathlib import Path

# ======================================================================
# 配置
# ======================================================================

# ---- 单文件模式（当 ENABLE_DIR_TRAVERSAL=False 时生效，保持原逻辑）----
INPUT_PATH = r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH\Wandering_Sword\Content\JH\Skills\JH_A_ZhongSheng\JH_A_RenSheng\GE_RenSheng_BD.json"

# ---- 目录遍历模式（当 ENABLE_DIR_TRAVERSAL=True 时生效）----
# 开关：True=只遍历目录；False=只处理单文件
ENABLE_DIR_TRAVERSAL: bool = False

# 可配置多个根目录；会递归子目录
SCAN_DIRS: List[str] = [
    r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH\Wandering_Sword\Content\JH\Skills\JH_A_ZhongSheng",
]

# 仅处理文件名以这些前缀开头的 .json；例如 ("GE",) 或 ("GE","JH")
FILENAME_PREFIXES: Tuple[str, ...] = ("GE",)    # 留空 tuple() 或 [] 表示不过滤前缀（处理所有 .json）

# ---- 输出控制（对单文件与遍历均适用）----
WRITE_TO_SOURCE = True                     # True: 覆盖源文件；False: 输出到 FIXED_OUTPUT_DIR
MAKE_BACKUP = False                        # 备份.bak文件，仅在 WRITE_TO_SOURCE=True 时有效
FIXED_OUTPUT_DIR = Path(r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles")

# 上游生成的“主函数→imports”映射
MAIN_IMPORTS_MAP_PATH = r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles\fc_main_imports.json"

# NameMap 总表（文本，每行一个条目）
NAMEMAP_TXT = Path(r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles\namemap_all.txt")

# 仅用于 Import.OuterIndex 归一化 的目标函数名前缀
TARGET_PREFIXES = ("JHGEExtAct_", "JHExecutionPhase_", "JHGEExtReq_")

# ======================================================================
# 基本 I/O
# ======================================================================

def load_json(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到输入文件：{path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(obj: Any, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# ======================================================================
# Imports / Exports 解析
# ======================================================================

def get_or_create_imports_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """返回顶层 Imports 列表；若无则创建空列表并挂在 'Imports'。"""
    imports = data.get("Imports")
    if not isinstance(imports, list):
        imports = []
        data["Imports"] = imports
    return imports

def get_import_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """只读获取 Imports；若无则兜底扫描。"""
    imports = data.get("Imports")
    if isinstance(imports, list):
        return [x for x in imports if isinstance(x, dict)]
    res: List[Dict[str, Any]] = []
    for v in data.values():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and str(item.get("$type", "")).startswith("UAssetAPI.Import"):
                    res.append(item)
    return res

def build_import_index_from_list(import_objs: List[Dict[str, Any]]) -> Dict[str, int]:
    """由 import 列表建立 名称->负索引 映射：第0个->-1，第1个->-2 ..."""
    mapping: Dict[str, int] = {}
    for i, imp in enumerate(import_objs):
        name = imp.get("ObjectName")
        if isinstance(name, str) and name:
            mapping[name] = -(i + 1)
    return mapping

def get_exports_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    exports = data.get("Exports")
    if isinstance(exports, list):
        return [x for x in exports if isinstance(x, dict)]
    res: List[Dict[str, Any]] = []
    for v in data.values():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and str(item.get("$type", "")).startswith("UAssetAPI.ExportTypes.NormalExport"):
                    res.append(item)
    return res

def base_from_object_name(obj_name: str) -> str:
    """去掉末尾 '_数字' 后缀；不动中间下划线。"""
    m = re.match(r"^(.*?)(?:_\d+)?$", obj_name)
    return m.group(1) if m else obj_name

def dedupe_export_object_names(exports: List[Dict[str, Any]]) -> List[Tuple[int, str, str]]:
    """
    若某“基名”组内存在完全相同的 ObjectName，统一重命名为 base_0..n-1；
    返回改名记录 (index, old, new)（index 为切片 exports 的相对索引）。
    """
    groups: Dict[str, List[int]] = {}
    fullnames_by_base: Dict[str, set] = {}
    for idx, exp in enumerate(exports):
        name = exp.get("ObjectName")
        if not isinstance(name, str) or not name:
            continue
        base = base_from_object_name(name)
        groups.setdefault(base, []).append(idx)
        fullnames_by_base.setdefault(base, set()).add(name)

    changes: List[Tuple[int, str, str]] = []
    for base, idx_list in groups.items():
        if len(fullnames_by_base[base]) < len(idx_list):
            for order, idx in enumerate(idx_list):
                exp = exports[idx]
                old = exp.get("ObjectName")
                new = f"{base}_{order}"
                if old != new:
                    exp["ObjectName"] = new
                    changes.append((idx, old, new))
    return changes

# ======================================================================
# Imports 补齐 & 归一化
# ======================================================================

def is_target_function_name(name: Optional[str]) -> bool:
    """是否属于需要统一 OuterIndex 的“目标函数 Import”（含 Default__）。"""
    if not isinstance(name, str) or not name:
        return False
    if name == "/Script/JH":
        return False
    core = name[9:] if name.startswith("Default__") else name
    return core.startswith(TARGET_PREFIXES)

def find_jh_package_neg_index(imports: List[Dict[str, Any]]) -> Optional[int]:
    """查找 ObjectName == '/Script/JH' 且 ClassName == 'Package' 的 Import 负索引。"""
    for i, imp in enumerate(imports):
        if imp.get("ObjectName") == "/Script/JH" and imp.get("ClassName") == "Package":
            return -(i + 1)
    return None

def unify_import_outerindex(imports: List[Dict[str, Any]], target_neg_index: int) -> Tuple[int, List[str]]:
    """将所有目标函数 Import 的 OuterIndex 改为 target_neg_index。"""
    changed = 0
    changed_names: List[str] = []
    for imp in imports:
        name = imp.get("ObjectName")
        if is_target_function_name(name) and imp.get("OuterIndex") != target_neg_index:
            imp["OuterIndex"] = target_neg_index
            changed += 1
            changed_names.append(name)
    return changed, changed_names

def collect_used_main_functions(exports: List[Dict[str, Any]]) -> Set[str]:
    """从 Exports[3:] 统计本文件用到的“主函数基名”集合。"""
    used: Set[str] = set()
    for exp in exports[3:]:
        obj_name = exp.get("ObjectName")
        if not isinstance(obj_name, str) or not obj_name:
            continue
        base = base_from_object_name(obj_name)
        if base.startswith("Default__"):
            base = base[len("Default__"):]
        used.add(base)
    return used

def load_main_imports_map(path: str) -> Dict[str, List[Dict[str, Any]]]:
    """读取上游生成的 { pure_main_fn: [main_import_obj, default_import_obj, ...] }。"""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到主函数 Imports 映射文件：{path}")
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    return obj if isinstance(obj, dict) else {}

def append_missing_imports_for_mains(
    data: Dict[str, Any],
    mains: Set[str],
    main_imports_map: Dict[str, List[Dict[str, Any]]]
) -> int:
    """对每个主函数追加缺失的“主库→Default 库” Import（按顺序）。"""
    imports = get_or_create_imports_list(data)
    exist_names = { imp.get("ObjectName") for imp in imports if isinstance(imp, dict) }
    added = 0
    for m in sorted(mains):
        cands = main_imports_map.get(m)
        if not cands or not isinstance(cands, list):
            continue
        for want in (m, f"Default__{m}"):
            if want in exist_names:
                continue
            found = next((c for c in cands if isinstance(c, dict) and c.get("ObjectName") == want), None)
            if found is None:
                continue
            imports.append(deepcopy(found))
            exist_names.add(want)
            added += 1
    return added

# ======================================================================
# NameMap 工具
# ======================================================================

JSONType = Union[dict, list, str, int, float, bool, None]

def get_namemap_key_and_list(data: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """取 NameMap/Namemap（大小写容错）。若不存在则创建空列表挂到 'NameMap'。"""
    key = next((k for k in data.keys() if str(k).lower() == "namemap"), None)
    if key is None:
        key = "NameMap"
        data[key] = []
    nm = data.get(key)
    if not isinstance(nm, list):
        nm = []
        data[key] = nm
    return key, nm

def namemap_strings_set(nm: List[Any]) -> set:
    """将 NameMap 中所有字符串抽出为 set；兼容元素是 dict 的情况。"""
    s = set()
    for item in nm:
        if isinstance(item, str):
            s.add(item)
        elif isinstance(item, dict):
            for cand in ("Name", "Value", "String", "Text"):
                val = item.get(cand)
                if isinstance(val, str):
                    s.add(val); break
    return s

def ensure_strings_in_namemap(data: Dict[str, Any], strings: List[str]) -> int:
    """确保 strings 里的每个字符串都出现在 NameMap 末尾（若缺失则追加）。"""
    _, nm = get_namemap_key_and_list(data)
    exist = namemap_strings_set(nm)
    added = 0
    for s in strings:
        if s and s not in exist:
            nm.append(s)
            exist.add(s)
            added += 1
    return added

def canon_property(s: str) -> str:
    if not isinstance(s, str): return s
    s = s.strip()
    return re.sub(r'PropertyData$', 'Property', s) if s else s

_prop_token_re = re.compile(r'[A-Za-z_][A-Za-z0-9_]*Property(?:Data)?')

def extract_property_like_tokens(text: str) -> Set[str]:
    if not isinstance(text, str): return set()
    return set(_prop_token_re.findall(text))

def collect_all_strings(obj: JSONType) -> Set[str]:
    """抽取 JSON 中出现过的所有字符串（键、值、嵌套）"""
    found: Set[str] = set()
    def _walk(o: JSONType):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str): found.add(k)
                _walk(v)
        elif isinstance(o, list):
            for x in o: _walk(x)
        elif isinstance(o, str):
            found.add(o)
    _walk(obj)
    return found

def load_lines(path: Path) -> List[str]:
    lines: List[str] = []
    with path.open("r", encoding="utf-8") as f:
        for ln in f:
            s = ln.rstrip("\n\r")
            if s.strip():
                lines.append(s)
    return lines

# ======================================================================
# 单文件处理逻辑封装（保持原流程不变）
# ======================================================================

def process_one_json_file(input_path: str) -> str:
    """
    处理单个 JSON 文件；完全沿用原 main() 的顺序与逻辑。
    返回：实际写入的输出路径（或源路径）。
    """
    # 读取 JSON
    data = load_json(input_path)

    # -------- Exports & Imports 基础 -------
    exports = get_exports_list(data)
    if not exports:
        raise RuntimeError("未能在 JSON 中找到任何 Exports。")

    # (1) 识别本文件“用到的主函数”
    used_mains = collect_used_main_functions(exports)
    print(f"[扫描] 本文件用到的主函数种类：{len(used_mains)}")

    # (2) 从映射补齐缺失 Imports（主库→Default）
    try:
        main_imports_map = load_main_imports_map(MAIN_IMPORTS_MAP_PATH)
    except FileNotFoundError as e:
        main_imports_map = {}
        print(f"[警告] {e}；跳过 Import 补齐。")

    if main_imports_map:
        added = append_missing_imports_for_mains(data, used_mains, main_imports_map)
        if added:
            print(f"[Imports] 已按主库→Default 顺序补齐 {added} 条缺失的 Import。")
        else:
            print("[Imports] 未发现需要补齐的 Import。")

    # (3) 重建 Import 索引
    import_list = get_or_create_imports_list(data)
    if not import_list:
        raise RuntimeError("未能在 JSON 中找到任何 Imports，无法建立索引。")
    import_idx = build_import_index_from_list(import_list)

    # (4) 统一 OuterIndex -> /Script/JH（若存在）
    jh_pkg_neg = find_jh_package_neg_index(import_list)
    if jh_pkg_neg is not None:
        changed, _ = unify_import_outerindex(import_list, jh_pkg_neg)
        if changed:
            print(f"[Import] 已将 {changed} 条“目标函数 Import”的 OuterIndex 归一为 {jh_pkg_neg}")
    else:
        print("[Import] 未找到 '/Script/JH' 的 Package Import，跳过 OuterIndex 归一。")

    # (5) Exports[3:] 同名标准化
    rename_changes = dedupe_export_object_names(exports[3:])
    if rename_changes:
        print("已对 Exports 中重复的 ObjectName 进行标准化重命名：")
        for idx, old, new in rename_changes:
            print(f"  - Exports[{idx+3}]: {old} -> {new}")

    # (6) 修正 Exports[3:] 索引
    missing_records: List[str] = []
    for i in range(3, len(exports)):
        exp = exports[i]
        obj_name = exp.get("ObjectName")
        if not isinstance(obj_name, str) or not obj_name:
            continue

        base = base_from_object_name(obj_name)
        non_default = base
        default_name = f"Default__{base}"

        idx_class = import_idx.get(non_default)
        idx_template = import_idx.get(default_name)

        if idx_class is None or idx_template is None:
            lack = []
            if idx_class is None:    lack.append(non_default)
            if idx_template is None: lack.append(default_name)
            missing_records.append(
                f"Exports[{i}] ObjectName='{obj_name}' 缺少 Imports: {', '.join(lack)}"
            )
            continue

        exp["SerializationBeforeCreateDependencies"] = [idx_class, idx_template]
        exp["ClassIndex"]   = idx_class
        exp["TemplateIndex"]= idx_template

    if missing_records:
        print("警告：以下条目在 Imports 中未找到对应库（相关 export 未改动）：")
        for line in missing_records:
            print("  - " + line)

    # ====================== 最后一步：补齐 NameMap ======================
    # (NM-1) 先把所有 import 的三元写入（ObjectName / ClassPackage / ClassName）
    nm_from_imports: List[str] = []
    for imp in import_list:
        on = imp.get("ObjectName");    cp = imp.get("ClassPackage");    cn = imp.get("ClassName")
        if isinstance(on, str) and on: nm_from_imports.append(on)
        if isinstance(cp, str) and cp: nm_from_imports.append(cp)
        if isinstance(cn, str) and cn: nm_from_imports.append(cn)
    added1 = ensure_strings_in_namemap(data, nm_from_imports)

    # (NM-2) 再按 namemap_all.txt 与“文件出现过的字符串”对比补齐
    try:
        nm_lines = load_lines(NAMEMAP_TXT)
    except Exception as e:
        nm_lines = []
        print(f"[NameMap] 加载总表失败（{e}），跳过总表对比阶段。")

    # 生成“文件内出现过的字符串”的标准化集合
    all_json_strings: Set[str] = collect_all_strings(data)
    all_json_canon: Set[str] = set()
    for s in all_json_strings:
        all_json_canon.add(canon_property(s))
        for tok in extract_property_like_tokens(s):
            all_json_canon.add(canon_property(tok))

    # 仅把“总表里有、文件中出现但 NameMap 没有”的条目追加
    _, nm_list = get_namemap_key_and_list(data)
    existing_exact: Set[str] = {s for s in nm_list if isinstance(s, str)}
    existing_canon: Set[str] = {canon_property(s) for s in existing_exact}

    to_add_from_table: List[str] = []
    for s in nm_lines:
        cs = canon_property(s)
        if cs in all_json_canon and cs not in existing_canon:
            to_add_from_table.append(s)
            existing_canon.add(cs)

    added2 = ensure_strings_in_namemap(data, to_add_from_table)

    print(f"[NameMap] 追加（from imports）: {added1} 条；追加（from total table）: {added2} 条。")

    # ====================== 写回 / 备份 ======================
    basename = os.path.basename(input_path)
    if WRITE_TO_SOURCE:
        # 备份
        if MAKE_BACKUP:
            try:
                raw = open(input_path, "r", encoding="utf-8").read()
            except Exception:
                raw = ""
            try:
                bak_path = input_path + ".bak"
                with open(bak_path, "w", encoding="utf-8") as bf:
                    bf.write(raw)
                print(f"[备份] 已写入：{bak_path}")
            except Exception:
                print("[警告] 备份失败，继续写入。")
        out_path = input_path
    else:
        out_path = str(FIXED_OUTPUT_DIR / basename)

    save_json(data, out_path)
    print(f"[完成] 已写回：{out_path}")
    return out_path

# ======================================================================
# 目录遍历工具
# ======================================================================

def _iter_json_files(root_dirs: Iterable[str], prefixes: Tuple[str, ...]) -> Iterable[Tuple[str, str]]:
    """
    递归遍历多个根目录，产出 (root_dir, json_file_path)。
    仅当文件名（不含路径）以指定前缀之一开头且以 .json 结尾时匹配。
    prefix 为空表示不过滤前缀（只要是 .json 即可）。
    """
    prefixes = tuple(prefixes or tuple())
    for root in root_dirs:
        if not os.path.isdir(root):
            print(f"[跳过] 非目录或不存在：{root}")
            continue
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if not fn.lower().endswith(".json"):
                    continue
                if prefixes and not any(fn.startswith(p) for p in prefixes):
                    continue
                yield (root, os.path.join(dirpath, fn))

def _calc_output_path_for_mirroring(src_path: str, root_dir: str) -> str:
    """
    在 WRITE_TO_SOURCE=False 时，把输出镜像到 FIXED_OUTPUT_DIR 下：
    FIXED_OUTPUT_DIR / <相对 root_dir 的路径>。
    不改扩展名与文件名。
    """
    rel = os.path.relpath(src_path, start=root_dir)
    out_path = FIXED_OUTPUT_DIR / rel
    return str(out_path)

# ======================================================================
# 主流程
# ======================================================================

def main():
    global WRITE_TO_SOURCE
    if ENABLE_DIR_TRAVERSAL:
        # -------- 目录模式：只处理目录，忽略单文件 INPUT_PATH --------
        print("[模式] 目录遍历：启用")
        total = 0
        done = 0
        for root_dir, json_path in _iter_json_files(SCAN_DIRS, FILENAME_PREFIXES):
            total += 1
            print(f"\n[处理] {json_path}")
            # 单次输出路径策略：
            # - WRITE_TO_SOURCE=True: 就地覆盖（与单文件逻辑一致）
            # - WRITE_TO_SOURCE=False: 按 root_dir 镜像到 FIXED_OUTPUT_DIR
            if WRITE_TO_SOURCE:
                _ = process_one_json_file(json_path)
                done += 1
            else:
                # 临时改写 save 目的地：通过临时切换全局 FIXED_OUTPUT_DIR 的使用点来实现镜像输出
                # 为保持“单文件逻辑不改”，这里采用：处理完后再把结果写到镜像路径
                # 具体做法：直接在处理函数中按“单文件模式（False）”生成结果到 FIXED_OUTPUT_DIR/文件名，
                # 但为了严格镜像，我们这里再读回并写到镜像路径。
                # ——为减少 I/O，我们直接在此处实现“镜像写回”版本：
                try:
                    data = load_json(json_path)  # 读源
                    # 复用完整处理流水线，但不写盘；为保持最小侵入，这里简单复制 process_one_json_file 的主体：
                    # ------- 以下直接调用主体代码（简化：把 process_one_json_file 拆分将很侵入，这里复用并重写输出）-------
                    # 为不重复逻辑，这里再调用一次，但把最终写回交给我们：
                    # 实际更优方案是把“处理”和“写回”分离；为满足“不改变既有逻辑”，我们尽量少动。
                    # 简洁起见：直接调用处理函数产生到默认 FIXED_OUTPUT_DIR/basename，然后再移动到镜像路径。
                    # 但移动需要知道那个默认路径名：
                    basename = os.path.basename(json_path)
                    # 暂时保留现场配置
                    old_write = WRITE_TO_SOURCE
                    WRITE_TO_SOURCE = False
                    tmp_out = process_one_json_file(json_path)  # 写到 FIXED_OUTPUT_DIR / basename
                    WRITE_TO_SOURCE = old_write
                    # 读取临时输出，写到镜像路径
                    tmp_data = load_json(tmp_out)
                    mirror_out = _calc_output_path_for_mirroring(json_path, root_dir)
                    save_json(tmp_data, mirror_out)
                    print(f"[镜像输出] {mirror_out}")
                    done += 1
                except Exception as e:
                    print(f"[错误] {json_path}: {e}")
        print(f"\n[汇总] 目标匹配文件：{total}，成功处理：{done}")
    else:
        # -------- 单文件模式：保持完全原逻辑 --------
        print("[模式] 单文件：启用")
        _ = process_one_json_file(INPUT_PATH)

if __name__ == "__main__":
    main()
