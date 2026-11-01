"""Minimal Excel formula engine (pure python) for the XLS sheet view.

Supports: numbers, strings, booleans, A1 / $A$1 / Sheet!A1 / 'My Sheet'!A1:B9
references, operators (+ - * / ^ & % = <> < > <= >=, unary -), and the
functions in FUNCTIONS below, plus terminal-only functions:

    =TV("NASDAQ:AAPL", "last")    live quote field (last, change, change_pct,
                                   open, high, low, prev_close, volume, bid, ask ...)

Unsupported functions evaluate to "#NAME?" — the Excel service then falls back
to the value Excel itself cached in the file (if any).
"""
from __future__ import annotations

import datetime as dt
import math
import re
import statistics
from typing import Any, Callable

# ---------------------------------------------------------------------------
# values / errors
# ---------------------------------------------------------------------------


class XLError(str):
    pass


DIV0, VALUE, REF, NAME, NA, CIRC, NUM = (XLError(e) for e in
                                         ("#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#N/A", "#CIRC!", "#NUM!"))


class Range(list):
    """2-D list of values (rows)."""

    def flat(self) -> list[Any]:
        return [v for row in self for v in row]


def col_to_num(col: str) -> int:
    n = 0
    for ch in col.upper():
        n = n * 26 + ord(ch) - 64
    return n


def num_to_col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


_ADDR = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")


def split_addr(addr: str) -> tuple[int, int]:
    m = _ADDR.match(addr)
    if not m:
        raise ValueError(addr)
    return int(m.group(2)), col_to_num(m.group(1))


def norm_addr(addr: str) -> str:
    r, c = split_addr(addr)
    return f"{num_to_col(c)}{r}"


# ---------------------------------------------------------------------------
# tokenizer / parser
# ---------------------------------------------------------------------------
_SHEET = r"(?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!"
_CELL = r"\$?[A-Za-z]{1,3}\$?\d+"
TOKEN = re.compile(
    r"\s*(?:"
    r"(?P<str>\"(?:[^\"]|\"\")*\")"
    r"|(?P<num>\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)"
    r"|(?P<func>[A-Za-z_][A-Za-z0-9_.]*)(?=\s*\()"
    rf"|(?P<ref>(?:{_SHEET})?{_CELL}(?::{_CELL})?)"
    r"|(?P<bool>TRUE|FALSE|true|false)\b"
    r"|(?P<op><=|>=|<>|[-+*/^&=<>%(),;])"
    r")"
)


def tokenize(src: str) -> list[tuple[str, str]]:
    pos, out = 0, []
    src = src.rstrip()
    while pos < len(src):
        m = TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise SyntaxError(f"unexpected {src[pos:pos + 10]!r}")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))  # type: ignore[arg-type]
        pos = m.end()
    return out


class Parser:
    """Precedence (low→high): comparison, &, + -, * /, ^, unary -, %."""

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.t, self.i = tokens, 0

    def peek(self) -> tuple[str, str] | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> tuple[str, str]:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expect(self, v: str) -> None:
        tok = self.peek()
        if not tok or tok[1] != v:
            raise SyntaxError(f"expected {v!r}")
        self.i += 1

    def parse(self):
        node = self.comparison()
        if self.peek() is not None:
            raise SyntaxError(f"unexpected token {self.peek()[1]!r}")  # type: ignore[index]
        return node

    def _binary(self, ops: tuple[str, ...], nxt):
        node = nxt()
        while (tok := self.peek()) and tok[0] == "op" and tok[1] in ops:
            self.take()
            node = ("bin", tok[1], node, nxt())
        return node

    def comparison(self):
        return self._binary(("=", "<>", "<", ">", "<=", ">="), self.concat)

    def concat(self):
        return self._binary(("&",), self.additive)

    def additive(self):
        return self._binary(("+", "-"), self.term)

    def term(self):
        return self._binary(("*", "/"), self.power)

    def power(self):
        return self._binary(("^",), self.unary)

    def unary(self):
        tok = self.peek()
        if tok and tok[0] == "op" and tok[1] in ("-", "+"):
            self.take()
            node = self.unary()
            return ("neg", node) if tok[1] == "-" else node
        return self.postfix()

    def postfix(self):
        node = self.primary()
        while (tok := self.peek()) and tok == ("op", "%"):
            self.take()
            node = ("pct", node)
        return node

    def primary(self):
        tok = self.peek()
        if tok is None:
            raise SyntaxError("unexpected end of formula")
        kind, v = self.take()
        if kind == "num":
            return ("lit", float(v))
        if kind == "str":
            return ("lit", v[1:-1].replace('""', '"'))
        if kind == "bool":
            return ("lit", v.upper() == "TRUE")
        if kind == "ref":
            return ("ref", v)
        if kind == "func":
            self.expect("(")
            args = []
            if self.peek() != ("op", ")"):
                while True:
                    if self.peek() in (("op", ","), ("op", ";")):
                        args.append(("lit", None))
                    else:
                        args.append(self.comparison())
                    if self.peek() in (("op", ","), ("op", ";")):
                        self.take()
                        continue
                    break
            self.expect(")")
            return ("call", v.upper(), args)
        if (kind, v) == ("op", "("):
            node = self.comparison()
            self.expect(")")
            return node
        raise SyntaxError(f"unexpected {v!r}")


