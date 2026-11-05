"""
完整 ReAct 智能体 Demo（基于 DeepSeek）
新场景：查询某个城市的天气，然后判断是否适合户外运动。
已加强提示词，确保模型单步输出，真正实现多轮交互。
"""

import os
import json
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

def get_weather(city: str) -> str:
    weather_db = {
        "北京": "晴天，温度 28°C，微风",
        "上海": "小雨，温度 24°C，湿度较高",
        "广州": "雷阵雨，温度 32°C，风力较大"
    }
    return weather_db.get(city, "多云，温度 20°C，无持续风向")

def check_activity(weather_desc: str) -> str:
    if "雨" in weather_desc or "雷" in weather_desc:
        return "不适合户外运动，建议选择室内活动。"
    elif "晴天" in weather_desc or "多云" in weather_desc:
        return "天气不错，适合户外运动，注意防晒补水。"
    else:
        return "天气状况一般，可以进行轻度户外活动，但需留意天气变化。"

TOOLS_MAP = {
    "get_weather": get_weather,
    "check_activity": check_activity,
}

# 改进后的提示词
SYSTEM_PROMPT = """
你是一个生活助手，可以调用工具获取信息。你必须严格遵循以下规则：

1. 每次只输出 **一步** 的推理和一个行动。
2. 输出格式必须严格为：
   思考：<你这一步的推理>
   行动：<工具名(参数=值)>
   STOP
3. 绝对不能输出“观察：”或对工具结果的任何猜测。观察结果将由用户（系统）在下一轮提供给你。
4. 当你收集到足够信息时，最后一轮输出格式为：
   思考：<最终推理>
   回答：<给用户的最终答案>
   STOP

可用工具：
- get_weather(city) -> 返回指定城市的天气状况
- check_activity(weather) -> 根据天气描述返回是否适合户外运动
"""

def run_react_agent(user_query: str) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query}
    ]

    log = {
        "user_query": user_query,
        "turns": [],
        "final_answer": None
    }

    max_turns = 5
    for turn in range(max_turns):
        turn_record = {
            "turn_number": turn + 1,
            "input_messages": [dict(msg) for msg in messages],
            "model_output": None,
            "parsed_action": None,
            "observation": None
        }

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0,
            max_tokens=600
        )
        reply = response.choices[0].message.content

        # 如果模型多输出了，截断到 STOP 之前
        if "STOP" in reply:
            reply = reply.split("STOP")[0].strip()

        turn_record["model_output"] = reply
        messages.append({"role": "assistant", "content": reply})

        if "回答：" in reply:
            final_answer = reply.split("回答：")[-1].strip()
            log["final_answer"] = final_answer
            log["turns"].append(turn_record)
            break

        if "行动：" not in reply:
            log["turns"].append(turn_record)
            break

        action_lines = [line for line in reply.split("\n") if line.startswith("行动：")]
        if not action_lines:
            log["turns"].append(turn_record)
            break

        action_text = action_lines[0].replace("行动：", "").strip()
        turn_record["parsed_action"] = action_text

        if "(" in action_text and action_text.endswith(")"):
            tool_name = action_text.split("(")[0].strip()
            args_str = action_text[len(tool_name)+1:-1].strip()
            args = []
            if args_str:
                if "=" in args_str:
                    param_value = args_str.split("=", 1)[1].strip().strip('"').strip("'")
                    args.append(param_value)
                else:
                    args.append(args_str.strip().strip('"').strip("'"))

            if tool_name in TOOLS_MAP:
                func = TOOLS_MAP[tool_name]
                try:
                    if args:
                        result = func(*args)
                    else:
                        result = func()
                except Exception as e:
                    result = f"工具调用出错: {e}"
            else:
                result = f"工具 {tool_name} 不存在"
        else:
            result = "行动格式不正确，需要包含括号"

        observation = f"观察：{result}"
        turn_record["observation"] = observation
        messages.append({"role": "user", "content": observation})
        log["turns"].append(turn_record)

    return log

def save_log_and_summary(log: dict, filepath: str = "react_agent_log.json"):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f"✅ 运行日志已保存到: {filepath}\n")

    num_calls = len(log["turns"])
    print(f"📊 API 总共调用次数: {num_calls}")
    if log["final_answer"]:
        print(f"📌 最终答案: {log['final_answer']}\n")

    for turn in log["turns"]:
        t = turn["turn_number"]
        print(f"--- 第 {t} 次调用 ---")
        print(f"输入 messages (共 {len(turn['input_messages'])} 条):")
        for i, msg in enumerate(turn["input_messages"]):
            role = msg["role"]
            text = msg["content"].replace("\n", " ")[:120]
            print(f"  [{i}] {role}: {text}...")
        print(f"模型输出:\n  {turn['model_output']}")
        if turn.get("parsed_action"):
            print(f"解析动作: {turn['parsed_action']}")
        if turn.get("observation"):
            print(f"观察结果: {turn['observation']}")
        print()
    print("=" * 50)

if __name__ == "__main__":
    user_input = "北京今天适合户外运动吗？"
    log_data = run_react_agent(user_input)
    save_log_and_summary(log_data)