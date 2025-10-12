"""
功能：
- 导出 Buffs / Skills 指定 ID 的 Blueprint 路径，格式为：ID + 基础路径 + 完整路径_C，以及Icon和大招
- 去掉“数值闭区间模式”，仅保留“按出现顺序的起止ID”与“显式ID清单”
- 顶部常量可直接控制：模式、各自起止ID、各自离散ID清单、输入输出路径
"""

import json, os, sys, argparse
from typing import Any, List, Tuple, Optional, Iterable, Set, Dict

# ====================== 顶部总开关（你改这里即可） ======================
# 模式：0 = 同时导出 skills 与 buffs；1 = 仅 skills；2 = 仅 buffs
MODE_OVERRIDE: Optional[int] = 0

# —— Buffs：起止ID（按出现顺序，含终点），或离散清单（二者选其一，清单优先）——
BUFFS_START_ID: Optional[int] = 2593060    # 例：2025910；None 表示从文件开头
BUFFS_END_ID:   Optional[int] = 2593066    # 例：2025966；None 表示到文件末尾
BUFFS_ID_LIST:  Optional[str] = None    # 逗号分隔字符串，如 "2025910,2025911,2025966"；设定后优先生效

# —— Skills：起止ID（按出现顺序，含终点），或离散清单（二者选其一，清单优先）——
SKILLS_START_ID: Optional[int] = 0   # 例：999
SKILLS_END_ID:   Optional[int] = 0
SKILLS_ID_LIST:  Optional[str] = None   # 如 "999,1001,1200"

# —— 输入控制——
DEFAULT_BUFFS_JSON = r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH\Wandering_Sword\Content\JH\Tables\Buffs.json"
DEFAULT_SKILLS_JSON = r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH\Wandering_Sword\Content\JH\Tables\Skills.json"

# —— 输出控制、输出路径——
FIXED_OUTPUT_DIR    = r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles"
OUTPUT_TO_FIXED_DIR = True  # True: 输出到 FIXED_OUTPUT_DIR；False: 输出到脚本目录（除非命令行指定）
# =====================================================================

# ===== 常量 =====
SOFT_OBJ_TYPE    = "UAssetAPI.PropertyTypes.Objects.SoftObjectPropertyData, UAssetAPI"
STRUCT_PROP_TYPE = "UAssetAPI.PropertyTypes.Structs.StructPropertyData, UAssetAPI"
TARGET_STRUCT_BUFFS  = "BuffSetting"
TARGET_STRUCT_SKILLS = "SkillSetting"

# ===== 新增：图标字段名（只导完整一条，且仅导“带点”的版本）=====
BUFF_ICON_FIELD   = "Icon"                # /Game/JH/UI/Icon/T_Skill834.T_Skill834
SKILL_ULTRA_FIELD = "UltimateSkillIcon"   # /Game/JH/JHNeoUI/UIAssets/Skill/Ultra/T_xxx.T_xxx

def is_int_str(s: str) -> bool:
    try:
        int(s); return True
    except:
        return False

def _split_base(full: str) -> str:
    """从完整路径取点号前的 base；无点返回原串"""
    if not isinstance(full, str):
        return ""
    return full.split(".", 1)[0] if "." in full else full

def _valid_str(x: Optional[str]) -> bool:
    """过滤 None / 'None' / 空串"""
    return isinstance(x, str) and x.strip() != "" and x != "None"

def find_blueprint_asset_name(struct_value_list) -> Optional[str]:
    """从结构体 Value 列表中找到 Blueprint 的 AssetName（/Game/.../GA_xxx.GA_xxx_C）"""
    for item in struct_value_list:
        if not isinstance(item, dict):
            continue
        if item.get("$type") == SOFT_OBJ_TYPE and item.get("Name") == "Blueprint":
            v = item.get("Value", {})
            if isinstance(v, dict):
                ap = v.get("AssetPath")
                if isinstance(ap, dict):
                    an = ap.get("AssetName")
                    if _valid_str(an):
                        return an
                if _valid_str(v.get("AssetName")):
                    return v["AssetName"]
                if _valid_str(v.get("AssetPathName")):
                    return v["AssetPathName"]
    return None

# ===== 新增：抽取任意 SoftObject 字段 =====
def find_soft_object_asset(struct_value_list, field_name: str) -> Optional[str]:
    """
    读取如 Icon / UltimateSkillIcon 这类 SoftObject 字段的 AssetName 完整路径。
    只返回字符串，None 或 'None' 直接视为无效。
    """
    for item in struct_value_list:
        if not isinstance(item, dict):
            continue
        if item.get("$type") == SOFT_OBJ_TYPE and item.get("Name") == field_name:
            v = item.get("Value", {})
            if isinstance(v, dict):
                ap = v.get("AssetPath")
                if isinstance(ap, dict):
                    an = ap.get("AssetName")
                    if _valid_str(an):
                        return an
                if _valid_str(v.get("AssetName")):
                    return v["AssetName"]
                if _valid_str(v.get("AssetPathName")):
                    return v["AssetPathName"]
    return None

