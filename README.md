# nanobot-webbridge-plugin

🎉 **WebBridge channel plugin for [nanobot](https://github.com/ramonpaolo/nanobot)** — Enables a beautiful web chat interface for your AI agent!

This plugin adds a WebSocket server to nanobot that accepts connections from [agent-webbridge](https://github.com/ramonpaolo/webbridge-agent), providing a universal web frontend.

---

## Architecture

```
┌─────────────────────┐          ┌─────────────────────┐          ┌─────────────────────┐
│   agent-webbridge  │◄────────►│   nanobot (with     │◄────────►│   AI Agent (LLM)    │
│   (Web Frontend)   │  wss    │   webbridge plugin) │  json    │                     │
│   port 8080        │          │   port 18791       │          │                     │
└─────────────────────┘          └─────────────────────┘          └─────────────────────┘
         │                                                                              │
         │  User's Browser                                                             │
         └──────────────────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

- **nanobot** installed and running
- **Python 3.10+**
- **agent-webbridge** frontend (see [agent-webbridge](https://github.com/ramonpaolo/webbridge-agent))

---

## Installation

### 1. Install the plugin

```bash
# Using pip
pip install nanobot-webbridge-plugin

# Or from source
git clone https://github.com/ramonpaolo/nanobot-webbridge-plugin.git
cd nanobot-webbridge-plugin
pip install -e .
```

### 2. Configure nanobot

Edit your `~/.nanobot/config.json`:

```json
{
  "channels": {
    "webbridge": {
      "enabled": true,
      "host": "0.0.0.0",
      "port": 18791,
      "hmac_secret": "",           // Optional: for message signatures
      "allowed_connections": [
        {
          "api_key": "sk_live_your_unique_api_key_here",
          "ip": null               // null = any IP, or "192.168.1.100" for specific IP
        }
      ]
    }
  }
}
```

### 3. Generate a secure API Key

```bash
# Generate a 32-character random key
openssl rand -hex 16

# Example output: 4a7b9c2e1f3d8h6i0jklmnopqrstuvwx
```

### 4. Restart nanobot

```bash
# If using systemd
systemctl --user restart nanobot

# If using PM2
pm2 restart nanobot

# If running directly
nanobot run
```

---

## Frontend Setup

Now set up the [agent-webbridge](https://github.com/ramonpaolo/webbridge-agent) frontend:

```bash
git clone https://github.com/ramonpaolo/webbridge-agent.git
cd webbridge-agent
cp .env.example .env
```

Edit `.env`:

```env
API_KEY=sk_live_your_unique_api_key_here    # Must match nanobot config
AGENT_WS_URL=ws://localhost:18791           # nanobot webbridge URL
HMAC_SECRET=                                # Leave empty if not using HMAC
AGENT_NAME=My Agent
```

Run:

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8080
```

Open **http://localhost:8080** in your browser.

---

## Security

### Security Layers

| Layer | Description |
|-------|-------------|
| **API Key** | Required for WebSocket handshake |
| **IP Whitelist** | Optional per-API-key IP restriction |
| **HMAC Signature** | Optional message integrity verification |

### IP Whitelist

Restrict access to specific IPs:

```json
"allowed_connections": [
  {
    "api_key": "sk_live_...",
    "ip": "192.168.1.100"    // Only this IP can use this key
  },
  {
    "api_key": "sk_live_...",
    "ip": null               // Any IP can use this key
  }
]
```

### HMAC Signatures (Optional)

For extra security, enable HMAC signatures:

1. Set the same `hmac_secret` in both nanobot config and agent-webbridge `.env`
2. Messages will include a signature verified by both sides

---

## Configuration Reference

### nanobot `config.json`

```json
{
  "channels": {
    "webbridge": {
      "enabled": true,                      // true to enable
      "host": "0.0.0.0",                   // Interface to bind
      "port": 18791,                        // WebSocket port
      "hmac_secret": "",                   // Optional HMAC secret
      "allowed_connections": [              // Required: at least one
        {
          "api_key": "sk_live_...",        // Your API key
          "ip": null                        // IP whitelist (null = any)
        }
      ]
    }
  }
}
```

### agent-webbridge `.env`

```env
API_KEY=sk_live_your_unique_api_key_here    # Required
AGENT_WS_URL=ws://localhost:18791           # Required
HMAC_SECRET=                                 # Optional
AGENT_NAME=My Agent                         # Optional
PORT=8080                                    # Optional
ALLOWED_ORIGINS=*                           # Optional
```

---

## Troubleshooting

### "Access denied" error

1. Verify `api_key` matches exactly in both configs
2. Check that `allowed_connections` is not empty
3. If using IP whitelist, verify your IP is allowed

### "Connection refused" error

1. Ensure nanobot is running with webbridge enabled
2. Check that `AGENT_WS_URL` in agent-webbridge `.env` is correct
3. Verify no firewall is blocking the ports

### Messages not being received

1. Check nanobot logs for message processing errors
2. Verify the agent is configured to respond on the webbridge channel

---

## Development

```bash
# Clone the repo
git clone https://github.com/ramonpaolo/nanobot-webbridge-plugin.git
cd nanobot-webbridge-plugin

# Install in development mode
pip install -e .

# Run tests
pytest tests/ -v
```

---

## License

MIT © [ramonpaolo](https://github.com/ramonpaolo)
