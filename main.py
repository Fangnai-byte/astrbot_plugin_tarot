# -*- coding: utf-8 -*-
"""塔罗占卜：发一张（或三张）手绘卡片。

- `/塔罗 [问题]` 抽一张，正逆随机
- `/塔罗 三张 [问题]` 过去 / 现在 / 未来，三张不重复
- `/塔罗 牌 <名字>` 翻某张牌的牌义
- `/塔罗 帮助`

卡片用 Pillow 画，不依赖浏览器，也不联网；临时图写在 AstrBot 的临时目录。
"""
from __future__ import annotations

import asyncio
import os
import re
import random
import time
from datetime import datetime
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

try:  # 包加载 / 单文件加载都能跑
    from .tarot_data import DECK
    from . import card_render
    from . import spreads as spread_defs
except ImportError:  # pragma: no cover
    from tarot_data import DECK
    import card_render
    import spreads as spread_defs

PLUGIN_NAME = "astrbot_plugin_tarot"
TAG = "[tarot]"
CARD_DIR_KEEP = 40

_rng = random.SystemRandom()


def _cfg(config: Any, key: str, default: Any) -> Any:
    try:
        value = config.get(key, default)
    except Exception:
        return default
    return default if value is None else value


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "是")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _as_list(value: Any) -> list:
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [x.strip() for x in value.replace("，", ",").split(",") if x.strip()]
    return []


def _renderer_for(layout: str):
    """牌阵布局 → 渲染函数。"""
    if layout == "cross":
        return card_render.render_cross
    if layout == "celtic":
        return card_render.render_celtic
    return card_render.render_spread


def plugin_data_dir() -> str:
    """持久化目录：data/plugin_data/astrbot_plugin_tarot/（只放上一局记录）。"""
    try:
        from astrbot.core.star.star_tools import StarTools

        base = str(StarTools.get_data_dir(PLUGIN_NAME))
    except Exception:
        here = os.path.dirname(os.path.abspath(__file__))
        base = os.path.join(os.path.dirname(os.path.dirname(here)),
                            "plugin_data", PLUGIN_NAME)
    os.makedirs(base, exist_ok=True)
    return base


def last_draw_path() -> str:
    return os.path.join(plugin_data_dir(), "last_draw.json")


def load_last_draws() -> dict:
    import json

    path = last_draw_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("%s 读取上一局失败: %s", TAG, exc)
        return {}


def save_last_draw(key: str, record: dict, keep: int = 60) -> None:
    """记下这一局。只留最近 keep 个，别越存越大。"""
    import json

    data = load_last_draws()
    data[key] = record
    if len(data) > keep:
        ordered = sorted(data.items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)
        data = dict(ordered[:keep])
    path = last_draw_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("%s 保存上一局失败: %s", TAG, exc)


def history_path() -> str:
    return os.path.join(plugin_data_dir(), "history.json")


def load_history() -> dict:
    import json

    path = history_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("%s 读取提问史失败: %s", TAG, exc)
        return {}


def history_rows(uid: str) -> list:
    """取某个人的提问史，脏数据一律当空。"""
    raw = load_history().get(uid)
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def save_history(uid: str, entry: dict, keep: int = 60) -> None:
    """记一条提问。每人只留最近 keep 条，旧的丢掉。"""
    import json

    data = load_history()
    items = data.get(uid)
    if not isinstance(items, list):
        items = []
    items = [row for row in items if isinstance(row, dict)]
    items.append(entry)
    data[uid] = items[-keep:]
    path = history_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("%s 保存提问史失败: %s", TAG, exc)


def question_key(text: str) -> str:
    """把问题归一：去空白、去标点、统一小写。只差个标点算同一个问题。"""
    if not text:
        return ""
    drop = set(" \t\r\n，。！？、；：,.!?;:\"'“”‘’()（）[]【】…—~～")
    return "".join(ch for ch in text.lower() if ch not in drop)


def card_dir() -> str:
    """卡片临时图目录：AstrBot 的 temp 目录下，不进插件目录。"""
    path = os.path.join(get_astrbot_temp_path(), "tarot_cards")
    os.makedirs(path, exist_ok=True)
    return path


def prune_cards(keep: int = CARD_DIR_KEEP) -> None:
    """只留最近几张，别把临时目录堆满。"""
    try:
        folder = card_dir()
        files = [os.path.join(folder, n) for n in os.listdir(folder)
                 if n.endswith((".png", ".jpg"))]
        if len(files) <= keep:
            return
        files.sort(key=os.path.getmtime)
        for path in files[:-keep]:
            try:
                os.remove(path)
            except OSError:
                pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("%s 清理旧卡片失败: %s", TAG, exc)


def pick(allow_reversed: bool = True) -> tuple[dict, bool]:
    """抽一张：牌和正逆位都随机。"""
    card = _rng.choice(DECK)
    reversed_ = bool(allow_reversed) and _rng.random() < 0.5
    return card, reversed_




def draw_spread(key: str, reversed_ratio: float = 0.35) -> tuple[dict, list[tuple]]:
    """按牌阵抽牌，返回（牌阵定义, [(牌, 逆位?, 位置名, 位置含义), ...]）。

    reversed_ratio 是逆位出现的概率，默认 35%。真实占卜里逆位没有一半那么多。
    """
    info = spread_defs.spread(key)
    positions = info["positions"]
    ratio = max(0.0, min(1.0, float(reversed_ratio)))
    cards = _rng.sample(DECK, len(positions))
    items = [
        (card, _rng.random() < ratio, pos, mean)
        for card, (pos, mean) in zip(cards, positions)
    ]
    return info, items


