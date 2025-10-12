# -*- coding: utf-8 -*-
"""
功能：
查找NameMap的重复项，主要用于Buffs。
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

TARGET_KEY_LOWER = "namemap"

def load_json_preserve_pairs(fp: Path):
    # 保留对象顺序与重复键
    with fp.open('r', encoding='utf-8-sig') as f:
        return json.load(f, object_pairs_hook=lambda pairs: pairs)

def is_pairs_object(node):
    return isinstance(node, list) and node and all(isinstance(p, tuple) and len(p) == 2 for p in node)

def walk_find_key(node, path="$"):
    """递归查找 key(不区分大小写) == NameMap/Namemap，返回 [(value, path_str)]"""
    found = []

    if is_pairs_object(node):
        # 对象（以[(k,v), ...]表示）
        for k, v in node:
            subpath = f"{path}.{k}"
            if isinstance(k, str) and k.lower() == TARGET_KEY_LOWER:
                found.append((v, subpath))
            found.extend(walk_find_key(v, subpath))
    elif isinstance(node, dict):
        # 普通 dict（无重复键信息）
        for k, v in node.items():
            subpath = f"{path}.{k}"
            if isinstance(k, str) and k.lower() == TARGET_KEY_LOWER:
                found.append((v, subpath))
            found.extend(walk_find_key(v, subpath))
    elif isinstance(node, list):
        # 普通数组
        for i, v in enumerate(node):
            found.extend(walk_find_key(v, f"{path}[{i}]"))
    # 其它类型无需处理
    return found

def json_hashable(v):
    try:
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(v)

def report_for_namemap(value, path):
    print(f"\n=== 命中 NameMap 位置: {path} ===")
    if is_pairs_object(value):
        # NameMap 是“对象”形式
        keys = [k for k, _ in value]
        cntk = Counter(keys)
        dup_keys = [k for k, c in cntk.items() if c > 1]
        if dup_keys:
            print("[重复键]")
            for k in dup_keys:
                print(f"  键 '{k}' 出现 {cntk[k]} 次")
        else:
            print("[重复键] 未发现")

        v2k = defaultdict(list)
        for k, v in value:
            v2k[json_hashable(v)].append(k)
        dup_vals = {h: ks for h, ks in v2k.items() if len(ks) > 1}
        if dup_vals:
            print("[重复值（不同键映射到相同值）]")
            for h, ks in dup_vals.items():
                print(f"  值 {h} 被这些键共享：{', '.join(map(str, ks))}")
        else:
            print("[重复值（不同键映射到相同值）] 未发现")

    elif isinstance(value, list):
        # NameMap 是数组（你的例子就是这种）
        items = [json_hashable(v) for v in value]
        cnt = Counter(items)
        dups = [(it, n) for it, n in cnt.items() if n > 1]
        if dups:
            print("[数组重复元素]")
            for it, n in dups:
                print(f"  元素 {it} 出现 {n} 次")
        else:
            print("[数组重复元素] 未发现")
    else:
        print(f"[提示] NameMap 类型为 {type(value).__name__}，未定义重复检查。")

def main():
    default_path = r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH\Wandering_Sword\Content\JH\Skills\JH_N_XuanTaiZaoHua\GE_JH_N_XuanzDao.json"
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(default_path)

    if not path.exists():
        print(f"文件不存在：{path}")
        sys.exit(1)

    try:
        data = load_json_preserve_pairs(path)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败：{e}")
        sys.exit(2)

    hits = walk_find_key(data)
    if not hits:
        print("未找到名为 'NameMap/Namemap' 的节点。")
        return

    for value, p in hits:
        report_for_namemap(value, p)

if __name__ == "__main__":
    main()
