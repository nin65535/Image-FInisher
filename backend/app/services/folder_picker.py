from __future__ import annotations


def pick_folder() -> str | None:
    """Open the Windows native folder picker and return the selected path."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(parent=root, title="入力フォルダを選択")
        return selected or None
    finally:
        root.destroy()