SUIT_THEME = {
    "杖": "行动和热情",
    "杯": "情绪和关系",
    "剑": "想法和冲突",
    "钱": "现实和积累",
    "权杖": "行动和热情",
    "圣杯": "情绪和关系",
    "宝剑": "想法和冲突",
    "星币": "现实和积累",
}


def _rank_of(card: dict) -> str:
    """从中文名里去掉花色，剩下就是点数：权杖八 → 八。"""
    suit = card.get("suit") or ""
    name = card.get("name_cn") or ""
    return name[len(suit):] if suit and name.startswith(suit) else ""


def relation_notes(items: list[tuple]) -> list[str]:
    """牌与牌之间能读出点什么。没有就返回空列表，不硬凑。"""
    notes = []
    total = len(items)
    if total < 2:
        return notes

    suits: dict[str, int] = {}
    ranks: dict[str, int] = {}
    for card, _rev, _pos, _mean in items:
        suit = card.get("suit")
        if suit:
            suits[suit] = suits.get(suit, 0) + 1
            rank = _rank_of(card)
            if rank:
                ranks[rank] = ranks.get(rank, 0) + 1

    for suit, n in sorted(suits.items(), key=lambda kv: -kv[1]):
        if n >= 3:
            notes.append(f"{suit}出了 {n} 张，重心在{SUIT_THEME.get(suit, '这一块')}上。")

    for rank, n in sorted(ranks.items(), key=lambda kv: -kv[1]):
        if n >= 2:
            label = rank if rank.isdigit() or rank in ("一", "二", "三", "四", "五", "六", "七",
                                                     "八", "九", "十") else rank + "牌"
            notes.append(f"两张{label}，同一个课题又出现一遍，两张对着看。")

    rev_positions = [i for i, (_c, rev, _p, _m) in enumerate(items) if rev]
    if len(rev_positions) >= 2:
        front_end = total // 2
        front = sum(1 for i in rev_positions if i < front_end)
        back = len(rev_positions) - front
        if front >= 2 and back == 0:
            notes.append("逆位压在开头，卡点在最开始那一步。")
        elif back >= 2 and front == 0:
            notes.append("逆位落在后面，过程没事，收尾出了岔子。")

    majors = sum(1 for card, *_ in items if card.get("arcana") == "major")
    if majors * 2 > total:
        notes.append("大阿卡纳过半，这事不小，也不是三五天能过去的。")

    return notes


CHOICE_WORDS = ("要不要", "该不该", "能不能", "会不会", "是不是", "行不行", "可不可以", "值得吗")
FORECAST_WORDS = ("运势", "运气", "会发生", "会怎样", "怎么样", "如何", "什么情况", "顺利")
HOW_WORDS = ("怎么办", "怎么做", "如何做", "该做什么", "建议", "怎么处理")


def question_kind(question: str) -> str:
    """问题归个类，决定收尾怎么接。"""
    q = (question or "").strip()
    if not q:
        return ""
    if any(w in q for w in CHOICE_WORDS):
        return "choice"
    if any(w in q for w in HOW_WORDS):
        return "how"
    if any(w in q for w in FORECAST_WORDS):
        return "forecast"
    return "other"


def _answer_line(items: list, question: str) -> str:
    """按问题类型，用牌面直接回一句。"""
    kind = question_kind(question)
    if not kind or not items:
        return ""

    last_card, last_rev, last_pos, _m = items[-1]
    words = last_card.get("keywords") or []
    tone = "、".join(words[:2]) if words else ""
    state = "逆位" if last_rev else "正位"

    if kind == "choice":
        if last_rev:
            return (f"照这个走向，硬做不顺。{last_card['name_cn']}逆位卡在{last_pos}，"
                    f"拆小一点先试，比一次做满稳。")
        return f"照这个走向，可以做。{last_pos}是{last_card['name_cn']}正位，方向对。"

    if kind == "forecast":
        if tone:
            return f"主调是{tone}。{last_pos}的{last_card['name_cn']}（{state}）定的调。"
        return f"主调看{last_pos}那张，{last_card['name_cn']}（{state}）。"

    if kind == "how":
        adv = next((it for it in items if it[2] in ("建议", "行动")), None)
        if adv:
            card, rev, pos, _mean = adv
            body = card["reversed"] if rev else card["upright"]
            return f"先照「{pos}」那张做。{body}"
        return f"从{last_pos}开始动。{last_card['reversed'] if last_rev else last_card['upright']}"

    return ""


def _tail_line(items: list[tuple]) -> str:
    """按逆位数量给一句整体判断。"""
    total = len(items)
    reversed_count = sum(1 for _c, rev, _p, _m in items if rev)
    if total == 1:
        return ""
    if reversed_count == 0:
        return "一张逆位都没有，事情比你想的顺，该走就走。"
    if reversed_count * 2 > total:
        return "逆位偏多，卡的地方多半在你自己这边。"
    if reversed_count * 2 == total:
        return "正逆各半，一半在推一半在拖，先认最不想认的那张。"
    return "整体顺，只有一两处别扭，把那一处解决掉。"


