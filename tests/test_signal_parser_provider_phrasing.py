"""Trade-management phrasing of the GTMO VIP provider.

Cases are the provider's own wording, found by replaying the full channel
export (2022-2026) through the parser. Each group pins both sides: what must be
acted on, and the look-alike chat, questions, plans and reports that must not.
"""

import pytest

from models import Direction, SignalType
from signal_parser import MessageFlow, is_signal_like, parse_signal, parse_signals


def _kinds(text: str) -> list[tuple[str, float | None]]:
    out = []
    for a in parse_signals(text):
        value = a.new_sl if a.type == SignalType.MODIFY_SL else a.close_percent
        out.append((a.type.value, value))
    return out


# ═══════════════════════════════════════════════════════════════════════
# SL moves with a level
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("text, level", [
    ("I'm on low risk so I'll also adjust SL to 4025 ok", 4025.0),
    ("Move SL to 3898 ok", 3898.0),
    ("Update SL to 4129.3 ok last update.", 4129.3),
    ("Adjust SL to 4545 for now", 4545.0),
    ("Moving SL to 4030.3", 4030.3),
    ("SL to 4086", 4086.0),
    ("New SL 4368 ok", 4368.0),
    ("Update Sl to: 1880", 1880.0),
    ("adjust sl to maximum 2395", 2395.0),
    ("Adjusting SL 3317", 3317.0),
    ("Adjust SL: 3940.5 because it went has such a big volume", 3940.5),
    ("actually lets place the SL at 4385 ok below this low.", 4385.0),
    ("Last adjustment because I didnt add any further entries, my new SL will be at 4189.5, "
     "to avoid being wicked out.", 4189.5),
    ("Lets adjust SL to 3902 guys its quite high volume I dont want to get wicked out ok", 3902.0),
    # The reason sits between the verb and the level.
    ("I'll already adjust SL because of this insane volume to 3989.2", 3989.2),
    ("Adjust SL due to high volume to 4132.2", 4132.2),
    ("new SL to avoid getting wicked out 3776.5", 3776.5),
    # "better" / "below" / "because" must not be read as "be" (breakeven).
    ("Move SL better to 4137", 4137.0),
    ("Last adjustment for today, I'll move my SL below this wick at 3956, "
     "so move SL to 3955, if we don't fly by this time", 3955.0),
    # Pip counts next to the level are not the level.
    ("Already at the bottom of the zone , move SL 15 pips down to 3948.5", 3948.5),
    ("Adjust SL +20 pips to 4630", 4630.0),
    ("Move SL +15 pips last adjustment ok , new SL to 4536.5", 4536.5),
    ("Guys I'll one last time adjust SL +15 more pips ok\n\nSo new SL is 4336.5 ok", 4336.5),
    # A comma between the instruction and the level.
    ("but will adjust SL +20 pips for now, to 4319 to avoid high volume spikes", 4319.0),
    ("Adjust SL +20 pips to, 4022", 4022.0),
    # A message that is only the level.
    ("SL: 3432", 3432.0),
    ("Update SL: 4978", 4978.0),
])
def test_sl_move_to_level(text, level):
    assert _kinds(text) == [("modify_sl", level)]


@pytest.mark.parametrize("text", [
    "Not adjusting SL this time",
    "I'm not going to adjust SL on this trade, will stick to 4000.20",
    "I will not adjust SL on this trade, the SL is already placed below the zone.",
    "Might adjust the SL",
    "Filled the entire zone now just watchin not placing more entries for now. But I might adjust SL stay tuned!",
    "Stick to the SL, I'm not adjusting for this trade",
    "Hit SL",
    "Gold 2150\nSL: 2140",
])
def test_sl_talk_that_is_not_a_move(text):
    assert not any(a.type == SignalType.MODIFY_SL for a in parse_signals(text))


# ═══════════════════════════════════════════════════════════════════════
# Breakeven
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("text", [
    "Make sure u set breakeven too!",
    "SET BREAKEVENNN!!!",
    "Set breakevennnn nowww!!🤑🤑🤑🙏🏽",
    "TP2 checkkk🤑🤑🤑 \n\nSet breakeven now for zero risk everyone!!",
    "SET BREAKEVENNNN NOW 4022 HITT",
    "BREAKEVEN ZERO RISK!!",
    "SET FULLY BREAKEVEN GUYS NO MORE RISK COME ON !!!!",
    "I WILL SET BREAKEVEN NOW FOR ZERO RISK!!! 🤑🤑🤑🤑🤑",
    "Holding only my bottom entries set breakeven NOW for zero risk🤑🤑🤑🚀",
    "Breakeven set zero risk!🤑🤑🤑💦",
    "Turn this trade now 100% into zero risk by moving your SL below the entries!👍🏽",
    "STOP LOSS TO THE ENTRY NOW, OR TRAIL SL INTO PROFITS!!!!",
    "Move SL to breakeven",
    "Move SL to BE",
    "SL to entry",
    # Advice to holders: the bot holds, so it applies.
    "if u want to hold set be+",
    "instanr profit! 🔥 can close all if satisfied, if you like to hold make sure to set be+ 🏅",
    "ok again! 😎 almost tp2 💰 scalper can close now all if satisfied!💥 only hold with be+ now!",
])
def test_breakeven(text):
    assert _kinds(text) == [("modify_sl", 0.0)]


