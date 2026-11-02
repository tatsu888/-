"""ECON catalog — what a macro investor watches (~400 series), as data.

Each entry:
    id        stable id "<country>.<name>"
    name      Japanese label
    country   US JP EA DE FR IT ES NL UK CN KR TW IN CA AU BR MX CH ID VN GLOBAL
    category  景気・生産 / 消費・所得 / 住宅 / 企業・投資 / 雇用 / 物価 / 貿易・対外 / 金融・流動性 / 金利 /
              信用・金融環境 / マインド / 財政 / 為替 / 商品 / 株式
    axis      growth / labor / inflation / liquidity / rates / fx / equity / fiscal / external
    source    fred | estat | ecb | eurostat | wb | dbnomics | market | derived
    code      source-specific (FRED id, e-Stat search recipe, ECB "FLOW/KEY", Eurostat "dataset?filters",
              World Bank "COUNTRY/INDICATOR", DBnomics "PROVIDER/DATASET/SERIES", TradingView symbol, formula)
    freq      D W M Q A
    tf        the signal used for z-scores and composites: yoy (change vs a year ago, %) | lvl (as published) |
              d1 (change from the previous period) | d12 (change vs a year ago, in units — rates)
    good      +1 / -1: direction of the signal that means MORE of the axis (stronger growth, tighter labour market,
              more inflation, more liquidity). 0 = shown but not used in composites.
    key       headline indicator (release notifications, dashboard)

Codes were written from the providers' published identifiers but could NOT be fetched from the development
environment (outbound network blocked). The SOURCES tab shows, per series, whether the first fetch on the user's
PC worked; a wrong or discontinued code shows up there and can be fixed or replaced from the screen.
"""
from __future__ import annotations

from typing import Any

COUNTRIES = {"GLOBAL": "世界", "US": "米国", "JP": "日本", "EA": "ユーロ圏", "DE": "ドイツ", "FR": "フランス",
             "IT": "イタリア", "ES": "スペイン", "NL": "オランダ", "UK": "英国", "CN": "中国", "KR": "韓国", "TW": "台湾",
             "IN": "インド", "CA": "カナダ", "AU": "豪州", "BR": "ブラジル", "MX": "メキシコ", "CH": "スイス",
             "ID": "インドネシア", "VN": "ベトナム"}
CATEGORIES = ["景気・生産", "消費・所得", "住宅", "企業・投資", "雇用", "物価", "貿易・対外", "金融・流動性", "金利",
              "信用・金融環境", "マインド", "財政", "為替", "商品", "株式"]
AXES = {"growth": "成長", "labor": "雇用", "inflation": "インフレ", "liquidity": "流動性", "rates": "金利", "fx": "為替",
        "equity": "株式", "fiscal": "財政", "external": "対外"}
# composites: which axes feed which composite
COMPOSITES = {"growth": ("growth", "labor"), "inflation": ("inflation",), "liquidity": ("liquidity",)}
WORLD = ("US", "EA", "JP", "CN")          # the WORLD composite = mean of these regions
LAG_M = {"D": 0, "W": 0, "M": 1, "Q": 2, "A": 6}   # months until a reference period is known (regime analysis)

CATALOG: list[dict[str, Any]] = []


def E(id: str, name: str, country: str, category: str, axis: str, source: str, code: Any, freq: str = "M",
      tf: str = "yoy", good: int = 1, unit: str = "", key: bool = False, note: str | None = None) -> None:
    CATALOG.append({"id": id, "name": name, "country": country, "category": category, "axis": axis, "source": source,
                    "code": code, "freq": freq, "tf": tf, "good": good, "unit": unit, "key": key, "note": note,
                    "lag_m": LAG_M[freq]})


def F(id: str, name: str, country: str, category: str, axis: str, code: str, freq: str = "M", tf: str = "yoy",
      good: int = 1, unit: str = "", key: bool = False, note: str | None = None) -> None:
    E(id, name, country, category, axis, "fred", code, freq, tf, good, unit, key, note)


# ======================================================================================================
# 米国（FRED: BEA / BLS / Census / FRB / 地区連銀 / ICE BofA / Treasury）
# ======================================================================================================
G, C, H, B, L, P, T, M, R, CR, S, FS = ("景気・生産", "消費・所得", "住宅", "企業・投資", "雇用", "物価", "貿易・対外",
                                        "金融・流動性", "金利", "信用・金融環境", "マインド", "財政")
