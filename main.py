from orchestrator import run
 # 假设你暴露了 client 实例

if __name__ == "__main__":
    # user_input = "周末北京去上海两天，预算3000"
    # user_input = "我想去一个暖和的海边城市玩三天，预算4000元，不想到处跑景点，只想放松。"
    # user_input = "下个月月初从成都去西安自驾游五天，预算8000元，带父母（三人），需要无障碍设施，偏好历史文化景点和当地小吃。"
    # user_input = "五一假期从广州去长沙玩三天，预算总共800元，能省则省，只要能逛吃就行。"
    user_input = "下周二到周四去深圳出差，其中周三下午和晚上有空闲，预算2000元用于个人休闲，喜欢科技和创意园区。"
    result = run(user_input)
    print("\n===== 最终结果 =====")
    print(result)
    # 显式关闭，避免退出时报错

