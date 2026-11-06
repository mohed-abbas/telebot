"""Parse Telegram trading signals into structured SignalAction objects.

Handles zone-based entries, multiple TPs, and trade management updates.

Trade-management messages are matched against the GTMO VIP provider's real
phrasing (replayed from a full channel export, 2022-2026). The provider writes
loosely — "SET BREAKEVENNN NOW!!", "adjust SL because of this volume to 3989.2",
"OUT OF ALL ENTRIES NOW!!!" — and mixes instructions with optional advice
("close all if satisfied"), plans ("At TP2 I'll close half") and questions
("Did you set breakeven?"). So each message is normalized, split into clauses,
and an instruction is only acted on when its clause is not a question, negated,
conditional, hedged, or (for closes) optional or in the future without "now".

The bot follows the provider as a trader who HOLDS: optional closes ("close all
if satisfied") are not acted on, but the advice to holders that comes with them
("to hold set be+") is.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from models import Direction, SignalAction, SignalType, SYMBOL_MAP, _SYMBOL_PATTERN

logger = logging.getLogger(__name__)

_KEYWORDS_PATH = Path(__file__).parent / "signal_keywords.json"


def _load_keywords() -> dict:
    if _KEYWORDS_PATH.exists():
        with open(_KEYWORDS_PATH) as f:
            return json.load(f)
    return {}


KEYWORDS = _load_keywords()

# ── Regex patterns ──────────────────────────────────────────────────────

_SYMBOL_RX = r"(?P<symbol>gold|xauusd|xau/?usd|xau)"
# "buy" / "sell", plus the provider's variants: "sel" (typo), "add sells".
_DIRECTION_RX = r"(?:add\s+)?(?P<direction>buy|sell?)s?"
# Words the provider puts between symbol, direction and "now":
# "Gold re-entry buy now", "Gold buy now again", "Gold continue sell now".
_FILLER_RX = r"(?:(?:again|re-?entry|continue|slowly)\W+)*"

# New trade: "Gold sell now 4978 - 4982" or "XAUUSD BUY 2150-2155"
_RE_OPEN = re.compile(
    r"(?:re-?entry\W+)?" + _SYMBOL_RX + r"\s+" + _FILLER_RX
    + _DIRECTION_RX + r"\s+" + _FILLER_RX
    + r"(?:now\s+)?" + _FILLER_RX + r"@?\s*"
    r"(?P<price1>[\d]+(?:\.[\d]+)?)\s*[-–—]\s*(?P<price2>[\d]+(?:\.[\d]+)?)",
    re.IGNORECASE,
)

# Fallback: single-price entry "Gold buy 2150" (no zone)
_RE_OPEN_SINGLE = re.compile(
    r"(?:re-?entry\W+)?" + _SYMBOL_RX + r"\s+" + _FILLER_RX
    + _DIRECTION_RX + r"\s+" + _FILLER_RX
    + r"(?:now\s+)?" + _FILLER_RX + r"@?\s*(?P<price>[\d]+(?:\.[\d]+)?)",
    re.IGNORECASE,
)

# Phase 6 D-01 / D-02 — text-only "now" signal ("Gold buy now", "XAU sell now").
# Anchors ^...$ + \b keyword boundaries ensure any trailing numeric token makes
# this recognizer miss, so _RE_OPEN / _RE_OPEN_SINGLE still win for priced text.
# Re-entries ("Re-entry gold sell now", "Gold buy now again") are the same order.
_RE_OPEN_TEXT_ONLY = re.compile(
    r"^\W*(?:re-?entry\W+)?" + _SYMBOL_RX + r"\s+" + _FILLER_RX
    + _DIRECTION_RX + r"\s+" + _FILLER_RX
    + r"\b(?:now|asap|immediate)\b"
    r"(?:\W+(?:again|re-?entry))?[^\w\d]*$",
    re.IGNORECASE,
)

# SL line: "SL: 4986" or "SL 4986" or "sl : 4986"
_RE_SL = re.compile(
    r"(?:^|\n)\s*sl\s*[:.]?\s*(?P<sl>[\d]+(?:\.[\d]+)?)",
    re.IGNORECASE,
)

# TP lines: "TP: 4975" or "TP. 4975" or "TP1: 4975" or "TP: open"
_RE_TP = re.compile(
    r"(?:^|\n)\s*tp\d?\s*[:.]?\s*(?P<tp>[\d]+(?:\.[\d]+)?|open)",
    re.IGNORECASE,
)

# TP update: "New TP: 4965" or "Update TP: 4965". Same line only, so an open
# signal's "SL: will update\n\nTP: 1933" is not read as a TP update.
_RE_TP_UPDATE = re.compile(
    r"(?:(?:update|new)[ \t]+tp[ \t]*[:.]?[ \t]*(?P<tp>[\d]+(?:\.[\d]+)?))",
    re.IGNORECASE,
)

_RE_CLOSE_PERCENT = re.compile(r"(\d+)\s*%", re.IGNORECASE)

# ── Trade-management phrasing (matched on normalized clauses) ──────────
# Normalized text is lower-case with runs of 3+ equal letters collapsed to one
# ("breakevennnn" -> "breakeven", "alll" -> "al"), so words that are spelled
# with a double letter are written tolerant of both: al{1,2}, los{1,2}.

_SL_WORD = r"(?:sl|stop ?los{1,2}|stoplos{1,2})"
_SL_VERB = (
    r"(?:adjust|adjusting|adjusted|update|updating|updated|move|moving|moved|"
    r"change|changing|set|setting|put|place|new)"
)
# "Adjust SL ...", "Move my SL ...", "SL updated", "SL to 4025".
_RE_SL_TRIGGER = re.compile(
    rf"\b{_SL_VERB}\b[^.!?]{{0,40}}?\b{_SL_WORD}\b"
    rf"|\b{_SL_WORD}\b[^.!?]{{0,20}}\b(?:updated?|adjusted)\b"
    rf"|\b{_SL_WORD}\s+to\s+\d"
)
# A whole message that is only a level: "SL: 3432", "SL to 3742 ok", "New SL 4368".
_RE_SL_STANDALONE = re.compile(
    rf"^\W*(?:new\s+)?{_SL_WORD}\s*(?:to|:|=|is)?\s*(?P<price>\d{{3,5}}(?:[.,]\d{{1,2}})?)\W*(?:ok|for now)?\W*$"
)
# A message that is only a price, used for a pending "adjust SL +15 pips" announcement.
_RE_BARE_PRICE = re.compile(
    r"^\W*(?:new\s+sl\W+)?(?P<price>\d{3,5}(?:[.,]\d{1,2})?)\W*(?:ok)?\W*$"
)
# Price-like numbers; pip counts, percentages and dollar amounts are excluded.
_RE_LEVEL = re.compile(
    r"(?<![\d.,+$-])(?P<num>\d{3,5}(?:[.,]\d{1,2})?)(?![\d%k$])(?!\s*(?:pips?|points?|%|k\b|\$))"
)
# Words just before a level that mark it as the new SL, best first.
_LEVEL_LEAD_PRIORITY = (
    re.compile(r"\bto\s*:?\s*(?:max(?:imum)?\s+)?$"),
    re.compile(r"(?::|=|\bis|\bbe|\bbe at)\s*$"),
    re.compile(r"\bat\s*$"),
)

# Breakeven. "be" counts only as its own word at the end of the instruction
# ("set be+", "set your be now"), never inside "because", "below", "better" or
# as the verb ("be ready", "would be that").
_BE_WORD = (
    r"(?:break ?even|be\+|\bbe\b(?=\s*(?:$|[!.,+]|now\b|for\b|on (?:all|the|my|your|ur|top|bottom|"
    r"best|lowest|highest)\b|to hold\b|and\b|ok\b|asap\b|if\b)))"
)
_RE_BE = re.compile(
    # "Set breakeven", "SET FULLY BREAKEVEN", "set your be+", "move to BE"
    rf"\b(?:set|setting|move|moving|put|activate)\b(?:\s+\w+){{0,3}}?\s+{_BE_WORD}"
    # "Move SL to entry", "moving your SL below the entries", "SL is set at entries"
    rf"|\b(?:set|setting|move|moving|moved|put|place|adjust\w*|trail\w*)\b[^.!?]{{0,25}}\b{_SL_WORD}\b"
    rf"(?:\s+\w+){{0,3}}?\s+(?:to|at|above|below|on)\s+"
    rf"(?:\w+\s+){{0,2}}?(?:break ?even|be\+?|entry|entries|entry price)\b"
    rf"|\b{_SL_WORD}\s+(?:is\s+)?(?:set\s+)?(?:to|at)\s+(?:the\s+|my\s+|your\s+|all\s+)?"
    r"(?:break ?even|be\+?|entry|entries|entry price)\b"
    # "only hold with be+", "holding the lowest one with breakeven"
    rf"|\bhold(?:ing)?\b[^.!?]{{0,40}}\bwith\s+(?:\w+\s+)?(?:break ?even|be\+?)"
    # Provider's own state: "Breakeven set", "Fully breakeven set", "I'm at zero risk now"
    r"|\bbreak ?even (?:is )?set\b|\bfully break ?even\b"
    r"|\b(?:i'?m|we'?re|we are|i am)\s+(?:at|on)\s+zero risk\b"
    # A clause that is just the word: "Breakeven", "BREAKEVEN ZERO RISK", "breakeven now"
    r"|^\W*break ?even(?:\s+now)?(?:\s+(?:for\s+)?zero risk)?(?:\s+now)?\W*$"
)
# Reports that breakeven already closed trades — information, not an instruction.
_RE_BE_INFO = re.compile(r"\b(?:hit|hits|hitting)\b[^.!?]{0,15}break ?even|break ?even\b[^.!?]{0,15}\b(?:hit|hits)\b|\bin break ?even\b")

_RE_CLOSE_ALL = re.compile(
    r"\bout of (?:al{1,2}|every\w*)\b"
    r"|\bcut(?:ting)? (?:the |my |this )?(?:los{1,2}|trade)\b"
    r"|\b(?:close|exit)\s+(?:al{1,2}|everything|gold|xauusd|xau|(?:the |this )?trades?)\b"
    r"(?!\s+(?:top|bottom|first|worst|highest|lowest|best|last|lower|higher|worse)\b)"
)
# Provider reports having closed everything: "CLOSED ALL NOW", "All entries closed".
_RE_CLOSED_ALL = re.compile(
    r"\b(?:closed|exited)\s+(?:al{1,2}|everything)\b"
    r"(?!\s+(?:top|bottom|first|worst|highest|lowest|best|last|lower|higher|worse)\b)"
    r"|\bal{1,2}\s+(?:entries|positions|trades)\s+(?:are\s+)?closed\b"
)
_RE_PARTIAL = re.compile(
    r"\bclose\s+(?:half|partial|\d+\s*%)"
    r"|\btp\s*1\s*(?:hit|reached|done).*(?:close|partial)"
    r"|\bsecure\s+(?:(?:ur|your|those|the|some|half)\s+)?(?:profits?|partial)\b"
    r"|\btake\s+(?:partial|half)\s+(?:profits?|off)\b"
    r"|\b(?:take|taking|close|secure)\b(?:\s+\w+){0,2}?\s+(?:half|partial|partially|some|more)\s+"
    r"(?:of\s+)?(?:the\s+|your\s+|ur\s+)?profits?\b"
    r"|\b(?:take|taking)\s+(?:partially|some|more)\s+profits?\b"
    r"|\b(?:close|take)\b(?:\s+\w+){0,2}?\s+(?:worst|first|top|lowest|highest|bottom|lower|higher|worse)\s+"
    r"(?:entries|entry|positions|ones)\b"
)

# Guards. A clause matching any of these is not acted on.
_RE_NEGATION = re.compile(
    r"\b(?:not|don'?t|dont|won'?t|wont|never|no need|didn'?t|didnt|cannot|can'?t)\b"
)
_RE_CONDITION = re.compile(r"\b(?:if|once|when|whenever|unless|until|incase|in case|as soon as)\b")
# "At TP3 I'll close half", "TP1 to close worst entries". Not used for SL moves,
# where "at 4189.5" is the level itself.
_RE_AT_LEVEL = re.compile(r"\bat (?:tp\s*\d|\d{3,5})\b|\btp\s*\d\s+to\b")
# A clause that opens with a condition ("Once we hit TP1, lets take ...") puts
# the clause after it under that condition too.
_RE_LEADING_CONDITION = re.compile(
    r"^\W*(?:if|once|when|whenever|unless|as soon as|at tp\s*\d|at \d{3,5})\b"
)
_RE_HEDGE = re.compile(
    r"\b(?:might|maybe|perhaps|stay tuned|be ready|get ready|prepare|ready to|"
    r"about to|thinking|think about|from time to time|why|explain\w*|"
    # Telling the story of an earlier trade.
    r"yesterday|this morning|today morning|earlier today|last week)\b"
)
# Optional advice for closes: "scalper can close all", "you may secure",
# "take partially profits the way your satisfied".
_RE_OPTIONAL = re.compile(
    r"\b(?:can|could|may|depending|the way (?:you'?re|your|ur|you are|u r) satisfied)\b"
)
# Leaving the whole choice to the reader: "close or set breakeven, you decide".
_RE_YOUR_CHOICE = re.compile(r"\b(?:you decide|your choice|up to you|its up to you|it's up to you)\b")
_RE_FUTURE = re.compile(
    r"\b(?:i'?ll|i will|will|gonna|going to|shortly|soon|later|next|then we)\b"
)
# A clause that asks rather than tells, even without a "?".
_RE_QUESTION_START = re.compile(
    r"^\W*(?:did|does|have you|has|are you|r u|who|who'?s|how|what|which|anyone|"
    r"did anyone|is anyone|is everyone)\b"
)
_RE_NOW = re.compile(r"\b(?:now|immediately|already|right away)\b")
# Conditions that only address holders ("if you want to hold set be+") or
# satisfied traders ("close all if satisfied, to hold set be+"). The bot holds,
# so breakeven advice under these conditions applies to it.
_RE_HOLDER_CONDITION = re.compile(
    r"\bif\s+(?:you|u)?\s*(?:want|like|wanna|would like)?\s*(?:to\s+)?(?:keep\s+)?hold(?:ing)?\b"
    r"|\bif\s+(?:you'?re|your|ur|you are|u r)\s+(?:still\s+)?holding\b"
    r"|\bin ?case\s+(?:you|u)\s+(?:are\s+)?(?:still\s+)?holding\b"
    r"|\bif\s+(?:you'?re|your|ur|you are|u r|you|u)?\s*(?:satisfied|happy)\b"
)

# Seconds a pending "adjust SL +15 pips" announcement waits for its level.
SL_FOLLOWUP_WINDOW_SECONDS = 120
# Seconds after a partial close during which another one is dropped.
PARTIAL_CLOSE_COOLDOWN_SECONDS = 180


def _resolve_symbol(raw: str) -> str:
    """Map raw symbol text to canonical MT5 symbol."""
    return SYMBOL_MAP.get(raw.lower().strip(), raw.upper().strip())


def _select_target_tp(tps: list[float | str], index: int = 2) -> float | None:
    """Select TP at 1-based index (default TP2). Skip 'open' values."""
    numeric = [tp for tp in tps if isinstance(tp, (int, float))]
    if len(numeric) >= index:
        return numeric[index - 1]
    if numeric:
        return numeric[-1]  # fallback to last numeric TP
    return None


_SIGNAL_KEYWORDS = {
    "buy", "sell", "sl", "tp", "entry", "entries", "close", "exit",
    "breakeven", "cut loss", "out of all", "adjust",
}
_RE_PRICE_LIKE = re.compile(r"\b\d{3,5}(?:\.\d{1,2})?\b")


def is_signal_like(text: str) -> bool:
    """Heuristic: does this text look like it might be a trading signal?

    Requires at least 2 trading keywords OR 1 keyword + a price-like number.
    This reduces false positives from casual messages mentioning 'gold' or 'buy'.
    """
    lower = _normalize(text)
    keyword_count = sum(1 for kw in _SIGNAL_KEYWORDS if kw in lower)
    has_price = bool(_RE_PRICE_LIKE.search(text))

    if keyword_count >= 2:
        return True
    if keyword_count >= 1 and has_price:
        return True
    return False


def parse_signal(text: str) -> SignalAction | None:
    """Parse a Telegram message into a SignalAction, or None if not a signal.

    A message with two instructions ("take half profits and set breakeven")
    returns the first; parse_signals() returns both.
    """
    actions = parse_signals(text)
    return actions[0] if actions else None


def parse_signals(text: str) -> list[SignalAction]:
    """Parse a Telegram message into the SignalActions it asks for, in order.

    Priority order:
    1. New trade at the start of the message (zone, single price, text-only)
    2. Trade management: close all, else partial close, then SL/breakeven
    3. TP update
    4. New trade anywhere in the message
    """
    stripped = text.strip()
    if not stripped:
        return []

    # ── 1. New trade leading the message ──────────────────────────────
    # An open signal can itself contain management words ("SL: will update"),
    # so a message that starts with one is a new trade.
    opened = _parse_open(stripped, text, anchored=True)
    if opened:
        return [opened]

    # ── 2. Trade management ───────────────────────────────────────────
    actions = _parse_management(stripped, text)
    if actions:
        return actions

    # ── 3. TP update ──────────────────────────────────────────────────
    tp_update = _RE_TP_UPDATE.search(stripped)
    if tp_update:
        return [SignalAction(
            type=SignalType.MODIFY_TP,
            symbol=_extract_symbol_from_text(stripped),
            raw_text=text,
            new_tp=float(tp_update.group("tp")),
        )]

    # ── 4. New trade anywhere ─────────────────────────────────────────
    opened = _parse_open(stripped, text, anchored=False)
    if opened:
        return [opened]

    if is_signal_like(stripped):
        logger.warning("Signal-like text not parsed: %.200s", stripped)
    return []


def _parse_open(stripped: str, raw_text: str, anchored: bool) -> SignalAction | None:
    """Zone entry, then single-price entry, then text-only "now" entry."""
    def ok(match: re.Match | None) -> bool:
        if not match:
            return False
        return not anchored or not re.search(r"\w", stripped[:match.start()])

    open_match = _RE_OPEN.search(stripped)
    if ok(open_match):
        return _build_open_signal(open_match, stripped, raw_text, zone=True)

    open_single = _RE_OPEN_SINGLE.search(stripped)
    if ok(open_single):
        return _build_open_signal(open_single, stripped, raw_text, zone=False)

    # Phase 6 D-01/D-02: the regex is line-anchored so any numeric/extra token
    # forces a miss here — maintaining the D-02 "no numerics" invariant.
    text_only_match = _RE_OPEN_TEXT_ONLY.match(stripped)
    if text_only_match:
        symbol = _resolve_symbol(text_only_match.group("symbol"))
        direction = (
            Direction.BUY
            if text_only_match.group("direction").lower() == "buy"
            else Direction.SELL
        )
        return SignalAction(
            type=SignalType.OPEN_TEXT_ONLY,
            symbol=symbol,
            raw_text=raw_text,
            direction=direction,
            entry_zone=None,
            sl=None,
            tps=[],
        )
    return None


def _build_open_signal(
    match: re.Match, stripped: str, raw_text: str, zone: bool
) -> SignalAction | None:
    """Build a SignalAction for a new trade from a regex match."""
    symbol = _resolve_symbol(match.group("symbol"))
    direction = Direction.BUY if match.group("direction").upper() == "BUY" else Direction.SELL

    if zone:
        p1 = float(match.group("price1"))
        p2 = float(match.group("price2"))
        entry_zone = (min(p1, p2), max(p1, p2))
    else:
        price = float(match.group("price"))
        entry_zone = (price, price)  # single price = zero-width zone

    # Extract SL
    sl_match = _RE_SL.search(stripped)
    sl = float(sl_match.group("sl")) if sl_match else None

    # Extract all TPs
    tps: list[float | str] = []
    for tp_match in _RE_TP.finditer(stripped):
        val = tp_match.group("tp")
        tps.append(val.lower() if val.lower() == "open" else float(val))

    # Validate SL direction
    if sl is not None and entry_zone:
        zone_mid = (entry_zone[0] + entry_zone[1]) / 2
        if direction == Direction.BUY and sl >= zone_mid:
            logger.warning("Invalid signal: BUY but SL (%.2f) >= entry zone mid (%.2f)", sl, zone_mid)
            return None
        if direction == Direction.SELL and sl <= zone_mid:
            logger.warning("Invalid signal: SELL but SL (%.2f) <= entry zone mid (%.2f)", sl, zone_mid)
            return None

    # Select target TP (TP2 by default)
    target_tp_index = KEYWORDS.get("default_target_tp", 2)
    target_tp = _select_target_tp(tps, target_tp_index)

    return SignalAction(
        type=SignalType.OPEN,
        symbol=symbol,
        raw_text=raw_text,
        direction=direction,
        entry_zone=entry_zone,
        sl=sl,
        tps=tps,
        target_tp=target_tp,
    )


# ── Trade management ────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Lower-case, straighten quotes, collapse stretched letters and spaces."""
    t = text.lower()
    t = t.replace("‘", "'").replace("’", "'").replace("`", "'")
    # Quoted text is what readers are asked to send back ('PM me "closed all"').
    t = re.sub(r"[\"“”„«»][^\"“”„«»\n]*[\"“”„«»]", " ", t)
    t = re.sub(r"([a-z])\1{2,}", r"\1", t)  # "breakevennnn" -> "breakeven"
    return re.sub(r"[ \t]+", " ", t)