F("US.GDP", "実質 GDP", "US", G, "growth", "GDPC1", "Q", key=True)
F("US.GDP_SAAR", "実質 GDP（前期比年率）", "US", G, "growth", "A191RL1Q225SBEA", "Q", "lvl", unit="%", key=True)
F("US.GDPNOW", "GDPNow（アトランタ連銀の推計）", "US", G, "growth", "GDPNOW", "Q", "lvl", unit="%")
F("US.IP", "鉱工業生産", "US", G, "growth", "INDPRO", key=True)
F("US.IP_MFG", "製造業生産", "US", G, "growth", "IPMAN")
F("US.CAPU", "設備稼働率", "US", G, "growth", "TCU", tf="lvl", unit="%")
F("US.CFNAI", "シカゴ連銀全米活動指数", "US", G, "growth", "CFNAI", tf="lvl")
F("US.WEI", "週次経済指数（NY 連銀）", "US", G, "growth", "WEI", "W", "lvl")
F("US.RECPROB", "景気後退確率（平滑化）", "US", G, "growth", "RECPROUSM156N", tf="lvl", good=-1, unit="%")
F("US.CORP_PROFITS", "企業利益（税引後）", "US", B, "growth", "CP", "Q")
F("US.NONRES_INV", "民間非住宅投資", "US", B, "growth", "PNFI", "Q")
F("US.RES_INV", "住宅投資", "US", H, "growth", "PRFI", "Q")
F("US.GOV_SPEND", "政府支出", "US", FS, "fiscal", "GCE", "Q", good=0)
F("US.RETAIL", "小売売上高", "US", C, "growth", "RSAFS", key=True)
F("US.RETAIL_XFS", "小売売上高（飲食除く）", "US", C, "growth", "RSXFS")
F("US.RETAIL_REAL", "実質小売売上高", "US", C, "growth", "RRSFS")
F("US.PCE_REAL", "実質個人消費支出", "US", C, "growth", "PCEC96")
F("US.DPI_REAL", "実質可処分所得", "US", C, "growth", "DSPIC96")
F("US.SAVING", "貯蓄率", "US", C, "growth", "PSAVERT", tf="lvl", good=0, unit="%")
F("US.VEHICLES", "自動車販売台数", "US", C, "growth", "TOTALSA")
F("US.DEBT_SERVICE", "家計の債務返済比率", "US", C, "growth", "TDSP", "Q", "lvl", good=-1, unit="%")
F("US.CC_DELINQ", "クレジットカード延滞率", "US", CR, "growth", "DRCCLACBS", "Q", "lvl", good=-1, unit="%")
F("US.DURABLES", "耐久財受注", "US", B, "growth", "DGORDER")
F("US.DURABLES_XT", "耐久財受注（輸送用機器除く）", "US", B, "growth", "ADXTNO")
F("US.CORE_CAPEX", "コア資本財受注（国防・航空機除く）", "US", B, "growth", "NEWORDER", key=True)
F("US.FACTORY", "製造業新規受注", "US", B, "growth", "AMTMNO")
F("US.BIZINV", "企業在庫", "US", B, "growth", "BUSINV", good=0)
F("US.INV_SALES", "在庫売上比率", "US", B, "growth", "ISRATIO", tf="lvl", good=-1)
F("US.CONSTR", "建設支出", "US", H, "growth", "TTLCONS")
F("US.HOUST", "住宅着工", "US", H, "growth", "HOUST", key=True)
F("US.PERMIT", "建築許可", "US", H, "growth", "PERMIT")
F("US.NEWHOME", "新築住宅販売", "US", H, "growth", "HSN1F")
F("US.EXHOME", "中古住宅販売", "US", H, "growth", "EXHOSLUSM495S")
F("US.CASESHILLER", "ケース・シラー住宅価格", "US", H, "growth", "CSUSHPINSA")
F("US.FHFA", "FHFA 住宅価格", "US", H, "growth", "USSTHPI", "Q")
F("US.MORT30", "30 年住宅ローン金利", "US", R, "rates", "MORTGAGE30US", "W", "lvl", good=0, unit="%")
F("US.EMPIRE", "NY 連銀製造業景況指数", "US", S, "growth", "GACDISA066MSFRBNY", tf="lvl", key=True)
F("US.PHILLY", "フィラデルフィア連銀製造業景況指数", "US", S, "growth", "GACDFSA066MSFRBPHI", tf="lvl", key=True)
F("US.UMICH", "ミシガン大消費者信頼感", "US", S, "growth", "UMCSENT", tf="lvl", key=True)
F("US.EPU", "経済政策不確実性指数", "US", S, "growth", "USEPUINDXD", "D", "lvl", good=-1)
# labour
F("US.NFP", "非農業部門雇用者数（前月差）", "US", L, "labor", "PAYEMS", tf="d1", unit="千人", key=True)
F("US.PRIVATE_NFP", "民間雇用者数（前月差）", "US", L, "labor", "USPRIV", tf="d1", unit="千人")
F("US.GOV_NFP", "政府雇用者数（前月差）", "US", L, "labor", "USGOVT", tf="d1", good=0, unit="千人")
F("US.UNRATE", "失業率", "US", L, "labor", "UNRATE", tf="lvl", good=-1, unit="%", key=True)
F("US.U6", "U6 失業率", "US", L, "labor", "U6RATE", tf="lvl", good=-1, unit="%")
F("US.PARTIC", "労働参加率", "US", L, "labor", "CIVPART", tf="lvl", unit="%")
F("US.EPOP_PRIME", "プライムエイジ就業率（25〜54 歳）", "US", L, "labor", "LNS12300060", tf="lvl", unit="%")
F("US.SAHM", "サーム・ルール（リアルタイム）", "US", L, "labor", "SAHMREALTIME", tf="lvl", good=-1)
F("US.CLAIMS", "新規失業保険申請件数", "US", L, "labor", "ICSA", "W", "lvl", good=-1, key=True)
F("US.CLAIMS4W", "新規失業保険申請（4 週平均）", "US", L, "labor", "IC4WSA", "W", "lvl", good=-1)
F("US.CCLAIMS", "失業保険継続受給者数", "US", L, "labor", "CCSA", "W", "lvl", good=-1)
F("US.JOLTS", "求人件数（JOLTS）", "US", L, "labor", "JTSJOL", tf="lvl")
F("US.QUITS", "自発的離職率", "US", L, "labor", "JTSQUR", tf="lvl", unit="%")
F("US.HIRES", "採用率", "US", L, "labor", "JTSHIR", tf="lvl", unit="%")
F("US.HOURS", "週平均労働時間", "US", L, "labor", "AWHAETP", tf="lvl")
F("US.TEMP", "人材派遣の雇用", "US", L, "labor", "TEMPHELPS")
F("US.MFG_EMP", "製造業雇用", "US", L, "labor", "MANEMP")
F("US.PRODUCTIVITY", "労働生産性", "US", G, "growth", "OPHNFB", "Q")
# inflation
F("US.CPI", "CPI", "US", P, "inflation", "CPIAUCSL", key=True)
F("US.CORECPI", "コア CPI", "US", P, "inflation", "CPILFESL", key=True)
F("US.CPI_SERV", "CPI サービス", "US", P, "inflation", "CUSR0000SAS")
F("US.CPI_SERV_XE", "CPI エネルギー除くサービス", "US", P, "inflation", "CUSR0000SASLE")
F("US.CPI_CORE_GOODS", "CPI コア財", "US", P, "inflation", "CUSR0000SACL1E")
F("US.CPI_SHELTER", "CPI 住居費", "US", P, "inflation", "CUSR0000SAH1")
F("US.CPI_RENT", "CPI 家賃", "US", P, "inflation", "CUSR0000SEHA")
F("US.CPI_OER", "CPI 帰属家賃", "US", P, "inflation", "CUSR0000SEHC")
F("US.CPI_ENERGY", "CPI エネルギー", "US", P, "inflation", "CPIENGSL")
F("US.CPI_FOOD", "CPI 食品", "US", P, "inflation", "CPIUFDSL")
F("US.PCE", "PCE デフレーター", "US", P, "inflation", "PCEPI")
F("US.COREPCE", "コア PCE デフレーター", "US", P, "inflation", "PCEPILFE", key=True)
F("US.STICKY_CPI", "粘着的コア CPI（前年比）", "US", P, "inflation", "CORESTICKM159SFRBATL", tf="lvl", unit="%")
F("US.MEDIAN_CPI", "中央値 CPI（前月比年率）", "US", P, "inflation", "MEDCPIM158SFRBCLE", tf="lvl", unit="%")
F("US.TRIM_PCE", "トリム平均 PCE（12 か月）", "US", P, "inflation", "PCETRIM12M159SFRBDAL", tf="lvl", unit="%")
F("US.PPI", "PPI 最終需要", "US", P, "inflation", "PPIFIS")
F("US.PPI_ALL", "PPI 全商品", "US", P, "inflation", "PPIACO")
F("US.IMPORT_PX", "輸入物価", "US", P, "inflation", "IR")
F("US.AHE", "平均時給", "US", L, "inflation", "CES0500000003", key=True)
F("US.AHE_PROD", "平均時給（生産・非管理職）", "US", L, "inflation", "AHETPI")
F("US.ECI", "雇用コスト指数", "US", L, "inflation", "ECIALLCIV", "Q")
F("US.ECI_WAGES", "雇用コスト指数（賃金）", "US", L, "inflation", "ECIWAG", "Q")
F("US.ULC", "単位労働コスト", "US", L, "inflation", "ULCNFB", "Q")
F("US.BEI5", "5 年ブレークイーブン・インフレ", "US", P, "inflation", "T5YIE", "D", "lvl", unit="%")
F("US.BEI10", "10 年ブレークイーブン・インフレ", "US", P, "inflation", "T10YIE", "D", "lvl", unit="%")
F("US.5Y5Y", "5 年先 5 年インフレ期待", "US", P, "inflation", "T5YIFR", "D", "lvl", unit="%")
F("US.MICH_INF", "ミシガン大 1 年先期待インフレ", "US", P, "inflation", "MICH", tf="lvl", unit="%")
F("US.CLEV_INF", "クリーブランド連銀 1 年期待インフレ", "US", P, "inflation", "EXPINF1YR", tf="lvl", unit="%")
F("US.GASOLINE", "ガソリン小売価格", "US", P, "inflation", "GASREGW", "W")
# money, credit, Fed balance sheet, financial conditions
F("US.M2", "マネーサプライ M2", "US", M, "liquidity", "M2SL", key=True)
F("US.FED_ASSETS", "FRB 総資産", "US", M, "liquidity", "WALCL", "W", unit="百万ドル")
F("US.RESERVES", "準備預金残高", "US", M, "liquidity", "WRESBAL", "W", unit="10 億ドル")
F("US.RRP", "翌日物リバースレポ残高", "US", M, "liquidity", "RRPONTSYD", "D", "lvl", good=-1, unit="10 億ドル")
F("US.TGA", "財務省一般勘定（TGA）", "US", M, "liquidity", "WTREGEN", "W", "lvl", good=-1, unit="10 億ドル")
F("US.BANK_LOANS", "銀行貸出", "US", M, "liquidity", "TOTLL", "W")
F("US.CI_LOANS", "商工業貸出", "US", M, "liquidity", "BUSLOANS")
F("US.CONS_CREDIT", "消費者信用残高", "US", M, "liquidity", "TOTALSL")
F("US.DEPOSITS", "銀行預金", "US", M, "liquidity", "DPSACBW027SBOG", "W")
F("US.SLOOS", "融資基準（SLOOS、引き締め超）", "US", CR, "liquidity", "DRTSCILM", "Q", "lvl", good=-1, unit="%")
F("US.NFCI", "金融環境指数（シカゴ連銀）", "US", CR, "liquidity", "NFCI", "W", "lvl", good=-1, key=True)
F("US.ANFCI", "調整後金融環境指数", "US", CR, "liquidity", "ANFCI", "W", "lvl", good=-1)
F("US.STLFSI", "金融ストレス指数（セントルイス連銀）", "US", CR, "liquidity", "STLFSI4", "W", "lvl", good=-1)
F("US.HY_OAS", "ハイイールド・スプレッド", "US", CR, "liquidity", "BAMLH0A0HYM2", "D", "lvl", good=-1, unit="%")
F("US.IG_OAS", "投資適格スプレッド", "US", CR, "liquidity", "BAMLC0A0CM", "D", "lvl", good=-1, unit="%")
F("US.CCC_OAS", "CCC 以下スプレッド", "US", CR, "liquidity", "BAMLH0A3HYC", "D", "lvl", good=-1, unit="%")
F("US.DOLLAR", "ドル指数（広義、FRB）", "US", "為替", "liquidity", "DTWEXBGS", "D", good=-1)
F("US.VIX", "VIX", "US", CR, "liquidity", "VIXCLS", "D", "lvl", good=-1)
# rates
for _id, _n, _c in (("US.FFR", "FF 金利（実効）", "DFF"), ("US.SOFR", "SOFR", "SOFR"), ("US.UST3M", "米国債 3 か月", "DGS3MO"),
                    ("US.UST2", "米国債 2 年", "DGS2"), ("US.UST5", "米国債 5 年", "DGS5"), ("US.UST10", "米国債 10 年", "DGS10"),
                    ("US.UST30", "米国債 30 年", "DGS30"), ("US.REAL10", "米 10 年実質金利（TIPS）", "DFII10"),
                    ("US.2S10S", "2 年 10 年スプレッド", "T10Y2Y"), ("US.3M10Y", "3 か月 10 年スプレッド", "T10Y3M"),
                    ("US.TERM_PREMIUM", "10 年タームプレミアム（Kim-Wright）", "THREEFYTP10")):
    F(_id, _n, "US", R, "rates", _c, "D", "lvl", good=0, unit="%", key=_id in ("US.UST2", "US.UST10"))
