# -*- coding: utf-8 -*-
"""V11 DataProvider v2 — 500彩票网完整解析"""
import urllib.request, re
from typing import List, Optional, Tuple

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
URL = "https://trade.500.com/jczq/"


class Match500:
    """500彩票网的比赛数据"""
    def __init__(self, match_id, league, home_team, away_team, match_time,
                 handicap, odds_win, odds_draw, odds_loss,
                 nspf_win=0.0, nspf_draw=0.0, nspf_loss=0.0,
                 fixture_id="", home_rank=None, away_rank=None):
        self.match_id = match_id
        self.league = league
        self.home_team = home_team
        self.away_team = away_team
        self.match_time = match_time
        self.handicap = handicap
        self.odds_win = odds_win    # 让球胜
        self.odds_draw = odds_draw  # 让球平
        self.odds_loss = odds_loss  # 让球负
        self.nspf_win = nspf_win    # 普通胜
        self.nspf_draw = nspf_draw  # 普通平
        self.nspf_loss = nspf_loss  # 普通负
        self.fixture_id = fixture_id
        self.home_rank = home_rank
        self.away_rank = away_rank
    
    def __repr__(self):
        return f"[{self.match_id}] {self.league} {self.home_team}-{self.away_team} 让{self.handicap}  {self.odds_win}/{self.odds_draw}/{self.odds_loss}"


def fetch_500_matches() -> Tuple[bool, str, List[Match500]]:
    """从500彩票网获取所有比赛"""
    try:
        req = urllib.request.Request(URL, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
    except Exception as e:
        return False, f"网络错误: {e}", []
    
    try:
        html = raw.decode("gbk", errors="replace")
    except Exception:
        html = raw.decode("utf-8", errors="replace")
    
    # 找所有比赛行
    tr_pattern = re.compile(
        r'<tr class="bet-tb-tr[^"]*"[^>]*data-fixtureid="(\d+)"[^>]*>.*?</tr>',
        re.DOTALL
    )
    
    matches = []
    for m in tr_pattern.finditer(html):
        tr = m.group(0)
        fixture_id = m.group(1)
        
        try:
            parsed = _parse_row(tr)
            if parsed:
                matches.append(parsed)
        except Exception:
            continue
    
    return True, f"获取{len(matches)}场比赛", matches


def _parse_row(tr: str) -> Optional[Match500]:
    """解析单行"""
    # data-* 属性
    def get_data(attr):
        m2 = re.search(f'data-{attr}="([^"]*)"', tr)
        return m2.group(1) if m2 else ""
    
    matchnum = get_data("matchnum")
    league = get_data("simpleleague")
    home = get_data("homesxname")
    away = get_data("awaysxname")
    match_time = get_data("matchtime")
    handicap_str = get_data("rangqiu")
    
    if not matchnum:
        return None
    
    # 让球数
    handicap = 0
    if handicap_str:
        try:
            handicap = int(handicap_str)
        except ValueError:
            handicap = 0
    
    fixture_id = get_data("fixtureid")
    
    # 赔率提取（稳健方式：取全部data-sp值）
    # 顺序: [nspf_win, nspf_draw, nspf_loss, spf_win, spf_draw, spf_loss]
    all_sp_values = re.findall(r'data-sp="([\d.]+)"', tr)
    odds_win = odds_draw = odds_loss = 0.0
    nspf_win = nspf_draw = nspf_loss = 0.0
    
    if len(all_sp_values) >= 6:
        nspf_win = float(all_sp_values[0])
        nspf_draw = float(all_sp_values[1])
        nspf_loss = float(all_sp_values[2])
        odds_win = float(all_sp_values[3])
        odds_draw = float(all_sp_values[4])
        odds_loss = float(all_sp_values[5])
    elif len(all_sp_values) >= 3:
        odds_win = float(all_sp_values[0])
        odds_draw = float(all_sp_values[1])
        odds_loss = float(all_sp_values[2])
    
    return Match500(
        match_id=matchnum,
        league=league,
        home_team=home,
        away_team=away,
        match_time=match_time,
        handicap=handicap,
        odds_win=odds_win,
        odds_draw=odds_draw,
        odds_loss=odds_loss,
        nspf_win=nspf_win,
        nspf_draw=nspf_draw,
        nspf_loss=nspf_loss,
        fixture_id=fixture_id,
    )


def matches_to_v11(matches_500: List[Match500]) -> list:
    """转换为V11能用的Match格式"""
    from v11_analyzer_v2 import Match as V11Match, AvgOdds
    
    v11_matches = []
    for m in matches_500:
        v11 = V11Match(
            match_id=m.match_id,
            league=m.league,
            home_team=m.home_team,
            away_team=m.away_team,
            home_rank=None,
            away_rank=None,
            handicap=m.handicap,
            odds_win=m.odds_win,
            odds_draw=m.odds_draw,
            odds_loss=m.odds_loss,
            avg_odds=None,
        )
        v11_matches.append(v11)
    
    return v11_matches


if __name__ == "__main__":
    ok, msg, matches = fetch_500_matches()
    print(f"500彩票网: {msg}")
    
    if matches:
        print(f"\n第1-20场:")
        for m in matches[:20]:
            print(f"  {m}")
        
        # 找周六比赛
        sat = [m for m in matches if "周六" in m.match_id]
        print(f"\n周六比赛 ({len(sat)}场):")
        for m in sat:
            print(f"  {m}")
        
        # 转换为V11格式
        v11s = matches_to_v11(matches)
        print(f"\n转换为V11格式: {len(v11s)} 场比赛")
        for v in v11s[:5]:
            print(f"  [{v.match_id}] {v.league} {v.home_team}-{v.away_team} 让{v.handicap}  {v.odds_win}/{v.odds_draw}/{v.odds_loss}")
