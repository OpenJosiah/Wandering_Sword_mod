#!# -*- coding: utf-8 -*-
"""
功能：
输入当前代码段的ObjectName 或 OuterIndex，输出其当前位置以及被谁引用。
"""

import json


def load_exports(json_path):
    """读取 JSON 并返回 exports 列表"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('Exports', [])


def build_index_maps(exports):
    """
    构建两张映射表：
    1. name_to_pos: ObjectName -> [位置…]
    2. outer_to_pos: OuterIndex -> [位置…]
    """
    name_to_pos = {}
    outer_to_pos = {}
    for i, exp in enumerate(exports, start=1):
        name = exp.get('ObjectName', '')
        outer = exp.get('OuterIndex', None)
        name_to_pos.setdefault(name, []).append(i)
        outer_to_pos.setdefault(outer, []).append(i)
    return name_to_pos, outer_to_pos


def main():
    json_path = r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_1\Wandering_Sword\Content\JH\Skills\WD_N_LiuYunTaiJi\GE_WD_N_LiuYunTaiJi_BD.json"
    exports = load_exports(json_path)
    name_map, outer_map = build_index_maps(exports)

    print(f"已加载 {len(exports)} 个 Export 条目。")
    print("输入 ObjectName 或 OuterIndex，可多次查询；输入 q 退出。")

    while True:
        key = input(">> ").strip()
        if key.lower() == 'q':
            print("退出。")
            break

        # 先尝试按 OuterIndex 查找
        found = False
        try:
            idx = int(key)
            pos_list = outer_map.get(idx, [])
            if pos_list:
                found = True
                print(f"OuterIndex = {idx} 对应位置：{pos_list}")
                for pos in pos_list:
                    obj = exports[pos - 1].get('ObjectName', '')
                    print(f"  {pos}: ObjectName = {obj}")
        except ValueError:
            pass

        # 再按 ObjectName 查找
        pos_list = name_map.get(key, [])
        if pos_list:
            found = True
            print(f"ObjectName = '{key}' 对应位置：{pos_list}")
            for pos in pos_list:
                outer = exports[pos - 1].get('OuterIndex', None)
                print(f"  {pos}: OuterIndex = {outer}")

        if not found:
            print("❌ 未找到匹配，请确认输入是否正确。")


if __name__ == '__main__':
    main()
