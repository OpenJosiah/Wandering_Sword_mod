"""
功能：
- 导出 指定文件夹及其子文件夹中，所有GE、GA文件 的 Blueprint 路径，格式为：ID + 基础路径 + 完整路径_C
- 可以指定单个BuffId或者SkillId，只导出其完整路径_C
"""

import os
import re
import json
from typing import Any, Dict, List, Optional, Tuple

# === 配置区（按需修改） =========================================================
SEARCH_DIRS = [
    r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH\Wandering_Sword\Content\JH\Skills",
]
OUTPUT_DIR = r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles"

# 新增：输出控制
# True  -> 完整输出（原有行为）：写 GE_output.txt / GA_output.txt，每条三行、带逗号
# False -> 指定输出：只打印你指定的 buffid/skillid 对应的 “完整路径_C” 单行（无逗号），不写文件
FULL_OUTPUT: bool = False

# 新增：指定输出的目标（仅当 FULL_OUTPUT=False 时生效；填 None 表示不指定）
#   - buffid: GE 的 Id
#   - skillid: GA 的 SkillId
SPECIFY_BUFFIDS: List[int] = [2593060,2593061,2593062,2593063,2593064,2593065]      # 例如：[2592920, 2592930]
SPECIFY_SKILLIDS: List[int] = []     # 例如：[2592902, 2592903]
# ============================================================================


# === 工具函数 ===
def read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        print(f"[读取失败] {path} -> {e}")
        return None

def split_path_parts(p: str) -> List[str]:
    return os.path.normpath(p).split(os.sep)

def build_namemap_from_path(file_path: str) -> Optional[Tuple[str, str, List[str], str]]:
    """
    从文件绝对路径解析：
      - Skills 到 文件名 之间的所有目录为“中途路径”（0~N层，自适应）
      - 名称 = 去扩展名的文件名
    返回：(namemap, base_prefix, middle_parts, name)
      namemap: /Game/JH/Skills/<中途路径...>/<名称>
      base_prefix: /Game/JH/Skills
    """
    parts = split_path_parts(file_path)
    idx = None
    for i, seg in enumerate(parts):
        if seg.lower() == "skills":
            idx = i
            break
    if idx is None:
        return None

    middle_parts = parts[idx + 1 : -1]  # 可能为 []
    name = os.path.splitext(os.path.basename(file_path))[0]

    base_prefix = "/Game/JH/Skills"
    nm_parts = [base_prefix] + middle_parts + [name]
    namemap = "/".join(nm_parts).replace("//", "/")
    return namemap, base_prefix, middle_parts, name

def json_contains_value(obj: Any, target: str) -> bool:
    """递归检查 JSON 是否包含指定字符串值（完全匹配）"""
    if isinstance(obj, dict):
        for v in obj.values():
            if json_contains_value(v, target):
                return True
    elif isinstance(obj, list):
        for v in obj:
            if json_contains_value(v, target):
                return True
    else:
        if isinstance(obj, str) and obj == target:
            return True
    return False

def extract_ge_id(obj: Dict[str, Any]) -> Optional[int]:
    """
    优先严格按要求：读取 Exports[2] -> Data 中 Name == "Id" 的 Value
    若结构稍有差异，做容错：尝试 Export/exports/递归回退。
    """
    for key in ("Exports", "Export", "exports", "export"):
        if key in obj and isinstance(obj[key], list) and len(obj[key]) > 2 and isinstance(obj[key][2], dict):
            data = obj[key][2].get("Data")
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("Name") == "Id":
                        val = item.get("Value")
                        if isinstance(val, int):
                            return val
    # 回退：全表递归找 Name=="Id" 的 int Value
    found: List[int] = []

    def dfs(o: Any):
        if isinstance(o, dict):
            if o.get("Name") == "Id" and isinstance(o.get("Value"), int):
                found.append(o["Value"])
            for v in o.values():
                dfs(v)
        elif isinstance(o, list):
            for v in o:
                dfs(v)

    dfs(obj)
    return found[0] if found else None

def extract_ga_skillid(obj: Dict[str, Any]) -> Optional[int]:
    """递归查找 SkillId 的 int 值（兼容 {"Name":"SkillId","Value":int} 或 {"SkillId":int}）"""
    result: List[int] = []

    def dfs(o: Any):
        if isinstance(o, dict):
            if o.get("Name") == "SkillId" and isinstance(o.get("Value"), int):
                result.append(o["Value"])
            if "SkillId" in o and isinstance(o["SkillId"], int):
                result.append(o["SkillId"])
            for v in o.values():
                dfs(v)
        elif isinstance(o, list):
            for v in o:
                dfs(v)

    dfs(obj)
    return result[0] if result else None

def ensure_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

def write_block(fh, id_val: int, namemap: str, name: str):
    full_c = f"{namemap}.{name}_C"
    # 每条仍是三行、末尾带逗号，但不再额外空一行
    fh.write(f"\"{id_val}\",\n")
    fh.write(f"\"{namemap}\",\n")
    fh.write(f"\"{full_c}\",\n")   # ← 原来这里是 \n\n，去掉一个换行

