#!# -*- coding: utf-8 -*-
"""
功能：
检查输出两文件的NameMap差异项。
"""
import json, argparse, sys

# 默认路径（可直接双击/运行用）
DEFAULT_SRC = r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Tables\Fusions.json"
DEFAULT_DST = r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_2\Wandering_Sword\Content\JH\Tables\Fusions.json"

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def extract_namemap(obj):
    # 兼容常见命名和结构（列表 = 直接当作名字集合；字典 = 用 key 作为名字集合）
    for key in ("NameMap", "Namemap", "name_map", "nameMap"):
        if key in obj:
            nm = obj[key]
            if isinstance(nm, list):
                return set(map(str, nm))
            if isinstance(nm, dict):
                return set(map(str, nm.keys()))
    raise KeyError("未找到 NameMap/Namemap/name_map 字段")

def to_case_map(items):
    m = {}
    for x in items:
        xl = x.lower()
        if xl not in m:  # 保留首次出现的原始大小写
            m[xl] = x
    return m

def main():
    ap = argparse.ArgumentParser(description="比较两个 JSON 的 Namemap 差异（仅输出文件2多出/缺少的项）")
    ap.add_argument("src", nargs="?", default=DEFAULT_SRC, help="JSON 文件1（源）")
    ap.add_argument("dst", nargs="?", default=DEFAULT_DST, help="JSON 文件2（改动）")
    ap.add_argument("--ignore-case", action="store_true", help="忽略大小写比较")
    ap.add_argument("--out", help="将结果写入 JSON（仅含文件2多出/缺少）")
    args = ap.parse_args()

    j1 = load_json(args.src)
    j2 = load_json(args.dst)
    s1 = extract_namemap(j1)
    s2 = extract_namemap(j2)

    if args.ignore_case:
        s1l, s2l = {x.lower() for x in s1}, {x.lower() for x in s2}
        m1, m2 = to_case_map(s1), to_case_map(s2)
        extra_in_file2 = [m2[k] for k in sorted(s2l - s1l)]
        missing_in_file2 = [m1[k] for k in sorted(s1l - s2l)]
    else:
        extra_in_file2 = sorted(s2 - s1)
        missing_in_file2 = sorted(s1 - s2)

    # 只输出文件2的“多出/缺少”
    print(f"文件2多出: {len(extra_in_file2)} 项")
    for x in extra_in_file2:
        print("  +", x)
    print(f"文件2缺少: {len(missing_in_file2)} 项")
    for x in missing_in_file2:
        print("  -", x)

    if args.out:
        result = {
            "extra_in_file2": extra_in_file2,
            "missing_in_file2": missing_in_file2,
            "count": {
                "extra_in_file2": len(extra_in_file2),
                "missing_in_file2": len(missing_in_file2)
            }
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # 直接运行：用默认路径
        main()
    else:
        main()
