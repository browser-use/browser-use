# **User Interfaces of Browser-Use**

| **File Name**          | **User Interface** | **Description**                           | **Example Usage**                         |
|------------------------|-------------------|-------------------------------------------|-------------------------------------------|
| `command_line.py`      | **Terminal**      | Parses arguments for command-line execution. | `python command_line.py`                  |
| `gradio_demo.py`       | **Gradio**        | Provides a Gradio-based interactive UI.  | `python gradio_demo.py`                   |
| `streamlit_demo.py`    | **Streamlit**     | Runs a Streamlit-based web interface.    | `python -m streamlit run streamlit_demo.py` |
| `chatgpt_backend.py`   | **ChatGPT-Style** | FastAPI backend with WebSocket streaming | See below for full setup                  |

---

## 🚀 ChatGPT-Style Frontend (NEW!)

Frontend web moderno inspirado no ChatGPT para interagir com browser-use via texto e comandos de voz.

### Features

- ✨ Interface ChatGPT-style moderna
- 🎤 Reconhecimento de voz (Web Speech API)
- 📸 Preview do browser em tempo real
- ⚡ Streaming via WebSocket
- 🎮 Controles pause/resume/stop
- 📊 Timeline de ações expandível
- 🌙 Suporte a dark mode

### Quick Start

#### Backend

```bash
# Instalar dependências
pip install "browser-use[chatgpt-ui]"

# Configurar API keys
export OPENAI_API_KEY=your_key_here

# Iniciar backend
cd examples/ui
python chatgpt_backend.py
```

Backend: http://localhost:8000

#### Frontend

```bash
cd examples/ui/chatgpt-frontend

# Instalar e rodar
npm install
npm run dev
```

Frontend: http://localhost:3000

### Documentação Completa

Veja [chatgpt-frontend/README.md](chatgpt-frontend/README.md) para documentação detalhada, arquitetura, troubleshooting e exemplos de uso.

### Arquivos

```
examples/ui/
├── chatgpt_backend.py       # API FastAPI + WebSocket
├── session_manager.py        # Gerenciador de sessões
├── voice_services.py         # STT/TTS com OpenAI
└── chatgpt-frontend/         # Frontend Next.js
    ├── components/           # Componentes React
    ├── hooks/                # Custom hooks
    ├── app/                  # Pages Next.js
    └── README.md             # Docs completa
```

