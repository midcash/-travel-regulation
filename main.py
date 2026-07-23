"""Agent Workflow Platform — 入口（Travel Workflow 示例）。"""
import json
from src.application.orchestrator import run

if __name__ == "__main__":
    # user_input = "周末北京去上海两天，预算3000"
    # user_input = "我想去一个暖和的海边城市玩三天，预算4000元，不想到处跑景点，只想放松。"
    # user_input = "下个月月初从成都去西安自驾游五天，预算8000元，带父母（三人），需要无障碍设施，偏好历史文化景点和当地小吃。"
    # user_input = "五一假期从广州去长沙玩三天，预算总共800元，能省则省，只要能逛吃就行。"
    user_input = "下周二到周四去深圳出差，其中周三下午和晚上有空闲，预算2000元用于个人休闲，喜欢科技和创意园区。"

    state = run(user_input)

    # ---- 输出行程 ----
    print("\n===== 行程方案 =====")
    refined = state.refined_plan or state.plan or {}
    plan_days = refined.get("plan", {})
    for day in sorted(plan_days.keys()):
        print(f"\n{day}:")
        for a in plan_days[day]:
            print(f"  {a.get('time','')}  {a.get('activity','')}  ￥{a.get('cost',0)}  ({a.get('duration_min',0)}min)")

    # ---- 输出评审 ----
    review = state.review_result or {}
    qs = review.get("quality_scores", {})
    print(f"\n===== 质量评分 =====")
    print(f"综合: {qs.get('composite_score', '?')}  ({qs.get('verdict', '?')})")
    print(f"完整性: {qs.get('completeness', {}).get('score', '?')}  可行性: {qs.get('feasibility', {}).get('score', '?')}  约束: {qs.get('constraint_sat', {}).get('score', '?')}  体验: {qs.get('experience', {}).get('score', '?')}  准确: {qs.get('accuracy', {}).get('score', '?')}")
    print(f"重试: {state.retry_count}次")
    print(f"Budget: ￥{refined.get('total_cost', '?')} / 剩余 ￥{refined.get('budget_remaining', '?')}")

    # ---- 输出问题 ----
    issues = review.get("issues", [])
    if issues:
        print(f"\n===== 问题 ({len(issues)}) =====")
        for i in issues[:5]:
            print(f"  [{i.get('severity','?')}] {i.get('category','')}: {i.get('evidence','')[:80]}")