def compose_reading(items: list[tuple], question: str = "",
                    tail: bool = True, notes: bool = True,
                    groups: list | None = None,
                    extra_notes: list | None = None) -> str:
    """把牌位和牌义串成一段解读，不依赖大模型。

    groups 是 [(组名, 起始下标, 结束下标)]，给了就在组之间空一行。
    """
    lines = []
    many = len(items) >= 5

    for idx, (card, rev, pos, mean) in enumerate(items):
        if many:
            # 五张以上不再逐张铺牌义，只留位置和牌名，正文靠后面的关系和结论
            if idx == 0:
                lines.append("牌面：" + "，".join(
                    f"{p} {c['name_cn']}{'逆' if r else '正'}" for c, r, p, _ in items))
            continue
        if groups and idx and any(g[1] == idx for g in groups):
            lines.append("")
        pos_txt = "逆位" if rev else "正位"
        body = card["reversed"] if rev else card["upright"]
        line = f"{pos} · {card['name_cn']}（{pos_txt}），{body}"
        if card.get("note") and pos in ("建议", "结果", "行动"):
            line += card["note"]
        lines.append(line)

    if notes:
        rel = relation_notes(items)
        if extra_notes:
            rel = rel + [n for n in extra_notes if n]
        if rel:
            lines.append("\n" + "\n".join(rel))

    if question:
        lines.insert(0, f"你问的是「{question}」。")
    if tail:
        answer = _answer_line(items, question) if question else ""
        closing = answer or _tail_line(items)
        if closing:
            lines.append(f"\n{closing}")
    return "\n".join(lines)


def trim_llm_text(text: str, limit: int) -> str:
    """模型爱写长句。先按句号截到 limit 字以内，实在截不动就硬截。"""
    text = (text or "").strip().strip('"“”')
    if not text:
        return ""
    # 去掉 markdown 记号，QQ 上不显示这些
    for mark in ("**", "__", "##", "- "):
        text = text.replace(mark, "")
    text = text.replace("\n\n", "\n").strip()
    if text and text[-1] not in "。！？!?":
        text += "。"
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for punct in ("。", "！", "？", "\n"):
        pos = cut.rfind(punct)
        if pos >= limit * 0.5:
            return cut[: pos + 1].strip()
    return cut.rstrip("，、；：, ") + "。"


def find_card(name: str) -> dict | None:
    """按名字找牌，中文全名 / 中文简称 / 英文名都认。"""
    key = (name or "").strip().lower()
    if not key:
        return None
    for card in DECK:
        if key == card["name_cn"].lower() or key == card["name_en"].lower():
            return card
    for card in DECK:
        if key in card["name_cn"].lower() or key in card["name_en"].lower():
            return card
    return None




