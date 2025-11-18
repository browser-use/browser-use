#!/bin/bash
# Brev Launchable Setup Script
# Sets up NVIDIA Nemotron Nano 12B v2 VL with vLLM for browser-use
set -e

echo "=================================================="
echo "🚀 Setting up NVIDIA Nemotron + browser-use demo"
echo "=================================================="

# Update system
echo "📦 Updating system packages..."
sudo apt-get update -qq

# Install Python 3.11 if needed
echo "🐍 Setting up Python environment..."
if ! command -v python3.11 &> /dev/null; then
    sudo add-apt-repository ppa:deadsnakes/ppa -y
    sudo apt-get update -qq
    sudo apt-get install -y python3.11 python3.11-venv python3.11-dev
fi

# Create virtual environment
echo "📁 Creating virtual environment..."
python3.11 -m venv /home/ubuntu/venv
source /home/ubuntu/venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install vLLM
echo "⚡ Installing vLLM..."
pip install vllm

# Install browser-use and dependencies
echo "🌐 Installing browser-use..."
pip install browser-use playwright
playwright install chromium
playwright install-deps chromium

# Create example script
echo "📝 Creating example script..."
cat > /home/ubuntu/test_nemotron.py << 'EOF'
"""
Test browser-use with local Nemotron Nano 12B v2 VL
"""
import asyncio
from browser_use import Agent
from browser_use.llm.openai.chat import ChatOpenAI

async def main():
    print("🤖 Testing browser-use with local Nemotron model...")

    # Connect to local vLLM server
    llm = ChatOpenAI(
        model="nvidia/nemotron-nano-12b-v2-vl",
        base_url="http://localhost:8000/v1",
        api_key="dummy",  # vLLM doesn't need real API key
        temperature=0.7,
        max_tokens=1024,
    )

    agent = Agent(
        task="Go to github.com and find the browser-use repository stars count",
        llm=llm,
    )

    result = await agent.run()
    print("\n" + "="*80)
    print("Result:", result)
    print("="*80)

if __name__ == "__main__":
    asyncio.run(main())
EOF

# Create vLLM startup script
echo "🔧 Creating vLLM startup script..."
cat > /home/ubuntu/start_vllm.sh << 'EOF'
#!/bin/bash
# Start vLLM server with Nemotron Nano 12B v2 VL
source /home/ubuntu/venv/bin/activate

echo "🚀 Starting vLLM server with Nemotron Nano 12B v2 VL..."
echo "📍 Model: nvidia/nemotron-nano-12b-v2-vl"
echo "🌐 API: http://localhost:8000/v1"
echo ""

vllm serve nvidia/nemotron-nano-12b-v2-vl \
    --port 8000 \
    --gpu-memory-utilization 0.9 \
    --max-model-len 8192 \
    --trust-remote-code
EOF

chmod +x /home/ubuntu/start_vllm.sh

# Create systemd service for vLLM (optional - runs on boot)
echo "⚙️  Creating vLLM systemd service..."
sudo tee /etc/systemd/system/vllm.service > /dev/null << EOF
[Unit]
Description=vLLM Inference Server - Nemotron Nano 12B v2 VL
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu
ExecStart=/home/ubuntu/start_vllm.sh
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create README
echo "📄 Creating README..."
cat > /home/ubuntu/README.md << 'EOF'
# NVIDIA Nemotron + browser-use Demo

This Launchable runs a fully self-hosted browser automation demo using:
- **Model**: NVIDIA Nemotron Nano 12B v2 VL (with vision support)
- **Inference**: vLLM (OpenAI-compatible API)
- **Framework**: browser-use

## Quick Start

### 1. Start vLLM Server (if not already running)

```bash
source /home/ubuntu/venv/bin/activate
./start_vllm.sh
```

Wait 2-3 minutes for the model to load. You'll see:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 2. Run the Example

In a new terminal:

```bash
source /home/ubuntu/venv/bin/activate
python test_nemotron.py
```

### 3. Check vLLM API

```bash
curl http://localhost:8000/v1/models
```

## Architecture

```
┌─────────────────────────────────┐
│  This Brev GPU Instance         │
│                                 │
│  ┌──────────────────────────┐  │
│  │ vLLM Server :8000        │  │
│  │ - Nemotron Nano 12B VL   │  │
│  └──────────────────────────┘  │
│            ↓ localhost          │
│  ┌──────────────────────────┐  │
│  │ browser-use Agent        │  │
│  └──────────────────────────┘  │
└─────────────────────────────────┘
```

## Run vLLM as System Service (Auto-start)

To make vLLM start automatically on boot:

```bash
sudo systemctl enable vllm
sudo systemctl start vllm

# Check status
sudo systemctl status vllm

# View logs
sudo journalctl -u vllm -f
```

## GPU Requirements

- **Minimum**: A100 40GB
- **Recommended**: A100 80GB or H100
- **VRAM**: ~24GB for the model

## Custom Tasks

Edit `test_nemotron.py` and change the task:

```python
agent = Agent(
    task="Your custom task here",
    llm=llm,
)
```

## Troubleshooting

**vLLM not starting:**
```bash
# Check GPU
nvidia-smi

# Check logs
sudo journalctl -u vllm -n 50
```

**Out of memory:**
- Reduce `--gpu-memory-utilization` to 0.8 or 0.7
- Reduce `--max-model-len` to 4096

**Connection refused:**
- Wait 2-3 minutes for model to load
- Check vLLM is running: `ps aux | grep vllm`
EOF

echo ""
echo "=================================================="
echo "✅ Setup complete!"
echo "=================================================="
echo ""
echo "📝 Next steps:"
echo "  1. Start vLLM server:"
echo "     source /home/ubuntu/venv/bin/activate"
echo "     ./start_vllm.sh"
echo ""
echo "  2. Wait 2-3 minutes for model to load"
echo ""
echo "  3. Run example (in new terminal):"
echo "     source /home/ubuntu/venv/bin/activate"
echo "     python test_nemotron.py"
echo ""
echo "📖 See README.md for more details"
echo "=================================================="
