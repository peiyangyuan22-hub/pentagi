# -*- coding: utf-8 -*-
"""
V11 Rank Provider — 排名数据轻量管理

用法：
  from v11_rankings import RankProvider
  ranks = RankProvider()
  ranks.get("德甲", "拜仁")  # returns 1
  ranks.set_rank("德甲", "拜仁", 1)

排名数据来自用户提供的积分榜，手动更新。
每轮开始前检查 rank_file 的 last_updated。
"""

import json, os, re
from datetime import datetime
from typing import Optional, Dict

RANK_FILE = os.path.join(os.path.dirname(__file__), "v11_rankings.json")

# ==================== 默认排名数据 ====================
# 来源：用户提供的周六积分榜数据
DEFAULT_RANKS = {
    "德甲": {
        "勒沃库森": 1, "拜仁": 2, "莱比锡": 3, "多特蒙德": 4,
        "法兰克福": 5, "沃夫斯堡": 6, "柏林联合": 7, "霍芬海姆": 8,
        "门兴": 9, "圣保利": 10, "斯图加特": 11, "奥格斯堡": 12,
        "海登海姆": 13, "美因茨": 14, "云达不莱梅": 15, "弗赖堡": 16,
        "波鸿": 17, "基尔": 18,
    },
    "日职": {
        "东京绿茵": 1, "浦和红钻": 2, "东京FC": 3, "名古屋鲸八": 4,
        "水户蜀葵": 5, "川崎前锋": 6, "横滨水手": 7, "广岛三箭": 8,
        "大阪樱花": 9, "大阪钢巴": 10, "鹿岛鹿角": 11, "福冈黄蜂": 12,
        "神户胜利船": 13, "町田泽维亚": 14, "清水鼓动": 15,
        "磐田喜悦": 16, "鸟栖沙岩": 17, "札幌冈萨多": 18, "湘南比马": 19,
        "柏太阳神": 20,
    },
    "韩职": {
        "仁川联": 1, "大田市民": 2, "金泉尚武": 3, "全北现代": 4,
        "蔚山现代": 5, "浦项制铁": 6, "首尔FC": 7, "大邱FC": 8,
        "水原FC": 9, "光州FC": 10, "济州联": 11, "江原FC": 12,
        "忠南牙山": 13,
    },
    "澳超": {
        "珀斯光荣": 1, "布里斯班狮吼": 2, "阿德莱德联": 3,
        "悉尼FC": 4, "西悉尼流浪者": 5, "墨尔本城": 6,
        "墨尔本胜利": 7, "中央海岸水手": 8, "纽卡斯尔喷气机": 9,
        "惠灵顿凤凰": 10, "西部联": 11, "麦克阿瑟": 12,
    },
    "葡超": {
        "里斯本竞技": 1, "本菲卡": 2, "布拉加": 3, "波尔图": 4,
        "吉马良斯": 5, "法马利康": 6, "埃斯托里尔": 7, "阿马多拉": 8,
        "博阿维斯塔": 9, "国民": 10, "卡萨皮亚": 11,
        "圣克拉拉": 12, "法鲁人": 13, "里斯本": 1,
        "埃斯托里": 7,
    },
    "英超": {
        "阿森纳": 1, "曼城": 2, "曼联": 3, "利物浦": 4,
        "阿斯顿维拉": 5, "布莱顿": 6, "切尔西": 7, "热刺": 8,
        "纽卡斯尔": 9, "西汉姆联": 10, "布伦特福德": 11,
        "埃弗顿": 12, "水晶宫": 13, "狼队": 14, "伯恩茅斯": 15,
        "诺丁汉森林": 16, "富勒姆": 17, "伊普斯维奇": 18,
        "莱斯特城": 19, "南安普顿": 20,
    },
    "西甲": {
        "巴塞罗那": 1, "皇马": 2, "马竞": 3, "毕尔巴鄂": 4,
        "皇家贝蒂斯": 5, "皇家社会": 6, "比利亚雷亚尔": 7,
        "塞尔塔": 8, "巴列卡诺": 9, "赫罗纳": 10, "马洛卡": 11,
        "拉帕马斯": 12, "奥萨苏纳": 13, "塞维利亚": 14,
        "巴伦西亚": 15, "西班牙人": 16, "阿拉维斯": 17,
        "莱加内斯": 18, "赫塔费": 19, "巴拉多利德": 20,
    },
    "意甲": {
        "国米": 1, "AC米兰": 2, "那不勒斯": 3, "尤文": 4,
        "亚特兰大": 5, "拉齐奥": 6, "罗马": 7, "佛罗伦萨": 8,
        "博洛尼亚": 9, "都灵": 10, "乌迪内斯": 11, "热那亚": 12,
        "蒙扎": 13, "帕尔马": 14, "恩波利": 15, "维罗纳": 16,
        "莱切": 17, "科莫": 18, "卡利亚里": 19, "威尼斯": 20,
    },
    "中超": {
        "上海海港": 1, "上海申花": 2, "成都蓉城": 3,
        "北京国安": 4, "山东泰山": 5, "浙江": 6,
        "天津津门虎": 7, "武汉三镇": 8, "河南": 9,
        "长春亚泰": 10, "沧州雄狮": 11, "梅州客家": 12,
        "深圳新鹏城": 13, "南通支云": 14, "青岛海牛": 15,
        "青岛西海岸": 16,
    },
}

