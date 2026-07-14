"""AWS-backed adapters for tailwag-memory."""

from .slack_state import SlackDynamoDBPollStateStore

__all__ = ["SlackDynamoDBPollStateStore"]
