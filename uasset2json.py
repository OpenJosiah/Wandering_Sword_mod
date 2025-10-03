# -*- coding: utf-8 -*-
"""
功能：
将主文件夹、副文件夹及其子文件夹的所有uasset文件另存为Json。
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===== 必填路径 =====
EXE   = Path(r"D:\Program Files (x86)\Microsoft Visual Studio\works\UAssetDumpJson\UAssetDumpJson\UAssetDumpJson\bin\Release\net8.0\UAssetDumpJson.exe")
USMAP = Path(r"D:\Unreal_tools\Mappings.usmap")

# ===== 运行模式 =====
# MODE = "all"    # 遍历文件夹及其子文件夹（含可选副文件夹）
# MODE = "single" # 只处理单一文件
MODE = "all"
SKIP_POLICY = "none"   # "exists"：跳过已有json | "mtime"：uasset文件新于json时重跑 | "none"：全部重跑

# 主目录（MODE=all 时生效）
ROOT_DIR = Path(r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_2\Wandering_Sword\Content\JH\Tables")
# MODE=single 时生效（允许不带 .uasset 后缀）
SINGLE_UASSET = Path(r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_1\Wandering_Sword\Content\JH\Skills\CS_D_ShuangFengDao\GE_CS_D_ShuangFengDao_BD.uasset")

# 副文件夹（可选）
SUB_ENABLED = False
SUB_DIRS = [
    Path(r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Core"),
    Path(r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Skills"),
]

# 并行与跳过策略
MAX_WORKERS = 8
ONLY_WITH_UEXP = True #True只处理携带.uexp的.uasset文件；为False时单.uasset文件也处理

WRITE_ERROR_LOG = True
ERROR_LOG_PATH = Path.cwd() / f"uasset2json_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# 临时 usmap 目录（并发时为每个任务准备独立文件，避免锁usmap）
TEMP_DIR = Path(tempfile.gettempdir()) / "uasset_usmap_cache"
TEMP_DIR.mkdir(parents=True, exist_ok=True)


def run_utf8(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", check=False)
    except UnicodeDecodeError:
        p = subprocess.run(cmd, capture_output=True)
        p.stdout = p.stdout.decode("utf-8", "replace")
        p.stderr = p.stderr.decode("utf-8", "replace")
        return p


def make_task_usmap(base_usmap: Path) -> Path:
    """为当前任务准备独立的 usmap：优先硬链接，失败则复制。"""
    dst = TEMP_DIR / f"Mappings_{uuid4().hex}.usmap"
    try:
        os.link(base_usmap, dst)
    except OSError:
        shutil.copy2(base_usmap, dst)
    return dst


def need_process(uasset: Path) -> (bool, str):
    """按 SKIP_POLICY 判定是否处理。"""
    json_path = uasset.with_suffix(".json")
    if SKIP_POLICY == "none":
        return True, ""
    if not json_path.exists():
        return True, ""
    if SKIP_POLICY == "exists":
        return False, f"SKIP exists: {json_path}"
    if SKIP_POLICY == "mtime":
        src_m = uasset.stat().st_mtime
        ue = uasset.with_suffix(".uexp")
        if ue.exists():
            src_m = max(src_m, ue.stat().st_mtime)
        return (src_m > json_path.stat().st_mtime, "SKIP up-to-date: " + str(json_path))
    return True, ""


def try_convert(uasset: Path, use_usmap: bool, local_usmap: Path | None) -> tuple[bool, str, str]:
    """执行一次转换；返回 (ok, brief, detail)。"""
    cmd = [str(EXE), str(uasset)]
    if use_usmap and local_usmap is not None:
        cmd += ["--usmap", str(local_usmap)]
    proc = run_utf8(cmd)
    json_path = uasset.with_suffix(".json")
    ok = (proc.returncode == 0) and json_path.exists()
    if ok:
        return True, f"OK ({'usmap' if use_usmap else 'no-usmap'}): {uasset}", ""
    else:
        detail = [f"ERR ({'usmap' if use_usmap else 'no-usmap'}): {uasset} (code={proc.returncode})"]
        if proc.stdout: detail += ["--- STDOUT ---", proc.stdout.strip()]
        if proc.stderr: detail += ["--- STDERR ---", proc.stderr.strip()]
        return False, f"ERR ({'usmap' if use_usmap else 'no-usmap'}): {uasset}", "\n".join(detail)


def convert_one(uasset: Path):
    """先用 usmap；失败则无 usmap 再试。"""
    need, why = need_process(uasset)
    if not need:
        return True, why, ""

    if ONLY_WITH_UEXP and not uasset.with_suffix(".uexp").exists():
        return True, f"SKIP no .uexp: {uasset}", ""

    if not uasset.exists():
        return False, f"ERR: not found {uasset}", f"ERR: {uasset} (not found)"

    local_usmap = None
    if USMAP.exists():
        try:
            local_usmap = make_task_usmap(USMAP)
        except Exception:
            local_usmap = None

    try:
        if local_usmap is not None:
            ok, brief, detail = try_convert(uasset, use_usmap=True, local_usmap=local_usmap)
            if ok:
                return True, brief, ""
            first_fail_detail = detail
        else:
            first_fail_detail = "WARN: usmap missing or failed to prepare; skip first attempt."

        ok2, brief2, detail2 = try_convert(uasset, use_usmap=False, local_usmap=None)
        if ok2:
            return True, brief2, ""
        else:
            merged = []
            if first_fail_detail:
                merged.append(first_fail_detail)
            merged.append(detail2)
            return False, brief2, "\n\n---- FALLBACK MERGE ----\n\n".join(merged)
    finally:
        try:
            if local_usmap and local_usmap.exists():
                local_usmap.unlink()
        except Exception:
            pass


def resolve_single_uasset(given: Path) -> tuple[Path | None, str]:
    """
    single 模式下解析目标：
    - 允许去掉 .uasset 后缀的输入；
    - 依次尝试：原路径（若已 .uasset）、去掉后再补 .uasset；
    - 若均不存在，返回 None 及说明。
    """
    attempts: list[Path] = []
    if given.suffix.lower() == ".uasset":
        attempts.append(given)
    else:
        attempts.append(given)                     # 用户可能给了“完整无后缀路径”
        attempts.append(given.with_suffix(".uasset"))

    for cand in attempts:
        if cand.suffix.lower() == ".uasset" and cand.exists():
            return cand.resolve(), ""
    return None, "未找到 .uasset 文件：尝试了 " + " | ".join(str(p) for p in attempts)


def collect_files() -> list[Path]:
    """根据 MODE / SUB_ENABLED 收集待处理 .uasset 文件（去重、排序）。"""
    if MODE.lower() == "single":
        resolved, msg = resolve_single_uasset(SINGLE_UASSET)
        if resolved is None:
            print(msg)
            return []
        return [resolved]

    if not ROOT_DIR.exists():
        raise FileNotFoundError(f"根目录不存在: {ROOT_DIR}")

    files = {p.resolve() for p in ROOT_DIR.rglob("*.uasset")}
    if SUB_ENABLED:
        for sub in SUB_DIRS:
            try:
                sub = Path(sub)
                if sub.exists():
                    files |= {p.resolve() for p in sub.rglob("*.uasset")}
            except Exception:
                pass
    return sorted(files)


def main():
    # 基本检查
    missing = []
    if not EXE.exists():
        missing.append(f"转换器不存在: {EXE}")
    if MODE.lower() == "all" and not ROOT_DIR.exists():
        missing.append(f"根目录不存在: {ROOT_DIR}")
    if missing:
        print("初始化失败：\n" + "\n".join(missing))
        return

    files = collect_files()
    total = len(files)
    if total == 0:
        print("没有发现 .uasset 文件。")
        return

    workers = (total if MAX_WORKERS in (None, 0) else MAX_WORKERS)

    successes = failures = 0
    skipped_info = []
    error_details = []
    error_files = []  # 新增：收集失败的uasset路径
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(convert_one, f): f for f in files}
        for fut in as_completed(futures):
            ok, brief, detail = fut.result()
            if brief.startswith("SKIP"):
                skipped_info.append(brief); continue
            if ok:
                successes += 1
            else:
                failures += 1
                error_details.append(detail)
                error_files.append(futures[fut])  # 新增：记下出错的文件
    skipped = len(skipped_info)
    print(f"完成：成功 {successes} / 失败 {failures} / 跳过 {skipped} / 共 {total}")
    if skipped:
        print("跳过（最多10条）：")
        for s in skipped_info[:10]:
            print("  " + s)
    if failures:
        print("失败（最多10条）：")
        for d in error_details[:10]:
            print("  " + d.splitlines()[0])

        # 新增：显式打印失败文件路径（最多10条）
        print("错误文件（最多10条）：")
        for p in error_files[:10]:
            print("  " + str(p))

        if WRITE_ERROR_LOG:
            ERROR_LOG_PATH.write_text("\n\n====\n\n".join(error_details), encoding="utf-8")
            print(f"失败详情日志：{ERROR_LOG_PATH}")

if __name__ == "__main__":
    main()
