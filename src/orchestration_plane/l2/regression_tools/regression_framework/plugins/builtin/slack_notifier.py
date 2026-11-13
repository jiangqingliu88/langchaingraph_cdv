# src/regression_framework/plugins/builtin/slack_notifier.py
import requests
from ..base import NotifierPlugin
from ...core.logging_config import get_logger

logger = get_logger(__name__)

class SlackNotifier(NotifierPlugin):
    plugin_name = "slack"
    plugin_description = "Send regression report to Slack"
    
    def __init__(self):
        self.webhook_url = None
        self.channel = None
    
    def initialize(self, config: dict) -> bool:
        """从配置初始化"""
        self.webhook_url = config.get('webhook')
        self.channel = config.get('channel')
        if not self.webhook_url:
            logger.warning("Slack webhook URL not configured")
            return False
        return True
    
    def notify(self, summary: dict, report_url: str, report_data: dict):
        """发送Slack通知"""
        if not self.webhook_url:
            logger.warning("Slack webhook not configured, skipping")
            return
        
        # 构建消息
        status_emoji = "✅" if summary['pass_rate'] >= 95 else "⚠️" if summary['pass_rate'] >= 80 else "❌"
        message = {
            "text": f"{status_emoji} Regression Report",
            "attachments": [
                {
                    "color": "good" if summary['pass_rate'] >= 95 else "warning" if summary['pass_rate'] >= 80 else "danger",
                    "fields": [
                        {"title": "Total", "value": str(summary['total']), "short": True},
                        {"title": "Pass Rate", "value": f"{summary['pass_rate']:.1f}%", "short": True},
                        {"title": "Pass", "value": str(summary['pass']), "short": True},
                        {"title": "Fail", "value": str(summary['fail']), "short": True},
                        {"title": "Unknown", "value": str(summary['unknown']), "short": True},
                    ],
                    "footer": "Regression Framework",
                    "footer_icon": "https://www.slack.com/favicon.ico",
                    "ts": __import__('time').time()
                }
            ]
        }
        
        # 如果有报告URL，添加链接
        if report_url:
            message["attachments"][0]["title"] = "View Full Report"
            message["attachments"][0]["title_link"] = report_url
        
        try:
            response = requests.post(self.webhook_url, json=message, timeout=10)
            if response.status_code == 200:
                logger.info("Slack notification sent successfully")
            else:
                logger.warning(f"Slack notification failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Slack notification error: {e}")