# external, fiscal, markets
F("US.TRADE_BAL", "貿易収支（財・サービス）", "US", T, "external", "BOPGSTB", tf="lvl", good=0, unit="百万ドル")
F("US.EXPORTS", "輸出（財・サービス）", "US", T, "growth", "EXPGS", "Q")
F("US.IMPORTS", "輸入（財・サービス）", "US", T, "growth", "IMPGS", "Q")
F("US.CA", "経常収支", "US", T, "external", "IEABC", "Q", "lvl", good=0, unit="百万ドル")
F("US.DEFICIT", "月次財政収支", "US", FS, "fiscal", "MTSDS133FMS", tf="lvl", good=0, unit="百万ドル")
F("US.DEBT_GDP", "連邦債務 GDP 比", "US", FS, "fiscal", "GFDEGDQ188S", "Q", "lvl", good=0, unit="%")
F("US.DEBT", "連邦債務残高", "US", FS, "fiscal", "GFDEBTN", "Q", good=0)
F("US.SP500", "S&P 500（FRED）", "US", "株式", "equity", "SP500", "D", good=0)
F("US.NASDAQ", "NASDAQ 総合（FRED）", "US", "株式", "equity", "NASDAQCOM", "D", good=0)

# ======================================================================================================
# 日本（e-Stat：総務省・厚労省・財務省・経産省・国交省・内閣府 — 政府統計の総合窓口 API。ESTAT_APP_ID が必要）
# code = 検索の手順: stat（統計名）, stats_code（政府統計コード、分かる場合）, search（検索語）,
#        select（系列を決める語。各分類で名前に含まれるものを選び、残りの分類は「総数・全国・計」を選ぶ）, cycle
# ======================================================================================================
def J(id: str, name: str, category: str, axis: str, stat: str, search: str, select: list[str], freq: str = "M",
      tf: str = "yoy", good: int = 1, unit: str = "", key: bool = False, stats_code: str | None = None) -> None:
    cycle = {"M": "月次", "Q": "四半期", "A": "年次"}.get(freq)
    E(id, name, "JP", category, axis, "estat", {"stat": stat, "stats_code": stats_code, "search": search, "select": select,
                                                 "cycle": cycle}, freq, tf, good, unit, key)


J("JP.UNEMP", "完全失業率（季節調整値）", L, "labor", "労働力調査", "完全失業率 季節調整", ["完全失業率", "季節調整"],
  tf="lvl", good=-1, unit="%", key=True, stats_code="00200531")
J("JP.EMPLOYED", "就業者数", L, "labor", "労働力調査", "就業者 季節調整", ["就業者", "季節調整"], stats_code="00200531")
J("JP.LABOR_PARTIC", "労働力人口比率", L, "labor", "労働力調査", "労働力人口比率", ["労働力人口比率"], tf="lvl", unit="%",
  stats_code="00200531")
J("JP.JOBS_RATIO", "有効求人倍率（季節調整値）", L, "labor", "一般職業紹介状況", "有効求人倍率 季節調整", ["有効求人倍率", "季節調整"],
  tf="lvl", unit="倍", key=True, stats_code="00450222")
J("JP.NEW_JOBS_RATIO", "新規求人倍率（季節調整値）", L, "labor", "一般職業紹介状況", "新規求人倍率 季節調整",
  ["新規求人倍率", "季節調整"], tf="lvl", unit="倍", stats_code="00450222")
J("JP.WAGES", "現金給与総額（5 人以上）", L, "inflation", "毎月勤労統計調査", "現金給与総額 指数", ["現金給与総額", "調査産業計"],
  key=True, stats_code="00450071")
J("JP.REAL_WAGES", "実質賃金指数（現金給与総額）", L, "growth", "毎月勤労統計調査", "実質賃金指数", ["実質賃金", "現金給与総額"],
  key=True, stats_code="00450071")
J("JP.SCHEDULED_PAY", "所定内給与", L, "inflation", "毎月勤労統計調査", "所定内給与 指数", ["所定内給与", "調査産業計"],
  stats_code="00450071")
J("JP.HOURS", "総実労働時間", L, "labor", "毎月勤労統計調査", "総実労働時間 指数", ["総実労働時間", "調査産業計"],
  stats_code="00450071")
J("JP.CPI", "CPI 総合（全国）", P, "inflation", "消費者物価指数", "全国 総合 指数", ["総合", "全国"], key=True, stats_code="00200573")
J("JP.CORECPI", "CPI 生鮮食品を除く総合（コア）", P, "inflation", "消費者物価指数", "生鮮食品を除く総合", ["生鮮食品を除く総合", "全国"],
  key=True, stats_code="00200573")
J("JP.CORECORE", "CPI 生鮮食品及びエネルギーを除く総合", P, "inflation", "消費者物価指数", "生鮮食品及びエネルギーを除く総合",
  ["生鮮食品及びエネルギーを除く総合", "全国"], key=True, stats_code="00200573")
