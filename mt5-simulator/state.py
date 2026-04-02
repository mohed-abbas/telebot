"""In-memory state management for the MT5 simulator."""

from dataclasses import dataclass, field
import threading

GOLD_CONTRACT_SIZE = 100  # 1 lot = 100 troy oz
DEFAULT_LEVERAGE = 100


@dataclass
class SimulatedPosition:
    ticket: int
    symbol: str
    direction: str  # "buy" or "sell"
    volume: float
    open_price: float
    sl: float
    tp: float
    profit: float = 0.0
    comment: str = ""
    magic: int = 0


@dataclass
class SimulatedPendingOrder:
    ticket: int
    symbol: str
    order_type: str  # "buy_limit", "sell_limit", "buy_stop", "sell_stop"
    volume: float
    price: float
    sl: float
    tp: float
    comment: str = ""
    magic: int = 0


class SimulatorState:
    def __init__(self, initial_balance: float = 10000.0):
        self.connected = False
        self.login = 0
        self.server = ""
        self.balance = initial_balance
        self.currency = "USD"
        self.positions: dict[int, SimulatedPosition] = {}
        self.pending_orders: dict[int, SimulatedPendingOrder] = {}
        self._ticket_counter = 100000
        self._lock = threading.Lock()

    def next_ticket(self) -> int:
        with self._lock:
            self._ticket_counter += 1
            return self._ticket_counter

    def calculate_equity(self, get_price_fn) -> float:
        total_pnl = sum(
            self._position_pnl(pos, get_price_fn)
            for pos in self.positions.values()
        )
        return self.balance + total_pnl

    def calculate_margin(self, get_price_fn) -> float:
        total = 0.0
        for pos in self.positions.values():
            price_data = get_price_fn(pos.symbol)
            if price_data:
                mid = (price_data[0] + price_data[1]) / 2
                contract_size = GOLD_CONTRACT_SIZE  # TODO: per-symbol
                total += pos.volume * contract_size * mid / DEFAULT_LEVERAGE
        return total

    def _position_pnl(self, pos: SimulatedPosition, get_price_fn) -> float:
        price_data = get_price_fn(pos.symbol)
        if not price_data:
            return 0.0
        bid, ask = price_data
        close_price = bid if pos.direction == "buy" else ask
        contract_size = GOLD_CONTRACT_SIZE
        if pos.direction == "buy":
            return (close_price - pos.open_price) * pos.volume * contract_size
        else:
            return (pos.open_price - close_price) * pos.volume * contract_size
