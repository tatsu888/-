from app import formula as F


def ev(cells, quote=None):
    return F.Evaluator({"S": {k: ({"f": v, "v": None} if isinstance(v, str) and v.startswith("=") else {"v": v})
                              for k, v in cells.items()}}, quote)


def test_arithmetic_precedence():
    e = ev({"A1": 2, "A2": 3, "B1": "=A1+A2*2^2", "B2": "=-A1^2", "B3": "=50%*A2", "B4": '="x"&A1'})
    assert e.value("S", "B1") == 14
    assert e.value("S", "B2") == 4  # Excel semantics: unary minus binds tighter than ^ (=-2^2 is 4)
    assert e.value("S", "B3") == 1.5
    assert e.value("S", "B4") == "x2"


def test_functions_and_ranges():
    e = ev({"A1": 1, "A2": 2, "A3": 3, "A4": "txt", "B1": "=SUM(A1:A4)", "B2": "=AVERAGE(A1:A3)",
            "B3": "=IF(A1>0,\"pos\",\"neg\")", "B4": "=IFERROR(1/0,99)", "B5": "=ROUND(2.345,2)",
            "B6": "=SUMIF(A1:A3,\">1\")", "B7": "=COUNTA(A1:A4)", "B8": "=VLOOKUP(2,A1:A3,1,FALSE)",
            "B9": "=MAX(A1:A3)-MIN(A1:A3)"})
    assert e.value("S", "B1") == 6
    assert e.value("S", "B2") == 2
    assert e.value("S", "B3") == "pos"
    assert e.value("S", "B4") == 99
    assert e.value("S", "B5") == 2.35
    assert e.value("S", "B6") == 5
    assert e.value("S", "B7") == 4
    assert e.value("S", "B8") == 2
    assert e.value("S", "B9") == 2


def test_errors_cycles_unknown_function_fallback():
    e = F.Evaluator({"S": {"A1": {"f": "=A2"}, "A2": {"f": "=A1"}, "A3": {"f": "=1/0"},
                           "A4": {"f": "=XLOOKUP(1,A1:A2,A1:A2)", "v": 42}, "A5": {"f": "=A4*2"}}})
    assert e.value("S", "A1") == F.CIRC
    assert e.value("S", "A3") == F.DIV0
    assert e.value("S", "A4") == 42 and ("S", "A4") in e.stale  # Excel's cached value kept
    assert e.value("S", "A5") == 84


def test_cross_sheet_and_tv_function():
    e = F.Evaluator({"In": {"A1": {"v": 10}}, "Out": {"A1": {"f": "='In'!A1*TV(\"NASDAQ:AAPL\",\"last\")"}}},
                    quote=lambda s, f: 2.0 if (s, f) == ("NASDAQ:AAPL", "last") else None)
    assert e.value("Out", "A1") == 20
    assert e.tv_symbols == {"NASDAQ:AAPL"}