J("JP.CPI_GOODS", "CPI 財", P, "inflation", "消費者物価指数", "財 サービス 全国", ["財", "全国"], stats_code="00200573")
J("JP.CPI_SERV", "CPI サービス", P, "inflation", "消費者物価指数", "財 サービス 全国", ["サービス", "全国"], stats_code="00200573")
J("JP.TOKYO_CPI", "東京都区部 CPI（生鮮食品を除く総合）", P, "inflation", "消費者物価指数", "東京都区部 生鮮食品を除く総合",
  ["生鮮食品を除く総合", "東京都区部"], key=True, stats_code="00200573")
J("JP.HH_SPENDING", "消費支出（二人以上の世帯）", C, "growth", "家計調査", "消費支出 二人以上の世帯", ["消費支出", "二人以上の世帯"],
  key=True, stats_code="00200561")
J("JP.RETAIL", "小売業販売額", C, "growth", "商業動態統計調査", "小売業 販売額", ["小売業"], key=True, stats_code="00550030")
J("JP.WHOLESALE", "卸売業販売額", C, "growth", "商業動態統計調査", "卸売業 販売額", ["卸売業"], stats_code="00550030")
J("JP.HOUSING_STARTS", "新設住宅着工戸数", H, "growth", "建築着工統計調査", "新設住宅 着工戸数", ["新設住宅", "戸数"],
  stats_code="00600120")
J("JP.EXPORTS", "輸出額（全世界）", T, "growth", "貿易統計", "輸出 総額 全世界", ["輸出", "総額"], key=True, stats_code="00350300")
J("JP.IMPORTS", "輸入額（全世界）", T, "growth", "貿易統計", "輸入 総額 全世界", ["輸入", "総額"], stats_code="00350300")
J("JP.TRADE_BAL", "貿易収支（差引額）", T, "external", "貿易統計", "差引 総額", ["差引"], tf="lvl", good=0, stats_code="00350300")
J("JP.EXPORTS_US", "輸出額（対アメリカ）", T, "growth", "貿易統計", "輸出 アメリカ合衆国", ["輸出", "アメリカ合衆国"], stats_code="00350300")
J("JP.EXPORTS_CN", "輸出額（対中国）", T, "growth", "貿易統計", "輸出 中華人民共和国", ["輸出", "中華人民共和国"], stats_code="00350300")
J("JP.EXPORTS_ASIA", "輸出額（対アジア）", T, "growth", "貿易統計", "輸出 アジア", ["輸出", "アジア"], stats_code="00350300")
J("JP.EXPORTS_EU", "輸出額（対 EU）", T, "growth", "貿易統計", "輸出 ＥＵ", ["輸出", "ＥＵ"], stats_code="00350300")
J("JP.PROFITS", "経常利益（全産業）", B, "growth", "法人企業統計調査", "経常利益 全産業 季節調整", ["経常利益", "全産業"], "Q",
  key=True, stats_code="00350600")
J("JP.CAPEX", "設備投資（全産業）", B, "growth", "法人企業統計調査", "設備投資 全産業 季節調整", ["設備投資", "全産業"], "Q",
  key=True, stats_code="00350600")
J("JP.SALES", "売上高（全産業）", B, "growth", "法人企業統計調査", "売上高 全産業 季節調整", ["売上高", "全産業"], "Q", stats_code="00350600")
J("JP.GDP", "実質 GDP（季節調整系列）", G, "growth", "国民経済計算", "実質 季節調整系列 国内総生産", ["国内総生産", "実質"], "Q",
  key=True, stats_code="00100409")
J("JP.IP", "鉱工業生産指数（季節調整）", G, "growth", "鉱工業指数", "鉱工業 生産 季節調整済指数", ["生産", "鉱工業"], key=True)
J("JP.IP_SHIP", "鉱工業出荷指数", G, "growth", "鉱工業指数", "鉱工業 出荷 季節調整済指数", ["出荷", "鉱工業"])
J("JP.IP_INV", "鉱工業在庫指数", G, "growth", "鉱工業指数", "鉱工業 在庫 季節調整済指数", ["在庫", "鉱工業"], good=0)
J("JP.SERVICES_ACT", "第 3 次産業活動指数", G, "growth", "第3次産業活動指数", "第3次産業活動指数 季節調整", ["第3次産業"])
J("JP.MACHINERY", "機械受注（船舶・電力を除く民需）", B, "growth", "機械受注統計調査", "船舶・電力を除く民需", ["船舶・電力を除く民需"],
  key=True)
J("JP.CI_COINC", "景気動向指数 CI 一致指数", G, "growth", "景気動向指数", "CI 一致指数", ["一致指数"], tf="lvl", key=True)
J("JP.CI_LEAD", "景気動向指数 CI 先行指数", G, "growth", "景気動向指数", "CI 先行指数", ["先行指数"], tf="lvl", key=True)
J("JP.CONS_CONF", "消費者態度指数", S, "growth", "消費動向調査", "消費者態度指数 季節調整", ["消費者態度指数"], tf="lvl", key=True)
J("JP.WATCHERS", "景気ウォッチャー 現状判断 DI", S, "growth", "景気ウォッチャー調査", "現状判断DI 季節調整", ["現状判断"], tf="lvl",
  key=True)
J("JP.WATCHERS_OUT", "景気ウォッチャー 先行き判断 DI", S, "growth", "景気ウォッチャー調査", "先行き判断DI 季節調整", ["先行き判断"],
  tf="lvl")
J("JP.CGPI", "国内企業物価指数（総平均）", P, "inflation", "企業物価指数", "国内企業物価指数 総平均", ["国内企業物価指数", "総平均"],
  key=True)
J("JP.SPPI", "企業向けサービス価格指数", P, "inflation", "企業向けサービス価格指数", "企業向けサービス価格指数 総平均", ["総平均"])
J("JP.TANKAN_LM", "短観 業況判断 DI（大企業・製造業）", S, "growth", "全国企業短期経済観測調査", "業況判断 大企業 製造業",
  ["業況判断", "大企業", "製造業"], "Q", "lvl", key=True)
J("JP.TANKAN_LN", "短観 業況判断 DI（大企業・非製造業）", S, "growth", "全国企業短期経済観測調査", "業況判断 大企業 非製造業",
  ["業況判断", "大企業", "非製造業"], "Q", "lvl")
