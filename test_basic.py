"""
Basic connectivity tests - run this before starting development
Usage: python test_basic.py
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()


def test_env():
    print("=== 1. 检查环境变量 ===")
    required = ["SECONDME_CLIENT_ID", "SECONDME_CLIENT_SECRET", "KIMI_API_KEY"]
    optional = [
        "CANDIDATE_A_TOKEN", "CANDIDATE_B_TOKEN", "CANDIDATE_C_TOKEN",
        "AGENT_CODE_TOKEN", "AGENT_CONTENT_TOKEN", "AGENT_DATA_TOKEN",
    ]

    all_ok = True
    for key in required:
        val = os.getenv(key)
        if val:
            print(f"  ✅ {key}: {val[:8]}...")
        else:
            print(f"  ❌ {key}: 未设置")
            all_ok = False

    for key in optional:
        val = os.getenv(key)
        if val and not val.startswith("lba_at_candidate") and not val.startswith("lba_at_agent"):
            print(f"  ✅ {key}: {val[:12]}...")
        else:
            print(f"  ⚠️  {key}: 未设置（演示候选人账号需要今晚配置）")

    return all_ok


def test_kimi():
    print("\n=== 2. 测试 Kimi LLM 连接 ===")
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.getenv("KIMI_API_KEY"),
            base_url=os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1"),
        )
        resp = client.chat.completions.create(
            model=os.getenv("KIMI_MODEL", "moonshot-v1-8k"),
            messages=[{"role": "user", "content": "回复'OK'两个字"}],
            max_tokens=10,
        )
        print(f"  ✅ Kimi 连接成功：{resp.choices[0].message.content}")
        return True
    except Exception as e:
        print(f"  ❌ Kimi 连接失败：{e}")
        return False


def test_secondme_token(token_name: str):
    token = os.getenv(token_name)
    if not token or token.startswith("lba_at_candidate") or token.startswith("lba_at_agent"):
        print(f"  ⚠️  {token_name}: 跳过（使用占位符）")
        return None

    try:
        from secondme_client import SecondMeClient
        client = SecondMeClient(token)
        info = client.get_user_info()
        print(f"  ✅ {token_name}: 连接成功，用户名 = {info.get('name', '未知')}")
        return True
    except Exception as e:
        print(f"  ❌ {token_name}: 连接失败 - {e}")
        return False


def test_secondme():
    print("\n=== 3. 测试 Second Me 账号 ===")
    tokens = [
        "CANDIDATE_A_TOKEN", "CANDIDATE_B_TOKEN", "CANDIDATE_C_TOKEN",
        "AGENT_CODE_TOKEN",
    ]
    for t in tokens:
        test_secondme_token(t)


def test_requirement_agent():
    print("\n=== 4. 测试需求分析 Agent ===")
    try:
        from agents import RequirementAnalysisAgent
        agent = RequirementAnalysisAgent()
        response = agent.start("我需要一个网站")
        print(f"  ✅ Agent 响应（前100字）：{response[:100]}...")
        return True
    except Exception as e:
        print(f"  ❌ 需求分析 Agent 失败：{e}")
        return False


def test_task_decomposition():
    print("\n=== 5. 测试任务拆解 ===")
    try:
        from agents import decompose_tasks
        requirement = {
            "project_name": "官网博客",
            "core_description": "需要写5篇SEO文章",
            "tasks_hint": ["文案撰写"],
            "duration": "one-time",
            "team_context": "没有内容团队",
            "budget_hint": "low",
        }
        result = decompose_tasks(requirement)
        tasks = result.get("tasks", [])
        print(f"  ✅ 拆解出 {len(tasks)} 个任务：{[t['name'] for t in tasks]}")
        return True
    except Exception as e:
        print(f"  ❌ 任务拆解失败：{e}")
        return False


if __name__ == "__main__":
    print("HireNet 基础测试\n")

    env_ok = test_env()
    if not env_ok:
        print("\n⚠️  请先配置必要的环境变量再继续")
        sys.exit(1)

    kimi_ok = test_kimi()
    if not kimi_ok:
        print("\n❌ LLM 连接失败，后续测试跳过")
        sys.exit(1)

    test_secondme()
    test_requirement_agent()
    test_task_decomposition()

    print("\n=== 测试完成 ===")
    print("如果 LLM 测试通过，可以运行 python app.py 启动服务")
    print("Second Me 账号需要今晚配置完成才能使用完整功能")
