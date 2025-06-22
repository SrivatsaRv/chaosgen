"""
Slack Bot Integration

Provides Slack integration for the chaos engineering agent,
including slash commands and interactive messages.
"""

import os
import json
import requests
from typing import Dict, List, Any, Optional
import structlog

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = structlog.get_logger()


class SlackBot:
    """
    Slack bot for chaos engineering agent integration.
    
    Features:
    - Slash command handling
    - Interactive message responses
    - Real-time status updates
    - Report sharing
    """
    
    def __init__(self, token: str = None, signing_secret: str = None):
        self.token = token or os.getenv('SLACK_BOT_TOKEN')
        self.signing_secret = signing_secret or os.getenv('SLACK_SIGNING_SECRET')
        self.client = WebClient(token=self.token) if self.token else None
        
        logger.info("Slack bot initialized", has_token=bool(self.token))
    
    def post_experiment_suggestions(self, experiments: List[Dict[str, Any]], 
                                  channel: str = None) -> bool:
        """
        Post experiment suggestions to Slack with interactive buttons.
        
        Args:
            experiments: List of experiment specifications
            channel: Target Slack channel
            
        Returns:
            True if posted successfully
        """
        if not self.client:
            logger.warning("Slack client not initialized")
            return False
        
        try:
            channel = channel or os.getenv('SLACK_CHANNEL', '#sre-chaos')
            
            # Create message blocks
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🤖 Chaos Experiment Suggestions"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Generated {len(experiments)} chaos experiments for your infrastructure:"
                    }
                }
            ]
            
            # Add experiment details
            for i, experiment in enumerate(experiments):
                title = experiment.get('title', 'Unknown')
                description = experiment.get('description', 'No description')
                action = experiment.get('action', 'unknown')
                risk_level = experiment.get('risk_level', 'medium')
                
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{i+1}. {title}*\n{description}\n• Action: `{action}` • Risk: {risk_level}"
                    }
                })
            
            # Add action buttons
            actions = []
            for i, experiment in enumerate(experiments):
                actions.append({
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": f"Run #{i+1}"
                    },
                    "value": f"run_{i}",
                    "action_id": f"run_experiment_{i}"
                })
            
            blocks.append({
                "type": "actions",
                "elements": actions
            })
            
            # Post message
            response = self.client.chat_postMessage(
                channel=channel,
                blocks=blocks,
                text="Chaos experiment suggestions available"
            )
            
            logger.info("Posted experiment suggestions to Slack", 
                       channel=channel, 
                       experiment_count=len(experiments))
            return True
            
        except SlackApiError as e:
            logger.error("Failed to post to Slack", error=str(e))
            return False
    
    def post_experiment_status(self, run_id: str, status: str, spec: Dict[str, Any],
                             metrics: Optional[Dict[str, float]] = None,
                             channel: str = None) -> bool:
        """
        Post experiment status update to Slack.
        
        Args:
            run_id: Experiment run ID
            status: Current status
            spec: Experiment specification
            metrics: Optional current metrics
            channel: Target Slack channel
            
        Returns:
            True if posted successfully
        """
        if not self.client:
            return False
        
        try:
            channel = channel or os.getenv('SLACK_CHANNEL', '#sre-chaos')
            title = spec.get('title', 'Unknown Experiment')
            
            # Determine color and emoji based on status
            status_config = {
                'running': {'color': '#ffa500', 'emoji': '🔄'},
                'completed': {'color': '#36a64f', 'emoji': '✅'},
                'aborted': {'color': '#ff0000', 'emoji': '🛑'},
                'failed': {'color': '#ff0000', 'emoji': '❌'}
            }
            
            config = status_config.get(status, {'color': '#808080', 'emoji': '❓'})
            
            # Create message
            text = f"{config['emoji']} *{title}* - {status.upper()}\n"
            text += f"Run ID: `{run_id}`\n"
            
            if metrics:
                error_rate = metrics.get('error_rate', 0) * 100
                latency = metrics.get('latency_p95', 0) * 1000
                text += f"Error Rate: {error_rate:.1f}% | Latency: {latency:.0f}ms\n"
            
            # Post message
            response = self.client.chat_postMessage(
                channel=channel,
                text=text,
                unfurl_links=False
            )
            
            logger.info("Posted status update to Slack", run_id=run_id, status=status)
            return True
            
        except SlackApiError as e:
            logger.error("Failed to post status to Slack", error=str(e))
            return False
    
    def post_report_link(self, run_id: str, report_path: str, spec: Dict[str, Any],
                        summary: str = None, channel: str = None) -> bool:
        """
        Post report link to Slack.
        
        Args:
            run_id: Experiment run ID
            report_path: Path to the report file
            spec: Experiment specification
            summary: Optional summary text
            channel: Target Slack channel
            
        Returns:
            True if posted successfully
        """
        if not self.client:
            return False
        
        try:
            channel = channel or os.getenv('SLACK_CHANNEL', '#sre-chaos')
            title = spec.get('title', 'Unknown Experiment')
            
            # Create message
            text = f"📊 *RCA Report Ready: {title}*\n"
            text += f"Run ID: `{run_id}`\n"
            
            if summary:
                text += f"\n{summary}\n"
            
            text += f"\n📄 <{report_path}|View Full Report>"
            
            # Post message
            response = self.client.chat_postMessage(
                channel=channel,
                text=text,
                unfurl_links=False
            )
            
            logger.info("Posted report link to Slack", run_id=run_id, report_path=report_path)
            return True
            
        except SlackApiError as e:
            logger.error("Failed to post report link to Slack", error=str(e))
            return False
    
    def send_direct_message(self, user_id: str, message: str) -> bool:
        """
        Send a direct message to a user.
        
        Args:
            user_id: Slack user ID
            message: Message text
            
        Returns:
            True if sent successfully
        """
        if not self.client:
            return False
        
        try:
            response = self.client.chat_postMessage(
                channel=user_id,
                text=message
            )
            
            logger.info("Sent DM to user", user_id=user_id)
            return True
            
        except SlackApiError as e:
            logger.error("Failed to send DM", user_id=user_id, error=str(e))
            return False


# Convenience functions for external use
def post_experiment_suggestions(experiments: List[Dict[str, Any]], 
                               channel: str = None) -> bool:
    """Post experiment suggestions to Slack"""
    bot = SlackBot()
    return bot.post_experiment_suggestions(experiments, channel)


def post_experiment_status(run_id: str, status: str, spec: Dict[str, Any],
                          metrics: Optional[Dict[str, float]] = None,
                          channel: str = None) -> bool:
    """Post experiment status to Slack"""
    bot = SlackBot()
    return bot.post_experiment_status(run_id, status, spec, metrics, channel)


def post_report_link(run_id: str, report_path: str, spec: Dict[str, Any],
                    summary: str = None, channel: str = None) -> bool:
    """Post report link to Slack"""
    bot = SlackBot()
    return bot.post_report_link(run_id, report_path, spec, summary, channel) 