def parse(formula: str):
    src = formula[1:] if formula.startswith("=") else formula
    return Parser(tokenize(src)).parse()


# ---------------------------------------------------------------------------
# coercion helpers
# ---------------------------------------------------------------------------

def to_num(v: Any) -> float | XLError:
    if isinstance(v, XLError):
        return v
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if v is None or v == "":
        return 0.0
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return VALUE
    return VALUE


def to_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def to_bool(v: Any) -> bool | XLError:
    if isinstance(v, XLError):
        return v
    if isinstance(v, str):
        if v.upper() in ("TRUE", "FALSE"):
            return v.upper() == "TRUE"
        return VALUE
    n = to_num(v)
    return n if isinstance(n, XLError) else n != 0


def _nums(args: list[Any]) -> list[float] | XLError:
    """Numbers for aggregate functions: ranges skip text/blank, scalars are coerced."""
    out: list[float] = []
    for a in args:
        if isinstance(a, Range):
            for v in a.flat():
                if isinstance(v, XLError):
                    return v
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append(float(v))
        else:
            n = to_num(a)
            if isinstance(n, XLError):
                return n
            out.append(n)
    return out


def _first_err(*vals: Any) -> XLError | None:
    for v in vals:
        if isinstance(v, XLError):
            return v
    return None


def _criteria(crit: Any) -> Callable[[Any], bool]:
    if isinstance(crit, str):
        m = re.match(r"^(<=|>=|<>|<|>|=)?(.*)$", crit)
        op, rhs = (m.group(1) or "="), m.group(2)  # type: ignore[union-attr]
        rn = to_num(rhs)
        if not isinstance(rn, XLError):
            def f(v, op=op, rn=rn):
                n = to_num(v)
                if isinstance(n, XLError) or (isinstance(v, str) and v != "" and isinstance(to_num(v), XLError)):
                    return op == "<>"
                return {"=": n == rn, "<>": n != rn, "<": n < rn, ">": n > rn, "<=": n <= rn, ">=": n >= rn}[op]
            return f
        return lambda v, op=op, rhs=rhs: (to_str(v).lower() == rhs.lower()) if op == "=" else (
            to_str(v).lower() != rhs.lower())
    return lambda v: v == crit or (to_num(v) == to_num(crit) and not isinstance(to_num(v), XLError))


def _round(x: float, d: int, mode: str) -> float:
    f = 10 ** d
    if mode == "up":
        return math.copysign(math.ceil(abs(x) * f - 1e-9) / f, x)
    if mode == "down":
        return math.copysign(math.floor(abs(x) * f + 1e-9) / f, x)
    return math.copysign(math.floor(abs(x) * f + 0.5) / f, x)


def _math1(fn: Callable[[float], float]) -> Callable[..., Any]:
    def wrapped(x):
        n = to_num(x)
        if isinstance(n, XLError):
            return n
        try:
            return fn(n)
        except (ValueError, OverflowError):
            return NUM
    return wrapped


