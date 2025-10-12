# -*- coding: utf-8 -*-
import json
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from pathlib import Path

# === 配置：任务 JSON 路径（按需修改/保持不变） ===
QUESTS_JSON_PATH = Path(r"D:\Unreal_tools\original_files\Wandering_Sword\Content\JH\Tables\Quests.json")

def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        messagebox.showerror("错误", f"找不到文件：\n{path}")
    except json.JSONDecodeError as e:
        messagebox.showerror("错误", f"JSON 解析失败：\n{e}")
    except Exception as e:
        messagebox.showerror("错误", f"读取失败：\n{e}")
    return None

def iter_quest_blocks(obj):
    """
    递归遍历，产出所有 'StructType' == 'QuestSetting' 的块（原样 dict）。
    """
    if isinstance(obj, dict):
        # 先判断当前节点是否是 QuestSetting
        stype = obj.get("StructType")
        if stype == "QuestSetting":
            yield obj
        # 递归子节点
        for v in obj.values():
            yield from iter_quest_blocks(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from iter_quest_blocks(x)

def block_matches_id(block: dict, qid: str) -> bool:
    """
    匹配规则：
    1) block['Name'] 与 qid 字符串相等；
    2) 或在 block['Value']（数组）中找到 Name=='QuestId' 且 Value==qid(整数)。
    """
    # 规则1：Name 直接匹配（注意 JSON 中 Name 常为字符串）
    if str(block.get("Name")) == str(qid):
        return True

    # 规则2：内部 QuestId 匹配
    try:
        want = int(qid)
    except ValueError:
        return False

    vals = block.get("Value")
    if isinstance(vals, list):
        for item in vals:
            if (
                isinstance(item, dict)
                and item.get("Name") == "QuestId"
                and item.get("Value") == want
            ):
                return True
    return False

def find_blocks_by_id(data, qid: str):
    return [b for b in iter_quest_blocks(data) if block_matches_id(b, qid)]

def do_search():
    qid = entry_id.get().strip()
    output.delete("1.0", tk.END)

    if not qid:
        messagebox.showwarning("提示", "请输入任务 ID。")
        return

    data = load_json(QUESTS_JSON_PATH)
    if data is None:
        return

    blocks = find_blocks_by_id(data, qid)
    if not blocks:
        output.insert(tk.END, f"未找到任务 ID = {qid} 的代码段。\n")
        return

    # 若找到多个，全部输出，之间用分隔线
    for idx, blk in enumerate(blocks, 1):
        if len(blocks) > 1:
            output.insert(tk.END, f"—— 匹配 {idx}/{len(blocks)} ——\n")
        output.insert(
            tk.END,
            json.dumps(blk, ensure_ascii=False, indent=2) + "\n"
        )
        if idx != len(blocks):
            output.insert(tk.END, "\n" + "=" * 80 + "\n\n")

def copy_all():
    text = output.get("1.0", tk.END)
    if not text.strip():
        messagebox.showinfo("提示", "没有可复制的内容。")
        return
    root.clipboard_clear()
    root.clipboard_append(text)
    messagebox.showinfo("提示", "已复制到剪贴板。")

# === UI ===
root = tk.Tk()
root.title("任务代码段提取器（输入 ID -> 输出代码段）")
root.geometry("880x640")

frm_top = ttk.Frame(root, padding=10)
frm_top.pack(side=tk.TOP, fill=tk.X)

ttk.Label(frm_top, text="任务ID：").pack(side=tk.LEFT)
entry_id = ttk.Entry(frm_top, width=20)
entry_id.pack(side=tk.LEFT, padx=(4, 10))
entry_id.focus()

btn_search = ttk.Button(frm_top, text="查找", command=do_search)
btn_search.pack(side=tk.LEFT, padx=(0, 10))

btn_copy = ttk.Button(frm_top, text="复制输出", command=copy_all)
btn_copy.pack(side=tk.LEFT)

ttk.Label(frm_top, text=f"数据源：{QUESTS_JSON_PATH}", foreground="#666").pack(side=tk.LEFT, padx=12)

output = ScrolledText(root, wrap=tk.NONE, undo=False, font=("Consolas", 10))
output.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0,10))

# 绑定回车直接搜索
root.bind("<Return>", lambda e: do_search())

root.mainloop()
