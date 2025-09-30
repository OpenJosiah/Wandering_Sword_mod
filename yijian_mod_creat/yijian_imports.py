#!# -*- coding: utf-8 -*-
"""
功能：
输出每个Import包位置以及他的索引。
"""

import json
import pandas as pd

# 你的 JSON 文件路径
json_path = r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH\Wandering_Sword\Content\JH\Skills\JH_N_GuaiDanZhiYue\GE_XinYang.json"

# 载入并提取 Imports
with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)
imports = data.get('Imports', [])

# 1. 构建 子对象 映射：-1→第1个 ObjectName，-2→第2个…
child_map = { -i: imp.get('ObjectName', '') for i, imp in enumerate(imports, start=1) }

# 2. 同步提取 OuterIndex 列表，并构建 OuterIndex 标签映射：-1→第1个 OuterIndex，-2→第2个…
outer_list = [imp.get('OuterIndex', 0) for imp in imports]
outer_map = { -i: idx for i, idx in enumerate(outer_list, start=1) }

# 3. 逐条生成“子→父”对，跳过反向重复，OuterIndex=0 标为父 0
seen_edges = set()
rows = []

for i, imp in enumerate(imports, start=1):
    child_label = -i
    child_name  = child_map[child_label]
    parent_index = outer_list[i-1]

    # 定位 parent_label 和 parent_name
    if parent_index == 0:
        parent_label = 0
        parent_name  = ''
    elif parent_index in child_map:
        parent_label = parent_index
        parent_name  = child_map[parent_label]
    else:
        # 在 outer_map 里找到对应标签 -j，使其值等于 parent_index
        parent_label = next((lbl for lbl, idx in outer_map.items() if idx == parent_index), parent_index)
        parent_name  = child_map.get(parent_label, '')

    # 跳过与已有记录反向重复的条目
    edge_key = frozenset((child_label, parent_label))
    if edge_key in seen_edges:
        continue
    seen_edges.add(edge_key)

    rows.append({
        '子对象': f'{child_label}（{child_name}）',
        '父对象': f'{parent_label}（{parent_name}）'
    })

# 输出结果表格
df = pd.DataFrame(rows)
print(df.to_string(index=False))
