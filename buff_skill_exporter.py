# -*- coding: utf-8 -*-
"""
功能：
1) 读取 Buffs.json / Skills.json，遍历 Exports 中的 BuffSetting / SkillSetting。
2) 提取字段：
   - Buff：ID(Name) / ViewName / Description
   - Skill：ID(Name) / ViewName
3) 支持按遍历顺序的起止 ID 过滤（起始含，结束不含）。
4) 导出为一个 Excel（两工作表：Buffs、Skills）到指定目录。
"""


import json
import os
from typing import Any, Dict, Generator, List, Optional, Tuple
import pandas as pd

# ==== 输入与输出配置 ====
buffs  = r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_1\Wandering_Sword\Content\JH\Tables\Buffs.json"
skills = r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_1\Wandering_Sword\Content\JH\Tables\Skills.json"

OUTPUT_XLSX = "buffs和skills.xlsx"
FIXED_OUTPUT_DIR = r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles"
OUTPUT_TO_FIXED_DIR = True  # True: 输出到指定路径；False: 输出到程序当前目录

# ==== 采集范围（按遍历顺序；None 表示不限制；结束ID不包含在结果中）====
BUFF_ID_START: Optional[str] = None
BUFF_ID_END:   Optional[str] = None  # 兼容旧逻辑
SKILL_ID_START: Optional[str] = None
SKILL_ID_END:   Optional[str] = None  # 兼容旧逻辑

def iter_nodes(obj: Any) -> Generator[Dict[str, Any], None, None]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from iter_nodes(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_nodes(item)

# ===== Buffs =====

def is_buff_setting(node: Dict[str, Any]) -> bool:
    t = node.get("$type", "")
    return (
        isinstance(t, str)
        and t.endswith("StructPropertyData, UAssetAPI")
        and node.get("StructType") == "BuffSetting"
        and isinstance(node.get("Value"), list)
    )

def extract_text_from_textproperty(prop: Dict[str, Any]) -> Optional[str]:
    if not isinstance(prop, dict):
        return None
    if str(prop.get("$type", "")).endswith("TextPropertyData, UAssetAPI"):
        cis = prop.get("CultureInvariantString")
        if isinstance(cis, str) and cis.strip():
            return cis.strip()
        val = prop.get("Value")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None

def extract_buff_fields(buff_node: Dict[str, Any]) -> Tuple[str, str, str]:
    buff_id = str(buff_node.get("Name", "")).strip()
    name_text, desc_text = "", ""
    for entry in buff_node.get("Value", []):
        if not isinstance(entry, dict):
            continue
        entry_name = entry.get("Name")
        if entry_name == "ViewName":
            txt = extract_text_from_textproperty(entry)
            if txt:
                name_text = txt
        elif entry_name == "Description":
            txt = extract_text_from_textproperty(entry)
            if txt:
                desc_text = txt
        if name_text and desc_text:
            break
    return buff_id, name_text, desc_text

def collect_buffs(data: Any) -> List[Tuple[str, str, str]]:
    rows: List[Tuple[str, str, str]] = []
    started = BUFF_ID_START is None

    def process_node(node: Dict[str, Any]) -> bool:
        nonlocal started
        if not is_buff_setting(node):
            return True
        buff_id, name_text, desc_text = extract_buff_fields(node)
        if not buff_id:
            return True

        if not started and BUFF_ID_START is not None and buff_id == BUFF_ID_START:
            started = True  # 从起始ID这一条开始收集

        if BUFF_ID_END is not None and buff_id == BUFF_ID_END:
            return False  # 碰到结束ID即停止，不收集该条

        if started:
            rows.append((buff_id, name_text, desc_text))
        return True

    exports = data.get("Exports") if isinstance(data, dict) else None
    if isinstance(exports, list):
        for node in exports:
            if isinstance(node, dict):
                if not process_node(node):
                    break
            for sub in iter_nodes(node):
                if sub is node:
                    continue
                if not process_node(sub):
                    return rows
    else:
        for node in iter_nodes(data):
            if isinstance(node, dict):
                if not process_node(node):
                    break
    return rows

# ===== Skills =====

def is_skill_setting(node: Dict[str, Any]) -> bool:
    t = node.get("$type", "")
    return (
        isinstance(t, str)
        and t.endswith("StructPropertyData, UAssetAPI")
        and node.get("StructType") == "SkillSetting"
        and isinstance(node.get("Value"), list)
    )

def extract_skill_fields(skill_node: Dict[str, Any]) -> Tuple[str, str]:
    skill_id = str(skill_node.get("Name", "")).strip()
    name_text = ""
    for entry in skill_node.get("Value", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("Name") == "ViewName":
            txt = extract_text_from_textproperty(entry)
            if txt:
                name_text = txt
                break
    return skill_id, name_text

def collect_skills(data: Any) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    started = SKILL_ID_START is None

    def process_node(node: Dict[str, Any]) -> bool:
        nonlocal started
        if not is_skill_setting(node):
            return True
        skill_id, name_text = extract_skill_fields(node)
        if not skill_id:
            return True

        if not started and SKILL_ID_START is not None and skill_id == SKILL_ID_START:
            started = True

        if SKILL_ID_END is not None and skill_id == SKILL_ID_END:
            return False  # 不包含结束ID

        if started:
            rows.append((skill_id, name_text))
        return True

    exports = data.get("Exports") if isinstance(data, dict) else None
    if isinstance(exports, list):
        for node in exports:
            if isinstance(node, dict):
                if not process_node(node):
                    break
            for sub in iter_nodes(node):
                if sub is node:
                    continue
                if not process_node(sub):
                    return rows
    else:
        for node in iter_nodes(data):
            if isinstance(node, dict):
                if not process_node(node):
                    break
    return rows

# ================== 入口 ==================

def main():
    if not os.path.isfile(buffs):
        raise FileNotFoundError(f"找不到输入文件：{buffs}")
    with open(buffs, "r", encoding="utf-8") as f:
        buffs_data = json.load(f)
    buff_rows = collect_buffs(buffs_data)

    if not os.path.isfile(skills):
        raise FileNotFoundError(f"找不到输入文件：{skills}")
    with open(skills, "r", encoding="utf-8") as f:
        skills_data = json.load(f)
    skill_rows = collect_skills(skills_data)

    out_dir = FIXED_OUTPUT_DIR if OUTPUT_TO_FIXED_DIR else os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, OUTPUT_XLSX)

    df_buffs = pd.DataFrame(buff_rows, columns=["BuffID", "Name", "Description"])
    df_skills = pd.DataFrame(skill_rows, columns=["SkillID", "Name"])
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df_buffs.to_excel(writer, index=False, sheet_name="Buffs")
        df_skills.to_excel(writer, index=False, sheet_name="Skills")

    print(f"已导出 Buff 记录 {len(buff_rows)} 条、Skill 记录 {len(skill_rows)} 条 到：{out_path}")

    if BUFF_ID_END is not None:
        print(f"Buffs：按遍历顺序从 {BUFF_ID_START or '文件开头'} 收集，遇到 {BUFF_ID_END} 即停止（不含该条）。")
    if SKILL_ID_END is not None:
        print(f"Skills：按遍历顺序从 {SKILL_ID_START or '文件开头'} 收集，遇到 {SKILL_ID_END} 即停止（不含该条）。")

if __name__ == "__main__":
    main()