@pytest.mark.parametrize("text", [
    "Breakeven hit",
    "BREAKEVEN HIT!",
    "Some entries hit breakeven, rest still runninggg🤑🤑💦",
    "I dont care if it hits breakeven",
    "Did you took some profits and set breakeven?",
    "Who's still holding a few entries with breakeven, who has closed all profits?",
    "Once we hit TP1, lets take worst entries and set breakeven ok",
    "At Tp2 I‘ll close half profits & set breakeven for zero risk!🤑🤑👏🏽",
    "Why did we set breakeven 😂😂😂",
    "Message me now everyone \"blues, closed or breakeven set\" @GoldTraderInfo",
    "now the more likely move would be that this support sends gold to the top of the range",
    "Its a small SL because i dont want to risk more today ok respect the sl",
    "be ready ok",
])
def test_not_breakeven(text):
    assert parse_signals(text) == [] or not any(
        a.type == SignalType.MODIFY_SL for a in parse_signals(text)
    )


# ═══════════════════════════════════════════════════════════════════════
# Close all
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("text", [
    "OUT OF ALL ENTRIES NOW!!!",
    "Out of all trades",
    "I‘m completly out of all positions!!",
    "Breakeven hit, out of all entries!",
    "Last few entries hit breakeven now, out of all trades!",
    "Cut loss now",
    "Cut loss guys sorry, bears are too strong pushing it down.",
    "I've used this small push to cut loss",
    "I'm cutting loss here.",
    "CLOSED ALL NOWWWWW",
    "TEAM VIP, ALL ENTRIES CLOSED",
    "Closed all entries",
    "300+ pips I‘ll close all now!!",
    "Close all",
    "Close gold",
    "Exit trade",
])
def test_close_all(text):
    assert _kinds(text) == [("close", None)]


@pytest.mark.parametrize("text", [
    "ok, trade in profit 🏆 scalper can close all if satisfied🙏🏽",
    "If I close all now I‘ll be recovered but I‘ll hold, I believe too much in this trade too close now!",
    "If I get to $5k with this 2 entries I‘ll close all",
    "Did you close all trades in profits or u still holding a few like me?",
    "Have you closed all your profits, or you still holding a few entries like me ?",
    "Team VIP TP4 is waterfall, I'm going to be happy with so I might close all shortly!",
    "If it breaks lower then this now, I will have to cut loss",
    "I'll cut loss 10 pips before SL",
    "First sell hit 5 TP‘s 🤑🤑 I closed all entries from there",
    "📥 PM me \"still holding a few, or closed all profits\" @GoldTraderInfo",
    "Message me \"still in or closed all\" @GoldTraderInfo",
    "Take some profits if your happy or close all if your satisfied",
])
def test_not_close_all(text):
    assert not any(a.type == SignalType.CLOSE for a in parse_signals(text))


# ═══════════════════════════════════════════════════════════════════════
# Partial close
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("text, pct", [
    ("TAKE SOME PROFITSSSS", 50.0),
    ("Take some profits from the top now!", 50.0),
    ("close worst entries", 50.0),
    ("Close ur worst entries now to reduce risk and take some profits🚀🙏🏽🤑", 50.0),
    ("I‘m taking half profits now", 50.0),
    ("Close half", 50.0),
    ("Close 30% gold", 30.0),
    ("Secure profits", 50.0),
    ("TP1 hit - close partial", 50.0),
])
def test_partial_close(text, pct):
    assert _kinds(text) == [("close_partial", pct)]


@pytest.mark.parametrize("text", [
    "At TP3 I‘ll close half profits again 🤑🤑🚀",
    "TP4 and I‘ll close half profits",
    "Did anyone manage to secure some profits",
    "Rocket upp above all entries then we start taking some Profits 🙏🏽🤑",
    "Make sure to take some profits from time to time, and be on breakeven!",
    "instant profit! zero floating🙏🏽 scalper can close half or all if satisfied💰",
    "can secure already if satisfied 💰",
])
def test_not_partial_close(text):
    assert not any(a.type == SignalType.CLOSE_PARTIAL for a in parse_signals(text))


# ═══════════════════════════════════════════════════════════════════════
# Two instructions in one message
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("text", [
    "TAKE HALF PROFITS NOW AND SET BREAKEVEN EVERYONEEEEE",
    "Set breakeven and take some profits 👍🏽🤑",
    "Close worst entries and set breakeven now ok",
    "Team VIP, lets take some profits & set breakeven for zero risk!!",
])
def test_partial_close_then_breakeven(text):
    assert _kinds(text) == [("close_partial", 50.0), ("modify_sl", 0.0)]
    assert parse_signal(text).type == SignalType.CLOSE_PARTIAL


