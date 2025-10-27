# Browser-Use ChatGPT Frontend

Interface web moderna estilo ChatGPT para controlar o browser-use através de comandos de texto e voz.

## 🎯 Features

- ✨ **Interface ChatGPT-style** - Design moderno e intuitivo
- 🎤 **Comandos de Voz** - Reconhecimento de fala via Web Speech API
- 📸 **Preview em Tempo Real** - Visualização de screenshots durante execução
- ⚡ **WebSocket Streaming** - Atualizações em tempo real de cada step
- 🎮 **Controles Interativos** - Pause, resume e stop do agente
- 📊 **Timeline de Ações** - Histórico completo expandível
- 🌙 **Dark Mode** - Tema escuro automático

## 🚀 Quick Start

### 1. Instalar Dependências do Backend

```bash
cd /workspaces/browser-use
pip install fastapi uvicorn websockets openai
```

### 2. Configurar Variáveis de Ambiente

Crie um arquivo `.env` na raiz do projeto:

```bash
# OpenAI (obrigatório para LLM e serviços de voz)
OPENAI_API_KEY=your_openai_api_key_here

# Opcional: Outros provedores LLM
ANTHROPIC_API_KEY=your_anthropic_key
GOOGLE_API_KEY=your_google_key
```

### 3. Iniciar Backend

```bash
cd examples/ui
python chatgpt_backend.py
```

O backend estará rodando em `http://localhost:8000`

### 4. Instalar Dependências do Frontend

```bash
cd examples/ui/chatgpt-frontend
npm install
```

### 5. Iniciar Frontend

```bash
npm run dev
```

O frontend estará rodando em `http://localhost:3000`

## 📖 Como Usar

### Via Texto

1. Digite sua tarefa no campo de input
2. Pressione Enter ou clique no botão enviar
3. Acompanhe a execução em tempo real no chat e no preview do browser

**Exemplos de tarefas:**

```
- Vá para google.com e pesquise por "automação web"
- Encontre o número de estrelas do repositório browser-use no GitHub
- Entre no site amazon.com e busque por "notebook"
- Extraia os títulos das notícias principais do g1.com
```

### Via Voz

1. Clique no ícone do microfone 🎤
2. Fale sua tarefa claramente
3. Clique novamente para parar a gravação
4. O texto será transcrito automaticamente e você pode enviá-lo

### Controles Durante Execução

- **⏸️ Pause** - Pausa a execução do agente
- **▶️ Resume** - Retoma a execução pausada
- **⏹️ Stop** - Para completamente a execução
- **🖥️ Toggle Preview** - Mostra/esconde o preview do browser

## 🏗️ Arquitetura

```
┌─────────────────────────────────────┐
│  Frontend (Next.js + React)         │
│  - Chat Interface                   │
│  - Voice Recognition (Web API)      │
│  - Browser Preview                  │
│  - Action Timeline                  │
└─────────────┬───────────────────────┘
              │ WebSocket + REST API
┌─────────────▼───────────────────────┐
│  Backend (FastAPI)                  │
│  - chatgpt_backend.py               │
│  - session_manager.py               │
│  - voice_services.py                │
└─────────────┬───────────────────────┘
              │ Agent Control
┌─────────────▼───────────────────────┐
│  Browser-Use Agent                  │
│  - Browser Automation               │
│  - LLM Integration                  │
│  - Screenshot Capture               │
└─────────────────────────────────────┘
```

## 🔧 Configuração Avançada

### Mudar Provedor LLM

Edite a requisição em `ChatInterface.tsx`:

```typescript
llm_provider: 'anthropic',  // openai, anthropic, google, groq
llm_model: 'claude-3-5-sonnet-20241022',
```

### Ajustar Número de Steps

```typescript
max_steps: 20,  // Padrão: 10
```

### Usar OpenAI Whisper para Transcrição

Se preferir usar a API do Whisper ao invés da Web Speech API nativa:

1. Desabilite o reconhecimento nativo no frontend
2. Grave áudio e envie para o endpoint `/api/voice/transcribe`
3. O backend processará via OpenAI Whisper

## 📁 Estrutura de Arquivos

```
examples/ui/
├── chatgpt_backend.py       # API FastAPI principal
├── session_manager.py        # Gerenciamento de sessões
├── voice_services.py         # Serviços STT/TTS
└── chatgpt-frontend/
    ├── app/
    │   ├── layout.tsx        # Layout principal
    │   ├── page.tsx          # Página home
    │   └── globals.css       # Estilos globais
    ├── components/
    │   ├── Sidebar.tsx       # Lista de conversas
    │   ├── ChatInterface.tsx # Interface principal
    │   ├── MessageBubble.tsx # Componente de mensagem
    │   ├── BrowserPreview.tsx# Preview do browser
    │   └── ActionTimeline.tsx# Timeline de ações
    ├── hooks/
    │   ├── useWebSocket.ts   # Hook WebSocket
    │   └── useSpeechRecognition.ts
    ├── package.json
    ├── tsconfig.json
    ├── tailwind.config.js
    └── next.config.js
```

## 🐛 Troubleshooting

### Backend não conecta

- Verifique se o backend está rodando: `curl http://localhost:8000`
- Confira as variáveis de ambiente no `.env`
- Veja os logs do terminal onde o backend está rodando

### WebSocket não conecta

- Certifique-se que CORS está configurado corretamente
- Verifique se a porta 8000 está liberada
- Confira o console do browser para erros

### Reconhecimento de voz não funciona

- Web Speech API só funciona em HTTPS ou localhost
- Alguns browsers não suportam (use Chrome/Edge)
- Verifique permissões de microfone no browser

### Screenshots não aparecem

- Verifique se o diretório `/tmp/browser-use-sessions/` existe
- Confira se o agente tem permissões de escrita
- Veja logs do backend para erros de captura

## 🚢 Deploy em Produção

### Backend

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar com Gunicorn
gunicorn chatgpt_backend:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Frontend

```bash
# Build de produção
npm run build

# Servir build
npm run start
```

### Docker (TODO)

```bash
docker-compose up
```

## 📝 Notas

- **Custos**: Cada execução consome tokens do LLM escolhido
- **Rate Limits**: Respeite os limites da API do provedor LLM
- **Segurança**: Não exponha suas API keys publicamente
- **Browser**: Chromium será baixado automaticamente pelo Playwright

## 🤝 Contribuindo

Contribuições são bem-vindas! Por favor:

1. Fork o repositório
2. Crie uma branch para sua feature
3. Commit suas mudanças
4. Push para a branch
5. Abra um Pull Request

## 📄 Licença

MIT License - veja LICENSE para detalhes

## 🙏 Agradecimentos

- Browser-Use team pelo framework incrível
- OpenAI pela API de LLM e Whisper
- Next.js e React pela base do frontend
- Tailwind CSS pelo sistema de design
