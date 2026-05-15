# -*- coding: utf-8 -*-
"""
V11 MCP Server — Cherry Studio MCP 桥接
让Cherry Studio里的AI可以调用V11 Pipeline的工具

MCP Stdio 协议：
- 标准输入接收 JSON-RPC 请求
- 标准输出返回 JSON-RPC 响应
- 每行一个完整的 JSON 对象

暴露的工具：
1. run_pipeline — 跑V11全自动流水线
2. get_odds_cache — 查赔率缓存
3. get_rankings — 查联赛排名
4. analyze_raw — 直接分析原始数据
5. get_status — 流水线状态
6. get_last_result — 最近一次Pipeline结果
"""
import sys
import json
import os
import traceback

# 确保路径
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def run_pipeline(params: dict = None) -> dict:
    """跑V11全自动流水线"""
    from run_pipeline import main as pipeline_main
    # 捕获输出
    from io import StringIO
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        pipeline_main()
        output = sys.stdout.getvalue()
        return {"success": True, "output": output[:8000], "truncated": len(output) > 8000}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        sys.stdout = old_stdout


def get_odds_cache(params: dict = None) -> dict:
    """查赔率缓存 (可选参数 date: YYYY-MM-DD)"""
    from v11_odds_cache import OddsCache
    cache = OddsCache()
    data = cache.load_cache()
    if not data:
        return {"has_cache": False, "matches": 0, "detail": "无缓存"}
    
    summary = {}
    for mid, info in data.items():
        summary[mid] = {
            "league": info.get("league", ""),
            "home": info.get("home_team", ""),
            "away": info.get("away_team", ""),
            "direction": info.get("direction", ""),
            "confidence": info.get("confidence", 0),
        }
    return {"has_cache": True, "matches": len(summary), "detail": summary}


def get_rankings(params: dict = None) -> dict:
    """查联赛排名 (可选参数 league_name 筛选联赛)"""
    from v11_rankings import RankProvider
    rp = RankProvider()
    all_data = rp.all_rankings
    if params and "league_name" in params:
        league = params["league_name"]
        filtered = {k: v for k, v in all_data.items() if league.lower() in k.lower()}
        if filtered:
            return {"leagues": list(filtered.keys()), "data": filtered}
        return {"leagues": [], "data": {}, "msg": f"未找到联赛: {league}"}
    return {"leagues": list(all_data.keys()), "count": len(all_data)}


def analyze_raw(params: dict) -> dict:
    """直接分析原始数据 (必须传 raw_data)
    raw_data 格式: 与500网抓取格式一致的列表"""
    from v11_analyzer_v2 import V11Analyzer, Match, AvgOdds, Prediction
    raw = params.get("raw_data", [])
    if not raw:
        return {"success": False, "error": "需要 raw_data 参数"}
    
    matches = []
    for r in raw:
        matches.append(Match(
            match_id=r.get("match_id", "X000"),
            league=r.get("league", ""),
            home_team=r.get("home_team", ""),
            away_team=r.get("away_team", ""),
            home_rank=r.get("home_rank"),
            away_rank=r.get("away_rank"),
            handicap=r.get("handicap", 0),
            odds_win=r.get("odds_win", 0),
            odds_draw=r.get("odds_draw", 0),
            odds_loss=r.get("odds_loss", 0),
            avg_odds=AvgOdds(
                r.get("avg_win", 0),
                r.get("avg_draw", 0),
                r.get("avg_loss", 0),
            ) if r.get("avg_win") else None,
        ))
    
    analyzer = V11Analyzer()
    results = analyzer.analyze_matches(matches)
    strategies = analyzer.build_strategies(results)
    
    output = []
    for p in results:
        output.append({
            "match_id": p.match_id,
            "league": p.league,
            "direction": p.direction,
            "label": p.label,
            "min_odd": p.min_odd,
            "confidence": p.confidence,
            "vote_info": p.vote_info,
            "rank_note": p.rank_note,
        })
    
    return {"success": True, "predictions": output, "strategies": strategies}