def process_file(json_path: str, issues: List[str], ge_records: List[Tuple[int, str, str]], ga_records: List[Tuple[int, str, str]]):
    base = os.path.basename(json_path)
    stem, ext = os.path.splitext(base)
    if ext.lower() != ".json":
        return

    # 大小写严格区分：前缀与 _BD 后缀
    is_ge = stem.startswith("GE_") or stem.endswith("_BD")
    is_ga = stem.startswith("GA_")

    # 非 GE / GA（且不满足 _BD 规则）的文件直接跳过
    if not (is_ge or is_ga):
        return

    # 忽略项：GA 且文件名包含 Passive / PASS（按段匹配，大小写不敏感），避免命中如 "bypass"
    if is_ga:
        if re.search(r'(?i)(?:^|_)(passive|pass)(?:_|$)', stem):
            return

    nm_info = build_namemap_from_path(json_path)
    if nm_info is None:
        issues.append(f"[路径无法定位 Skills] {json_path}")
        return
    namemap, base_prefix, middle_parts, name = nm_info

    data = read_json(json_path)
    if data is None:
        issues.append(f"[JSON读取失败] {json_path}")
        return

    # 确认 JSON 内确实包含该 NameMap（完全匹配）
    has_nm = json_contains_value(data, namemap)
    if not has_nm:
        issues.append(f"[NameMap未找到] {json_path} :: {namemap}")

    # 提取 ID / SkillId
    if is_ge:
        ge_id = extract_ge_id(data)
        if ge_id is None:
            issues.append(f"[GE缺少Id] {json_path}")
        else:
            ge_records.append((ge_id, namemap, name))
    else:  # is_ga
        skill_id = extract_ga_skillid(data)
        if skill_id is None:
            issues.append(f"[GA缺少SkillId] {json_path}")
        else:
            ga_records.append((skill_id, namemap, name))

# === 主流程 ===
def main():
    ensure_dir(OUTPUT_DIR)
    ge_records: List[Tuple[int, str, str]] = []  # (id, namemap, name)
    ga_records: List[Tuple[int, str, str]] = []  # (id, namemap, name)
    issues: List[str] = []

    # 扫描与收集
    for root in SEARCH_DIRS:
        if not os.path.isdir(root):
            issues.append(f"[目录不存在] {root}")
            continue
        for dirpath, _, filenames in os.walk(root):
            for fname in filenames:
                if not fname.lower().endswith(".json"):
                    continue
                # 不再用文件名前缀筛选，全部交给 process_file 判定
                process_file(os.path.join(dirpath, fname), issues, ge_records, ga_records)

    # 统一排序（按 ID 升序）
    ge_records.sort(key=lambda x: x[0])
    ga_records.sort(key=lambda x: x[0])

    if FULL_OUTPUT:
        # === 原有完整输出：写 GE_output.txt / GA_output.txt，并在控制台打印报告 ===
        ge_out = os.path.join(OUTPUT_DIR, "GE_output.txt")
        ga_out = os.path.join(OUTPUT_DIR, "GA_output.txt")
        with open(ge_out, "w", encoding="utf-8") as fh:
            for ge_id, namemap, name in ge_records:
                write_block(fh, ge_id, namemap, name)
        with open(ga_out, "w", encoding="utf-8") as fh:
            for skill_id, namemap, name in ga_records:
                write_block(fh, skill_id, namemap, name)

        print("=== 处理完成（完整输出）===")
        print(f"GE 写入：{ge_out}  条目：{len(ge_records)}")
        print(f"GA 写入：{ga_out}  条目：{len(ga_records)}")

        if issues:
            print("\n=== 报告（缺失/异常）===")
            for line in issues:
                print(line)
    else:
        # === 指定输出模式：仅打印；按 GE/GA 分组 ===
        # 先建 id -> (namemap, name) 的索引，便于 O(1) 查找
        ge_index = {i: (nm, n) for (i, nm, n) in ge_records}
        ga_index = {i: (nm, n) for (i, nm, n) in ga_records}

        if not SPECIFY_BUFFIDS and not SPECIFY_SKILLIDS:
            print("[指定输出模式] 请在配置区填写 SPECIFY_BUFFIDS 或 SPECIFY_SKILLIDS（至少一个）。")
        else:
            if SPECIFY_BUFFIDS:
                print("GE：")
                # 按你输入的顺序输出
                for _id in SPECIFY_BUFFIDS:
                    hit = ge_index.get(_id)
                    if hit:
                        nm, n = hit
                        full_c = f"{nm}.{n}_C"
                        print(f'    "{_id}","{full_c}"')   # 找到：带引号，无逗号
                    else:
                        print(f"    [未找到指定 buffid：{_id}]")  # 未找到：不带引号

            if SPECIFY_SKILLIDS:
                print("GA：")
                for _id in SPECIFY_SKILLIDS:
                    hit = ga_index.get(_id)
                    if hit:
                        nm, n = hit
                        full_c = f"{nm}.{n}_C"
                        print(f'    "{_id}","{full_c}"')
                    else:
                        print(f"    [未找到指定 skillid：{_id}]")

        # （可选）仍打印扫描报告，便于排错
        if issues:
            print("\n=== 报告（缺失/异常）===")
            for line in issues:
                print(line)

if __name__ == "__main__":
    main()