# ===== 新增：从当前 JSON 提取 NameMap 集合（用于导出前判重）=====
def extract_namemap_set(root: Any) -> Set[str]:
    """
    Unreal 导出的 JSON 通常顶层有 NameMap 数组；这里仅拿到字符串项。
    若没有顶层 NameMap，不报错，返回空集合。
    """
    seen: Set[str] = set()
    if isinstance(root, dict):
        nm = root.get("NameMap")
        if isinstance(nm, list):
            for s in nm:
                if _valid_str(s):
                    seen.add(s)
    return seen

# ===== 新增：批内去重 + NameMap 过滤 + “带点优先”=====
def filter_and_dedupe(rows: List[Tuple[str, str, str]],
                      namemap_seen: Set[str],
                      keep_full_only_for_icon: bool) -> Tuple[List[Tuple[str, str, str]], bool]:
    """
    rows: (id, base, full)
    - 先过滤无效(full 为空/'None')
    - 若同一资源同时出现 '/A/B' 与 '/A/B.T'，保留“带点”版本
    - 在当前 JSON 的 NameMap 里已存在的 full 直接剔除
    返回：(过滤后的行, 是否全部存在/无需导出)
    """
    # 1) 先剔除无效和图标“只保留带点”的版本
    candidates: List[Tuple[str, str, str]] = []
    for id_, base, full in rows:
        if not _valid_str(full):
            continue
        # 图标字段我们后续写出时只会打一行 full，但这里为了“一种只保留一种”，优先保留带点
        candidates.append((id_, base, full))

    if not candidates:
        return [], True

    # 2) 带点优先：若同 base 既有无点又有带点，只保留带点
    has_dot_bases = { _split_base(f) for _, _, f in candidates if "." in f }
    dedup_dot: List[Tuple[str, str, str]] = []
    seen_full: Set[str] = set()
    for id_, base, full in candidates:
        base0 = _split_base(full)
        if "." not in full and base0 in has_dot_bases:
            continue
        if full in seen_full:
            continue
        seen_full.add(full)
        dedup_dot.append((id_, base, full))

    # 3) 用 NameMap 过滤（当前 JSON 自带 NameMap）
    out: List[Tuple[str, str, str]] = []
    for id_, base, full in dedup_dot:
        if full in namemap_seen:
            continue
        out.append((id_, base, full))

    all_exist = (len(out) == 0 and len(dedup_dot) > 0)
    return out, all_exist

def collect_by_id_sequence(data: Any, struct_type: str, id_iter: Iterable[str]) -> List[Tuple[str, str, str]]:
    """按显式 ID 清单（字符串）收集，输出顺序=文件出现顺序"""
    want = set(id_iter)
    rows: List[Tuple[str, str, str]] = []

    def dfs(node: Any):
        if not want:
            return
        if isinstance(node, dict):
            if (
                node.get("$type") == STRUCT_PROP_TYPE and
                node.get("StructType") == struct_type and
                isinstance(node.get("Name"), str) and
                isinstance(node.get("Value"), list)
            ):
                this_id = node["Name"]
                if this_id in want:
                    vals = node["Value"]
                    # Blueprint 三元组
                    full_bp = find_blueprint_asset_name(vals)
                    if _valid_str(full_bp):
                        rows.append((this_id, _split_base(full_bp), full_bp))
                    # 追加图标（只导完整路径），id/base 置空
                    if struct_type == TARGET_STRUCT_BUFFS:
                        full_icon = find_soft_object_asset(vals, BUFF_ICON_FIELD)
                        if _valid_str(full_icon):
                            rows.append(("", "", full_icon))
                    if struct_type == TARGET_STRUCT_SKILLS:
                        full_ulti = find_soft_object_asset(vals, SKILL_ULTRA_FIELD)
                        if _valid_str(full_ulti):
                            rows.append(("", "", full_ulti))
                    want.discard(this_id)
            for v in node.values():
                if not want: break
                dfs(v)
        elif isinstance(node, list):
            for v in node:
                if not want: break
                dfs(v)

    dfs(data)
    return rows