# Sentence boundaries: sentence punctuation (not a decimal point), new lines,
# "|" and ";". Clauses split sentences further on ", " and "&". Delimiters are
# kept so a sentence can be seen as a question.
_RE_SENTENCE = re.compile(r"(.+?)((?:(?<!\d)\.(?!\d)|[!?\n;|])+|$)", re.S)
_RE_CLAUSE_SPLIT = re.compile(r",\s|&")
_RE_LEVEL_FRAGMENT = re.compile(r"^(?:to|at)?\W*\d{3,5}(?:[.,]\d{1,2})?\b")


def _clauses(norm: str) -> list[tuple[str, bool]]:
    """(clause, is_question) pairs of a normalized message.

    Every clause of a sentence that ends in "?" is a question ("Have you closed
    all your profits, or you still holding a few?"), as is a clause that opens
    like one ("Did anyone manage to secure some profits").
    """
    out = []
    for m in _RE_SENTENCE.finditer(norm):
        sentence_question = "?" in m.group(2)
        parts: list[str] = []
        for part in _RE_CLAUSE_SPLIT.split(m.group(1)):
            part = part.strip()
            if not part:
                continue
            # A level split off by a comma belongs to the clause before it:
            # "adjust SL +20 pips for now, to 4319".
            if parts and _RE_LEVEL_FRAGMENT.match(part):
                parts[-1] = f"{parts[-1]}, {part}"
            else:
                parts.append(part)
        for clause in parts:
            out.append((clause, sentence_question or bool(_RE_QUESTION_START.search(clause))))
    return out