@register(PLUGIN_NAME, "Fangnai-byte", "塔罗牌占卜：七个牌阵，本地画纸质牌阵图", "1.0.0")
class TarotPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config if config is not None else {}
        self._last_ask: dict[str, float] = {}
        self._last_group: dict[str, float] = {}
        self._pending: dict[str, dict] = {}
        card_render.use_art(_as_bool(_cfg(self.config, "card_art", True), True))
        card_render.use_art(_as_bool(_cfg(self.config, "card_art", True), True))
        card_render.use_font_style(
            str(_cfg(self.config, "font_style", "舒体")),
            str(_cfg(self.config, "font_style_small", "楷体")),
        )

    # ---------------- 配置 ----------------
    @property
    def card_enabled(self) -> bool:
        return _as_bool(_cfg(self.config, "card_enabled", True), True)

    @property
    def reversed_enabled(self) -> bool:
        return _as_bool(_cfg(self.config, "reversed_enabled", True), True)

    @property
    def question_lock_hours(self) -> float:
        hours = _as_int(_cfg(self.config, "question_lock_hours", 12), 12, 0, 720)
        return float(hours)

    def _question_blocked(self, event: AstrMessageEvent, question: str):
        """同一个问题在锁定期内再抽就拦下，返回提示语；放行返回空串。"""
        hours = self.question_lock_hours
        if hours <= 0 or not question:
            return ""
        key = question_key(question)
        if not key:
            return ""
        uid = str(event.get_sender_id() or event.unified_msg_origin)
        now = time.time()
        for entry in reversed(history_rows(uid)):
            if entry.get("q") != key:
                continue
            used = now - float(entry.get("ts", 0))
            if used < hours * 3600:
                when = entry.get("at", "")
                first = entry.get("first", "")
                left = hours - used / 3600
                if left >= 1:
                    remain = f"{int(left)}小时"
                else:
                    remain = f"{max(1, int(left * 60))}分钟"
                head = f"这个问题 {when} 抽过了"
                if first:
                    head += f"，头一张是{first}"
                return f"{head}。再过{remain}，或者把问题问细一点。"
        return ""

    def _remember_question(self, event: AstrMessageEvent, question: str,
                           spread_name: str, items: list) -> None:
        key = question_key(question)
        if not key:
            return
        uid = str(event.get_sender_id() or event.unified_msg_origin)
        first = items[0][0]["name_cn"] if items else ""
        save_history(uid, {
            "ts": time.time(),
            "at": datetime.now().strftime("%m-%d %H:%M"),
            "q": key,
            "raw": question[:40],
            "spread": spread_name,
            "first": first,
            "gid": str(event.get_group_id() or ""),
            "cards": [{"n": c["name_cn"], "r": bool(r)} for c, r, _p, _m in items],
        })

    @property
    def reversed_ratio(self) -> float:
        percent = _as_int(_cfg(self.config, "reversed_percent", 35), 35, 0, 100)
        return percent / 100.0

    @property
    def manual_mode(self) -> bool:
        """默认要先报数字。老的 manual_draw_enabled 也认。"""
        raw = _cfg(self.config, "manual_draw", None)
        if raw is None:
            raw = _cfg(self.config, "manual_draw_enabled", True)
        return _as_bool(raw, True)

    @property
    def three_enabled(self) -> bool:
        return _as_bool(_cfg(self.config, "three_card_enabled", True), True)

    @property
    def card_width(self) -> int:
        return _as_int(_cfg(self.config, "card_width", 900), 900, 640, 1400)

    @property
    def cooldown(self) -> int:
        return _as_int(_cfg(self.config, "cooldown_seconds", 5), 5, 0, 600)

    def _allowed(self, event: AstrMessageEvent) -> bool:
        ids = _as_list(_cfg(self.config, "allow_user_ids", []))
        if not ids:
            return True
        return str(event.get_sender_id()) in ids

    @property
    def group_cooldown(self) -> int:
        return _as_int(_cfg(self.config, "group_cooldown_seconds", 10), 10, 0, 600)

    def _throttled(self, event: AstrMessageEvent) -> int:
        """返回还需等待的秒数，0 表示可以抽。

        两层：同一个人有冷却，同一个会话也有冷却。
        只按人限流的话，十个人轮流抽，群里照样刷屏。
        """
        now = time.time()
        if not hasattr(self, "_last_group"):
            self._last_group = {}
        if not hasattr(self, "_last_ask"):
            self._last_ask = {}
        umo = str(event.unified_msg_origin or "")
        uid = str(event.get_sender_id() or umo)

        if self.group_cooldown > 0:
            last_g = self._last_group.get(umo, 0.0)
            wait_g = int(self.group_cooldown - (now - last_g))
            if wait_g > 0:
                return wait_g

        if self.cooldown > 0:
            last = self._last_ask.get(uid, 0.0)
            wait = int(self.cooldown - (now - last))
            if wait > 0:
                return wait

        self._last_ask[uid] = now
        self._last_group[umo] = now
        return 0

    # ---------------- 出图 ----------------
    async def _render(self, func, *args) -> str:
        """渲染放到线程里，别卡事件循环。"""
        return await asyncio.to_thread(func, *args)

    def _path(self, prefix: str) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return os.path.join(card_dir(), f"{prefix}_{stamp}.jpg")

    def _footer(self) -> str:
        return str(_cfg(self.config, "footer_text", "") or "").strip()

    # ---------------- 命令 ----------------
    @filter.command("塔罗", alias={"tarot"})
    async def cmd_tarot(self, event: AstrMessageEvent, action: str = ""):
        """抽一局：按牌阵抽牌、出图、再给一段解读。"""
        if not self._allowed(event):
            yield event.plain_result("这个只对白名单开了。")
            return

        args = self._tokens(event)
        sub = args[0] if args else ""
        rest = args[1:]

        if sub in ("帮助", "help", "?", "？"):
            yield event.plain_result(self._help_text())
            return

        if sub in ("牌阵", "列出", "spreads", "list"):
            lines = ["现在能抽的牌阵："]
            for key, info in spread_defs.SPREADS.items():
                lines.append(f"· {info['name']}（{key}，{len(info['positions'])} 张）：{info['desc']}")
            lines.append("\n用法，/塔罗 十字 要不要换工作")
            yield event.plain_result("\n".join(lines))
            return

        if sub in ("群统计", "本群统计", "groupstats"):
            yield event.plain_result(self._group_stats_text(event))
            return

        if sub in ("统计", "stats", "记录"):
            yield event.plain_result(self._stats_text(event))
            return

        if sub in ("回看", "上一局", "last"):
            key = str(event.get_sender_id() or event.unified_msg_origin)
            record = load_last_draws().get(key)
            if not record:
                yield event.plain_result("还没抽过，先来一局。")
                return
            async for item in self._replay(event, record):
                yield item
            return

        # 「抽」只是个别名，真正的模式由配置决定
        if sub in ("抽", "手动", "pick", "draw"):
            used_default = False
            key_x = spread_defs.resolve(rest[0]) if rest else ""
            if key_x:
                sub = rest[0]
                rest = rest[1:]
            else:
                sub = ""
                args = rest
                rest = []

        if sub in ("牌", "查", "card"):
            name = " ".join(rest)
            if not name:
                yield event.plain_result("想看哪张？例如：/塔罗 牌 月亮")
                return
            card = find_card(name)
            if card is None:
                yield event.plain_result(f"没找到「{name}」。中文全名、英文名都行。")
                return
            if self.card_enabled:
                try:
                    path = await self._render(
                        card_render.render_spread,
                        [(card, False, "正 位", "这一面的说法"),
                         (card, True, "逆 位", "倒过来那一面的说法")],
                        self._path("card"), "牌 义", "", self._footer(),
                        self.card_width,
                    )
                    yield event.chain_result([Image.fromFileSystem(path)])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s 查牌出图失败，退回文字: %s", TAG, exc)
            yield event.plain_result(self._detail_text(card))
            return

        # 第一个词是牌阵名就用它，否则整句当问题
        used_default = False
        spread_key = spread_defs.resolve(sub)
        if spread_key:
            question = " ".join(rest)
        else:
            spread_key = spread_defs.resolve(_cfg(self.config, "default_spread", "时间")) or "时间"
            used_default = True
            question = " ".join(args)

        if not self.three_enabled and len(spread_defs.spread(spread_key)["positions"]) > 1:
            spread_key = "一张"

        wait = self._throttled(event)
        if wait:
            yield event.plain_result(f"别急，{wait} 秒后再抽。")
            return

        blocked = self._question_blocked(event, question)
        if blocked:
            yield event.plain_result(blocked)
            return

        if self.manual_mode:
            async for item in self._start_manual(event, spread_key, question, used_default):
                yield item
            return

        if _as_bool(_cfg(self.config, "shuffle_notice", True), True):
            yield event.plain_result("洗牌中…")

        ratio = self.reversed_ratio if self.reversed_enabled else 0.0
        info, items = draw_spread(spread_key, ratio)
        async for item in self._deliver(event, info, items, question, used_default):
            yield item

    async def _start_manual(self, event: AstrMessageEvent, spread_key: str,
                            question: str, used_default: bool):
        """洗牌、记下待抽的牌局，让对方报数字。"""
        info = spread_defs.spread(spread_key)
        need = len(info["positions"])
        deck = list(DECK)
        _rng.shuffle(deck)
        uid = str(event.get_sender_id() or event.unified_msg_origin)
        if not hasattr(self, "_pending"):
            self._pending = {}
        self._pending[uid] = {
            "ts": time.time(),
            "deck": [c["name_cn"] for c in deck],
            "need": need,
            "spread": spread_key,
            "question": question,
            "used_default": used_default,
        }
        yield event.plain_result(
            f"{info['name']}，{need} 张。\n"
            f"牌洗好了，从 1 到 78 里报 {need} 个数，空格隔开，比如 {self._sample_numbers(need)}。"
        )

    # ---------------- 出结果 ----------------
    async def _deliver(self, event: AstrMessageEvent, info: dict, items: list,
                       question: str, used_default: bool = False):
        """出图、出解读、记账。自动抽和手动抽都走这里。"""
        if not self.card_enabled:
            yield event.plain_result(f"{info['name']}\n\n"
                                      + compose_reading(items, question, groups=info.get("groups")))
            return

        renderer = _renderer_for(info.get("layout", "grid"))
        try:
            path = await self._render(
                renderer, items, self._path("spread"), info["name"],
                question if self._include_question() else "", self._footer(),
                self.card_width,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s 出图失败，退回文字: %s", TAG, exc)
            yield event.plain_result(f"{info['name']}\n\n"
                                      + compose_reading(items, question, groups=info.get("groups")))
            return

        await asyncio.to_thread(prune_cards)
        yield event.chain_result([Image.fromFileSystem(path)])

        # 解读总是算出来（回看要用），发不发由 reading_text 决定。
        # 开了模型也只让它补两三句，逐张牌那段照旧由固定文案给。
        use_llm = _as_bool(_cfg(self.config, "llm_reading", False), False)
        reading = compose_reading(
            items, question, tail=True, groups=info.get("groups"),
            extra_notes=[self._repeat_cards_note(event, items)],
        )
        if use_llm:
            extra = await self._llm_reading(info, items, question)
            if extra:
                reading = reading + "\n\n" + extra

        if _as_bool(_cfg(self.config, "reading_text", True), True):
            hint = self._repeat_hint(event, question)
            if hint:
                reading = hint + "\n\n" + reading
            advice = self._spread_hint(question, used_default)
            if advice:
                reading = reading + chr(10) * 2 + advice
            yield event.plain_result(reading)

        self._remember(event, info, items, question, reading)
        self._remember_question(event, question, info["name"], items)

    def _sample_numbers(self, need: int) -> str:
        picks = sorted(_rng.sample(range(1, 79), need))
        return " ".join(str(n) for n in picks)

    def _pending_get(self, uid: str) -> dict | None:
        """取出待抽的牌局，超时就丢掉。"""
        if not hasattr(self, "_pending"):
            self._pending = {}
        item = self._pending.get(uid)
        if not item:
            return None
        ttl = _as_int(_cfg(self.config, "manual_timeout_seconds", 180), 180, 30, 900)
        if time.time() - float(item.get("ts", 0)) > ttl:
            self._pending.pop(uid, None)
            return None
        return item

    def _pending_take(self, uid: str) -> dict | None:
        item = self._pending_get(uid)
        if item:
            self._pending.pop(uid, None)
        return item

    @filter.regex(r"^[\s\d,，、]{1,80}$")
    async def cmd_pick_numbers(self, event: AstrMessageEvent):
        """接住报数字的那条消息。没有待抽的牌局就什么都不做。"""
        uid = str(event.get_sender_id() or event.unified_msg_origin)
        pending = self._pending_get(uid)
        if not pending:
            return

        text = TarotPlugin._clean_message(getattr(event, "message_str", "") or "")
        nums = [int(x) for x in re.findall(r"\d+", text)]
        need = int(pending.get("need", 1))
        if not nums:
            return
        if len(nums) != need:
            yield event.plain_result(f"要 {need} 个数，你报了 {len(nums)} 个。再报一次，空格隔开。")
            return
        if any(n < 1 or n > 78 for n in nums):
            yield event.plain_result("数字要在 1 到 78 之间。再报一次。")
            return
        if len(set(nums)) != len(nums):
            yield event.plain_result("有重复的数。牌不会重复发，换几个数。")
            return

        pending = self._pending_take(uid)
        if not pending:
            return

        by_name = {c["name_cn"]: c for c in DECK}
        deck = pending["deck"]
        info = spread_defs.spread(pending["spread"])
        ratio = self.reversed_ratio if self.reversed_enabled else 0.0
        items = []
        for n, (pos, mean) in zip(nums, info["positions"]):
            card = by_name.get(deck[n - 1])
            if card is None:
                continue
            items.append((card, _rng.random() < ratio, pos, mean))
        if not items:
            yield event.plain_result("牌没对上，重新来一局吧。")
            return

        async for item in self._deliver(event, info, items, pending["question"],
                                       bool(pending.get("used_default"))):
            yield item

    @filter.regex(r"^(?=[^\d]*\d)[\s\d,，、A-Za-z]{1,40}$")
    async def cmd_pick_hint(self, event: AstrMessageEvent):
        """数字里夹了字母：提醒只报数字。没有待抽的牌局就不吭声。"""
        uid = str(event.get_sender_id() or event.unified_msg_origin)
        pending = self._pending_get(uid)
        if not pending:
            return
        text = TarotPlugin._clean_message(getattr(event, "message_str", "") or "")
        if re.fullmatch(r"[\s\d,，、]{1,40}", text):
            return  # 纯数字交给上面那个 handler
        need = int(pending.get("need", 1))
        yield event.plain_result(
            f"只报数字就行，{need} 个，空格隔开，比如 {self._sample_numbers(need)}。"
        )

    @filter.regex(r"塔罗|tarot")
    async def cmd_tarot_fallback(self, event: AstrMessageEvent):
        """命令没匹配上时兜一层：@ 或引用让开头多了杂物，也能认出来。

        这条只管标准指令接不住的消息。消息本来就以「塔罗」开头的话让路，
        否则同一条消息会被处理两遍，第二遍撞冷却，回一句「别急」。
        """
        if not getattr(event, "is_at_or_wake_command", False):
            return
        raw = str(getattr(event, "message_str", "") or "").strip().lstrip("/").strip()
        if raw.lower().startswith(("塔罗", "tarot")):
            return
        text = TarotPlugin._clean_message(raw)
        if not re.match(r"^(塔罗|tarot)(?![一-鿿])", text, re.I):
            return
        async for item in self.cmd_tarot(event):
            yield item

    @filter.regex(r"(抽|占|算|起|看|来|帮|给|洗)[^，。！？]{0,4}(牌|卦)")
    async def cmd_tarot_loose(self, event: AstrMessageEvent):
        """没写「塔罗」也能抽：「抽个牌」「帮我算一卦」。

        只认 At 或唤醒之后的话。命令词开头的让路，免得同一条走两遍。
        """
        if not getattr(event, "is_at_or_wake_command", False):
            return
        raw = str(getattr(event, "message_str", "") or "").strip().lstrip("/").strip()
        if raw.lower().startswith(("塔罗", "tarot", "抽牌", "抽塔罗")):
            return
        question = re.sub(r"^(帮我|给我|麻烦|能不能|可以)?\s*"
                          r"(抽|占|算|起|看|来|给|帮|洗)[^，。！？]{0,4}(牌|卦)[，。！？\s]*",
                          "", raw)
        if len(question) > 40:
            question = ""
        original = str(getattr(event, "message_str", "") or "")
        try:
            # 借命令那条路：把消息改写成「塔罗 问题」，跑完还原
            event.message_str = ("塔罗 " + question).strip()
            async for item in self.cmd_tarot(event):
                yield item
        finally:
            try:
                event.message_str = original
            except Exception:
                pass

    def _repeat_cards_note(self, event: AstrMessageEvent, items: list,
                           window: int = 5) -> str:
        """最近几局反复出现的牌。返回一句提示，没有就空串。"""
        uid = str(event.get_sender_id() or event.unified_msg_origin)
        rows = [e for e in history_rows(uid) if e.get("cards")]
        if not rows:
            return ""
        recent = rows[-window:]
        seen: dict[str, int] = {}
        for entry in recent:
            for card in entry["cards"]:
                name = str(card.get("n", ""))
                seen[name] = seen.get(name, 0) + 1

        hits = []
        for card, _rev, _pos, _mean in items:
            name = card["name_cn"]
            times = seen.get(name, 0)
            if times >= 1:
                hits.append((name, times))
        if not hits:
            return ""

        hits.sort(key=lambda kv: -kv[1])
        name, times = hits[0]

        # 上一局就有这张，最值得说
        prev = recent[-1]
        prev_names = {str(c.get("n", "")) for c in prev.get("cards") or []}
        if name in prev_names:
            return f"{name}上一局也出现了，连着两次。"
        if times >= 2:
            return f"{name}最近 {len(recent)} 局里出现过 {times} 次。"
        return ""

    def _stats_text(self, event: AstrMessageEvent) -> str:
        """最近抽过什么。数据来自提问史，只统计这个人的。"""
        uid = str(event.get_sender_id() or event.unified_msg_origin)
        entries = history_rows(uid)
        rows = [e for e in entries if e.get("cards")]
        if not rows:
            return "还没抽够，先来几局再统计。"

        total_cards = sum(len(e["cards"]) for e in rows)
        reversed_count = sum(1 for e in rows for c in e["cards"] if c.get("r"))

        suits: dict[str, int] = {}
        names: dict[str, int] = {}
        for entry in rows:
            for card in entry["cards"]:
                name = str(card.get("n", ""))
                names[name] = names.get(name, 0) + 1
                suit = next((k for k in SUIT_THEME if name.startswith(k)), "")
                if suit:
                    suits[suit] = suits.get(suit, 0) + 1

        lines = [f"最近抽了 {len(rows)} 局，{total_cards} 张牌。"]
        if suits:
            top_suits = sorted(suits.items(), key=lambda kv: -kv[1])[:2]
            lines.append("花色：" + "、".join(f"{k} {v} 张" for k, v in top_suits))
        top_names = sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        if top_names:
            lines.append("重复最多：" + "、".join(f"{k} ×{v}" for k, v in top_names if v > 1)
                         if any(v > 1 for _k, v in top_names) else "重复最多：还没有重复的牌")
        if total_cards:
            lines.append(f"逆位 {reversed_count} 张，占 {reversed_count / total_cards:.0%}。")
        lines.append("\n统计的是最近这些局，最多留 60 局。")
        return "\n".join(lines)

    def _group_stats_text(self, event: AstrMessageEvent) -> str:
        """整个群加起来的数：几局、几个人、谁抽得多、牌面偏什么。"""
        gid = str(event.get_group_id() or "")
        if not gid:
            return "群统计得在群里用。"

        data = load_history()
        rows = []
        people: dict[str, int] = {}
        for uid, entries in data.items():
            if not isinstance(entries, list):
                continue
            for row in entries:
                if not isinstance(row, dict) or not row.get("cards"):
                    continue
                if str(row.get("gid") or "") != gid:
                    continue
                rows.append(row)
                people[str(row.get("uid") or uid)] = people.get(str(row.get("uid") or uid), 0) + 1
        if not rows:
            return "这个群还没人抽过。"

        total_cards = sum(len(r["cards"]) for r in rows)
        rev = sum(1 for r in rows for c in r["cards"] if c.get("r"))
        names: dict[str, int] = {}
        for r in rows:
            for c in r["cards"]:
                n = str(c.get("n", ""))
                names[n] = names.get(n, 0) + 1

        lines = [f"本群一共抽了 {len(rows)} 局，{total_cards} 张牌，{len(people)} 个人抽过。"]
        top_people = sorted(people.items(), key=lambda kv: -kv[1])[:3]
        if top_people:
            lines.append("抽得最多：" + "、".join(f"××{uid[-4:]} {n} 局" for uid, n in top_people))
        top_cards = sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        if top_cards:
            lines.append("出得最多：" + "、".join(f"{k} ×{v}" for k, v in top_cards))
        if total_cards:
            lines.append(f"逆位 {rev} 张，占 {rev / total_cards:.0%}。")
        return "\n".join(lines)

    def _repeat_hint(self, event: AstrMessageEvent, question: str) -> str:
        """同一个问题近期问过，就提一句；没问过返回空串。"""
        q = (question or "").strip()
        if not q:
            return ""
        key = str(event.get_sender_id() or event.unified_msg_origin)
        record = load_last_draws().get(key) or {}
        prev_q = (record.get("question") or "").strip()
        if not prev_q or prev_q != q:
            return ""
        cards = record.get("cards") or []
        first = cards[0]["name"] if cards else ""
        when = record.get("at", "")
        if not first:
            return ""
        return f"上次问同一件事是 {when}，头一张是{first}。"

    def _spread_hint(self, question: str, used_default: bool) -> str:
        """用默认单张问了感情或事业类问题时，给一句牌阵建议。"""
        if not used_default or not question:
            return ""
        q = question
        groups = (
            (("关系", "感情", "喜欢", "爱", "他", "她", "复合", "分手", "恋爱", "暧昧"), "关系"),
            (("工作", "事业", "面试", "跳槽", "辞职", "升职", "offer", "转行", "考试"), "行动"),
            (("要不要", "该不该", "选哪个", "二选一", "还是"), "二选一"),
        )
        for words, key in groups:
            if any(w in q for w in words):
                target = spread_defs.SPREADS[key]
                return f"这类问题用「{target['name']}」更清楚，比如 /塔罗 {key} {q}"
        return ""

    def _remember(self, event: AstrMessageEvent, info: dict, items: list,
                  question: str, reading: str) -> None:
        """把这一局记下来，供 /塔罗 回看 用。"""
        key = str(event.get_sender_id() or event.unified_msg_origin)
        record = {
            "ts": time.time(),
            "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "spread": info["name"],
            "question": question,
            "reading": reading,
            "cards": [
                {
                    "name": card["name_cn"],
                    "rev": bool(rev),
                    "pos": pos,
                    "mean": mean,
                    "text": card["reversed"] if rev else card["upright"],
                }
                for card, rev, pos, mean in items
            ],
        }
        save_last_draw(key, record)

    async def _replay(self, event: AstrMessageEvent, record: dict):
        """按记录重画一次，不重新抽牌。"""
        by_name = {c["name_cn"]: c for c in DECK}
        items = []
        for entry in record.get("cards", []):
            card = by_name.get(entry.get("name", ""))
            if card is None:
                continue
            items.append((card, bool(entry.get("rev")), entry.get("pos", ""),
                          entry.get("mean", "")))
        if not items:
            yield event.plain_result("上一局的牌找不到了，再抽一次吧。")
            return

        head = f"{record.get('at', '')} 的那一局（{record.get('spread', '')}）"
        if record.get("question"):
            head += f"\n问的是「{record['question']}」"

        if self.card_enabled:
            info_guess = {"layout": "grid"}
            for candidate in spread_defs.SPREADS.values():
                if candidate["name"] == record.get("spread"):
                    info_guess = candidate
                    break
            renderer = _renderer_for(info_guess.get("layout", "grid"))
            try:
                path = await self._render(
                    renderer, items, self._path("replay"),
                    f"{record.get('spread', '牌阵')} · 回看",
                    "", self._footer(), self.card_width,
                )
                yield event.plain_result(head)
                yield event.chain_result([Image.fromFileSystem(path)])
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s 回看重画失败: %s", TAG, exc)
                yield event.plain_result(head)
        else:
            yield event.plain_result(head)

        reading = record.get("reading") or ""
        if reading:
            yield event.plain_result(reading)

    async def _llm_reading(self, info: dict, items: list, question: str) -> str:
        """让当前模型写一段解读；失败返回空串，调用方退回固定文案。"""
        try:
            provider = self.context.get_using_provider()
        except Exception:
            provider = None
        if provider is None:
            return ""
        lines = []
        for card, rev, pos, mean in items:
            state = "逆位" if rev else "正位"
            body = card["reversed"] if rev else card["upright"]
            lines.append(f"- {pos}（{mean}）：{card['name_cn']} {state}。{body}")
        limit = _as_int(_cfg(self.config, "llm_max_chars", 100), 100, 40, 400)
        prompt = (
            f"牌阵：{info['name']}\n"
            + (f"提问：{question}\n" if question else "")
            + "抽到的牌：\n" + "\n".join(lines)
            + f"\n\n接下来别再提牌名，也别解释牌义，上面都写过了。"
            f"第一句直接回答他问的事，别绕。两句以内，别超过 {limit} 字。"
            "建议要具体到时间或动作，别写「做决定」「调整心态」这种空话。"
            "照这个样子写：明天几件事会撞在一起。先给最要紧那件定个时间段，剩下的晚点处理。"
            "别用「之所以……就在于」「不是……而是」「你以为……其实」，别加引号，别用破折号。"
        )
        timeout = _as_int(_cfg(self.config, "llm_timeout_seconds", 25), 25, 5, 120)
        try:
            resp = await asyncio.wait_for(
                provider.text_chat(
                    prompt=prompt,
                    system_prompt="你是一个说话直接、不绕弯的塔罗牌解读者。",
                ),
                timeout=timeout,
            )
            text = (getattr(resp, "completion_text", "") or "").strip()
            # 提示词说了别提牌名，模型偶尔还是会复述。提到两张以上就判废，退回固定文案
            named = sum(1 for card, *_ in items if card["name_cn"] in text)
            if named >= 2:
                logger.info("%s 模型复述了 %d 张牌名，退回固定文案", TAG, named)
                return ""
            return trim_llm_text(text, limit)
        except asyncio.TimeoutError:
            logger.warning("%s 模型解读超时（%ss），退回固定文案", TAG, timeout)
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s 模型解读失败，退回固定文案: %s", TAG, exc)
            return ""

    def _include_question(self) -> bool:
        return _as_bool(_cfg(self.config, "include_question", True), True)

    @staticmethod
    def _clean_message(raw: str) -> str:
        """去掉开头的 @某人(123) 和 [引用…]，这些是框架塞进 message_str 的杂物。"""
        text = str(raw or "").strip()
        junk = re.compile(r"^(?:@\S*(?:\(\d+\))?\s*|\[[^\]]*\]\s*)")
        for _ in range(6):
            stripped = junk.sub("", text, count=1).strip()
            if stripped == text:
                break
            text = stripped
        return text

    @staticmethod
    def _tokens(event: AstrMessageEvent) -> list[str]:
        raw = TarotPlugin._clean_message(getattr(event, "message_str", "") or "")
        raw = raw.lstrip("/")
        parts = [p for p in raw.split() if p]
        if parts and parts[0].lower() in ("塔罗", "tarot"):
            parts = parts[1:]
        return parts

    def _detail_text(self, card: dict) -> str:
        words = " · ".join(card.get("keywords") or [])
        lines = [f"{card['name_cn']}（{card['name_en']}）"]
        if words:
            lines.append(f"关键词：{words}")
        if card.get("note"):
            lines.append(f"落到事上：{card['note']}")
        lines.append(f"\n正位：{card['upright']}")
        lines.append(f"逆位：{card['reversed']}")
        return "\n".join(lines)

    def _help_text(self) -> str:
        names = "、".join(
            f"{s['name']} {len(s['positions'])} 张" for s in spread_defs.SPREADS.values()
        )
        return (
            "塔罗\n"
            "/塔罗 [问题]           抽一局，用默认牌阵\n"
            "/塔罗 十字 [问题]      指定牌阵，名字见下\n"
            "/塔罗 牌阵             看看有哪些牌阵\n"
            "/塔罗 回看             翻上一局，牌不会变\n"
            "/塔罗 统计             看最近抽过什么\n"
            "/塔罗 牌 月亮          查一张牌\n"
            "/塔罗 帮助             这份说明\n"
            f"\n牌阵，{names}"
            f"\n牌堆 {len(DECK)} 张，大阿卡纳 22 加小阿卡纳 56"
        )
