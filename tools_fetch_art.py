# -*- coding: utf-8 -*-
"""自己下牌图：从 Wikimedia 取 1909 年版韦特牌的公有领域扫描件。

仓库里不带图片，需要的人在本机跑一次这个脚本，图会落到 art/。
用法：python tools_fetch_art.py
"""
import io
import os
import pathlib
import time

try:
    import requests
except ImportError:
    raise SystemExit("需要 requests：pip install requests")

BASE = "https://commons.wikimedia.org/wiki/Special:FilePath/"
ART = pathlib.Path(os.path.dirname(os.path.abspath(__file__))) / "art"
ART.mkdir(exist_ok=True)

MAJORS = [
    "RWS_Tarot_00_Fool", "RWS_Tarot_01_Magician", "RWS_Tarot_02_High_Priestess",
    "RWS_Tarot_03_Empress", "RWS_Tarot_04_Emperor", "RWS_Tarot_05_Hierophant",
    "RWS_Tarot_06_Lovers", "RWS_Tarot_07_Chariot", "RWS_Tarot_08_Strength",
    "RWS_Tarot_09_Hermit", "RWS_Tarot_10_Wheel_of_Fortune", "RWS_Tarot_11_Justice",
    "RWS_Tarot_12_Hanged_Man", "RWS_Tarot_13_Death", "RWS_Tarot_14_Temperance",
    "RWS_Tarot_15_Devil", "RWS_Tarot_16_Tower", "RWS_Tarot_17_Star",
    "RWS_Tarot_18_Moon", "RWS_Tarot_19_Sun", "RWS_Tarot_20_Judgement",
    "RWS_Tarot_21_World",
]
SUITS = {"wands": "Wands", "cups": "Cups", "swords": "Swords", "pents": "Pents"}


def fetch(name: str) -> bytes | None:
    """先按系统代理试，走不通再直连。有的机器只有其中一个能出去。"""
    url = BASE + name + ".jpg"
    headers = {"User-Agent": "astrbot-tarot/1.0"}
    for attempt, proxies in (("系统代理", None), ("直连", {})):
        try:
            r = requests.get(url, timeout=40, headers=headers, proxies=proxies)
            if r.status_code == 200 and len(r.content) > 5000:
                return r.content
        except Exception as exc:  # noqa: BLE001
            print(f"  {attempt}失败", name, type(exc).__name__)
    return None


def main() -> None:
    from PIL import Image

    todo = []
    for i, name in enumerate(MAJORS):
        todo.append((f"major_{i:02d}.jpg", name))
    for key, eng in SUITS.items():
        for n in range(1, 15):
            todo.append((f"{key}_{n:02d}.jpg", f"{eng}{n:02d}"))

    for target, src in todo:
        path = ART / target
        if path.exists():
            continue
        data = fetch(src)
        if not data:
            time.sleep(1.5)
            continue
        img = Image.open(io.BytesIO(data)).convert("L")
        w, h = img.size
        # 居中裁成 3:5
        if w / h > 0.6:
            nw = int(h * 0.6)
            img = img.crop(((w - nw) // 2, 0, (w + nw) // 2, h))
        else:
            nh = int(w / 0.6)
            img = img.crop((0, (h - nh) // 2, w, (h + nh) // 2))
        img.resize((300, 500), Image.LANCZOS).save(path, "JPEG", quality=86, optimize=True)
        print("  下载", target)
        time.sleep(0.8)

    print("完成，图片在", ART)


if __name__ == "__main__":
    main()