def _vlookup(key, table, col, approx=True):
    if not isinstance(table, Range):
        return VALUE
    c = int(to_num(col)) - 1
    if c < 0 or c >= len(table[0]):
        return REF
    approx = to_bool(approx) if approx is not None else True
    if approx is True:
        best = None
        for row in table:
            v = row[0]
            if isinstance(v, (int, float)) and isinstance(key, (int, float)) and v <= key:
                best = row
        return best[c] if best else NA
    for row in table:
        if to_str(row[0]).lower() == to_str(key).lower():
            return row[c]
    return NA


def _match(key, rng, mode=1):
    vals = rng.flat() if isinstance(rng, Range) else [rng]
    mode = int(to_num(mode)) if mode is not None else 1
    if mode == 0:
        for i, v in enumerate(vals):
            if to_str(v).lower() == to_str(key).lower():
                return float(i + 1)
        return NA
    best = None
    for i, v in enumerate(vals):
        if isinstance(v, (int, float)) and isinstance(key, (int, float)) and (v <= key if mode == 1 else v >= key):
            best = i
    return float(best + 1) if best is not None else NA


def _index(rng, r, c=None):
    if not isinstance(rng, Range):
        return VALUE
    r = int(to_num(r))
    c = int(to_num(c)) if c is not None else 1
    if len(rng) == 1 and c == 1 and r > 1:  # single-row range: INDEX(row, n)
        r, c = 1, r
    try:
        return rng[r - 1][c - 1]
    except IndexError:
        return REF


def _sumproduct(*ranges):
    if not ranges or not all(isinstance(r, Range) for r in ranges):
        return VALUE
    flats = [r.flat() for r in ranges]
    if len({len(f) for f in flats}) != 1:
        return VALUE
    total = 0.0
    for vals in zip(*flats):
        p = 1.0
        for v in vals:
            p *= v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0
        total += p
    return total


def _agg(fn: Callable[[list[float]], float], min_n: int = 1):
    def wrapped(*args):
        xs = _nums(list(args))
        if isinstance(xs, XLError):
            return xs
        if len(xs) < min_n:
            return DIV0
        try:
            return fn(xs)
        except (ValueError, statistics.StatisticsError, ZeroDivisionError):
            return DIV0
    return wrapped


def _sumif(rng, crit, sum_rng=None):
    if not isinstance(rng, Range):
        return VALUE
    pred = _criteria(crit)
    vals = rng.flat()
    sums = sum_rng.flat() if isinstance(sum_rng, Range) else vals
    return float(sum(s for v, s in zip(vals, sums) if pred(v) and isinstance(s, (int, float))))


def _countif(rng, crit):
    if not isinstance(rng, Range):
        return VALUE
    pred = _criteria(crit)
    return float(sum(1 for v in rng.flat() if pred(v)))


def _averageif(rng, crit, avg_rng=None):
    if not isinstance(rng, Range):
        return VALUE
    pred = _criteria(crit)
    vals = rng.flat()
    src = avg_rng.flat() if isinstance(avg_rng, Range) else vals
    xs = [s for v, s in zip(vals, src) if pred(v) and isinstance(s, (int, float))]
    return sum(xs) / len(xs) if xs else DIV0