def _blocked(clause: str, *, holder_ok: bool = False, level_ok: bool = False) -> bool:
    """Negated, conditional or hedged — not an instruction to act on now.

    holder_ok drops conditions that only address holders or satisfied traders
    ("if you want to hold", "if satisfied") before the check. level_ok allows
    "at <price>", which in an SL move is the new level, not a condition.
    """
    checked = _RE_HOLDER_CONDITION.sub(" ", clause) if holder_ok else clause
    return bool(
        _RE_NEGATION.search(checked)
        or _RE_CONDITION.search(checked)
        or (not level_ok and _RE_AT_LEVEL.search(checked))
        or _RE_HEDGE.search(checked)
    )


def _guarded_clauses(norm: str) -> list[tuple[str, str, bool]]:
    """(clause, text to guard-check, is_question) for each clause.

    The guard text is the clause itself, prefixed by the clause before it when
    that one opened with a condition ("Once we hit TP1, lets take ...").
    """
    out = []
    carry = ""
    for clause, is_question in _clauses(norm):
        out.append((clause, f"{carry} {clause}".strip(), is_question))
        carry = clause if _RE_LEADING_CONDITION.search(clause) else ""
    return out


def _sl_move_allowed(clause: str, guarded: str) -> bool:
    """The clause asks to move the SL, and is not negated, conditional or hedged.

    Only the words up to the SL instruction are checked for a negation, since
    the reason that follows often has one ("adjust SL to 3902, I don't want to
    get wicked out") while "not adjusting SL" puts it before.
    """
    trigger = _RE_SL_TRIGGER.search(clause)
    if not trigger:
        return False
    lead = guarded[: len(guarded) - len(clause) + trigger.end()]
    without_negation = _RE_NEGATION.sub(" ", guarded)
    return not _RE_NEGATION.search(lead) and not _blocked(without_negation, level_ok=True)


