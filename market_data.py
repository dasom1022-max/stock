"""yfinance / pykrx 로 국내외 시세를 수집해 Gemini 프롬프트용 요약 텍스트를 만듭니다.

- 해외 지수·선물·환율·금리·원자재·미국 빅테크: yfinance
- 국내 관심종목: yfinance(.KS/.KQ, 장중 시세 반영) 우선, 실패 시 pykrx 일별 OHLCV로 보완
- 관심종목 코드가 비어 있거나 종목명과 맞지 않으면 pykrx 종목명 검색으로 자동 보정
어떤 단계가 실패해도 예외를 밖으로 던지지 않고, 가능한 데이터만 반환합니다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

KST = ZoneInfo("Asia/Seoul")
WATCHLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------
def load_watchlist(path: str = WATCHLIST_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _norm(name: str) -> str:
    return "".join(name.split()).upper()


def _metrics(close: pd.Series, volume: pd.Series | None = None) -> dict | None:
    """종가 시계열로 단기·중기 지표를 계산합니다."""
    close = close.dropna()
    if len(close) < 2:
        return None

    last = float(close.iloc[-1])

    def ret(n: int) -> float | None:
        if len(close) > n:
            base = float(close.iloc[-1 - n])
            return (last / base - 1) * 100 if base else None
        return None

    ma20 = float(close.tail(20).mean()) if len(close) >= 20 else None
    ma60 = float(close.tail(60).mean()) if len(close) >= 60 else None

    vol_ratio = None
    if volume is not None:
        v = volume.dropna()
        if len(v) >= 21 and float(v.iloc[-21:-1].mean()) > 0:
            vol_ratio = float(v.iloc[-1]) / float(v.iloc[-21:-1].mean())

    return {
        "date": close.index[-1].strftime("%m/%d"),
        "last": last,
        "d1": ret(1),
        "d5": ret(5),
        "d20": ret(20),
        "vs_ma20": (last / ma20 - 1) * 100 if ma20 else None,
        "vs_ma60": (last / ma60 - 1) * 100 if ma60 else None,
        "high60": float(close.tail(60).max()),
        "vol_ratio": vol_ratio,
    }


def _fmt_pct(x: float | None) -> str:
    return "-" if x is None else f"{x:+.1f}%"


def _fmt_price(x: float) -> str:
    if abs(x) >= 1000:
        return f"{x:,.0f}"
    if abs(x) >= 10:
        return f"{x:,.2f}"
    return f"{x:,.3f}"


# ---------------------------------------------------------------------------
# yfinance
# ---------------------------------------------------------------------------
def _yf_download(tickers: list[str], period: str = "4mo") -> dict[str, pd.DataFrame]:
    """여러 티커를 한 번에 내려받아 {티커: DataFrame} 으로 반환합니다."""
    if not tickers:
        return {}
    try:
        import yfinance as yf

        raw = yf.download(
            tickers,
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            threads=True,
            progress=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[market_data] yfinance 다운로드 실패: {exc}")
        return {}

    out: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return out
    for t in tickers:
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df.dropna(how="all")
            if not df.empty and df["Close"].notna().sum() >= 2:
                out[t] = df
        except Exception:  # noqa: BLE001
            continue
    return out


# ---------------------------------------------------------------------------
# pykrx
# ---------------------------------------------------------------------------
def _pykrx_name_map() -> dict[str, tuple[str, str]]:
    """{정규화 종목명: (코드, 'KS'|'KQ')} — 실패 시 빈 dict."""
    try:
        from pykrx import stock

        result: dict[str, tuple[str, str]] = {}
        today = datetime.now(KST)
        # 휴장일이면 목록이 비므로 최근 7일 중 첫 영업일을 사용
        for back in range(7):
            day = (today - timedelta(days=back)).strftime("%Y%m%d")
            for market, suffix in (("KOSPI", "KS"), ("KOSDAQ", "KQ")):
                for code in stock.get_market_ticker_list(day, market=market):
                    name = stock.get_market_ticker_name(code)
                    if isinstance(name, str):
                        result.setdefault(_norm(name), (code, suffix))
            if result:
                break
        # ETF 는 별도 목록
        try:
            for code in stock.get_etf_ticker_list(day):
                name = stock.get_etf_ticker_name(code)
                if isinstance(name, str):
                    result.setdefault(_norm(name), (code, "KS"))
        except Exception:  # noqa: BLE001
            pass
        return result
    except Exception as exc:  # noqa: BLE001
        print(f"[market_data] pykrx 종목명 조회 실패(코드 보정 생략): {exc}")
        return {}


def _pykrx_ohlcv(code: str) -> pd.DataFrame | None:
    try:
        from pykrx import stock

        end = datetime.now(KST)
        start = end - timedelta(days=130)
        df = stock.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
        if df is None or df.empty:
            return None
        df = df.rename(columns={"종가": "Close", "거래량": "Volume"})
        return df
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------
def resolve_domestic(items: list[dict]) -> list[dict]:
    """코드가 비었거나 이름과 맞지 않는 종목을 pykrx 로 보정합니다."""
    name_map = _pykrx_name_map()
    if not name_map:
        return [i for i in items if i.get("code")]

    code_to_name = {v[0]: k for k, v in name_map.items()}
    resolved = []
    for item in items:
        key = _norm(item["name"])
        code = (item.get("code") or "").strip()
        if key in name_map and code_to_name.get(code) != key:
            new_code, market = name_map[key]
            if code:
                print(f"[market_data] 코드 보정: {item['name']} {code} -> {new_code}")
            item = {**item, "code": new_code, "market": market}
        elif not code:
            print(f"[market_data] 종목명을 찾지 못해 제외: {item['name']}")
            continue
        resolved.append(item)
    return resolved


def collect_global(items: list[dict]) -> list[dict]:
    data = _yf_download([i["ticker"] for i in items])
    rows = []
    for i in items:
        df = data.get(i["ticker"])
        m = _metrics(df["Close"]) if df is not None else None
        if m:
            rows.append({"name": i["name"], **m})
    return rows


def collect_domestic(items: list[dict]) -> list[dict]:
    items = resolve_domestic(items)
    primary = {i["code"]: f"{i['code']}.{i.get('market') or 'KS'}" for i in items}
    data = _yf_download(list(primary.values()))

    # 시장 구분이 틀렸을 가능성 → 반대 시장 접미사로 재시도
    missing = [c for c, t in primary.items() if t not in data]
    alt = {c: f"{c}.{'KQ' if primary[c].endswith('.KS') else 'KS'}" for c in missing}
    data.update(_yf_download(list(alt.values())))

    rows = []
    for i in items:
        code = i["code"]
        df = data.get(primary[code])
        if df is None:
            df = data.get(alt.get(code, ""))
        if df is None:
            df = _pykrx_ohlcv(code)
        m = _metrics(df["Close"], df.get("Volume")) if df is not None else None
        if m:
            rows.append({"name": i["name"], "code": code, **m})
        else:
            print(f"[market_data] 시세 없음: {i['name']}({code})")
    return rows


# ---------------------------------------------------------------------------
# 프롬프트용 텍스트
# ---------------------------------------------------------------------------
def format_global(rows: list[dict]) -> str:
    lines = ["이름 | 최근값(기준일) | 1일 | 5일 | 20일"]
    for r in rows:
        lines.append(
            f"{r['name']} | {_fmt_price(r['last'])}({r['date']}) | "
            f"{_fmt_pct(r['d1'])} | {_fmt_pct(r['d5'])} | {_fmt_pct(r['d20'])}"
        )
    return "\n".join(lines)


def format_domestic(rows: list[dict]) -> str:
    lines = ["종목(코드) | 현재가(기준일) | 1일 | 5일 | 20일 | 20일선 대비 | 60일선 대비 | 60일 고점 대비 | 거래량(20일 평균 대비)"]
    for r in rows:
        from_high = (r["last"] / r["high60"] - 1) * 100 if r["high60"] else None
        vol = "-" if r["vol_ratio"] is None else f"{r['vol_ratio']:.1f}배"
        lines.append(
            f"{r['name']}({r['code']}) | {_fmt_price(r['last'])}({r['date']}) | "
            f"{_fmt_pct(r['d1'])} | {_fmt_pct(r['d5'])} | {_fmt_pct(r['d20'])} | "
            f"{_fmt_pct(r['vs_ma20'])} | {_fmt_pct(r['vs_ma60'])} | {_fmt_pct(from_high)} | {vol}"
        )
    return "\n".join(lines)


def build_market_snapshot() -> str:
    """프롬프트에 붙일 시세 스냅샷 문자열. 수집 실패 시 빈 문자열."""
    try:
        wl = load_watchlist()
    except Exception as exc:  # noqa: BLE001
        print(f"[market_data] watchlist.json 로드 실패: {exc}")
        return ""

    global_rows = collect_global(wl.get("global", []))
    domestic_rows = collect_domestic(wl.get("domestic", []))
    print(f"[market_data] 수집 완료: 해외 {len(global_rows)}건, 관심종목 {len(domestic_rows)}건")

    parts = []
    if global_rows:
        parts.append("■ 국내외 지수·선물·환율·금리·원자재·미국 빅테크 (yfinance)\n" + format_global(global_rows))
    if domestic_rows:
        parts.append("■ 관심종목 시세 (yfinance/pykrx)\n" + format_domestic(domestic_rows))
    return "\n\n".join(parts)


if __name__ == "__main__":
    # 사용법: python market_data.py [출력파일]  (생략 시 화면 출력)
    import sys

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    body = build_market_snapshot() or "(수집된 데이터 없음 — 웹 검색으로 시세를 확인할 것)"
    text = f"# 시세 스냅샷\n수집 시각: {now}\n(장중 시세는 15~20분 지연될 수 있음)\n\n{body}\n"
    if len(sys.argv) > 1:
        os.makedirs(os.path.dirname(os.path.abspath(sys.argv[1])), exist_ok=True)
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[market_data] 저장: {sys.argv[1]}")
    else:
        print(text)