def _text_fn(fn):
    def wrapped(*args):
        e = _first_err(*args)
        return e if e else fn(*args)
    return wrapped


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "SUM": _agg(sum, 0),
    "AVERAGE": _agg(lambda xs: sum(xs) / len(xs)),
    "MIN": _agg(lambda xs: min(xs) if xs else 0.0, 0),
    "MAX": _agg(lambda xs: max(xs) if xs else 0.0, 0),
    "PRODUCT": _agg(lambda xs: math.prod(xs), 0),
    "MEDIAN": _agg(statistics.median),
    "STDEV": _agg(statistics.stdev, 2), "STDEV.S": _agg(statistics.stdev, 2),
    "STDEV.P": _agg(statistics.pstdev), "VAR": _agg(statistics.variance, 2),
    "VAR.S": _agg(statistics.variance, 2), "VAR.P": _agg(statistics.pvariance),
    "COUNT": lambda *a: float(sum(1 for x in a for v in (x.flat() if isinstance(x, Range) else [x])
                                  if isinstance(v, (int, float)) and not isinstance(v, bool))),
    "COUNTA": lambda *a: float(sum(1 for x in a for v in (x.flat() if isinstance(x, Range) else [x])
                                   if v not in (None, ""))),
    "AND": lambda *a: _first_err(*a) or all(to_bool(v) is True for x in a
                                              for v in (x.flat() if isinstance(x, Range) else [x])),
    "OR": lambda *a: _first_err(*a) or any(to_bool(v) is True for x in a
                                             for v in (x.flat() if isinstance(x, Range) else [x])),
    "NOT": lambda v: (lambda b: b if isinstance(b, XLError) else not b)(to_bool(v)),
    "ROUND": lambda x, d=0: _first_err(to_num(x), to_num(d)) or _round(to_num(x), int(to_num(d)), "half"),
    "ROUNDUP": lambda x, d=0: _first_err(to_num(x), to_num(d)) or _round(to_num(x), int(to_num(d)), "up"),
    "ROUNDDOWN": lambda x, d=0: _first_err(to_num(x), to_num(d)) or _round(to_num(x), int(to_num(d)), "down"),
    "ABS": _math1(abs), "SQRT": _math1(math.sqrt), "LN": _math1(math.log), "EXP": _math1(math.exp),
    "LOG10": _math1(math.log10), "INT": _math1(lambda x: float(math.floor(x))),
    "LOG": lambda x, b=10: _first_err(to_num(x), to_num(b)) or _math1(lambda v: math.log(v, to_num(b)))(x),
    "POWER": lambda x, y: _first_err(to_num(x), to_num(y)) or _math1(lambda v: v ** to_num(y))(x),
    "MOD": lambda x, y: _first_err(to_num(x), to_num(y)) or (DIV0 if to_num(y) == 0 else
                                                               to_num(x) - to_num(y) * math.floor(to_num(x) / to_num(y))),
    "PI": lambda: math.pi,
    "CONCAT": _text_fn(lambda *a: "".join(to_str(v) for x in a for v in (x.flat() if isinstance(x, Range) else [x]))),
    "CONCATENATE": _text_fn(lambda *a: "".join(to_str(v) for v in a)),
    "LEN": _text_fn(lambda s: float(len(to_str(s)))),
    "UPPER": _text_fn(lambda s: to_str(s).upper()), "LOWER": _text_fn(lambda s: to_str(s).lower()),
    "TRIM": _text_fn(lambda s: " ".join(to_str(s).split())),
    "LEFT": _text_fn(lambda s, n=1: to_str(s)[: int(to_num(n))]),
    "RIGHT": _text_fn(lambda s, n=1: to_str(s)[-int(to_num(n)):] if int(to_num(n)) else ""),
    "MID": _text_fn(lambda s, a, n: to_str(s)[int(to_num(a)) - 1: int(to_num(a)) - 1 + int(to_num(n))]),
    "TODAY": lambda: dt.date.today().isoformat(),
    "NOW": lambda: dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "VLOOKUP": _vlookup, "MATCH": _match, "INDEX": _index, "SUMPRODUCT": _sumproduct,
    "SUMIF": _sumif, "COUNTIF": _countif, "AVERAGEIF": _averageif,
}
LAZY = {"IF", "IFERROR", "IFNA"}


# ---------------------------------------------------------------------------
# evaluation over a workbook
# ---------------------------------------------------------------------------
QuoteLookup = Callable[[str, str], Any]