J("JP.MONEY_M2", "マネーストック M2（平均残高）", M, "liquidity", "マネーストック", "M2 平均残高", ["M2"], key=True)
J("JP.BANK_LENDING", "銀行貸出（銀行計）", M, "liquidity", "貸出・預金動向", "貸出 銀行計 平均残高", ["貸出", "銀行計"])
J("JP.CURRENT_ACCOUNT", "経常収支", T, "external", "国際収支統計", "経常収支", ["経常収支"], tf="lvl", good=0)
J("JP.POPULATION", "総人口（人口推計）", G, "growth", "人口推計", "総人口 月次", ["総人口"], good=0, stats_code="00200524")
# 日本（FRED: 日銀・BIS・OECD の転載。e-Stat が使えないときの代わりにもなる）
F("JP.BOJ_ASSETS", "日銀総資産", "JP", M, "liquidity", "JPNASSETS", key=True)
F("JP.USDJPY", "ドル円（FRB H.10）", "JP", "為替", "fx", "DEXJPUS", "D", "lvl", good=0)
F("JP.REER", "実質実効為替レート（BIS）", "JP", "為替", "fx", "RBJPBIS", tf="lvl", good=0)
F("JP.HOUSE_PX", "実質住宅価格（BIS）", "JP", H, "growth", "QJPR628BIS", "Q")
F("JP.JGB10_M", "10 年国債利回り（月次、OECD）", "JP", R, "rates", "IRLTLT01JPM156N", tf="lvl", good=0, unit="%")
F("JP.CALL_RATE", "無担保コール翌日物（月次、OECD）", "JP", R, "rates", "IRSTCI01JPM156N", tf="lvl", good=0, unit="%")
F("JP.UNEMP_OECD", "失業率（OECD 調和）", "JP", L, "labor", "LRHUTTTTJPM156S", tf="lvl", good=-1, unit="%")
F("JP.CPI_OECD", "CPI 前年比（OECD）", "JP", P, "inflation", "CPALTT01JPM659N", tf="lvl", unit="%")
F("JP.EXPORTS_USD", "輸出（ドル建て、季調、OECD）", "JP", T, "growth", "XTEXVA01JPM667S")
F("JP.GDP_FRED", "実質 GDP（FRED）", "JP", G, "growth", "JPNRGDPEXP", "Q")
F("JP.CLI", "OECD 景気先行指数", "JP", G, "growth", "JPNLOLITONOSTSAM", tf="lvl")
F("JP.BCI", "企業景況感（OECD）", "JP", S, "growth", "BSCICP03JPM665S", tf="lvl")
F("JP.CCI", "消費者信頼感（OECD）", "JP", S, "growth", "CSCICP03JPM665S", tf="lvl")
F("JP.EPU", "経済政策不確実性指数", "JP", S, "growth", "JPNEPUINDXM", tf="lvl", good=-1)

# ======================================================================================================
# ユーロ圏（ECB Data Portal / Eurostat）と欧州各国
# ======================================================================================================
def ECB(id: str, name: str, category: str, axis: str, key_: str, freq: str = "M", tf: str = "lvl", good: int = 1,
        unit: str = "%", key: bool = False, country: str = "EA") -> None:
    E(id, name, country, category, axis, "ecb", key_, freq, tf, good, unit, key)


ECB("EA.HICP", "HICP 総合（前年比）", P, "inflation", "ICP/M.U2.N.000000.4.ANR", key=True)
ECB("EA.CORE_HICP", "HICP コア（エネルギー・食品・酒・たばこ除く）", P, "inflation", "ICP/M.U2.N.XEF000.4.ANR", key=True)
ECB("EA.HICP_SERV", "HICP サービス（前年比）", P, "inflation", "ICP/M.U2.N.SERV00.4.ANR")
ECB("EA.HICP_ENERGY", "HICP エネルギー（前年比）", P, "inflation", "ICP/M.U2.N.NRGY00.4.ANR")
ECB("EA.DFR", "ECB 預金ファシリティ金利", R, "rates", "FM/D.U2.EUR.4F.KR.DFR.LEV", "D", good=0, key=True)
ECB("EA.M3", "M3（前年比）", M, "liquidity", "BSI/M.U2.Y.V.M30.X.I.U2.2300.Z01.A", key=True)
ECB("EA.EURUSD", "ユーロ・ドル", "為替", "fx", "EXR/D.USD.EUR.SP00.A", "D", good=0, unit="")
ECB("EA.AAA2Y", "ユーロ圏 AAA 国債 2 年", R, "rates", "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y", "D", good=0)
ECB("EA.AAA10Y", "ユーロ圏 AAA 国債 10 年", R, "rates", "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y", "D", good=0)
ECB("EA.UNEMP_ECB", "失業率（ECB）", L, "labor", "LFSI/M.I9.S.UNEHRT.TOTAL0.15_74.T", good=-1)
ECB("EA.CISS", "システミック・ストレス指数（CISS）", CR, "liquidity", "CISS/D.U2.Z0Z.4F.EC.SS_CIN.IDX", "D", good=-1, unit="")


def EU(id: str, name: str, country: str, category: str, axis: str, dataset: str, filters: str, freq: str = "M",
       tf: str = "yoy", good: int = 1, unit: str = "", key: bool = False) -> None:
    E(id, name, country, category, axis, "eurostat", f"{dataset}?{filters}", freq, tf, good, unit, key)


_EU = {"EA": "EA20", "DE": "DE", "FR": "FR", "IT": "IT", "ES": "ES", "NL": "NL"}
_HICP_GEO = {"EA": "EA", "DE": "DE", "FR": "FR", "IT": "IT", "ES": "ES", "NL": "NL"}
for cc, geo in _EU.items():
    nm = COUNTRIES[cc]
    EU(f"{cc}.UNEMP", f"{nm} 失業率", cc, L, "labor", "une_rt_m", f"geo={geo}&s_adj=SA&age=TOTAL&sex=T&unit=PC_ACT", tf="lvl",
       good=-1, unit="%", key=cc == "EA")
    EU(f"{cc}.HICP_RATE", f"{nm} HICP 前年比（Eurostat）", cc, P, "inflation", "prc_hicp_manr",
       f"geo={_HICP_GEO[cc]}&coicop=CP00&unit=RCH_A", tf="lvl", unit="%")
    if cc != "NL":
        EU(f"{cc}.IP", f"{nm} 鉱工業生産", cc, G, "growth", "sts_inpr_m", f"geo={geo}&s_adj=SCA&nace_r2=B-D&unit=I21",
           key=cc in ("EA", "DE"))
        EU(f"{cc}.RETAIL", f"{nm} 小売売上（数量）", cc, C, "growth", "sts_trtu_m",
           f"geo={geo}&s_adj=SCA&nace_r2=G47&indic_bt=VOL_SLS&unit=I21")
        EU(f"{cc}.ESI", f"{nm} 景況感指数（ESI）", cc, S, "growth", "ei_bssi_m_r2", f"geo={geo}&indic=BS-ESI-I&s_adj=SA", tf="lvl",
           key=cc == "EA")
        EU(f"{cc}.GDP", f"{nm} 実質 GDP（前年比）", cc, G, "growth", "namq_10_gdp",
           f"geo={geo}&unit=CLV_PCH_SM&s_adj=SCA&na_item=B1GQ", "Q", "lvl", unit="%", key=cc in ("EA", "DE"))
EU("EA.HICP_CORE_ES", "ユーロ圏 HICP コア前年比（Eurostat）", "EA", P, "inflation", "prc_hicp_manr", "geo=EA&coicop=TOT_X_NRG_FOOD&unit=RCH_A",
   tf="lvl", unit="%")
EU("EA.IND_CONF", "ユーロ圏 製造業信頼感", "EA", S, "growth", "ei_bssi_m_r2", "geo=EA20&indic=BS-ICI-BAL&s_adj=SA", tf="lvl")
EU("EA.SERV_CONF", "ユーロ圏 サービス業信頼感", "EA", S, "growth", "ei_bssi_m_r2", "geo=EA20&indic=BS-SCI-BAL&s_adj=SA", tf="lvl")
EU("EA.CONS_CONF", "ユーロ圏 消費者信頼感", "EA", S, "growth", "ei_bssi_m_r2", "geo=EA20&indic=BS-CSMCI-BAL&s_adj=SA", tf="lvl",
   key=True)
EU("EA.EMP_EXP", "ユーロ圏 雇用見通し指数（EEI）", "EA", L, "labor", "ei_bssi_m_r2", "geo=EA20&indic=BS-EEI-I&s_adj=SA", tf="lvl")
F("EA.REER", "ユーロ 実質実効為替レート（BIS）", "EA", "為替", "fx", "RBXMBIS", tf="lvl", good=0)
F("EA.HOUSE_PX", "ユーロ圏 実質住宅価格（BIS）", "EA", H, "growth", "QXMR628BIS", "Q")
for cc, nm in (("DE", "独"), ("FR", "仏"), ("IT", "伊"), ("ES", "西")):
    F(f"{cc}.BOND10", f"{nm} 10 年国債利回り（月次、OECD）", cc, R, "rates", f"IRLTLT01{cc}M156N", tf="lvl", good=0, unit="%")
