"""WebBridge channel for nanobot — universal web interface for agents."""

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from collections import OrderedDict
from typing import Any

from loguru import logger

from pydantic import BaseModel, Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base


class AllowedConnection(BaseModel):
    """A permitted API key and optional IP whitelist."""
    api_key: str
    ip: str | None = None  # None means accept any IP


class WebBridgeConfig(Base):
    """WebBridge channel configuration."""
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 18791
    allowed_connections: list[AllowedConnection] = Field(default_factory=list)
    hmac_secret: str = ""  # Shared secret for HMAC signatures
    streaming: bool = True  # Enable real streaming from LLM


class WebBridgeChannel(BaseChannel):
    """
    WebSocket server channel that accepts connections from agent-webbridge.
    
    Security layers:
    1. API Key validation in handshake
    2. Optional IP whitelisting per API Key
    3. HMAC signature verification on every message
    
    Streaming:
    - Real streaming from LLM via send_delta()
    - Each chunk sent immediately to WebSocket client
    - Supports stream_start, chunk, stream_end message types
    
    Configuration in nanobot config.json:
    
    {
      "channels": {
        "webbridge": {
          "enabled": true,
          "host": "0.0.0.0",
          "port": 18791,
          "streaming": true,
          "hmac_secret": "optional_hmac_secret",
          "allowed_connections": [
            {
              "api_key": "sk_live_your_api_key",
              "ip": "192.168.1.100"  // optional, null for any IP
            }
          ]
        }
      }
    }
    """

    name = "webbridge"
    display_name = "WebBridge"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WebBridgeConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebBridgeConfig.model_validate(config)
        super().__init__(config, bus)
        self._server = None
        self._connected_clients: dict[str, asyncio.Queue] = {}
        self._ws_connections: dict[str, Any] = {}
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        
        # Streaming state per chat
        self._stream_buffers: dict[str, str] = {}  # chat_id -> accumulated content
        self._stream_active: dict[str, bool] = {}  # chat_id -> is streaming

    def _find_connection(self, api_key: str, client_ip: str) -> AllowedConnection | None:
        """Find matching allowed connection."""
        for conn in self.config.allowed_connections:
            if conn.api_key != api_key:
                continue
            if conn.ip is not None and conn.ip != client_ip:
                logger.warning(
                    "WebBridge: IP mismatch for api_key. Expected {}, got {}",
                    conn.ip, client_ip
                )
                return None
            return conn
        return None

    def _verify_hmac(self, data: dict) -> bool:
        """Verify HMAC signature on a message."""
        if not self.config.hmac_secret:
            return True
        
        signature = data.get("signature", "")
        timestamp = data.get("timestamp", 0)
        content = data.get("content", "")
        sender_id = data.get("sender_id", "")
        
        if not signature or not timestamp:
            return False
        
        current_time = int(time.time())
        if abs(current_time - timestamp) > 300:
            logger.warning("WebBridge: Message timestamp too old or in future")
            return False
        
        message = f"{timestamp}:{sender_id}:{content}"
        expected = hmac.new(
            self.config.hmac_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return secrets.compare_digest(signature, expected)

    async def start(self) -> None:
        """Start the WebSocket server."""
        import websockets
        
        host = self.config.host
        port = self.config.port
        
        logger.info("Starting WebBridge server on {}:{}", host, port)
        
        self._running = True
        self._server = await websockets.serve(
            self._handle_ws_client,
            host,
            port,
            max_size=10 * 1024 * 1024  # 10MB max message
        )
        
        logger.info("WebBridge server started on ws://{}:{}", host, port)

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        self._running = False
        
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        
        self._connected_clients.clear()
        self._ws_connections.clear()
        self._stream_buffers.clear()
        self._stream_active.clear()
        logger.info("WebBridge server stopped")

    async def send_delta(self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None) -> None:
        """
        Deliver a streaming text chunk from the LLM.
        
        This is called by the agent loop for each content delta during streaming.
        We send it immediately to the WebSocket client.
        """
        meta = metadata or {}
        stream_id = meta.get("_stream_id", f"{chat_id}:0")
        
        # Get or create stream buffer
        if stream_id not in self._stream_buffers:
            self._stream_buffers[stream_id] = ""
            self._stream_active[stream_id] = True
            # Send stream_start
            if chat_id in self._ws_connections:
                try:
                    await self._ws_connections[chat_id].send(json.dumps({
                        "type": "stream_start",
                        "content": "",
                        "stream_id": stream_id,
                    }, ensure_ascii=False))
                except Exception as e:
                    logger.error("WebBridge: Error sending stream_start: {}", e)
        
        # Accumulate and send chunk
        self._stream_buffers[stream_id] += delta
        
        if chat_id in self._ws_connections:
            try:
                await self._ws_connections[chat_id].send(json.dumps({
                    "type": "chunk",
                    "content": delta,
                    "stream_id": stream_id,
                }, ensure_ascii=False))
            except Exception as e:
                logger.error("WebBridge: Error sending chunk: {}", e)
        
        # Check for stream end
        if meta.get("_stream_end"):
            self._stream_active[stream_id] = False
            
            # Send final message with complete content
            if chat_id in self._ws_connections:
                try:
                    full_content = self._stream_buffers.pop(stream_id, "")
                    await self._ws_connections[chat_id].send(json.dumps({
                        "type": "message",
                        "content": full_content,
                        "stream_id": stream_id,
                        "stream_end": True,
                    }, ensure_ascii=False))
                except Exception as e:
                    logger.error("WebBridge: Error sending stream_end: {}", e)
            else:
                self._stream_buffers.pop(stream_id, None)

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to a connected webbridge client."""
        api_key = msg.chat_id
        
        if api_key not in self._ws_connections:
            logger.warning("WebBridge: No connected client for api_key {}", api_key)
            return
        
        # If this is a streaming delta, use send_delta
        if msg.metadata.get("_stream_delta"):
            await self.send_delta(api_key, msg.content, msg.metadata)
            return
        
        # Regular message send (non-streaming or final message)
        try:
            payload = {
                "type": "message",
                "content": msg.content,
                "chat_id": msg.chat_id,
            }
            if msg.media:
                payload["media"] = msg.media
            if msg.reply_to:
                payload["reply_to"] = msg.reply_to
            
            ws = self._ws_connections[api_key]
            await ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            logger.error("WebBridge: Error sending message: {}", e)

    async def _handle_ws_client(self, websocket: Any) -> None:
        """Handle a new WebSocket client connection."""
        client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
        logger.info("WebBridge: New connection from {}", client_ip)
        
        api_key = None
        
        try:
            try:
                auth_data = await asyncio.wait_for(websocket.recv(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("WebBridge: Client {} did not send auth in time", client_ip)
                await websocket.close(4001, "Authentication timeout")
                return
            
            try:
                auth = json.loads(auth_data)
            except json.JSONDecodeError:
                logger.warning("WebBridge: Invalid auth JSON from {}", client_ip)
                await websocket.close(4002, "Invalid auth format")
                return
            
            if auth.get("type") != "auth":
                logger.warning("WebBridge: Expected auth message, got {}", auth.get("type"))
                await websocket.close(4003, "Expected auth message")
                return
            
            api_key = auth.get("api_key", "")
            connection = self._find_connection(api_key, client_ip)
            
            if not connection:
                await websocket.close(4001, "Unauthorized")
                logger.warning("WebBridge: Unauthorized connection attempt from {}", client_ip)
                return
            
            await websocket.send(json.dumps({"type": "auth_success"}))
            logger.info("WebBridge: Client authenticated: {}", api_key[:8] + "...")
            
            self._ws_connections[api_key] = websocket
            
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                    await self._handle_client_message(data, api_key)
                except json.JSONDecodeError:
                    logger.warning("WebBridge: Invalid JSON from client")
                    continue
                except Exception as e:
                    logger.error("WebBridge: Error handling client message: {}", e)
                    break
                    
        except Exception as e:
            logger.error("WebBridge: Client error: {}", e)
        finally:
            if api_key:
                self._ws_connections.pop(api_key, None)
                self._connected_clients.pop(api_key, None)
            logger.info("WebBridge: Client cleaned up: {}", api_key[:8] + "..." if api_key else "unknown")

    async def _handle_client_message(self, data: dict, api_key: str) -> None:
        """Handle an incoming message from a webbridge client."""
        msg_type = data.get("type")
        
        if msg_type == "message":
            content = data.get("content", "")
            sender_id = data.get("sender_id", api_key)
            media = data.get("media", [])
            metadata = data.get("metadata", {})
            message_id = data.get("id", "")
            
            # Deduplicate messages
            if message_id:
                if message_id in self._processed_message_ids:
                    return
                self._processed_message_ids[message_id] = None
                while len(self._processed_message_ids) > 1000:
                    self._processed_message_ids.popitem(last=False)
            
            if not self._verify_hmac(data):
                logger.warning("WebBridge: HMAC verification failed for {}", sender_id)
                return
            
            await self._handle_message(
                sender_id=sender_id,
                chat_id=api_key,
                content=content,
                media=media,
                metadata={
                    **metadata,
                    "client_ip": data.get("client_ip"),
                    "timestamp": data.get("timestamp"),
                }
            )
        
        elif msg_type == "ping":
            await self._ws_connections.get(api_key).send(json.dumps({"type": "pong"}))
        
        elif msg_type == "ack":
            message_id = data.get("message_id")
            logger.debug("WebBridge: Message {} acknowledged", message_id)

    def is_allowed(self, sender_id: str) -> bool:
        """Check if sender_id is permitted."""
        allow_list = self.config.allowed_connections
        if not allow_list:
            logger.warning("{}: allowed_connections is empty — all access denied", self.name)
            return False
        for conn in allow_list:
            if conn.api_key == sender_id:
                return True
        return False