class Evaluator:
    """sheets: {sheet_name: {"A1": {"f": "=..."|None, "v": value}}}"""

    def __init__(self, sheets: dict[str, dict[str, dict[str, Any]]], quote: QuoteLookup | None = None) -> None:
        self.sheets = sheets
        self.quote = quote
        self.cache: dict[tuple[str, str], Any] = {}
        self.stack: set[tuple[str, str]] = set()
        self.ast_cache: dict[str, Any] = {}
        self.tv_symbols: set[str] = set()

    def value(self, sheet: str, addr: str) -> Any:
        key = (sheet, addr)
        if key in self.cache:
            return self.cache[key]
        if sheet not in self.sheets:
            return REF
        cell = self.sheets[sheet].get(addr)
        if cell is None:
            return None
        f = cell.get("f")
        if not f:
            return cell.get("v")
        if key in self.stack:
            return CIRC
        self.stack.add(key)
        try:
            ast = self.ast_cache.get(f)
            if ast is None:
                ast = self.ast_cache[f] = parse(f)
            v = self.eval(ast, sheet)
            if isinstance(v, Range):
                v = v[0][0] if v and v[0] else None
        except SyntaxError:
            v = NAME
        except RecursionError:
            v = CIRC
        finally:
            self.stack.discard(key)
        self.cache[key] = v
        return v

    def _resolve_ref(self, ref: str, sheet: str) -> tuple[str, str]:
        if "!" in ref:
            sh, ref = ref.rsplit("!", 1)
            sheet = sh[1:-1].replace("''", "'") if sh.startswith("'") else sh
        return sheet, ref

    def eval(self, node, sheet: str) -> Any:
        kind = node[0]
        if kind == "lit":
            return node[1]
        if kind == "ref":
            sh, ref = self._resolve_ref(node[1], sheet)
            if ":" in ref:
                a, b = ref.split(":")
                (r1, c1), (r2, c2) = split_addr(a), split_addr(b)
                r1, r2 = sorted((r1, r2))
                c1, c2 = sorted((c1, c2))
                if (r2 - r1 + 1) * (c2 - c1 + 1) > 200_000:
                    return REF
                return Range([[self.value(sh, f"{num_to_col(c)}{r}") for c in range(c1, c2 + 1)]
                              for r in range(r1, r2 + 1)])
            return self.value(sh, norm_addr(ref))
        if kind == "neg":
            v = to_num(self.eval(node[1], sheet))
            return v if isinstance(v, XLError) else -v
        if kind == "pct":
            v = to_num(self.eval(node[1], sheet))
            return v if isinstance(v, XLError) else v / 100
        if kind == "bin":
            return self._binop(node[1], self._scalar(self.eval(node[2], sheet)),
                               self._scalar(self.eval(node[3], sheet)))
        if kind == "call":
            return self._call(node[1], node[2], sheet)
        raise SyntaxError(kind)

    @staticmethod
    def _scalar(v: Any) -> Any:
        if isinstance(v, Range):
            return v[0][0] if v and v[0] else None
        return v

    def _binop(self, op: str, a: Any, b: Any) -> Any:
        if op == "&":
            return _first_err(a, b) or to_str(a) + to_str(b)
        if op in ("=", "<>", "<", ">", "<=", ">="):
            e = _first_err(a, b)
            if e:
                return e
            if isinstance(a, str) or isinstance(b, str):
                x, y = to_str(a).lower(), to_str(b).lower()
            else:
                x, y = to_num(a), to_num(b)
            return {"=": x == y, "<>": x != y, "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]
        x, y = to_num(a), to_num(b)
        e = _first_err(x, y)
        if e:
            return e
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if op == "/":
            return DIV0 if y == 0 else x / y
        if op == "^":
            try:
                return x ** y
            except (OverflowError, ZeroDivisionError):
                return NUM
        return VALUE

    def _call(self, name: str, args: list, sheet: str) -> Any:
        if name == "IF":
            cond = to_bool(self._scalar(self.eval(args[0], sheet)))
            if isinstance(cond, XLError):
                return cond
            if cond:
                return self.eval(args[1], sheet) if len(args) > 1 else True
            return self.eval(args[2], sheet) if len(args) > 2 else False
        if name in ("IFERROR", "IFNA"):
            v = self.eval(args[0], sheet)
            if isinstance(v, XLError) and (name == "IFERROR" or v == NA):
                return self.eval(args[1], sheet)
            return v
        vals = [self.eval(a, sheet) for a in args]
        if name == "TV":
            return self._tv(vals)
        fn = FUNCTIONS.get(name)
        if fn is None:
            return NAME
        try:
            return fn(*vals)
        except TypeError:
            return VALUE

    def _tv(self, vals: list[Any]) -> Any:
        if not vals:
            return VALUE
        sym = to_str(self._scalar(vals[0]))
        field = to_str(self._scalar(vals[1])) if len(vals) > 1 else "last"
        self.tv_symbols.add(sym)
        if self.quote is None:
            return NA
        v = self.quote(sym, field)
        return NA if v is None else v


def display(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.10g}"
    return to_str(v)
