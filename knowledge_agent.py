"""
KnowledgeAgent — LLM Tool-Calling 编排器（方案A）
使用 DeepSeek function calling 自主决定调用高德/途牛 API。
最大 3 轮 tool-calling，输出与 PlannerAgent 对齐的结构化数据。
API 失败直接返回 error 标记，不降级。
"""
import json
import os
import urllib.request
import urllib.parse
from openai import OpenAI

from state import AgentContext, AgentResult

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================
# 配置
# ============================================================
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL")
AMAP_KEY = os.environ.get("AMAP_API_KEY")
TUNIU_KEY = os.environ.get("TUNIU_API_KEY")

MAX_ROUNDS = 5
TIMEOUT = 15

# 途牛 MCP 端点
TUNIU_ENDPOINTS = {
    "hotel":  "https://openapi.tuniu.cn/mcp/hotel",
    "flight": "https://openapi.tuniu.cn/mcp/flight",
    "ticket": "https://openapi.tuniu.cn/mcp/ticket",
}

# ============================================================
# 工具白名单
# ============================================================
ALLOWED_TOOLS = {
    "amap_geocode",
    "tuniu_hotel_search",
    "tuniu_flight_search",
    "tuniu_ticket_search",
}

# ============================================================
# 工具 Schema（OpenAI function calling 格式）
# ============================================================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "amap_geocode",
            "description": "高德地图地理编码：将地址转换为经纬度坐标。调用时机：需要获取目的地或景点的地理位置坐标时。",
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {
                        "type": "string",
                        "description": "要查询的地址，如'上海'、'北京市朝阳区'、'外滩'",
                    }
                },
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tuniu_hotel_search",
            "description": "途牛酒店价格查询：搜索指定城市的酒店及每晚价格。调用时机：用户需要住宿信息时。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名，如'上海'"},
                    "checkIn": {"type": "string", "description": "入住日期 YYYY-MM-DD"},
                    "checkOut": {"type": "string", "description": "离店日期 YYYY-MM-DD"},
                },
                "required": ["city", "checkIn", "checkOut"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tuniu_flight_search",
            "description": "途牛航班价格查询：搜索两地之间最低票价（含高铁）。调用时机：用户需要城际交通信息时。",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_city": {"type": "string", "description": "出发城市"},
                    "to_city": {"type": "string", "description": "到达城市"},
                    "date": {"type": "string", "description": "出发日期 YYYY-MM-DD"},
                },
                "required": ["from_city", "to_city", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tuniu_ticket_search",
            "description": "途牛景区门票查询：搜索景点门票价格。调用时机：用户需要景区门票信息时。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenic": {"type": "string", "description": "景点名称，如'故宫'、'外滩'"},
                    "city": {"type": "string", "description": "所在城市，如'上海'"},
                },
                "required": ["scenic", "city"],
            },
        },
    },
]

# ============================================================
# System Prompt
# ============================================================
SYSTEM_PROMPT = """你是一个旅行数据查询 Agent。你可以调用工具获取真实的地理位置、酒店、航班、门票数据。

## 工作流程
1. 先调用 amap_geocode 获取目的地坐标
2. 根据需要调用 tuniu_hotel_search / tuniu_flight_search / tuniu_ticket_search 获取价格
3. 所有工具调用完成后，汇总为统一 JSON 输出

## 最终输出 Schema
{
  "destination": {
    "city": "城市名",
    "coordinates": {"lat": 纬度, "lng": 经度},
    "address": "详细地址"
  },
  "transportation": [
    {
      "type": "flight",
      "from": "出发城市",
      "to": "到达城市",
      "date": "YYYY-MM-DD",
      "price_range": {"low": 最低价, "median": 中位价, "high": 最高价},
      "currency": "CNY"
    }
  ],
  "hotels": [
    {
      "name": "酒店名",
      "price_per_night": 每晚价格,
      "rating": 评分,
      "city": "城市"
    }
  ],
  "attractions": [
    {
      "name": "景点名",
      "ticket_price": 门票价格,
      "city": "城市"
    }
  ],
  "meals": {
    "price_per_person": {"low": 最低, "median": 中位, "high": 最高},
    "currency": "CNY",
    "note": "基于目的地消费水平的估算"
  }
}

## 铁律
- 先查询后输出，禁止编造任何数字
- 今天的日期是2026年7月15日，调用工具的日期都在2026年7月15日之后
- 工具调用失败时，对应字段标记 {"error": "失败原因"}
- 最终输出只包含一行纯 JSON，无 markdown 标记、无解释文字
- meals 数据基于酒店和门票价格水平合理估算"""


# ============================================================
# 工具执行器
# ============================================================

def _exec_amap_geocode(address: str) -> dict:
    """高德地理编码：地址 → 经纬度。"""
    if not AMAP_KEY:
        return {"error": "AMAP_API_KEY 未配置"}

    params = urllib.parse.urlencode({
        "key": AMAP_KEY,
        "address": address,
        "output": "JSON",
    })
    url = f"https://restapi.amap.com/v3/geocode/geo?{params}"

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        data = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read())
    except Exception as e:
        return {"error": f"高德 API 请求失败: {e}"}

    geocodes = data.get("geocodes", [])
    if not geocodes or data.get("status") != "1":
        return {"error": f"未找到地址: {address}"}

    best = geocodes[0]
    location = best.get("location", "0,0")
    lng_str, lat_str = location.split(",")
    return {
        "lat": float(lat_str),
        "lng": float(lng_str),
        "display_name": best.get("formatted_address", address),
        "adcode": best.get("adcode"),
    }


