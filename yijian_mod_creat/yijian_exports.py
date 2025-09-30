#!# -*- coding: utf-8 -*-
"""
功能：
输出每个Export的详细代码段。
"""

import json
import os
import sys


import os
import sys

def clear_screen():
    print('\n' * 100)

def load_exports(json_path):
    """读取 JSON 并返回编号映射的 exports 列表"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    exports = data.get('Exports', [])
    # 编号从 1 开始
    return {i + 1: exports[i] for i in range(len(exports))}


def main():
    json_path = r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_1\Wandering_Sword\Content\JH\Skills\WD_N_LiuYunTaiJi\GE_WD_N_LiuYunTaiJi_BD.json"
    export_map = load_exports(json_path)
    header = f"共读取到 {len(export_map)} 个 Export 条目。输入编号查看，输入 e 清屏，输入 q 退出。"
    print(header)

    while True:
        choice = input(">> ").strip().lower()
        if choice == 'q':
            print("已退出。")
            break
        if choice == 'e':
            clear_screen()
            print(header)
            continue
        if not choice.isdigit():
            print("❌ 无效输入，请输入数字编号、e 或 q。")
            continue

        idx = int(choice)
        block = export_map.get(idx)
        if block is None:
            print(f"❌ 编号 {idx} 不存在，请重新输入。")
            continue

        # 美化输出整个 JSON 块
        print(json.dumps(block, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
