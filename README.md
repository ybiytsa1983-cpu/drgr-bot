# 🤖 drgr-bot + ⚡ Code VM

A Telegram bot with a built-in **AI-powered code editor** (Code VM) and **Android navigator PWA** — all runnable from a laptop in a few commands.

---

## ⚡ Quick Start — запуск с ноутбука

### Windows

```bat
REM 1. Clone the repo (once)
git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git
cd drgr-bot

REM 2. First-time setup (installs Python deps + shows Ollama instructions)
install.bat

REM 3. Launch the VM (every time)
vm.bat
```

Or **double-click** `vm.bat` in File Explorer — browser opens automatically.

### macOS / Linux

```bash
# 1. Clone the repo (once)
git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git
cd drgr-bot

# 2. First-time setup
chmod +x install.sh vm.sh
./install.sh

# 3. Launch the VM (every time)
./vm.sh
```

---

## 🖥 What opens in the browser

| URL | Description |
|-----|-------------|
| `http://localhost:5000/` | ⚡ Code VM — Monaco Editor with AI code generation |
| `http://localhost:5000/navigator/` | 🧭 DRGRNav — Android PWA Navigator (online + offline) |
| `http://localhost:5000/challenges` | 🚀 Hard challenge prompts (JSON) |

---

## 🤖 AI features (Ollama)

The VM uses **Ollama** for local AI code generation. Install it once:

| Platform | Install |
|----------|---------|
| Windows | Download from [ollama.com/download](https://ollama.com/download) and run installer |
| macOS | `brew install ollama` |
| Linux | `curl -fsSL https://ollama.com/install.sh \| sh` |

Then pull the preferred model (runs in background, ~5 GB):

```bash
ollama pull qwen3-vl:8b
ollama serve          # keep this running in a separate terminal
```

The VM auto-detects Ollama at `http://localhost:11434`. Override with:

```bash
OLLAMA_HOST=http://my-server:11434 ./vm.sh
```

---

## 🧭 DRGRNav — Android Navigator

Open `http://YOUR_LAPTOP_IP:5000/navigator/` in **Chrome on Android** → tap ⋮ → **Add to Home Screen** to install as a full-screen app.

Features:
- 🗺 Online: OpenStreetMap tiles, OSRM routing (car / bike / walk), Nominatim search
- 📴 Offline: Service Worker caches 2 000 tiles + 200 routes, IndexedDB saved routes
- 📍 GPS with accuracy circle, re-center button
- 🌑 Dark theme, Russian UI, touch-friendly

Find your laptop IP:

```bash
# Windows
ipconfig | findstr IPv4

# macOS / Linux
ip route get 1 | awk '{print $NF; exit}'
```

---

## 🚀 VM Features

| Feature | Shortcut |
|---------|---------|
| ⚡ Generate code with AI | Ctrl+G → type prompt → Code |
| 🌐 Generate full HTML page | Ctrl+G → HTML, or open HTML tab |
| ▶ Run code (Python / JS) | Ctrl+Enter |
| 🔍 Lint / static check | Ctrl+Shift+K |
| 🚀 Hard challenge tasks | Tasks tab |
| 💬 AI chat about code | AI tab |
| 📊 Stats & self-learning | Stats tab |

---

## 🗂 Project layout

```
drgr-bot/
├── vm/
│   ├── server.py          # Flask backend
│   ├── static/
│   │   └── index.html     # Monaco Editor UI
│   ├── start_vm.bat       # Windows double-click launcher
│   └── create_shortcut.ps1 # Create Windows Desktop shortcut
├── navigator/
│   ├── index.html         # Android PWA navigator
│   ├── sw.js              # Service Worker (offline caching)
│   └── manifest.json      # PWA manifest
├── vm.sh                  # Linux/macOS terminal launcher
├── vm.bat                 # Windows terminal launcher
├── install.sh             # First-time setup (Linux/macOS)
├── install.bat            # First-time setup (Windows)
└── requirements.txt
```

---

## 🛠 Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VM_PORT` | `5000` | Port for the Code VM server |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API base URL |
| `OLLAMA_TIMEOUT` | `120` | Seconds to wait for AI response |
| `OLLAMA_DEFAULT_MODEL` | *(auto)* | Override the default AI model |

---

## 📋 Requirements

- Python 3.8 or newer
- pip (comes with Python)
- Modern browser (Chrome, Edge, Firefox)
- Ollama (optional, for AI features)