def test_optional_partial_keeps_breakeven():
    # "the way your satisfied" leaves the close to the reader; breakeven stays.
    text = "Set breakeven for zero risk & take some profits the way your satisfied🤑🤑👏🏽"
    assert _kinds(text) == [("modify_sl", 0.0)]


def test_your_choice_closes_nothing():
    text = ("Almost at TP2 , High Impact news in 5 minutes if you want zero risk, "
            "close or set breakeven or take some profits, you decide")
    assert _kinds(text) == []


def test_close_all_wins_over_other_instructions():
    assert _kinds("Breakeven hit out of all tradeessss") == [("close", None)]


# ═══════════════════════════════════════════════════════════════════════
# Re-entries and open signals
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("text, direction", [
    ("Gold buy now again", Direction.BUY),
    ("Gold sell now again", Direction.SELL),
    ("Re-entry gold sell now", Direction.SELL),
    ("Gold re-entry buy now", Direction.BUY),
    ("Gold buy re-entry now", Direction.BUY),
    ("Gold buy now re-entry", Direction.BUY),
])
def test_text_only_reentry(text, direction):
    s = parse_signal(text)
    assert s.type == SignalType.OPEN_TEXT_ONLY
    assert s.direction == direction


@pytest.mark.parametrize("text, direction, zone", [
    ("Gold re-entry sell now 4163.8 - 4168\n\nSL: 4172\n\nTP: 4161\nTP: 4159\nTP: open",
     Direction.SELL, (4163.8, 4168.0)),
    ("Gold buy now re-entry 4213 - 4210\n\nSL: 4207\n\nTP: 4215\nTP: 4217\nTP: open",
     Direction.BUY, (4210.0, 4213.0)),
    ("Gold sel now 4911.8 - 4915\n\nSL: 4920\n\nTP: 4908\nTP: 4906",
     Direction.SELL, (4911.8, 4915.0)),
])
def test_reentry_signal_with_levels(text, direction, zone):
    s = parse_signal(text)
    assert s.type == SignalType.OPEN
    assert s.direction == direction
    assert s.entry_zone == zone


def test_open_signal_with_sl_to_follow_is_not_a_tp_update():
    s = parse_signal("Gold sell now 1935 - 1938\n\nSL: will update\n\nTP: 1933\nTP: 1931")
    assert s.type == SignalType.OPEN
    assert s.sl is None


# ═══════════════════════════════════════════════════════════════════════
# Unparsed instructions still raise an alert
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("text", [
    "Take more Profits at TP1 ok, set breakeven after",
    "Set TP1, 4020, at some of our first entries / worst entries ok",
])
def test_unparsed_instruction_is_signal_like(text):
    assert is_signal_like(text)


# ═══════════════════════════════════════════════════════════════════════
# MessageFlow: level in the next message, repeated partial closes
# ═══════════════════════════════════════════════════════════════════════


def test_sl_level_in_the_next_message():
    flow = MessageFlow()
    assert flow.actions_for("vip", "Move SL +15 more pips ok", now=1000.0) == []
    [action] = flow.actions_for("vip", "4282.5", now=1030.0)
    assert action.type == SignalType.MODIFY_SL
    assert action.new_sl == 4282.5
    # Used once: a second bare price is chat again.
    assert flow.actions_for("vip", "4290", now=1040.0) == []


def test_bare_price_without_announcement_is_ignored():
    flow = MessageFlow()
    assert flow.actions_for("vip", "4282.5", now=1000.0) == []


def test_sl_announcement_expires():
    flow = MessageFlow(sl_window_seconds=120)
    flow.actions_for("vip", "Let's adjust SL + 15 pips", now=1000.0)
    assert flow.actions_for("vip", "4282.5", now=1200.0) == []


def test_sl_announcement_is_per_chat():
    flow = MessageFlow()
    flow.actions_for("vip", "Let's adjust SL + 15 pips", now=1000.0)
    assert flow.actions_for("public", "4282.5", now=1010.0) == []


def test_negated_announcement_does_not_wait_for_a_level():
    flow = MessageFlow()
    flow.actions_for("vip", "Will not adjust SL on this trade", now=1000.0)
    assert flow.actions_for("vip", "4282.5", now=1010.0) == []


def test_repeated_partial_close_within_cooldown_is_dropped():
    flow = MessageFlow(partial_cooldown_seconds=180)
    first = flow.actions_for("vip", "Take some profitssss🤑🤑🤑💦", now=1000.0)
    assert [a.type for a in first] == [SignalType.CLOSE_PARTIAL]
    # Same minute: dropped, but the breakeven in it still runs.
    second = flow.actions_for("vip", "Set breakeven now and take some more profits", now=1030.0)
    assert [(a.type, a.new_sl) for a in second] == [(SignalType.MODIFY_SL, 0.0)]
    # After the cooldown it is a new partial close.
    third = flow.actions_for("vip", "TAKE SOME PROFITS", now=1300.0)
    assert [a.type for a in third] == [SignalType.CLOSE_PARTIAL]
