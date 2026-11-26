# MAX - Local AI Assistant

**MAX** is a personal AI assistant that runs **fully on your own computer**. You can talk to it by voice or type to it in a small floating window, and it can search the web, control apps and manage your calendar and email, using a local language model through **Ollama**.

## Features

- **Local LLM** through Ollama (default `qwen2.5:14b`, configurable with `MAX_MODEL`) with **tool calling**
- **Voice mode** with a wake word ("Max"): speech recognition with **faster-whisper** (CUDA when available) and a natural Portuguese voice with **Piper TTS**
- **Floating Tkinter window**, always on top, with the conversation history and a text box (voice and text work at the same time)
- **Tools the model can use**:
  - web search and reading web pages
  - weather and time
  - Spotify, YouTube and Google search
  - notes, clipboard and terminal
  - shell commands, with confirmation for dangerous ones
  - Google Calendar (list and create events) and Gmail (read and send emails)
- Works on **Windows, macOS and Linux**: system tools adapt to the OS
- Conversation history pruning and response validation to keep the model on track

## Tech

Python, Ollama, faster-whisper, Piper TTS, Tkinter, Google Calendar and Gmail APIs, threading

## Setup

1. Install [Ollama](https://ollama.com) and pull a model:
   ```
   ollama pull qwen2.5:14b
   ```
2. Install the Python packages:
   ```
   pip install -r requirements.txt
   ```
3. For voice, download the Piper voice `pt_PT-tugÃ£o-medium` (`.onnx` and `.onnx.json`) into this folder.
4. Optional, for Calendar and Gmail: create an OAuth client in Google Cloud and save it as `credentials.json` in this folder. The first run will ask you to sign in.
5. Run it:
   ```
   python max.py
   ```
   On Windows you can use `iniciar_max.bat`, which also starts Ollama if needed.

## Author

Rodrigo Costa ([@rodrigo2024134442](https://github.com/rodrigo2024134442)) - personal project