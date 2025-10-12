# -*- coding: utf-8 -*-
"""
批量把 UAssetAPI 导出的 JSON 还原为 .uasset（或 .umap）。
"""

# ===== 1) 配置（仅改这里） =====
from pathlib import Path
from datetime import datetime
EXE = Path(r"D:\Unreal_tools\UAssetGUI.exe")  # UAssetGUI 可执行文件

# "all"全文件夹还原 or "single"单个文件还原
MODE = "all"
SKIP_POLICY = "mtime"            # "none" 全部重建；"exists" 目标存在即跳过；"mtime" JSON 更新才重建

# 主文件夹路径
ROOT_DIR = Path(r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_2\Wandering_Sword\Content\JH\Tables")
# Single文件路径
SINGLE_JSON = Path(r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_1\Wandering_Sword\Content\JH\Tables\Buffs.json")

SUB_ENABLED = False  # 是否启用副文件夹遍历
SUB_DIRS = [
    Path(r"D:\Unreal_tools\yijian\Wandering_Sword-WindowsNoEditor_XTZH\Wandering_Sword\Content\JH\Tables"),
]

USE_OUTDIR = False  # False=就地输出；True=镜像输出到 OUT_ROOT
OUT_ROOT = Path(r"D:\Python\pythonProject1\Files\yijian_mod_creat\outputfiles")

DEFAULT_OUTPUT_EXT = ".uasset"   # 需要 .umap 时改为 ".umap"
MAX_WORKERS = 8                  # 并行数

WRITE_ERROR_LOG = True
ERROR_LOG_PATH = Path.cwd() / f"json2uasset_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
# 仅用于“错误文件名清单”（当错误数>10时才会生成）
ERROR_FILES_TXT = Path.cwd() / f"json2uasset_error_files_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
# =================================

# ===== 2) 运行与路径工具 =====
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

def run_utf8(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", check=False)
    except UnicodeDecodeError:
        p = subprocess.run(cmd, capture_output=True)
        p.stdout = p.stdout.decode("utf-8", "replace"); p.stderr = p.stderr.decode("utf-8", "replace")
        return p

def resolve_single_json(given: Path) -> tuple[Path | None, str]:
    tries = [given] + ([given.with_suffix(".json")] if given.suffix.lower() != ".json" else [])
    for c in tries:
        if c.suffix.lower() == ".json" and c.exists():
            return c.resolve(), ""
    return None, "未找到 .json：尝试 " + " | ".join(str(p) for p in tries)

def collect_json_files() -> list[Path]:
    if MODE.lower() == "single":
        f, _msg = resolve_single_json(SINGLE_JSON)
        if f is None:
            return []
        return [f]
    if not ROOT_DIR.exists():
        raise FileNotFoundError(f"根目录不存在: {ROOT_DIR}")
    files = {p.resolve() for p in ROOT_DIR.rglob("*.json")}
    if SUB_ENABLED:
        for sub in SUB_DIRS:
            if sub.exists():
                files |= {p.resolve() for p in sub.rglob("*.json")}
    return sorted(files)

def map_out_path(json_path: Path) -> Path:
    if not USE_OUTDIR:
        return json_path.with_suffix(DEFAULT_OUTPUT_EXT)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        rel = json_path.resolve().relative_to(ROOT_DIR.resolve())
        outp = (OUT_ROOT / rel).with_suffix(DEFAULT_OUTPUT_EXT)
    except Exception:
        outp = (OUT_ROOT / json_path.name).with_suffix(DEFAULT_OUTPUT_EXT)
    outp.parent.mkdir(parents=True, exist_ok=True)
    return outp

# ===== 3) 跳过策略与转换 =====
def need_process(json_path: Path) -> tuple[bool, str, Path]:
    out_asset = map_out_path(json_path)
    if SKIP_POLICY == "none":
        return True, "", out_asset
    if not out_asset.exists():
        return True, "", out_asset
    if SKIP_POLICY == "exists":
        return False, f"SKIP exists: {out_asset}", out_asset
    if SKIP_POLICY == "mtime":
        src_m = json_path.stat().st_mtime
        dst_m = out_asset.stat().st_mtime
        uexp = out_asset.with_suffix(".uexp")
        if uexp.exists():
            dst_m = max(dst_m, uexp.stat().st_mtime)
        return (src_m > dst_m, "SKIP up-to-date: " + str(out_asset), out_asset)
    return True, "", out_asset  # 容错

def try_convert(json_path: Path, out_asset: Path) -> tuple[bool, str, str]:
    if not EXE.exists():
        return False, f"ERR: UAssetGUI 不存在 {EXE}", f"ERR: UAssetGUI 不存在 {EXE}"
    cmd = [str(EXE), "fromjson", str(json_path), str(out_asset)]
    proc = run_utf8(cmd)
    ok = (proc.returncode == 0) and out_asset.exists()
    if ok:
        return True, f"OK: {json_path} -> {out_asset}", ""
    detail = [f"ERR: {json_path} -> {out_asset} (code={proc.returncode})"]
    if proc.stdout: detail += ["--- STDOUT ---", proc.stdout.strip()]
    if proc.stderr: detail += ["--- STDERR ---", proc.stderr.strip()]
    return False, f"ERR: {json_path}", "\n".join(detail)

def convert_one(json_path: Path) -> tuple[bool, str, str]:
    if not json_path.exists():
        return False, f"ERR: not found {json_path}", f"ERR: {json_path} (not found)"
    need, why, out_asset = need_process(json_path)
    if not need:
        return True, why, ""
    out_asset.parent.mkdir(parents=True, exist_ok=True)
    return try_convert(json_path, out_asset)

# ===== 4) 主流程（总结果 + 错误名按规则输出/写入） =====
def main():
    # 初始化失败时，仅输出一次性错误
    missing = []
    if not EXE.exists(): missing.append(f"UAssetGUI 不存在: {EXE}")
    if MODE.lower() == "all" and not ROOT_DIR.exists(): missing.append(f"根目录不存在: {ROOT_DIR}")
    if missing:
        print("初始化失败：" + " | ".join(missing))
        return

    files = collect_json_files()
    total = len(files)
    if total == 0:
        print("完成：成功 0 / 失败 0 / 跳过 0 / 共 0")
        return

    successes = failures = skipped = 0
    error_details = []
    error_files: list[Path] = []

    workers = (total if MAX_WORKERS in (None, 0) else MAX_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(convert_one, f): f for f in files}
        for fut in as_completed(futures):
            src = futures[fut]
            ok, brief, detail = fut.result()
            if brief.startswith("SKIP"):
                skipped += 1
                continue
            if ok:
                successes += 1
            else:
                failures += 1
                error_details.append(detail)
                error_files.append(src)

    # 总结果
    print(f"完成：成功 {successes} / 失败 {failures} / 跳过 {skipped} / 共 {total}")

    # 错误文件名输出策略
    if failures > 0:
        if failures > 10:
            # 只写 txt，不逐条打印
            try:
                ERROR_FILES_TXT.write_text("\n".join(str(p) for p in error_files), encoding="utf-8")
            except Exception:
                # 极端情况下写失败也不打断主流程
                pass
            print(f"错误文件清单已写入：{ERROR_FILES_TXT}")
        else:
            # 直接打印（不写 txt）
            print("错误文件（共{}）：".format(failures))
            for p in error_files:
                print(str(p))

    # 仍保留原有的详细错误日志（但不打印其路径）
    if failures and WRITE_ERROR_LOG:
        try:
            ERROR_LOG_PATH.write_text("\n\n====\n\n".join(error_details), encoding="utf-8")
        except Exception:
            pass

if __name__ == "__main__":
    main()