def collect_ordered(data: Any, struct_type: str, start_id_num: Optional[int], end_id_num: Optional[int]) -> List[Tuple[str, str, str]]:
    """按出现顺序从 start_id 到 end_id（含）收集；二者可为 None（开头/末尾）"""
    start_id = str(start_id_num) if start_id_num is not None else None
    end_id   = str(end_id_num)   if end_id_num   is not None else None

    rows: List[Tuple[str, str, str]] = []
    started = (start_id is None)
    stopped = False

    def dfs(node: Any):
        nonlocal started, stopped
        if stopped: return
        if isinstance(node, dict):
            if (
                node.get("$type") == STRUCT_PROP_TYPE and
                node.get("StructType") == struct_type and
                isinstance(node.get("Name"), str) and
                isinstance(node.get("Value"), list)
            ):
                this_id = node["Name"]
                if not started and start_id is not None and this_id == start_id:
                    started = True
                if started:
                    vals = node["Value"]
                    # Blueprint 三元组
                    full_bp = find_blueprint_asset_name(vals)
                    if _valid_str(full_bp):
                        rows.append((this_id, _split_base(full_bp), full_bp))
                    # 追加图标（只导完整路径），id/base 置空
                    if struct_type == TARGET_STRUCT_BUFFS:
                        full_icon = find_soft_object_asset(vals, BUFF_ICON_FIELD)
                        if _valid_str(full_icon):
                            rows.append(("", "", full_icon))
                    if struct_type == TARGET_STRUCT_SKILLS:
                        full_ulti = find_soft_object_asset(vals, SKILL_ULTRA_FIELD)
                        if _valid_str(full_ulti):
                            rows.append(("", "", full_ulti))
                    if end_id is not None and this_id == end_id:
                        stopped = True  # **包含**终结ID后停止
                        return
            for v in node.values():
                if stopped: break
                dfs(v)
        elif isinstance(node, list):
            for v in node:
                if stopped: break
                dfs(v)

    dfs(data)
    return rows

def decide_out_path(default_name: str, user_out: Optional[str]) -> str:
    if user_out:
        return user_out
    base_dir = FIXED_OUTPUT_DIR if OUTPUT_TO_FIXED_DIR else os.path.dirname(os.path.abspath(__file__))
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, default_name)

# ===== 修改：写出逻辑（图标只打一行“完整路径”，其余保持三行）=====
def write_triplets(out_path: str, rows: List[Tuple[str, str, str]]) -> None:
    lines = []
    for id_, base, full in rows:
        if not _valid_str(full):
            continue
        # 图标/Ulti：我们在采集时把 id/base 置空，这里只打一行 full
        if not id_ and not base:
            lines.append(f"\"{full}\",")
            continue
        # 兼容：若 base 为空则从 full 计算；仍是三行制
        base_eff = base if _valid_str(base) else _split_base(full)
        if not _valid_str(base_eff):
            # 极端兜底：只打一行 full
            lines.append(f"\"{full}\",")
        else:
            lines.append(f"\"{id_}\",")
            lines.append(f"\"{base_eff}\",")
            lines.append(f"\"{full}\",")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def parse_id_list(s: Optional[str]) -> Optional[List[str]]:
    if not s: return None
    raw = [x.strip() for x in s.split(",") if x.strip() != ""]
    return [str(int(x)) if is_int_str(x) else x for x in raw] or None

