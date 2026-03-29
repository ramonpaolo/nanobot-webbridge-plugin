"""
nanobot-webbridge-plugin

WebBridge channel plugin for nanobot.
Provides a WebSocket server that accepts connections from agent-webbridge.
"""

from .webbridge import WebBridgeChannel, WebBridgeConfig, AllowedConnection

__all__ = ["WebBridgeChannel", "WebBridgeConfig", "AllowedConnection"]