def _tuniu_mcp_call(endpoint_name: str, tool_name: str, arguments: dict) -> dict:
    """途牛 MCP JSON-RPC 2.0 调用。"""
    if not TUNIU_KEY:
        return {"error": "TUNIU_API_KEY 未配置"}

    endpoint = TUNIU_ENDPOINTS[endpoint_name]
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": 1,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "apiKey": TUNIU_KEY,
            },
            method="POST",
        )
        body = urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8")
    except Exception as e:
        return {"error": f"途牛 {endpoint_name} API 请求失败: {e}"}

    # 解析响应（SSE 或纯 JSON）
    data = None
    if "data:" in body:
        for line in body.split("\n"):
            if line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    pass
    if data is None:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return {"error": f"途牛响应解析失败", "raw": body[:300]}

    if "error" in (data or {}):
        err = data["error"]
        return {"error": f"途牛 JSON-RPC 错误: {err.get('message', str(err))}"}

    result = data.get("result")
    if result is None:
        return {"error": "途牛返回空结果"}

    # MCP 响应可能包装在 content 数组中
    if isinstance(result, dict) and "content" in result:
        for block in result["content"]:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                try:
                    return json.loads(text) if isinstance(text, str) else text
                except (json.JSONDecodeError, TypeError):
                    pass
    return result


def _exec_tuniu_hotel_search(city: str, checkIn: str, checkOut: str) -> dict:
    """途牛酒店价格查询。"""
    return _tuniu_mcp_call("hotel", "tuniuHotelSearch", {
        "cityName": city,
        "checkIn": checkIn,
        "checkOut": checkOut,
    })


def _exec_tuniu_flight_search(from_city: str, to_city: str, date: str) -> dict:
    """途牛航班价格查询。"""
    return _tuniu_mcp_call("flight", "searchLowestPriceFlight", {
        "departureCityName": from_city,
        "arrivalCityName": to_city,
        "departureDate": date,
    })


def _exec_tuniu_ticket_search(scenic: str, city: str) -> dict:
    """途牛景区门票查询。"""
    return _tuniu_mcp_call("ticket", "query_cheapest_tickets", {
        "scenic_name": scenic,
        "cityName": city,
    })


# 工具执行器注册表
TOOL_EXECUTORS = {
    "amap_geocode": _exec_amap_geocode,
    "tuniu_hotel_search": _exec_tuniu_hotel_search,
    "tuniu_flight_search": _exec_tuniu_flight_search,
    "tuniu_ticket_search": _exec_tuniu_ticket_search,
}


# ============================================================
# 主入口
# ============================================================

def _sanitize_json(raw: str) -> str:
    """从 LLM 输出中提取纯 JSON。"""
    raw = raw.strip()
    import re
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]
    return raw


def run(context: AgentContext) -> AgentResult:
    """接收 AgentContext（upstream_data = planner 输出的 plan），返回结构化知识数据。

    使用 DeepSeek function calling 自主编排高德 + 途牛 API 调用，
    最大 3 轮 tool-calling，超限强制输出当前结果。
    """
    if not DEEPSEEK_KEY:
        return AgentResult(
            agent="knowledge",
            data={},
            success=False,
            error="DEEPSEEK_API_KEY 未配置",
        )

    # 从 context 构造 LLM 输入：用户需求 + planner 行程
    input_text = f"用户需求: {context.user_input}\n\nPlanner 行程方案:\n{json.dumps(context.upstream_data, ensure_ascii=False, indent=2)}"

    client = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": input_text},
    ]

    for round_num in range(1, MAX_ROUNDS + 1):
        is_final_round = (round_num == MAX_ROUNDS)

        if is_final_round:
            # 最后一轮：禁止再调用工具，强制输出最终 JSON
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                max_tokens=4096,
                messages=messages,
                tool_choice="none",
            )
        else:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                max_tokens=4096,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )

        msg = resp.choices[0].message

        # LLM 返回了 tool_calls → 执行工具并进入下一轮
        if msg.tool_calls and not is_final_round:
            print(round_num)
            # 将 LLM 的 tool_call 消息加入对话
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                print(tc)
                tool_name = tc.function.name

                # --- 工具白名单校验 ---
                if tool_name not in ALLOWED_TOOLS:
                    tool_result = {"error": f"禁止调用未注册工具: {tool_name}"}
                else:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_result = {"error": f"工具参数 JSON 解析失败: {tc.function.arguments[:200]}"}
                    else:
                        executor = TOOL_EXECUTORS[tool_name]
                        try:
                            tool_result = executor(**args)
                        except TypeError as e:
                            tool_result = {"error": f"工具参数不匹配: {e}"}
                        except Exception as e:
                            tool_result = {"error": f"工具执行异常: {e}"}

                # 将工具结果加入对话
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })
                # print(tool_result)
            continue  # 进入下一轮

        # LLM 返回了文本（最终输出）
        content = msg.content or ""
        if not content.strip():
            return AgentResult(
                agent="knowledge",
                data={},
                success=False,
                error="LLM 未返回任何内容",
            )

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            sanitized = _sanitize_json(content)
            try:
                parsed = json.loads(sanitized)
            except json.JSONDecodeError:
                return AgentResult(
                    agent="knowledge",
                    data={},
                    success=False,
                    error=f"最终输出 JSON 解析失败: {content[:200]}",
                )

        return AgentResult(agent="knowledge", data=parsed)

    return AgentResult(
        agent="knowledge",
        data={},
        success=False,
        error="超过最大轮数未获得有效输出",
    )