F("DE.CLI", "ドイツ OECD 景気先行指数", "DE", G, "growth", "DEULOLITONOSTSAM", tf="lvl")

# ======================================================================================================
# 英国・中国・アジア・その他（FRED: FRB H.10 為替、BIS 実効為替・住宅価格、OECD の転載）
# ======================================================================================================
_FX = {"UK": ("DEXUSUK", "ポンド・ドル"), "CN": ("DEXCHUS", "ドル・人民元"), "KR": ("DEXKOUS", "ドル・ウォン"),
       "TW": ("DEXTAUS", "ドル・台湾ドル"), "IN": ("DEXINUS", "ドル・ルピー"), "CA": ("DEXCAUS", "ドル・カナダドル"),
       "AU": ("DEXUSAL", "豪ドル・ドル"), "BR": ("DEXBZUS", "ドル・レアル"), "MX": ("DEXMXUS", "ドル・ペソ"),
       "CH": ("DEXSZUS", "ドル・スイスフラン")}
for cc, (code, nm) in _FX.items():
    F(f"{cc}.FX", f"{nm}（FRB H.10）", cc, "為替", "fx", code, "D", "lvl", good=0)
_ISO3 = {"UK": "GBR", "CN": "CHN", "KR": "KOR", "IN": "IND", "CA": "CAN", "AU": "AUS", "DE": "DEU", "US": "USA", "BR": "BRA",
         "MX": "MEX", "ID": "IDN"}
_BIS = {"UK": "GB", "CN": "CN", "KR": "KR", "IN": "IN", "CA": "CA", "AU": "AU", "BR": "BR", "MX": "MX", "US": "US"}
for cc, b in _BIS.items():
    nm = COUNTRIES[cc]
    F(f"{cc}.REER", f"{nm} 実質実効為替レート（BIS）", cc, "為替", "fx", f"RB{b}BIS", tf="lvl", good=0)
    if cc not in ("IN", "BR", "MX"):
        F(f"{cc}.HOUSE_PX", f"{nm} 実質住宅価格（BIS）", cc, H, "growth", f"Q{b}R628BIS", "Q")
for cc in ("UK", "CN", "KR", "IN", "CA", "BR", "MX"):
    nm = COUNTRIES[cc]
    F(f"{cc}.CPI", f"{nm} CPI 前年比（OECD）", cc, P, "inflation", f"CPALTT01{_BIS[cc]}M659N", tf="lvl", unit="%", key=cc in ("UK", "CN"))
F("AU.CPI", "豪州 CPI 前年比（OECD、四半期）", "AU", P, "inflation", "CPALTT01AUQ659N", "Q", "lvl", unit="%")
for cc in ("UK", "KR", "CA", "AU"):
    nm = COUNTRIES[cc]
    F(f"{cc}.UNEMP", f"{nm} 失業率（OECD 調和）", cc, L, "labor", f"LRHUTTTT{_BIS[cc]}M156S", tf="lvl", good=-1, unit="%",
      key=cc == "UK")
for cc in ("UK", "KR", "CA", "AU"):
    nm = COUNTRIES[cc]
    F(f"{cc}.BOND10", f"{nm} 10 年国債利回り（月次、OECD）", cc, R, "rates", f"IRLTLT01{_BIS[cc]}M156N", tf="lvl", good=0, unit="%")
F("UK.RATE3M", "英国 3 か月金利（OECD）", "UK", R, "rates", "IR3TIB01GBM156N", tf="lvl", good=0, unit="%")
for cc in ("UK", "CN", "KR", "IN", "US"):
    F(f"{cc}.CLI", f"{COUNTRIES[cc]} OECD 景気先行指数", cc, G, "growth", f"{_ISO3[cc]}LOLITONOSTSAM", tf="lvl", key=cc in ("CN", "KR"))
F("CN.EXPORTS", "中国 輸出（ドル建て、OECD）", "CN", T, "growth", "XTEXVA01CNM667S", key=True)
F("CN.IMPORTS", "中国 輸入（ドル建て、OECD）", "CN", T, "growth", "XTIMVA01CNM667S")
F("CN.M2", "中国 M2", "CN", M, "liquidity", "MYAGM2CNM189N", key=True)
F("KR.EXPORTS", "韓国 輸出（ドル建て、OECD）— 世界貿易の先行指標", "KR", T, "growth", "XTEXVA01KRM667S", key=True)
F("KR.IMPORTS", "韓国 輸入（ドル建て、OECD）", "KR", T, "growth", "XTIMVA01KRM667S")
F("DE.EXPORTS", "ドイツ 輸出（ドル建て、OECD）", "DE", T, "growth", "XTEXVA01DEM667S")

# ======================================================================================================
# 世界（IMF 一次産品価格、不確実性）
# ======================================================================================================
for _id, _n, _c, _ax in (("GLOBAL.COMMOD", "一次産品価格指数（全体、IMF）", "PALLFNFINDEXM", "inflation"),
                         ("GLOBAL.ENERGY", "エネルギー価格指数（IMF）", "PNRGINDEXM", "inflation"),
                         ("GLOBAL.METALS", "金属価格指数（IMF）", "PMETAINDEXM", "growth"),
                         ("GLOBAL.FOOD", "食料価格指数（IMF）", "PFOODINDEXM", "inflation"),
                         ("GLOBAL.COPPER_M", "銅価格（IMF、月次）", "PCOPPUSDM", "growth"),
                         ("GLOBAL.IRON_ORE", "鉄鉱石価格（IMF）", "PIORECRUSDM", "growth"),
                         ("GLOBAL.WHEAT", "小麦価格（IMF）", "PWHEAMTUSDM", "inflation"),
                         ("GLOBAL.NATGAS_EU", "欧州天然ガス価格（IMF）", "PNGASEUUSDM", "inflation")):
    F(_id, _n, "GLOBAL", "商品", _ax, _c)
F("GLOBAL.BRENT_D", "ブレント原油（日次、EIA）", "GLOBAL", "商品", "inflation", "DCOILBRENTEU", "D")
F("GLOBAL.WTI_D", "WTI 原油（日次、EIA）", "GLOBAL", "商品", "inflation", "DCOILWTICO", "D")
F("GLOBAL.EPU", "世界の経済政策不確実性指数", "GLOBAL", S, "growth", "GEPUCURRENT", tf="lvl", good=-1)
F("GLOBAL.OECD_CLI", "OECD 全体 景気先行指数", "GLOBAL", G, "growth", "OECDLOLITONOSTSAM", tf="lvl", key=True)

# ======================================================================================================
# 年次の国際比較（世界銀行 WDI）
# ======================================================================================================
_WB_C = {"JP": "JPN", "US": "USA", "CN": "CHN", "DE": "DEU", "UK": "GBR", "IN": "IND", "KR": "KOR", "BR": "BRA", "ID": "IDN",
         "VN": "VNM"}
_WB_I = (("GDP_A", "実質 GDP 成長率（年次）", "NY.GDP.MKTP.KD.ZG", G, "growth", 1),
         ("INFL_A", "インフレ率（年次）", "FP.CPI.TOTL.ZG", P, "inflation", 1),
         ("CA_GDP_A", "経常収支 GDP 比（年次）", "BN.CAB.XOKA.GD.ZS", T, "external", 0),
         ("UNEMP_A", "失業率（年次、ILO 推計）", "SL.UEM.TOTL.ZS", L, "labor", -1))
for cc, iso in _WB_C.items():
    for suf, nm, ind, cat, ax, good in _WB_I:
        E(f"{cc}.{suf}", f"{COUNTRIES[cc]} {nm}", cc, cat, ax, "wb", f"{iso}/{ind}", "A", "lvl", good, "%")

