# -*- coding: utf-8 -*-
"""
功能：
删除主文件夹、副文件夹及其子文件夹的.bak和.json文件。
"""

import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===== 主根目录 =====
ROOT_DIR = Path(r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_1\Wandering_Sword\Content\JH\Skills")

# 副文件夹支持（True 启用，False 关闭）
SUB_ENABLED = True
SUB_DIRS = [
    Path(r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Core"),
    Path(r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Skills"),
]

# 始终删除 .bak；是否删除 .json
DELETE_JSON = True

# 可选：演练模式（不真正删除）
DRY_RUN = False

# ★ 新增：并行删除
PARALLEL_ENABLED = True                # True 并行；False 顺序
MAX_WORKERS = min(8, (os.cpu_count() or 4) * 2)  # 并发上限（可按机器调）

def should_delete(p: Path) -> bool:
    """是否需要删除该文件：.bak 一律删除；.json 取决于 DELETE_JSON。"""
    try:
        if not p.is_file():
            return False
        ext = p.suffix.casefold()
        if ext == ".bak":
            return True
        if ext == ".json":
            return DELETE_JSON
        return False
    except Exception:
        return False

def iter_files_recursive(root: Path):
    """递归产出 root 下的所有文件路径。"""
    for p in root.rglob("*"):
        if p.is_file():
            yield p

def collect_targets() -> list[Path]:
    """汇总 ROOT_DIR +（可选）SUB_DIRS 中所有需删除的文件（去重）。"""
    roots: list[Path] = [ROOT_DIR]
    if SUB_ENABLED:
        for d in SUB_DIRS:
            d = Path(d)
            if d.exists() and d.is_dir():
                roots.append(d)

    # 校验
    for r in roots:
        if not r.exists() or not r.is_dir():
            raise FileNotFoundError(f"路径不存在或不是文件夹：{r}")

    seen: set[Path] = set()
    candidates: list[Path] = []
    for root in roots:
        for p in iter_files_recursive(root):
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            if should_delete(rp):
                candidates.append(rp)
    return candidates

def delete_one(p: Path) -> tuple[bool, int, int, str]:
    """
    删除单个文件。
    返回：(ok, bytes, err_flag, msg)
      ok: 是否删除成功（或DRY_RUN视作成功）
      bytes: 文件大小（删除前统计）
      err_flag: 是否产生错误（1/0）
      msg: 打印信息（供顺序模式或必要时调试输出）
    """
    try:
        size = p.stat().st_size
    except Exception as e:
        return (False, 0, 1, f"[错误] 读取大小失败：{p} —— {e}")

    if DRY_RUN:
        return (True, size, 0, f"[DRY-RUN] 将删除：{p}")

    try:
        p.unlink()
        return (True, size, 0, f"已删除：{p}")
    except Exception as e:
        return (False, 0, 1, f"[错误] 无法删除：{p} —— {e}")

def main():
    targets = collect_targets()
    total = 0
    total_bytes = 0
    errors = 0

    if not targets:
        print("没有匹配到需要删除的文件。")
    else:
        if PARALLEL_ENABLED:
            # 并行删除（默认不逐条打印；如需可打印 msg）
            workers = max(1, MAX_WORKERS)
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(delete_one, p) for p in targets]
                for fut in as_completed(futs):
                    ok, size, err, _msg = fut.result()
                    total += 1 if (ok or err) else 0
                    total_bytes += size if ok else 0
                    errors += err
        else:
            # 顺序删除（逐条打印）
            for p in targets:
                ok, size, err, msg = delete_one(p)
                print(msg)
                total += 1 if (ok or err) else 0
                total_bytes += size if ok else 0
                errors += err

    mb = total_bytes / (1024 * 1024) if total_bytes else 0.0
    mode = "演练(DRY-RUN)" if DRY_RUN else "实际删除"

    print("-" * 60)
    print(f"模式：{mode}")
    print(f"主根目录：{ROOT_DIR}")
    print(f"副文件夹启用：{SUB_ENABLED}")
    if SUB_ENABLED:
        for d in SUB_DIRS:
            print(f"  - {d}")
    print(f"DELETE_JSON：{DELETE_JSON}")
    print(f"并行删除：{PARALLEL_ENABLED}（MAX_WORKERS={MAX_WORKERS}）")
    print(f"共匹配并{'计划' if DRY_RUN else '成功/尝试'}删除文件数：{len(targets)}")
    print(f"成功删除文件数：{total - errors}")
    print(f"累计字节：{total_bytes}  (~{mb:.2f} MB)")
    print(f"错误数：{errors}")

if __name__ == "__main__":
    main()