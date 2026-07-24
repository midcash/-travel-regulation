"""Agent Workflow Platform — 入口（Travel Workflow 示例）。"""
from src.application.orchestrator import run
from src.utils.logger import get_logger

logger = get_logger(__name__)

if __name__ == "__main__":
    # user_input = "周末北京去上海两天，预算3000"
    # user_input = "我想去一个暖和的海边城市玩三天，预算4000元，不想到处跑景点，只想放松。"
    # user_input = "下个月月初从成都去西安自驾游五天，预算8000元，带父母（三人），需要无障碍设施，偏好历史文化景点和当地小吃。"
    # user_input = "五一假期从广州去长沙玩三天，预算总共800元，能省则省，只要能逛吃就行。"
    user_input = "下周二到周四去深圳出差，其中周三下午和晚上有空闲，预算2000元用于个人休闲，喜欢科技和创意园区。"

    state = run(user_input)

    # ---- 输出行程 ----
    refined = state.refined_plan or state.plan or {}
    plan_days = refined.get("plan", {})
    plan_summary: list[dict] = []
    for day in sorted(plan_days.keys()):
        activities = [
            {
                "time": a.get("time", ""),
                "activity": a.get("activity", ""),
                "cost": a.get("cost", 0),
                "duration_min": a.get("duration_min", 0),
            }
            for a in plan_days[day]
        ]
        plan_summary.append({"day": day, "activities": activities})

    logger.info("final_plan", plan=plan_summary)

    # ---- 输出评审 ----
    review = state.review_result or {}
    qs = review.get("quality_scores", {})
    logger.info(
        "quality_scores",
        composite=qs.get("composite_score", "?"),
        verdict=qs.get("verdict", "?"),
        completeness=qs.get("completeness", {}).get("score", "?"),
        feasibility=qs.get("feasibility", {}).get("score", "?"),
        constraint_sat=qs.get("constraint_sat", {}).get("score", "?"),
        experience=qs.get("experience", {}).get("score", "?"),
        accuracy=qs.get("accuracy", {}).get("score", "?"),
    )
    logger.info(
        "budget_summary",
        total_cost=refined.get("total_cost", "?"),
        budget_remaining=refined.get("budget_remaining", "?"),
        retry_count=state.retry_count,
    )

    # ---- 输出问题 ----
    issues = review.get("issues", [])
    if issues:
        issues_summary = [
            {
                "severity": i.get("severity", "?"),
                "category": i.get("category", ""),
                "evidence": i.get("evidence", "")[:80],
            }
            for i in issues[:5]
        ]
        logger.info("issues_found", count=len(issues), issues=issues_summary)