# ======================================================================================================
# 市場（TradingView / Yahoo — ターミナルのデータ源）
# ======================================================================================================
def MK(id: str, name: str, country: str, category: str, axis: str, symbol: str, tf: str = "lvl", good: int = 0,
       unit: str = "", key: bool = False) -> None:
    E(id, name, country, category, axis, "market", symbol, "D", tf, good, unit, key)


for _id, _n, _cc, _s in (("US.MKT_UST2", "米 2 年（市場）", "US", "TVC:US02Y"), ("US.MKT_UST5", "米 5 年（市場）", "US", "TVC:US05Y"),
                         ("US.MKT_UST10", "米 10 年（市場）", "US", "TVC:US10Y"), ("US.MKT_UST30", "米 30 年（市場）", "US", "TVC:US30Y"),
                         ("JP.JGB2", "日本 2 年国債", "JP", "TVC:JP02Y"), ("JP.JGB5", "日本 5 年国債", "JP", "TVC:JP05Y"),
                         ("JP.JGB10", "日本 10 年国債", "JP", "TVC:JP10Y"), ("JP.JGB20", "日本 20 年国債", "JP", "TVC:JP20Y"),
                         ("JP.JGB30", "日本 30 年国債", "JP", "TVC:JP30Y"), ("DE.BUND10", "独 10 年国債", "DE", "TVC:DE10Y"),
                         ("UK.GILT10", "英 10 年国債", "UK", "TVC:GB10Y"), ("IT.BTP10", "伊 10 年国債", "IT", "TVC:IT10Y"),
                         ("FR.OAT10", "仏 10 年国債", "FR", "TVC:FR10Y"), ("CN.CGB10", "中国 10 年国債", "CN", "TVC:CN10Y"),
                         ("AU.ACGB10", "豪 10 年国債", "AU", "TVC:AU10Y")):
    MK(_id, _n, _cc, R, "rates", _s, unit="%", key=_id == "JP.JGB10")
for _id, _n, _cc, _s in (("JP.MKT_USDJPY", "ドル円（市場）", "JP", "FX:USDJPY"), ("EA.MKT_EURUSD", "ユーロドル（市場）", "EA", "FX:EURUSD"),
                         ("JP.EURJPY", "ユーロ円", "JP", "FX:EURJPY"), ("JP.AUDJPY", "豪ドル円", "JP", "FX:AUDJPY"),
                         ("CN.USDCNH", "ドル・オフショア人民元", "CN", "FX_IDC:USDCNH"), ("US.DXY", "ドル指数（DXY）", "US", "TVC:DXY"),
                         ("KR.MKT_USDKRW", "ドル・ウォン（市場）", "KR", "FX_IDC:USDKRW"), ("TW.MKT_USDTWD", "ドル・台湾ドル（市場）", "TW", "FX_IDC:USDTWD")):
    MK(_id, _n, _cc, "為替", "fx", _s)
for _id, _n, _s, _ax, _g in (("GLOBAL.WTI", "WTI 原油（市場）", "TVC:USOIL", "inflation", 1), ("GLOBAL.BRENT", "ブレント原油（市場）", "TVC:UKOIL", "inflation", 1),
                             ("GLOBAL.GOLD", "金", "TVC:GOLD", "inflation", 0), ("GLOBAL.SILVER", "銀", "TVC:SILVER", "inflation", 0),
                             ("GLOBAL.COPPER", "銅（COMEX）", "COMEX:HG1!", "growth", 1), ("GLOBAL.NATGAS", "天然ガス（NYMEX）", "NYMEX:NG1!", "inflation", 1),
                             ("GLOBAL.WHEAT_F", "小麦（CBOT）", "CBOT:ZW1!", "inflation", 1), ("GLOBAL.CORN", "トウモロコシ（CBOT）", "CBOT:ZC1!", "inflation", 1)):
    MK(_id, _n, "GLOBAL", "商品", _ax, _s, "yoy", _g, key=_id in ("GLOBAL.WTI", "GLOBAL.COPPER"))
for _id, _n, _cc, _s in (("JP.NI225", "日経平均", "JP", "TVC:NI225"), ("JP.TOPIX", "TOPIX", "JP", "TVC:TOPIX"),
                         ("US.SPX", "S&P 500", "US", "SP:SPX"), ("US.NDX", "NASDAQ 100", "US", "NASDAQ:NDX"),
                         ("US.SOX", "フィラデルフィア半導体株指数", "US", "NASDAQ:SOX"), ("CN.HSI", "ハンセン指数", "CN", "TVC:HSI"),
                         ("CN.SHCOMP", "上海総合", "CN", "SSE:000001"), ("KR.KOSPI", "KOSPI", "KR", "TVC:KOSPI"),
                         ("EA.SX5E", "ユーロ・ストックス 50", "EA", "TVC:SX5E"), ("DE.DAX", "DAX", "DE", "XETR:DAX"),
                         ("UK.FTSE", "FTSE 100", "UK", "TVC:UKX")):
    MK(_id, _n, _cc, "株式", "equity", _s, "yoy")
MK("US.MKT_VIX", "VIX（市場）", "US", CR, "liquidity", "TVC:VIX", good=-1)
MK("US.HYG", "ハイイールド債 ETF（HYG）", "US", CR, "liquidity", "AMEX:HYG", "yoy", 1)
MK("US.LQD", "投資適格債 ETF（LQD）", "US", CR, "liquidity", "AMEX:LQD", "yoy", 0)
MK("GLOBAL.EMB", "新興国ドル建て債 ETF（EMB）", "GLOBAL", CR, "liquidity", "AMEX:EMB", "yoy", 1)
MK("US.TLT", "米長期国債 ETF（TLT）", "US", R, "rates", "NASDAQ:TLT", "yoy", 0)

# ======================================================================================================
# 合成系列（ほかの系列から計算）
# ======================================================================================================
def D(id: str, name: str, country: str, category: str, axis: str, formula: dict[str, Any], freq: str = "D", tf: str = "lvl",
      good: int = 0, unit: str = "", key: bool = False) -> None:
    E(id, name, country, category, axis, "derived", formula, freq, tf, good, unit, key)


D("US.NET_LIQ", "米ネット流動性（FRB 総資産 − TGA − リバースレポ）", "US", M, "liquidity",
  {"lin": [["US.FED_ASSETS", 0.001], ["US.TGA", -1], ["US.RRP", -1]]}, "W", "yoy", 1, "10 億ドル", key=True)
D("GLOBAL.CU_AU", "銅・金レシオ（景気の体温計）", "GLOBAL", "商品", "growth", {"ratio": ["GLOBAL.COPPER", "GLOBAL.GOLD"]}, "D", "lvl", 1)
D("US.HYG_TLT", "HYG／TLT（リスク選好）", "US", CR, "liquidity", {"ratio": ["US.HYG", "US.TLT"]}, "D", "lvl", 1)
D("US.SOX_SPX", "半導体の相対（SOX／S&P 500）", "US", "株式", "growth", {"ratio": ["US.SOX", "US.SPX"]}, "D", "lvl", 1)
D("JP.US_JP_10Y", "日米 10 年金利差", "JP", R, "rates", {"lin": [["US.MKT_UST10", 1], ["JP.JGB10", -1]]}, "D", "lvl", 0, "%",
  key=True)
D("JP.US_JP_2Y", "日米 2 年金利差", "JP", R, "rates", {"lin": [["US.MKT_UST2", 1], ["JP.JGB2", -1]]}, "D", "lvl", 0, "%")
D("EA.BTP_BUND", "伊独 10 年スプレッド", "EA", CR, "liquidity", {"lin": [["IT.BTP10", 1], ["DE.BUND10", -1]]}, "D", "lvl", -1, "%")