LEAGUE_ALIASES = {
    "日职": "日职", "日职联": "日职",
    "韩职": "韩职", "K联赛": "韩职",
    "澳超": "澳超", "A联赛": "澳超",
    "英超": "英超", "英格兰超级": "英超",
    "德甲": "德甲", "德国甲级": "德甲",
    "西甲": "西甲", "西班牙甲级": "西甲",
    "意甲": "意甲", "意大利甲级": "意甲",
    "法甲": "法甲", "法国甲级": "法甲",
    "葡超": "葡超", "葡萄牙超级": "葡超",
    "荷甲": "荷甲",
    "中超": "中超",
}


class RankProvider:
    """排名数据提供器"""

    def __init__(self):
        self._data = self._load()

    def _load(self) -> Dict:
        try:
            with open(RANK_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "ranks" in data:
                    return data
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return {"ranks": dict(DEFAULT_RANKS), "last_updated": "default"}

    def save(self):
        self._data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(RANK_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self, league: str, team: str) -> Optional[int]:
        """获取某队在某联赛的排名"""
        # 联赛别名映射
        league_key = LEAGUE_ALIASES.get(league, league)

        ranks = self._data["ranks"].get(league_key, {})
        if team in ranks:
            return ranks[team]

        # 模糊匹配
        for name, rank in ranks.items():
            if name in team or team in name:
                return rank
        return None

    def set_rank(self, league: str, team: str, rank: int):
        """设置某队排名"""
        league_key = LEAGUE_ALIASES.get(league, league)
        if league_key not in self._data["ranks"]:
            self._data["ranks"][league_key] = {}
        self._data["ranks"][league_key][team] = rank

    def set_ranks_from_text(self, text: str):
        """从粘贴的排名文本解析（格式：联赛名、队伍名 排名）"""
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue
            name, val = parts[1], parts[2]
            for league_key in ["英超", "德甲", "西甲", "意甲", "法甲", "日职", "韩职", "澳超", "中超"]:
                if league_key in name:
                    break

    def apply_to_matches(self, matches: list) -> list:
        """给V11 Match列表批量补全排名"""
        from v11_analyzer_v2 import Match as V11Match
        count = 0
        for m in matches:
            hr = self.get(m.league, m.home_team)
            ar = self.get(m.league, m.away_team)
            if hr is not None:
                m.home_rank = hr
                count += 1
            if ar is not None:
                m.away_rank = ar
                count += 1
        return matches


if __name__ == "__main__":
    rp = RankProvider()
    print(f"RankProvider loaded, last_updated={rp._data.get('last_updated')}")
    for league, teams in rp._data["ranks"].items():
        total = len(teams)
        sample = list(teams.items())[:3]
        print(f"  {league}: {total} teams, e.g. {sample}")
    print(f"拜仁德甲排名: {rp.get('德甲', '拜仁')}")
    print(f"仁川联韩职排名: {rp.get('韩职', '仁川联')}")
