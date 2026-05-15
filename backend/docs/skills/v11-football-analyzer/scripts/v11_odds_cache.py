# -*- coding: utf-8 -*-
"""
V11 Odds Cache — 500彩票网赔率缓存 + TrendStep数据源

每天自动从500彩票网抓取竞彩赔率，缓存到本地json。
TrendStep从缓存中查找昨日赔率做趋势对比。

用法：
  cache = OddsCache()
  cache.fetch_today()          # 从500网获取当天数据
  cache.load_cache()           # 加载昨日数据
  trend_data = cache.get_trend(match_id)
"""

import json, os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple

CACHE_DIR = os.path.join(os.path.dirname(__file__), "_odds_cache")
TZ = timezone(timedelta(hours=8))  # 北京时间


def _today_key() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def _yesterday_key() -> str:
    return (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


class OddsCache:
    """
    赔率缓存系统 - 500彩票网数据本地存储
    每天一个JSON文件，按比赛ID索引
    
    缓存结构：
    {
      "2026-05-16": {
        "周六001": { "spf_win": 1.36, "spf_draw": 3.85, "spf_loss": 7.50, ... },
        ...
      }
    }
    """

    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._cache = {}  # {date: {match_id: odds_dict}}
        self._today_odds = None

    def fetch_today(self) -> Tuple[bool, str, list]:
        """从500彩票网获取今天所有比赛并缓存"""
        from v11_dataprovider_v2 import fetch_500_matches, Match500

        ok, msg, matches = fetch_500_matches()
        if not matches:
            return False, msg, []

        today = _today_key()
        if today not in self._cache:
            self._cache[today] = {}

        for m in matches:
            self._cache[today][m.match_id] = {
                "spf_win": m.odds_win,
                "spf_draw": m.odds_draw,
                "spf_loss": m.odds_loss,
                "nspf_win": m.nspf_win,
                "nspf_draw": m.nspf_draw,
                "nspf_loss": m.nspf_loss,
                "handicap": m.handicap,
                "league": m.league,
                "home_team": m.home_team,
                "away_team": m.away_team,
            }

        self._save_date(today)
        self._today_odds = matches
        return True, msg, matches

    def _save_date(self, date_key: str):
        """保存某天数据到文件"""
        path = os.path.join(CACHE_DIR, f"{date_key}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._cache[date_key], f, ensure_ascii=False, indent=2)

    def _load_date(self, date_key: str) -> dict:
        """加载某天缓存"""
        if date_key in self._cache:
            return self._cache[date_key]
        path = os.path.join(CACHE_DIR, f"{date_key}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._cache[date_key] = data
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def load_cache(self, date_key: Optional[str] = None) -> dict:
        """加载缓存"""
        if date_key is None:
            date_key = _yesterday_key()
        return self._load_date(date_key)

    def get_trend(self, match_id: str,
                  today_data: Optional[dict] = None) -> Optional[dict]:
        """
        获取某场比赛的赔率趋势
        
        Returns: { "direction": "up" | "down" | "stable", "change": float }
        """
        today_data = today_data or self._cache.get(_today_key(), {})

        if match_id not in today_data:
            return None

        today_odds = today_data[match_id]
        yesterday_odds = self._load_date(_yesterday_key()).get(match_id)

        if not yesterday_odds:
            return None

        # 对比关键方向（让球盘）
        # 注意：spf_win是让球胜，spf_loss是让球负
        # 如果我们预测方向是"让胜"，看spf_win是否在下降
        # 趋势方向 = "利好"：赔率下降（支持该方向）
        #         = "不利"：赔率上升

        diff_win = today_odds.get("spf_win", 0) - yesterday_odds.get("spf_win", 0)
        diff_draw = today_odds.get("spf_draw", 0) - yesterday_odds.get("spf_draw", 0)
        diff_loss = today_odds.get("spf_loss", 0) - yesterday_odds.get("spf_loss", 0)

        changes = {"win": diff_win, "draw": diff_draw, "loss": diff_loss, "total": 0}

        # 判断趋势方向
        # 让胜降赔→利好主队  |  让负降赔→利好客队
        if diff_win < -0.05:
            direction = "利好让胜"
        elif diff_loss < -0.05:
            direction = "利好让负"
        elif diff_draw < -0.05:
            direction = "利好让平"
        else:
            direction = "稳定"

        return {
            "direction": direction,
            "changes": changes,
            "today": today_odds,
            "yesterday": yesterday_odds,
        }

    def get_trend_for_pipeline(self, match_id: str) -> Optional[dict]:
        """为V11 Pipeline TrendStep准备的趋势数据"""
        return self.get_trend(match_id)

    def clear_cache(self, older_than_days: int = 14):
        """清理旧缓存"""
        now = datetime.now(TZ)
        for fname in os.listdir(CACHE_DIR):
            if not fname.endswith(".json"):
                continue
            try:
                d = datetime.strptime(fname.replace(".json", ""), "%Y-%m-%d")
                if (now - d).days > older_than_days:
                    os.remove(os.path.join(CACHE_DIR, fname))
            except ValueError:
                continue

    def get_today_odds_500(self) -> list:
        """获取今天的原始Match500列表"""
        if self._today_odds:
            return self._today_odds
        ok, msg, matches = self.fetch_today()
        return matches if ok else []


# ==================== 自动运行脚本 ====================

def run_daily_fetch():
    """每日自动抓取 - 供cron调用"""
    cache = OddsCache()
    ok, msg, matches = cache.fetch_today()
    if ok:
        from v11_rankings import RankProvider
        rp = RankProvider()
        v11_matches = _matches_to_v11(matches, rp)
        if v11_matches:
            from v11_analyzer_v2 import V11Analyzer
            analyzer = V11Analyzer()
            results = analyzer.analyze_matches(v11_matches)
            return ok, msg, results
    return ok, msg, []


def _matches_to_v11(matches_500: list, rp=None) -> list:
    """500Match→V11 Match转换"""
    from v11_analyzer_v2 import Match as V11Match, AvgOdds
    v11s = []
    for m in matches_500:
        v11 = V11Match(
            match_id=m.match_id,
            league=m.league,
            home_team=m.home_team,
            away_team=m.away_team,
            home_rank=rp.get(m.league, m.home_team) if rp else None,
            away_rank=rp.get(m.league, m.away_team) if rp else None,
            handicap=m.handicap,
            odds_win=m.odds_win,
            odds_draw=m.odds_draw,
            odds_loss=m.odds_loss,
            avg_odds=AvgOdds(m.nspf_win, m.nspf_draw, m.nspf_loss) if m.nspf_win else None,
        )
        v11s.append(v11)
    return v11s


if __name__ == "__main__":
    print("=" * 55)
    print("  V11 Odds Cache — 500彩票网自动抓取")
    print("=" * 55)

    cache = OddsCache()
    ok, msg, matches = cache.fetch_today()
    print(f"\n  500网: {msg}")

    if matches:
        print(f"  当天比赛: {len(matches)}场")
        cache.clear_cache(older_than_days=14)

        # 检查是否有昨日缓存（TrendStep用）
        yesterday = cache.load_cache()
        match_ids = set(yesterday.keys())
        if match_ids:
            print(f"  昨日缓存: {len(yesterday)}条")
            # 演示趋势
            sample = list(yesterday.keys())[0]
            trend = cache.get_trend(sample)
            if trend:
                print(f"  趋势示例 ({sample}): {trend['direction']}")
        else:
            print(f"  昨日缓存: 空（无法做趋势对比）")

        # 测试给V11 Match补排名
        from v11_rankings import RankProvider
        rp = RankProvider()
        v11s = _matches_to_v11(matches, rp)
        ranks_found = sum(1 for m in v11s if m.home_rank or m.away_rank)
        print(f"  V11转换: {len(v11s)}场, 匹配到排名: {ranks_found}个")

        # 如果有排名就跑Pipeline
        if ranks_found > 0:
            from v11_analyzer_v2 import V11Analyzer
            analyzer = V11Analyzer()
            results = analyzer.analyze_matches(v11s)
            green = [r for r in results if r.label == "🟢"]
            yellow = [r for r in results if r.label == "🟡"]
            print(f"  分析结果: {len(green)}绿/{len(yellow)}黄/{len(results)-len(green)-len(yellow)}灰")
            for p in green[:3]:
                print(f"    🟢 {p.match_id} {p.direction} odd={p.min_odd} conf={p.confidence}%")