def _future_without_now(clause: str) -> bool:
    return bool(_RE_FUTURE.search(clause)) and not _RE_NOW.search(clause)


def _parse_level(text: str) -> float:
    return float(text.replace(",", "."))


def _sl_level(clause: str) -> float | None:
    """The new SL level in an SL-move clause, or None if it gives none.

    The provider often puts a reason between the verb and the level ("adjust SL
    because of this insane volume to 3989.2") and a pip count next to it
    ("+20 pips to 4630"), so the level is the number led by "to", else by ":" /
    "is", else by "at", else the last level after the SL word.
    """
    sl_word = re.search(rf"\b{_SL_WORD}\b", clause)
    if not sl_word:
        return None
    tail_start = sl_word.end()
    levels = [m for m in _RE_LEVEL.finditer(clause) if m.start() >= tail_start]
    if not levels:
        return None
    for lead in _LEVEL_LEAD_PRIORITY:
        led = [m for m in levels if lead.search(clause[tail_start:m.start()])]
        if led:
            return _parse_level(led[-1].group("num"))
    return _parse_level(levels[-1].group("num"))


def _parse_management(stripped: str, raw_text: str) -> list[SignalAction]:
    """Close-all, partial close, SL move and breakeven instructions in a message.

    Close-all wins over everything else. Otherwise a partial close comes first,
    then the SL change, so "take half profits and set breakeven" closes half and
    moves the rest to breakeven.
    """
    symbol = _extract_symbol_from_text(stripped)
    norm = _normalize(stripped)

    whole_sl = _RE_SL_STANDALONE.match(norm)
    if whole_sl:
        return [SignalAction(
            type=SignalType.MODIFY_SL, symbol=symbol, raw_text=raw_text,
            new_sl=_parse_level(whole_sl.group("price")),
        )]

    close_all = False
    partial_pct: float | None = None
    new_sl: float | None = None   # last SL level given in the message
    breakeven = False
    your_choice = bool(_RE_YOUR_CHOICE.search(norm))

    for clause, guarded, is_question in _guarded_clauses(norm):
        if is_question:
            continue

        closes_blocked = (
            your_choice
            or _blocked(guarded)
            or _RE_OPTIONAL.search(clause)
            or _future_without_now(clause)
        )
        if not closes_blocked:
            if _RE_CLOSE_ALL.search(clause):
                close_all = True
            elif _RE_CLOSED_ALL.search(clause) and (
                _RE_NOW.search(clause) or len(clause.split()) <= 6
            ):
                close_all = True
            elif _RE_PARTIAL.search(clause):
                pct = _RE_CLOSE_PERCENT.search(clause)
                partial_pct = float(pct.group(1)) if pct else 50.0

        if _sl_move_allowed(clause, guarded):
            level = _sl_level(clause)
            if level is not None:
                new_sl = level
                continue

        if (
            not your_choice
            and _RE_BE.search(clause)
            and not _RE_BE_INFO.search(clause)
            and not _blocked(guarded, holder_ok=True)
            and not _future_without_now(clause)
        ):
            breakeven = True

    if close_all:
        return [SignalAction(type=SignalType.CLOSE, symbol=symbol, raw_text=raw_text)]

    actions: list[SignalAction] = []
    if partial_pct is not None:
        actions.append(SignalAction(
            type=SignalType.CLOSE_PARTIAL, symbol=symbol, raw_text=raw_text,
            close_percent=partial_pct,
        ))
    if new_sl is not None:
        # An explicit level beats a breakeven mention in the same message.
        actions.append(SignalAction(
            type=SignalType.MODIFY_SL, symbol=symbol, raw_text=raw_text, new_sl=new_sl,
        ))
    elif breakeven:
        actions.append(SignalAction(
            type=SignalType.MODIFY_SL, symbol=symbol, raw_text=raw_text,
            new_sl=0.0,  # sentinel: 0.0 means "use entry price"
        ))
    return actions


