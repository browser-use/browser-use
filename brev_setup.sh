#!/bin/bash
# Brev Launchable Setup Script
# NVIDIA Nemotron Nano 12B v2 VL + browser-use
set -e

# Detect Brev user
detect_brev_user() {
    if [ -n "$SUDO_USER" ]; then
        echo "$SUDO_USER"
    elif [ -f /home/ubuntu/.brev/lifecycle.log ]; then
        echo "ubuntu"
    elif [ -f /home/nvidia/.brev/lifecycle.log ]; then
        echo "nvidia"
    elif [ -d /home/ubuntu ]; then
        echo "ubuntu"
    elif [ -d /home/nvidia ]; then
        echo "nvidia"
    else
        echo "ubuntu"
    fi
}

USER=$(detect_brev_user)
HOME="/home/$USER"
export USER HOME

echo "=================================================="
echo "🚀 NVIDIA Nemotron + browser-use Setup"
echo "=================================================="
echo "👤 User: $USER"
echo "🏠 Home: $HOME"
echo ""

# Update system
echo "📦 Updating packages..."
apt-get update -qq

# Install vLLM
echo "⚡ Installing vLLM..."
pip install --quiet vllm

# Install browser-use
echo "🌐 Installing browser-use..."
pip install --quiet browser-use playwright
su - $USER -c "playwright install chromium"
su - $USER -c "playwright install-deps chromium"

# Create examples directory
EXAMPLES_DIR="$HOME/nemotron-browser-use"
mkdir -p "$EXAMPLES_DIR"

# Create test script
cat > "$EXAMPLES_DIR/test_browser.py" << 'EOF'
"""
Test browser-use with local Nemotron Nano 12B v2 VL
"""
import asyncio
from browser_use import Agent
from browser_use.llm.openai.chat import ChatOpenAI

async def main():
    print("🤖 Testing browser-use with Nemotron...")

    llm = ChatOpenAI(
        model="nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL-BF16",
        base_url="http://localhost:8000/v1",
        api_key="dummy",
        temperature=0.7,
    )

    agent = Agent(
        task="Go to github.com/browser-use/browser-use and find the star count",
        llm=llm,
    )

    result = await agent.run()
    print("\n" + "="*80)
    print("✅ Result:", result)
    print("="*80)

if __name__ == "__main__":
    asyncio.run(main())
EOF

# Create vLLM starter script
cat > "$EXAMPLES_DIR/start_vllm.sh" << 'EOF'
#!/bin/bash
echo "🚀 Starting vLLM server..."
echo "📍 Model: nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL-BF16"
echo "🌐 API: http://localhost:8000/v1"
echo ""
echo "⏳ This will take 2-3 minutes to load the model..."
echo ""

vllm serve nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL-BF16 \
    --port 8000 \
    --gpu-memory-utilization 0.9 \
    --max-model-len 8192 \
    --trust-remote-code
EOF

chmod +x "$EXAMPLES_DIR/start_vllm.sh"

# Create README
cat > "$EXAMPLES_DIR/README.md" << 'EOF'
# NVIDIA Nemotron + browser-use Demo

Fully self-hosted browser automation using NVIDIA Nemotron Nano 12B v2 VL.

## Quick Start

### 1. Start vLLM Server

```bash
cd ~/nemotron-browser-use
./start_vllm.sh
```

Wait 2-3 minutes for the model to load. You'll see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 2. Test Browser Automation

In a new terminal:

```bash
cd ~/nemotron-browser-use
python test_browser.py
```

### 3. Verify API

```bash
curl http://localhost:8000/v1/models
```

## Architecture

```
┌──────────────────────────┐
│  vLLM :8000              │
│  ↓ localhost             │
│  browser-use Agent       │
└──────────────────────────┘
```

## Custom Tasks

Edit `test_browser.py` and change the task:

```python
agent = Agent(
    task="Your custom task here",
    llm=llm,
)
```

## Requirements

- GPU: A100 80GB (recommended) or A100 40GB (tight fit)
- VRAM: ~24GB for BF16 model
- Model: NVIDIA-Nemotron-Nano-12B-v2-VL-BF16 (full precision)
EOF

# Set ownership
chown -R $USER:$USER "$EXAMPLES_DIR"

echo ""
echo "=================================================="
echo "✅ Setup complete!"
echo "=================================================="
echo ""
echo "📁 Examples: $EXAMPLES_DIR"
echo ""
echo "🚀 Quick start:"
echo "   cd $EXAMPLES_DIR"
echo "   ./start_vllm.sh"
echo ""
echo "⏳ Wait 2-3 min for model to load, then in new terminal:"
echo "   python test_browser.py"
echo ""
echo "📖 See README.md for details"
echo "=================================================="
