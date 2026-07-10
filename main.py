from orchestrator import run
 # 假设你暴露了 client 实例

if __name__ == "__main__":
    user_input = "周末北京去上海两天，预算3000"
    result = run(user_input)
    print("\n===== 最终结果 =====")
    print(result)
    # 显式关闭，避免退出时报错