def get_last_result(params: dict = None) -> dict:
    """查最近一次Pipeline结果 (读日志)"""
    results_dir = os.path.join(os.path.dirname(__file__), "_results")
    if not os.path.isdir(results_dir):
        return {"has_result": False, "msg": "无历史结果"}
    files = sorted([f for f in os.listdir(results_dir) if f.endswith(".json")], reverse=True)
    if not files:
        return {"has_result": False, "msg": "无历史结果"}
    latest = os.path.join(results_dir, files[0])
    with open(latest, "r", encoding="utf-8") as f:
        return {"has_result": True, "file": files[0], "data": json.load(f)}


TOOLS = {
    "run_pipeline": {
        "fn": run_pipeline,
        "description": "跑V11全自动流水线（500网抓取→排名→Pipeline→MC模拟→输出）",
        "params": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "get_odds_cache": {
        "fn": get_odds_cache,
        "description": "查赔率缓存数据，获取今日比赛的趋势对比信息",
        "params": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "日期 (YYYY-MM-DD 格式)，留空查最新",
                }
            },
        },
    },
    "get_rankings": {
        "fn": get_rankings,
        "description": "查联赛排名数据，支持按联赛名称搜索",
        "params": {
            "type": "object",
            "properties": {
                "league_name": {
                    "type": "string",
                    "description": "联赛名称关键词 (如 英超/德甲/意甲/西甲/法甲/中超/日职/韩职)",
                }
            },
        },
    },
    "analyze_raw": {
        "fn": analyze_raw,
        "description": "直接分析原始比赛数据，返回预测结果+串关方案",
        "params": {
            "type": "object",
            "properties": {
                "raw_data": {
                    "type": "array",
                    "description": "比赛数据列表，每项含 match_id, league, home_team, away_team, handicap, odds_win, odds_draw, odds_loss, 可选 home_rank/away_rank/avg_win/avg_draw/avg_loss",
                    "items": {"type": "object"},
                }
            },
            "required": ["raw_data"],
        },
    },
    "get_last_result": {
        "fn": get_last_result,
        "description": "查最近一次Pipeline运行的结果",
        "params": {
            "type": "object",
            "properties": {},
        },
    },
    "get_status": {
        "fn": lambda p: {
            "available_tools": list(TOOLS.keys()),
            "version": "v2.0 MCP",
            "data_provider": "500彩票网",
            "pipeline_steps": 9,
            "mc_simulations": 5000,
            "last_run": None,
        },
        "description": "查V11 MCP Server状态和可用工具",
        "params": {
            "type": "object",
            "properties": {},
        },
    },
}


def handle_request(request: dict) -> dict:
    """处理MCP JSON-RPC请求"""
    req_id = request.get("id", 0)
    method = request.get("method", "")
    
    # MCP 协议: tools/list
    if method == "tools/list":
        result = []
        for name, info in TOOLS.items():
            result.append({
                "name": name,
                "description": info["description"],
                "inputSchema": info["params"],
            })
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": result}}
    
    # MCP 协议: tools/call
    if method == "tools/call":
        tool_name = request.get("params", {}).get("name", "")
        tool_args = request.get("params", {}).get("arguments", {})
        
        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"未知工具: {tool_name}"},
            }
        
        try:
            result = TOOLS[tool_name]["fn"](tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]},
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(e), "data": traceback.format_exc()},
            }
    
    # MCP 协议: list_tools (兼容旧格式)
    if method == "list_tools":
        return handle_request({"id": req_id, "method": "tools/list"})
    
    # MCP 协议: call_tool (兼容旧格式)
    if method == "call_tool":
        return handle_request({
            "id": req_id,
            "method": "tools/call",
            "params": request.get("params", {}),
        })
    
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"未知方法: {method}"}}


def main():
    """主循环：从stdin读请求，写stdout响应"""
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    # 发送初始化消息
    init_msg = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "params": {},
    }
    main_loop = True
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError:
            error_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"JSON解析错误: {line[:100]}"},
            }
            sys.stdout.write(json.dumps(error_resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            break


if __name__ == "__main__":
    main()