def is_sl_announcement(text: str) -> bool:
    """An SL change announced without its level ("Move SL +15 more pips ok").

    The provider then sends the level in a separate message ("4282.5"); see
    MessageFlow.
    """
    norm = _normalize(text.strip())
    if _RE_SL_STANDALONE.match(norm):
        return False
    for clause, guarded, is_question in _guarded_clauses(norm):
        if is_question or not _sl_move_allowed(clause, guarded):
            continue
        if _RE_BE.search(clause):
            continue
        if _sl_level(clause) is None:
            return True
    return False


class MessageFlow:
    """Per-chat context around parse_signals(), for messages that depend on
    the ones before them.

    * SL level in a follow-up message: "Let's adjust SL + 15 pips" is followed
      within a minute by "4282.5". A bare price only means an SL level while an
      announcement from the same chat is pending.
    * Repeated partial closes: the provider often sends "Take some profits" and
      "I'm taking half profits" seconds apart. Each would close half of what is
      left, so a partial close within the cooldown of the previous one is
      dropped.
    """

    def __init__(
        self,
        sl_window_seconds: float = SL_FOLLOWUP_WINDOW_SECONDS,
        partial_cooldown_seconds: float = PARTIAL_CLOSE_COOLDOWN_SECONDS,
    ):
        self._sl_window = sl_window_seconds
        self._partial_cooldown = partial_cooldown_seconds
        self._sl_announced: dict[object, float] = {}  # chat -> announced at
        self._last_partial: dict[object, float] = {}  # chat -> last partial close

    def actions_for(
        self, chat: object, text: str, now: float | None = None,
    ) -> list[SignalAction]:
        """The actions one message asks for. Call for every message of the
        chat, in order."""
        now = time.time() if now is None else now
        actions = parse_signals(text)

        if any(a.type == SignalType.MODIFY_SL for a in actions):
            self._sl_announced.pop(chat, None)
        elif is_sl_announcement(text):
            self._sl_announced[chat] = now
        elif not actions:
            followup = self._sl_followup(chat, text, now)
            if followup:
                actions = [followup]

        kept = []
        for action in actions:
            if action.type == SignalType.CLOSE_PARTIAL:
                last = self._last_partial.get(chat)
                if last is not None and now - last < self._partial_cooldown:
                    logger.info(
                        "Partial close %.0fs after the previous one — dropped: %.100s",
                        now - last, text,
                    )
                    continue
                self._last_partial[chat] = now
            kept.append(action)
        return kept

    def _sl_followup(self, chat: object, text: str, now: float) -> SignalAction | None:
        announced = self._sl_announced.get(chat)
        if announced is None:
            return None
        if now - announced > self._sl_window:
            self._sl_announced.pop(chat, None)
            return None
        bare = _RE_BARE_PRICE.match(_normalize(text.strip()))
        if not bare:
            return None
        self._sl_announced.pop(chat, None)
        return SignalAction(
            type=SignalType.MODIFY_SL,
            symbol=_extract_symbol_from_text(text),
            raw_text=text,
            new_sl=_parse_level(bare.group("price")),
        )


