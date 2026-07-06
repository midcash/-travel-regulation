
"""风险识别工具 — stub 实现。

v1.0.0: 使用内置风险数据库，不接真实 API。
后续版本: 接入天气 API、外交部安全提醒、各国签证 API。

来源: spec/executor_spec.md §2.6
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

# ============================================================
# 内置风险数据库 (stub)
# ============================================================

_WEATHER_RISKS: Dict[str, Dict[str, Any]] = {
    "东京": {
        "typhoon_season": {"months": [7, 8, 9, 10], "risk": "high", "description": "台风季，可能影响航班和户外活动"},
        "hot_summer": {"months": [7, 8], "risk": "medium", "description": "高温湿热，体感温度可达 40°C+"},
        "cold_winter": {"months": [12, 1, 2], "risk": "low", "description": "冬季寒冷，平均 0-10°C"},
    },
    "Tokyo": {
        "typhoon_season": {"months": [7, 8, 9, 10], "risk": "high", "description": "台风季，可能影响航班和户外活动"},
        "hot_summer": {"months": [7, 8], "risk": "medium", "description": "高温湿热，体感温度可达 40°C+"},
        "cold_winter": {"months": [12, 1, 2], "risk": "low", "description": "冬季寒冷，平均 0-10°C"},
    },
    "曼谷": {
        "rainy_season": {"months": [5, 6, 7, 8, 9, 10], "risk": "medium", "description": "雨季，午后常有暴雨"},
        "hot_season": {"months": [3, 4, 5], "risk": "high", "description": "热季，气温可达 40°C"},
    },
    "Bangkok": {
        "rainy_season": {"months": [5, 6, 7, 8, 9, 10], "risk": "medium", "description": "雨季，午后常有暴雨"},
        "hot_season": {"months": [3, 4, 5], "risk": "high", "description": "热季，气温可达 40°C"},
    },
    "巴黎": {
        "cold_winter": {"months": [12, 1, 2], "risk": "low", "description": "冬季湿冷，平均 0-8°C"},
        "strike_risk": {"months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], "risk": "medium", "description": "法国罢工风险全年存在，可能影响交通"},
    },
    "Paris": {
        "cold_winter": {"months": [12, 1, 2], "risk": "low", "description": "冬季湿冷，平均 0-8°C"},
        "strike_risk": {"months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], "risk": "medium", "description": "法国罢工风险全年存在，可能影响交通"},
    },
    "马尔代夫": {
        "monsoon": {"months": [5, 6, 7, 8, 9, 10], "risk": "medium", "description": "西南季风，降雨增多"},
        "dry_season": {"months": [11, 12, 1, 2, 3, 4], "risk": "low", "description": "干季，最佳旅游时间"},
    },
    "Maldives": {
        "monsoon": {"months": [5, 6, 7, 8, 9, 10], "risk": "medium", "description": "西南季风，降雨增多"},
        "dry_season": {"months": [11, 12, 1, 2, 3, 4], "risk": "low", "description": "干季，最佳旅游时间"},
    },
}

_VISA_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "日本": {"visa_required": True, "passport_validity_months": 6, "processing_days": 7, "notes": "中国公民需签证，单次旅游签证有效期 90 天"},
    "Japan": {"visa_required": True, "passport_validity_months": 6, "processing_days": 7, "notes": "中国公民需签证，单次旅游签证有效期 90 天"},
    "泰国": {"visa_required": False, "passport_validity_months": 6, "processing_days": 0, "notes": "中国公民免签 30 天"},
    "Thailand": {"visa_required": False, "passport_validity_months": 6, "processing_days": 0, "notes": "中国公民免签 30 天"},
    "法国": {"visa_required": True, "passport_validity_months": 6, "processing_days": 15, "notes": "申根签证，需提前预约"},
    "France": {"visa_required": True, "passport_validity_months": 6, "processing_days": 15, "notes": "申根签证，需提前预约"},
    "韩国": {"visa_required": False, "passport_validity_months": 6, "processing_days": 0, "notes": "济州岛免签，其他地区需签证"},
    "South Korea": {"visa_required": False, "passport_validity_months": 6, "processing_days": 0, "notes": "济州岛免签，其他地区需签证"},
    "新加坡": {"visa_required": False, "passport_validity_months": 6, "processing_days": 0, "notes": "中国公民免签 30 天"},
    "Singapore": {"visa_required": False, "passport_validity_months": 6, "processing_days": 0, "notes": "中国公民免签 30 天"},
    "马来西亚": {"visa_required": False, "passport_validity_months": 6, "processing_days": 0, "notes": "中国公民免签 30 天"},
    "Malaysia": {"visa_required": False, "passport_validity_months": 6, "processing_days": 0, "notes": "中国公民免签 30 天"},
    "越南": {"visa_required": False, "passport_validity_months": 6, "processing_days": 0, "notes": "中国公民免签 15 天"},
    "Vietnam": {"visa_required": False, "passport_validity_months": 6, "processing_days": 0, "notes": "中国公民免签 15 天"},
}

_SAFETY_RISKS: Dict[str, List[Dict[str, Any]]] = {
    "巴黎": [
        {"type": "pickpocket", "severity": "medium", "description": "热门景点和地铁扒手较多，注意财物安全"},
        {"type": "scam", "severity": "low", "description": "街头签名骗局、假警察等，警惕主动搭讪者"},
    ],
    "Paris": [
        {"type": "pickpocket", "severity": "medium", "description": "热门景点和地铁扒手较多，注意财物安全"},
        {"type": "scam", "severity": "low", "description": "街头签名骗局、假警察等，警惕主动搭讪者"},
    ],
    "曼谷": [
        {"type": "scam", "severity": "medium", "description": "突突车/Taxi 宰客、珠宝骗局等"},
        {"type": "traffic", "severity": "medium", "description": "交通拥堵严重，摩托车事故多发"},
    ],
    "Bangkok": [
        {"type": "scam", "severity": "medium", "description": "突突车/Taxi 宰客、珠宝骗局等"},
        {"type": "traffic", "severity": "medium", "description": "交通拥堵严重，摩托车事故多发"},
    ],
    "罗马": [
        {"type": "pickpocket", "severity": "high", "description": "旅游区扒手猖獗，特别注意 Termini 火车站"},
    ],
    "Rome": [
        {"type": "pickpocket", "severity": "high", "description": "旅游区扒手猖獗，特别注意 Termini 火车站"},
    ],
}


def check_weather_risk(
    location: str,
    date_str: str,
) -> Dict[str, Any]:
    """检查目的地天气风险 (stub)。

    Args:
        location: 城市/国家名称
        date_str: 旅行日期 YYYY-MM-DD

    Returns:
        {risks: [{category, description, severity, mitigation}]}
    """
    risks: List[Dict[str, Any]] = []

    try:
        travel_date = date.fromisoformat(date_str)
        month = travel_date.month
    except (ValueError, TypeError):
        month = date.today().month

    # 查找目的地的天气风险
    # 先精确匹配，再部分匹配
    weather_info = _WEATHER_RISKS.get(location)
    if weather_info is None:
        for key in _WEATHER_RISKS:
            if key in location or location in key:
                weather_info = _WEATHER_RISKS[key]
                break

    if weather_info:
        for risk_name, risk_data in weather_info.items():
            if month in risk_data.get("months", []):
                severity = risk_data.get("risk", "low")
                mitigation_map = {
                    "typhoon_season": "购买旅行保险，关注天气预警，准备室内备选方案",
                    "hot_summer": "避开正午户外活动，备足饮用水，注意防晒",
                    "hot_season": "避开正午户外活动，选择有空调的场所",
                    "rainy_season": "携带雨具，安排室内备选景点",
                    "cold_winter": "携带保暖衣物，优先安排室内活动",
                    "monsoon": "关注天气预报，选择度假村内活动",
                    "strike_risk": "预留充足时间，关注当地交通公告",
                }
                risks.append({
                    "category": "weather",
                    "description": risk_data["description"],
                    "severity": severity,
                    "mitigation": mitigation_map.get(risk_name, "关注当地天气预警"),
                })

    return {
        "location": location,
        "month": month,
        "risks": risks,
        "source_type": "estimated",
        "notes": "stub 实现 — 使用内置风险数据库",
    }


def check_travel_requirements(
    nationality: str,
    destination: str,
) -> Dict[str, Any]:
    """检查旅行证件要求 (stub)。

    Args:
        nationality: 旅行者国籍
        destination: 目的地国家

    Returns:
        {visa_required, passport_validity_months, processing_days, notes, risks}
    """
    # 查找签证要求
    visa_info = _VISA_REQUIREMENTS.get(destination)
    if visa_info is None:
        for key in _VISA_REQUIREMENTS:
            if key in destination or destination in key:
                visa_info = _VISA_REQUIREMENTS[key]
                break

    if visa_info is None:
        visa_info = {
            "visa_required": True,
            "passport_validity_months": 6,
            "processing_days": 10,
            "notes": f"请自行核实 {destination} 的最新签证政策",
        }

    # 查找安全风险
    safety_risks = []
    safety_info = _SAFETY_RISKS.get(destination)
    if safety_info is None:
        for key in _SAFETY_RISKS:
            if key in destination or destination in key:
                safety_info = _SAFETY_RISKS[key]
                break

    if safety_info:
        safety_risks = safety_info

    return {
        "nationality": nationality,
        "destination": destination,
        "visa_required": visa_info["visa_required"],
        "passport_validity_months": visa_info["passport_validity_months"],
        "processing_days": visa_info["processing_days"],
        "notes": visa_info["notes"],
        "safety_risks": safety_risks,
        "source_type": "estimated",
        "disclaimer": "stub 实现 — 请以官方最新政策为准",
    }
