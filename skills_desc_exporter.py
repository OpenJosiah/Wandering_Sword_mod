# -*- coding: utf-8 -*-
"""
功能：
将Skills文件按照ID+名称+描述格式输出为Excel表。
"""

import json
import os
import re
from typing import Any, Dict, Generator, List, Optional, Tuple

import pandas as pd

# ===== 路径配置 =====
INPUT_SKILLS_PATH = r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_1\Wandering_Sword\Content\JH\Tables\Skills.json"
OUTPUT_XLSX = "skills描述.xlsx"

# ===== 工具函数 =====
def iter_nodes(obj: Any) -> Generator[Dict[str, Any], None, None]:
    """深度优先遍历 JSON，产出所有 dict 节点。"""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from iter_nodes(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_nodes(item)

def is_skill_setting(node: Dict[str, Any]) -> bool:
    """判断是否为 SkillSetting 结构。"""
    t = node.get("$type", "")
    return (
        isinstance(t, str)
        and t.endswith("StructPropertyData, UAssetAPI")
        and node.get("StructType") == "SkillSetting"
        and isinstance(node.get("Value"), list)
    )

def extract_text_from_textproperty(prop: Dict[str, Any]) -> Optional[str]:
    """
    从 TextPropertyData 提取文本：
    优先取 CultureInvariantString；若无，则回退到 Value（某些导出会把原文放到 Value）。
    """
    if not isinstance(prop, dict):
        return None
    if str(prop.get("$type", "")).endswith("TextPropertyData, UAssetAPI"):
        cis = prop.get("CultureInvariantString")
        if isinstance(cis, str) and cis.strip():
            return cis
        val = prop.get("Value")
        if isinstance(val, str) and val.strip():
            return val
    return None

_TAG_RE = re.compile(r"<[^>]+>")  # 去除如 <skill_flags ...>、</> 等

def strip_markup(text: str) -> str:
    """移除 <...> 标记，只保留纯文本；同时规范化换行与空白。"""
    if not isinstance(text, str):
        return ""
    # 去标签
    clean = _TAG_RE.sub("", text)
    # 统一换行符并去除尾随空白
    clean = clean.replace("\r\n", "\n").replace("\r", "\n").strip()
    return clean

def extract_skill_fields(skill_node: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    提取 (skill_id, name_text, desc_text)
    - skill_id: 该结构的 "Name"
    - name_text: Value 中 Name=="ViewName" 的文本
    - desc_text: Value 中 Name=="SpecialEffectDesc" 的文本（去除标记）
    """
    skill_id = str(skill_node.get("Name", "")).strip()
    name_text = ""
    desc_text = ""

    for entry in skill_node.get("Value", []):
        if not isinstance(entry, dict):
            continue
        entry_name = entry.get("Name")
        if entry_name == "ViewName":
            t = extract_text_from_textproperty(entry)
            if t:
                name_text = t.strip()
        elif entry_name == "SpecialEffectDesc":
            t = extract_text_from_textproperty(entry)
            if t:
                desc_text = strip_markup(t)

    return skill_id, name_text, desc_text

def collect_skills_from_exports(data: Any) -> List[Tuple[str, str, str]]:
    """
    仅遍历 Exports（若缺失，则回退到全局递归，增强鲁棒性），收集所有 SkillSetting。
    """
    rows: List[Tuple[str, str, str]] = []

    def process_node(node: Dict[str, Any]) -> None:
        if is_skill_setting(node):
            skill_id, name_text, desc_text = extract_skill_fields(node)
            if skill_id:  # 仅导出有 ID 的项
                rows.append((skill_id, name_text, desc_text))

    exports = data.get("Exports") if isinstance(data, dict) else None
    if isinstance(exports, list):
        # 先处理顶层 Exports 的每个节点
        for node in exports:
            if isinstance(node, dict):
                process_node(node)
            # Exports 节点内有时还会嵌套结构，递归其子项
            for sub in iter_nodes(node):
                if sub is node:
                    continue
                process_node(sub)
    else:
        # 回退：全局递归
        for node in iter_nodes(data):
            if isinstance(node, dict):
                process_node(node)

    return rows

# ===== 主流程 =====
def main():
    if not os.path.isfile(INPUT_SKILLS_PATH):
        raise FileNotFoundError(f"找不到输入文件：{INPUT_SKILLS_PATH}")

    with open(INPUT_SKILLS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = collect_skills_from_exports(data)

    out_path = os.path.join(os.getcwd(), OUTPUT_XLSX)
    df = pd.DataFrame(rows, columns=["SkillID", "Name", "Description"])
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Skills")

    print(f"已导出 {len(rows)} 条技能记录到：{out_path}")

if __name__ == "__main__":
    main()
