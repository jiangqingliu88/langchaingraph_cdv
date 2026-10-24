# src/regression_framework/plugins/examples/dingtalk_notifier.py
"""
钉钉机器人通知插件示例
使用方法：
  1. 将此文件复制到 plugins/ 目录
  2. 在 YAML 中配置：
     notifications:
       dingtalk:
         webhook: "https://oapi.dingtalk.com/robot/send?access_token=xxx"
         secret: "xxx"  # 可选，加签安全设置
"""
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
from ..base import NotifierPlugin
from ...core.logging_config import get_logger

logger = get_logger(__name__)

class DingTalkNotifier(NotifierPlugin):
    plugin_name = "dingtalk"
    plugin_description = "Send regression report to DingTalk"
    
    def __init__(self):
        self.webhook = None
        self.secret = None
    
    def initialize(self, config: dict) -> bool:
        self.webhook = config.get('webhook')
        self.secret = config.get('secret')
        return bool(self.webhook)
    
    def notify(self, summary: dict, report_url: str, report_data: dict):
        if not self.webhook:
            return
        
        # 构建钉钉消息（Markdown格式）
        status_emoji = "✅" if summary['pass_rate'] >= 95 else "⚠️" if summary['pass_rate'] >= 80 else "❌"
        content = f"""### {status_emoji} 回归报告
| 指标 | 数值 |
|------|------|
| 总数 | {summary['total']} |
| 通过率 | {summary['pass_rate']:.1f}% |
| ✅ Pass | {summary['pass']} |
| ❌ Fail | {summary['fail']} |
| ❓ Unknown | {summary['unknown']} |
"""
        if report_url:
            content += f"\n[查看完整报告]({report_url})"
        
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": "回归报告",
                "text": content
            }
        }
        
        # 处理加签（如果有）
        webhook_url = self.webhook
        if self.secret:
            timestamp = str(round(time.time() * 1000))
            sign = base64.b64encode(
                hmac.new(
                    self.secret.encode('utf-8'),
                    f"{timestamp}\n{self.secret}".encode('utf-8'),
                    hashlib.sha256
                ).digest()
            ).decode('utf-8')
            webhook_url = f"{self.webhook}&timestamp={timestamp}&sign={urllib.parse.quote(sign)}"
        
        try:
            response = requests.post(webhook_url, json=message, timeout=10)
            if response.status_code == 200:
                logger.info("DingTalk notification sent successfully")
            else:
                logger.warning(f"DingTalk notification failed: {response.text}")
        except Exception as e:
            logger.error(f"DingTalk notification error: {e}")