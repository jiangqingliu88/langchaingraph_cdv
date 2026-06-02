#!/bin/bash
# switch_llm.sh - 快速切换LLM提供商

set -e

echo "选择LLM提供商:"
echo "1) DeepSeek"
echo "2) OpenAI"
read -p "请输入选项 (1/2): " choice

case $choice in
    1)
        echo "切换到DeepSeek..."
        # 更新.env文件
        sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=deepseek/' .env
        sed -i 's/^LLM_MODEL=.*/LLM_MODEL=deepseek-chat/' .env
        sed -i 's|^LLM_BASE_URL=.*|LLM_BASE_URL=https://api.deepseek.com/v1|' .env
        echo "请确保LLM_API_KEY已设置为DeepSeek的API Key"
        ;;
    2)
        echo "切换到OpenAI..."
        sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=openai/' .env
        sed -i 's/^LLM_MODEL=.*/LLM_MODEL=gpt-4-turbo/' .env
        sed -i 's|^LLM_BASE_URL=.*|LLM_BASE_URL=|' .env
        echo "请确保LLM_API_KEY已设置为OpenAI的API Key"
        ;;
    *)
        echo "无效选项"
        exit 1
        ;;
esac

echo "切换完成! 运行 python scripts/test_deepseek.py 测试连接"