def load_json(path: str) -> Any:
    if not os.path.isfile(path):
        print(f"找不到文件：{path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    ap = argparse.ArgumentParser(description="导出 BuffSetting / SkillSetting 的 Blueprint 路径（ID、基础路径、完整路径_C）")

    # —— 命令行参数（若顶部常量非 None，将被覆盖）——
    ap.add_argument("--mode", type=int, default=0, help="0=同时导出 skills 与 buffs；1=仅 skills；2=仅 buffs")
    ap.add_argument("--buffs-json", default=DEFAULT_BUFFS_JSON, help="Buffs.json 路径")
    ap.add_argument("--skills-json", default=DEFAULT_SKILLS_JSON, help="Skills.json 路径")

    ap.add_argument("--buffs-start-id", type=int, default=None)
    ap.add_argument("--buffs-end-id",   type=int, default=None)
    ap.add_argument("--buffs-ids",      type=str, default=None)

    ap.add_argument("--skills-start-id", type=int, default=None)
    ap.add_argument("--skills-end-id",   type=int, default=None)
    ap.add_argument("--skills-ids",      type=str, default=None)

    ap.add_argument("--out-buffs",  default=None, help="Buffs 输出txt路径")
    ap.add_argument("--out-skills", default=None, help="Skills 输出txt路径")

    args = ap.parse_args()

    # 顶部常量优先生效
    mode = MODE_OVERRIDE if MODE_OVERRIDE is not None else args.mode

    buffs_start = BUFFS_START_ID if BUFFS_START_ID is not None else args.buffs_start_id
    buffs_end   = BUFFS_END_ID   if BUFFS_END_ID   is not None else args.buffs_end_id
    buffs_ids_s = BUFFS_ID_LIST  if BUFFS_ID_LIST  is not None else args.buffs_ids

    skills_start = SKILLS_START_ID if SKILLS_START_ID is not None else args.skills_start_id
    skills_end   = SKILLS_END_ID   if SKILLS_END_ID   is not None else args.skills_end_id
    skills_ids_s = SKILLS_ID_LIST  if SKILLS_ID_LIST  is not None else args.skills_ids

    do_skills = (mode in (0,1))
    do_buffs  = (mode in (0,2))

    # ===== Buffs =====
    if do_buffs:
        data_buffs = load_json(args.buffs_json)
        namemap_buffs = extract_namemap_set(data_buffs)

        ids_list = parse_id_list(buffs_ids_s)
        if ids_list is not None:
            rows_buffs = collect_by_id_sequence(data_buffs, TARGET_STRUCT_BUFFS, ids_list)
            eff_start = ids_list[0] if ids_list else "NA"
            eff_end   = ids_list[-1] if ids_list else "NA"
            tip = f"Buffs：按 ID 清单匹配到 {len(rows_buffs)} 条。清单首尾=({eff_start}→{eff_end})"
        else:
            rows_buffs = collect_ordered(data_buffs, TARGET_STRUCT_BUFFS, buffs_start, buffs_end)
            if rows_buffs:
                eff_start, eff_end = rows_buffs[0][0] or "BEGIN", rows_buffs[-1][0] or "END"
            else:
                eff_start = str(buffs_start) if buffs_start is not None else "BEGIN"
                eff_end   = str(buffs_end)   if buffs_end   is not None else "END"
            st = str(buffs_start) if buffs_start is not None else "BEGIN"
            ed = str(buffs_end)   if buffs_end   is not None else "END"
            tip = f"Buffs：按出现顺序匹配到 {len(rows_buffs)} 条（{st} -> {ed}，包含终结ID）。"

        # 新增：用 NameMap 过滤 + 带点优先 + 批内去重；并判断“全部存在”
        rows_buffs, all_exist_buffs = filter_and_dedupe(rows_buffs, namemap_buffs, keep_full_only_for_icon=True)

        if all_exist_buffs:
            print("Buffs：全部存在（当前 JSON 的 NameMap 已包含所有目标路径）。跳过写出。")
        else:
            out_buffs_name = f"BuffSetting_{eff_start}_to_{eff_end}.txt"
            out_buffs_path = decide_out_path(out_buffs_name, args.out_buffs)
            write_triplets(out_buffs_path, rows_buffs)
            print(tip)
            print(f"Buffs 已写出：{out_buffs_path}")

    # ===== Skills =====
    if do_skills:
        data_skills = load_json(args.skills_json)
        namemap_skills = extract_namemap_set(data_skills)

        ids_list_s = parse_id_list(skills_ids_s)
        if ids_list_s is not None:
            rows_skills = collect_by_id_sequence(data_skills, TARGET_STRUCT_SKILLS, ids_list_s)
            eff_start_s = ids_list_s[0] if ids_list_s else "NA"
            eff_end_s   = ids_list_s[-1] if ids_list_s else "NA"
            tip = f"Skills：按 ID 清单匹配到 {len(rows_skills)} 条。清单首尾=({eff_start_s}→{eff_end_s})"
        else:
            rows_skills = collect_ordered(data_skills, TARGET_STRUCT_SKILLS, skills_start, skills_end)
            if rows_skills:
                eff_start_s, eff_end_s = rows_skills[0][0] or "BEGIN", rows_skills[-1][0] or "END"
            else:
                eff_start_s = str(skills_start) if skills_start is not None else "BEGIN"
                eff_end_s   = str(skills_end)   if skills_end   is not None else "END"
            st = str(skills_start) if skills_start is not None else "BEGIN"
            ed = str(skills_end)   if skills_end   is not None else "END"
            tip = f"Skills：按出现顺序匹配到 {len(rows_skills)} 条（{st} -> {ed}，包含终结ID）。"

        # 新增：用 NameMap 过滤 + 带点优先 + 批内去重；并判断“全部存在”
        rows_skills, all_exist_skills = filter_and_dedupe(rows_skills, namemap_skills, keep_full_only_for_icon=True)

        if all_exist_skills:
            print("Skills：全部存在（当前 JSON 的 NameMap 已包含所有目标路径）。跳过写出。")
        else:
            out_skills_name = f"SkillSetting_{eff_start_s}_to_{eff_end_s}.txt"
            out_skills_path = decide_out_path(out_skills_name, args.out_skills)
            write_triplets(out_skills_path, rows_skills)
            print(tip)
            print(f"Skills 已写出：{out_skills_path}")

if __name__ == "__main__":
    main()