# ======================================================================================================
# フロー（資金の流れ）— 残高の系列は変化（Δ）を、フローの系列はその合計を見る
# ======================================================================================================
F("US.MMF_RETAIL", "MMF 残高（個人向け）", "US", M, "liquidity", "WRMFNS", "W", good=0, unit="10 億ドル")
F("US.MMF_INST", "MMF 残高（機関投資家向け）", "US", M, "liquidity", "WIMFNS", "W", good=0, unit="10 億ドル")
F("US.FOREIGN_UST", "海外投資家の米国債保有", "US", T, "liquidity", "FDHBFIN", "Q", good=0, unit="10 億ドル")
F("US.FED_UST", "FRB の米国債保有", "US", M, "liquidity", "FDHBFRBN", "Q", good=0, unit="10 億ドル")
F("US.FOREIGN_DEP", "海外銀行の在米銀行預金（大口）", "US", M, "liquidity", "DPSFACBW027SBOG", "W", good=0, unit="10 億ドル")
ECB("EA.ECB_ASSETS", "ECB（ユーロシステム）総資産", M, "liquidity", "ILM/W.U2.C.T000000.Z5.Z01", "W", "yoy", unit="百万ユーロ",
    key=True)
J("JP.FLOW_IN_EQ", "対内証券投資：株式・投資ファンド持分（ネット）", T, "liquidity", "対外及び対内証券売買契約等の状況",
  "対内証券投資 株式・投資ファンド持分", ["対内", "株式"], "M", "lvl", 1, "億円")
J("JP.FLOW_IN_BOND", "対内証券投資：中長期債（ネット）", T, "liquidity", "対外及び対内証券売買契約等の状況", "対内証券投資 中長期債",
  ["対内", "中長期債"], "M", "lvl", 1, "億円")
J("JP.FLOW_OUT_EQ", "対外証券投資：株式・投資ファンド持分（ネット）", T, "liquidity", "対外及び対内証券売買契約等の状況",
  "対外証券投資 株式・投資ファンド持分", ["対外", "株式"], "M", "lvl", 0, "億円")
J("JP.FLOW_OUT_BOND", "対外証券投資：中長期債（ネット）", T, "liquidity", "対外及び対内証券売買契約等の状況", "対外証券投資 中長期債",
  ["対外", "中長期債"], "M", "lvl", 0, "億円")

# flow meta: kind (stock = 残高 → 変化を見る / flow = 既にフロー → 合計を見る), group, currency and multiplier to
# currency units, sign (+1 = 増えると市場への資金供給). Only series with a known unit are converted to USD.
FLOW_GROUPS = ["中銀の流動性", "マネー・銀行信用", "現金待機（MMF）", "国際資本フロー", "投資部門別（日本株）"]
FLOW_META: dict[str, dict[str, Any]] = {
    "US.FED_ASSETS": {"kind": "stock", "group": "中銀の流動性", "ccy": "USD", "mult": 1e6, "sign": 1},
    "US.TGA": {"kind": "stock", "group": "中銀の流動性", "ccy": "USD", "mult": 1e9, "sign": -1},
    "US.RRP": {"kind": "stock", "group": "中銀の流動性", "ccy": "USD", "mult": 1e9, "sign": -1},
    "US.RESERVES": {"kind": "stock", "group": "中銀の流動性", "ccy": "USD", "mult": 1e9, "sign": 1},
    "US.NET_LIQ": {"kind": "stock", "group": "中銀の流動性", "ccy": "USD", "mult": 1e9, "sign": 1, "total": False},
    "JP.BOJ_ASSETS": {"kind": "stock", "group": "中銀の流動性", "ccy": "JPY", "mult": 1e8, "sign": 1},
    "EA.ECB_ASSETS": {"kind": "stock", "group": "中銀の流動性", "ccy": "EUR", "mult": 1e6, "sign": 1},
    "US.M2": {"kind": "stock", "group": "マネー・銀行信用", "ccy": "USD", "mult": 1e9, "sign": 1},
    "US.BANK_LOANS": {"kind": "stock", "group": "マネー・銀行信用", "ccy": "USD", "mult": 1e9, "sign": 1},
    "US.DEPOSITS": {"kind": "stock", "group": "マネー・銀行信用", "ccy": "USD", "mult": 1e9, "sign": 1},
    "US.CI_LOANS": {"kind": "stock", "group": "マネー・銀行信用", "ccy": "USD", "mult": 1e9, "sign": 1},
    "US.CONS_CREDIT": {"kind": "stock", "group": "マネー・銀行信用", "ccy": "USD", "mult": None, "sign": 1},
    "CN.M2": {"kind": "stock", "group": "マネー・銀行信用", "ccy": "CNY", "mult": 1, "sign": 1},
    "JP.MONEY_M2": {"kind": "stock", "group": "マネー・銀行信用", "ccy": "JPY", "mult": 1e8, "sign": 1},
    "JP.BANK_LENDING": {"kind": "stock", "group": "マネー・銀行信用", "ccy": "JPY", "mult": 1e8, "sign": 1},
    "US.MMF_RETAIL": {"kind": "stock", "group": "現金待機（MMF）", "ccy": "USD", "mult": 1e9, "sign": -1},
    "US.MMF_INST": {"kind": "stock", "group": "現金待機（MMF）", "ccy": "USD", "mult": 1e9, "sign": -1},
    "US.FOREIGN_UST": {"kind": "stock", "group": "国際資本フロー", "ccy": "USD", "mult": 1e9, "sign": 1},
    "US.FED_UST": {"kind": "stock", "group": "中銀の流動性", "ccy": "USD", "mult": 1e9, "sign": 1, "total": False},
    "US.FOREIGN_DEP": {"kind": "stock", "group": "国際資本フロー", "ccy": "USD", "mult": 1e9, "sign": 1},
    "JP.FLOW_IN_EQ": {"kind": "flow", "group": "国際資本フロー", "ccy": "JPY", "mult": 1e8, "sign": 1},
    "JP.FLOW_IN_BOND": {"kind": "flow", "group": "国際資本フロー", "ccy": "JPY", "mult": 1e8, "sign": 1},
    "JP.FLOW_OUT_EQ": {"kind": "flow", "group": "国際資本フロー", "ccy": "JPY", "mult": 1e8, "sign": 1},
    "JP.FLOW_OUT_BOND": {"kind": "flow", "group": "国際資本フロー", "ccy": "JPY", "mult": 1e8, "sign": 1},
    "JP.CURRENT_ACCOUNT": {"kind": "flow", "group": "国際資本フロー", "ccy": "JPY", "mult": 1e8, "sign": 1},
}
FX_FOR = {"JPY": ("JP.USDJPY", "per_usd"), "EUR": ("EA.EURUSD", "usd_per"), "CNY": ("CN.FX", "per_usd")}
for _e in CATALOG:
    if _e["id"] in FLOW_META:
        _e["flow"] = FLOW_META[_e["id"]]

BY_ID = {e["id"]: e for e in CATALOG}
assert len(BY_ID) == len(CATALOG), "duplicate ids in the ECON catalog"


def all_entries(custom: list[dict[str, Any]] | None = None, overrides: dict[str, dict[str, Any]] | None = None,
                disabled: list[str] | None = None) -> list[dict[str, Any]]:
    """The built-in catalog + the user's own series, with code fixes applied and disabled ones removed."""
    out = []
    for e in CATALOG + [{**{"lag_m": LAG_M.get(c.get("freq", "M"), 1), "good": 1, "key": False, "unit": "", "note": None}, **c,
                         "custom": True} for c in (custom or [])]:
        if e["id"] in (disabled or []):
            continue
        o = (overrides or {}).get(e["id"])
        out.append({**e, **o, "overridden": True} if o else e)
    return out