def _extract_symbol_from_text(text: str) -> str:
    """Try to find a known symbol in the text using compiled regex, default to XAUUSD."""
    match = _SYMBOL_PATTERN.search(text)
    if match:
        return SYMBOL_MAP[match.group().lower()]
    return "XAUUSD"  # default for gold signal groups


def format_parsed_signal(signal: SignalAction) -> str:
    """Format a parsed signal for Discord logging."""
    if signal.type == SignalType.OPEN:
        zone = signal.entry_zone
        zone_str = f"{zone[0]:.2f} - {zone[1]:.2f}" if zone else "N/A"
        dir_str = signal.direction.value.upper() if signal.direction else "?"
        tps_str = ", ".join(
            str(tp) if isinstance(tp, str) else f"{tp:.2f}" for tp in signal.tps
        )
        sl_str = f"{signal.sl:.2f}" if signal.sl is not None else "N/A"
        tp_str = f"{signal.target_tp:.2f}" if signal.target_tp is not None else "N/A"
        return (
            f"PARSED SIGNAL: {dir_str} {signal.symbol}\n"
            f"  Zone: {zone_str}\n"
            f"  SL: {sl_str}\n"
            f"  TPs: [{tps_str}]\n"
            f"  Target TP: {tp_str}"
        )
    elif signal.type == SignalType.CLOSE:
        return f"PARSED SIGNAL: CLOSE {signal.symbol}"
    elif signal.type == SignalType.CLOSE_PARTIAL:
        return f"PARSED SIGNAL: CLOSE {signal.close_percent:.0f}% {signal.symbol}"
    elif signal.type == SignalType.MODIFY_SL:
        if signal.new_sl == 0.0:
            return f"PARSED SIGNAL: MOVE SL TO BREAKEVEN {signal.symbol}"
        return f"PARSED SIGNAL: UPDATE SL → {signal.new_sl:.2f} {signal.symbol}"
    elif signal.type == SignalType.MODIFY_TP:
        return f"PARSED SIGNAL: UPDATE TP → {signal.new_tp:.2f} {signal.symbol}"
    return f"PARSED SIGNAL: {signal.type.value} {signal.symbol}"
