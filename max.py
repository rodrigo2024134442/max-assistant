"""
MAX - Assistente de IA local com Ollama (voz PIPER TTS + janela flutuante)
============================================================================
Podes falar com o MAX OU escrever-lhe, ao mesmo tempo. Há uma janela
flutuante (sempre por cima) com o histórico da conversa e uma caixa de
texto, e continua a funcionar por voz em segundo plano com wake word.

O MAX tem agora acesso à internet em tempo real (pesquisa + leitura de
páginas) e corre em Windows, macOS ou Linux — as ferramentas do sistema
(Spotify, terminal, comandos) adaptam-se automaticamente ao teu SO.

------------------------------------------------------------------------
INSTALAÇÃO
------------------------------------------------------------------------
1) Pacotes base:
    pip install ollama requests colorama pyperclip

2) Pacote de PESQUISA NA INTERNET:
    pip install ddgs

3) Pacotes de VOZ:
    pip install faster-whisper sounddevice numpy keyboard piper-tts

(tkinter já vem incluído no Python no Windows, não precisas instalar nada.
 No Linux pode ser preciso instalar o pacote 'python3-tk' via gestor de
 pacotes da distro.)
"""

import os
import platform
import subprocess
import webbrowser
import datetime
import json
import time
import re
import sys
import unicodedata
import difflib
import wave
import io
import queue
import threading
from urllib.parse import quote_plus

import requests
import ollama

import tkinter as tk
from tkinter import scrolledtext

try:
    from google_calendar import criar_evento_calendario, listar_eventos_calendario
    HAS_CALENDAR = True
except ImportError:
    HAS_CALENDAR = False

try:
    from google_email import listar_emails_recentes, enviar_email
    HAS_EMAIL = True
except ImportError:
    HAS_EMAIL = False


def _adicionar_dlls_nvidia_windows():
    if sys.platform != "win32":
        return
    for nome_pacote in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            modulo = __import__(nome_pacote, fromlist=["_"])
            pasta_base = list(modulo.__path__)[0]
            candidatos = [os.path.join(pasta_base, "bin"), pasta_base]
            for pasta_dll in candidatos:
                if os.path.isdir(pasta_dll) and any(
                    f.lower().endswith(".dll") for f in os.listdir(pasta_dll)
                ):
                    os.add_dll_directory(pasta_dll)
                    os.environ["PATH"] = pasta_dll + os.pathsep + os.environ.get("PATH", "")
        except Exception:
            pass


_adicionar_dlls_nvidia_windows()

# --- Dependências opcionais ---
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    C_USER = Fore.CYAN + Style.BRIGHT
    C_MAX = Fore.GREEN + Style.BRIGHT
    C_TOOL = Fore.YELLOW
    C_ERROR = Fore.RED + Style.BRIGHT
    C_RESET = Style.RESET_ALL
except ImportError:
    C_USER = C_MAX = C_TOOL = C_ERROR = C_RESET = ""

try:
    import pyperclip
    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False

try:
    import numpy as np
    import sounddevice as sd
    HAS_AUDIO_IO = True
except ImportError:
    HAS_AUDIO_IO = False

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    from piper.voice import PiperVoice
    HAS_TTS = True
except ImportError:
    HAS_TTS = False

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

try:
    from ddgs import DDGS  # pip install ddgs
    HAS_WEB_SEARCH = True
except ImportError:
    try:
        from duckduckgo_search import DDGS  # nome antigo do pacote, por compatibilidade
        HAS_WEB_SEARCH = True
    except ImportError:
        HAS_WEB_SEARCH = False

HAS_VOICE_INPUT = HAS_AUDIO_IO and HAS_WHISPER
HAS_VOICE_OUTPUT = HAS_TTS and HAS_AUDIO_IO

SISTEMA_OPERATIVO = platform.system()  # "Windows", "Darwin" (macOS) ou "Linux"


# ============================================================
# CONFIGURAÇÃO
# ============================================================
MODEL_NAME = os.environ.get("MAX_MODEL", "qwen2.5:14b")
MAX_HISTORY_MESSAGES = 30
LOG_CONVERSAS = True
LOG_PATH = "max_log.jsonl"

OLLAMA_OPTIONS = {
    "num_predict": 800,
    "temperature": 0.7,
    "repeat_penalty": 1.15,
    "top_p": 0.9,
    "top_k": 40,
}

WAKE_WORD_ENABLED = os.environ.get("MAX_WAKE_WORD", "true").lower() in ("1", "true", "sim")
WAKE_WORD_VARIANTS = ["max", "macs", "maxs", "maks"]

WHISPER_MODEL_SIZE = os.environ.get("MAX_WHISPER_SIZE", "medium")
WHISPER_DEVICE = os.environ.get("MAX_WHISPER_DEVICE", "auto")
WHISPER_LANGUAGE = "pt"
SAMPLE_RATE = 16000

SILENCE_THRESHOLD = 0.015
SILENCE_DURATION = 1.0
MIN_SPEECH_DURATION = 0.4

TTS_ENABLED = False  # desativa a síntese de voz se não quiseres ouvir o MAX a falar
PIPER_MODEL_PATH = "pt_PT-tugão-medium.onnx"
PIPER_CONFIG_PATH = "pt_PT-tugão-medium.onnx.json"

PALAVRAS_PERIGOSAS = [
    "del ", "rmdir", "rd ", "format", "shutdown", "diskpart",
    "reg delete", "taskkill", "netsh", "> nul",
    "rm -rf", "mkfs", "dd if=", ":(){ :|:& };:", "chmod -r 777 /",
]

# Filas de comunicação entre threads (voz / cérebro / GUI)
fila_entrada = queue.Queue()   # texto do utilizador (voz ou GUI) -> cérebro
fila_saida = queue.Queue()     # ("user"/"max"/"tool"/"erro"/"status", texto) -> GUI


def log(remetente: str, texto: str):
    """Escreve no terminal E manda para a fila da GUI."""
    cores = {"user": C_USER, "max": C_MAX, "tool": C_TOOL, "erro": C_ERROR, "sistema": C_TOOL}
    if remetente != "status":
        print(f"{cores.get(remetente, '')}{texto}{C_RESET}")
    fila_saida.put((remetente, texto))


# ============================================================
# FERRAMENTAS DISPONÍVEIS PARA O MODELO
# ============================================================

def abrir_youtube():
    webbrowser.open("https://www.youtube.com")
    return "YouTube aberto com sucesso."

def abrir_url(url: str):
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return f"O site {url} foi aberto."

def pesquisar_google(pesquisa: str):
    url = f"https://www.google.com/search?q={quote_plus(pesquisa)}"
    webbrowser.open(url)
    return f"A pesquisar '{pesquisa}' no Google."


def pesquisar_internet(pesquisa: str, num_resultados: int = 5):
    """Pesquisa na internet em tempo real e devolve um resumo dos resultados
    (título, pequeno resumo e link). Usa isto sempre que precisares de
    informação atual: notícias, preços, eventos recentes, factos que possam
    ter mudado desde os teus dados de treino, etc."""
    if not HAS_WEB_SEARCH:
        return "Pesquisa na internet indisponível (instala com: pip install ddgs)."
    try:
        resultados = list(DDGS().text(pesquisa, max_results=num_resultados))
        if not resultados:
            return f"Não encontrei resultados para '{pesquisa}'."
        linhas = []
        for r in resultados:
            titulo = (r.get("title") or "").strip()
            corpo = (r.get("body") or "").strip()
            url = (r.get("href") or "").strip()
            linhas.append(f"- {titulo}: {corpo} ({url})")
        return "Resultados da pesquisa:\n" + "\n".join(linhas)
    except Exception as e:
        return f"Erro ao pesquisar na internet: {e}"


def ler_pagina_web(url: str, limite_caracteres: int = 3000):
    """Vai a uma página web específica e devolve o texto principal dessa
    página, para o MAX poder ler, resumir ou responder a perguntas sobre
    o conteúdo atual de um site."""
    try:
        if not url.startswith("http"):
            url = "https://" + url
        resposta = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resposta.raise_for_status()
        texto = re.sub(r"<script.*?</script>|<style.*?</style>", "", resposta.text, flags=re.DOTALL | re.IGNORECASE)
        texto = re.sub(r"<[^>]+>", " ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        if not texto:
            return f"Não consegui extrair texto de {url}."
        return texto[:limite_caracteres]
    except Exception as e:
        return f"Erro ao aceder à página {url}: {e}"


def obter_tempo(cidade: str = "Lisboa"):
    try:
        res = requests.get(f"https://wttr.in/{cidade}?format=3", timeout=5)
        if res.status_code == 200:
            return f"Tempo em {cidade}: {res.text.strip()}"
        return "Não foi possível obter o estado do tempo."
    except Exception as e:
        return f"Erro ao procurar o tempo: {e}"

def obter_hora():
    agora = datetime.datetime.now()
    return agora.strftime("Agora são %H:%M de %d/%m/%Y.")

def copiar_para_clipboard(texto: str):
    if not HAS_CLIPBOARD:
        return "Ferramenta de clipboard indisponível (instala 'pyperclip')."
    pyperclip.copy(texto)
    return "Texto copiado para a área de transferência."

def criar_nota(nome_ficheiro: str, conteudo: str):
    pasta = os.path.join(os.path.expanduser("~"), "notas_max")
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, nome_ficheiro)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(conteudo)
    return f"Nota guardada em {caminho}"


def abrir_spotify():
    """Abre a aplicação Spotify, adaptando-se ao sistema operativo."""
    try:
        if SISTEMA_OPERATIVO == "Windows":
            os.startfile("spotify:")
        elif SISTEMA_OPERATIVO == "Darwin":
            subprocess.Popen(["open", "-a", "Spotify"])
        else:  # Linux e outros
            try:
                subprocess.Popen(["spotify"])
            except FileNotFoundError:
                subprocess.Popen(["xdg-open", "spotify:"])
        return "Spotify aberto."
    except Exception as e:
        return f"Erro ao abrir o Spotify: {e}"


def pesquisar_spotify(pesquisa: str):
    """Pesquisa algo no Spotify, adaptando-se ao sistema operativo."""
    uri = f"spotify:search:{quote_plus(pesquisa)}"
    try:
        if SISTEMA_OPERATIVO == "Windows":
            os.startfile(uri)
        elif SISTEMA_OPERATIVO == "Darwin":
            subprocess.Popen(["open", uri])
        else:
            subprocess.Popen(["xdg-open", uri])
        return f"A pesquisar '{pesquisa}' no Spotify."
    except Exception as e:
        return f"Erro ao pesquisar no Spotify: {e}"


def abrir_terminal():
    """Abre uma janela de terminal visível e independente, conforme o SO."""
    try:
        if SISTEMA_OPERATIVO == "Windows":
            subprocess.Popen("start cmd", shell=True)
        elif SISTEMA_OPERATIVO == "Darwin":
            subprocess.Popen(["open", "-a", "Terminal"])
        else:
            for emulador in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"):
                try:
                    subprocess.Popen([emulador])
                    break
                except FileNotFoundError:
                    continue
            else:
                return "Não encontrei nenhum emulador de terminal conhecido neste sistema."
        return "Terminal aberto."
    except Exception as e:
        return f"Erro ao abrir o terminal: {e}"


def executar_comando(comando: str):
    """Corre um comando na shell do sistema operativo atual (Windows, macOS
    ou Linux), mostra o output em tempo real no terminal/GUI e devolve-o."""
    if any(p in comando.lower() for p in PALAVRAS_PERIGOSAS):
        confirmacao = input(
            f"{C_ERROR}[MAX] O comando '{comando}' parece potencialmente "
            f"perigoso. Confirmas a execução? (sim/não): {C_RESET}"
        )
        if confirmacao.strip().lower() not in ("sim", "s", "yes", "y"):
            return "Execução cancelada pelo utilizador."

    encoding = "cp850" if SISTEMA_OPERATIVO == "Windows" else "utf-8"
    try:
        processo = subprocess.Popen(
            comando, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding=encoding, errors="replace", bufsize=1,
        )
        linhas = []
        for linha in processo.stdout:
            linha = linha.rstrip("\n")
            log("tool", f"  {linha}")
            linhas.append(linha)
        processo.wait(timeout=30)
        output = "\n".join(linhas).strip()
        return output if output else "Comando executado sem output."
    except subprocess.TimeoutExpired:
        processo.kill()
        return "O comando demorou demasiado tempo e foi interrompido."
    except Exception as e:
        return f"Erro ao executar o comando: {e}"


available_tools = {
    "abrir_youtube": abrir_youtube,
    "abrir_url": abrir_url,
    "pesquisar_google": pesquisar_google,
    "pesquisar_internet": pesquisar_internet,
    "ler_pagina_web": ler_pagina_web,
    "obter_tempo": obter_tempo,
    "obter_hora": obter_hora,
    "copiar_para_clipboard": copiar_para_clipboard,
    "criar_nota": criar_nota,
    "executar_comando": executar_comando,
    "abrir_terminal": abrir_terminal,
    "abrir_spotify": abrir_spotify,
    "pesquisar_spotify": pesquisar_spotify,
}

if HAS_CALENDAR:
    available_tools["criar_evento_calendario"] = criar_evento_calendario
    available_tools["listar_eventos_calendario"] = listar_eventos_calendario

if HAS_EMAIL:
    available_tools["listar_emails_recentes"] = listar_emails_recentes
    available_tools["enviar_email"] = enviar_email


# ============================================================
# UTILITÁRIOS
# ============================================================

def registar_log(entrada: dict):
    if not LOG_CONVERSAS:
        return
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
    except Exception:
        pass


def podar_historico(messages: list):
    if len(messages) <= MAX_HISTORY_MESSAGES:
        return messages
    sistema = messages[0]
    resto = messages[-(MAX_HISTORY_MESSAGES - 1):]
    return [sistema] + resto


def verificar_ollama():
    try:
        ollama.list()
        return True
    except Exception:
        return False


# ============================================================
# VOZ: RECONHECIMENTO (Whisper) e SÍNTESE (Piper TTS)
# ============================================================

_whisper_model = None
_piper_voice = None

def init_whisper():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    tentativas = []
    if WHISPER_DEVICE in ("auto", "cuda"):
        tentativas.append(("cuda", "float16"))
    tentativas.append(("cpu", "int8"))

    ultimo_erro = None
    for device, compute_type in tentativas:
        try:
            log("sistema", f"[MAX a carregar o modelo STT '{WHISPER_MODEL_SIZE}' em {device.upper()}...]")
            _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device=device, compute_type=compute_type)
            log("sistema", f"[Whisper pronto em {device.upper()}]")
            return _whisper_model
        except Exception as e:
            ultimo_erro = e
            if device == "cuda":
                log("erro", f"[GPU indisponível para o Whisper ({e}). A tentar CPU...]")

    raise RuntimeError(f"Não foi possível carregar o Whisper: {ultimo_erro}")


def init_tts():
    global _piper_voice
    if _piper_voice is None:
        if not os.path.exists(PIPER_MODEL_PATH) or not os.path.exists(PIPER_CONFIG_PATH):
            raise FileNotFoundError(f"Ficheiros de voz não encontrados: {PIPER_MODEL_PATH}.")
        log("sistema", "[A carregar modelo de voz Piper (Tugão)...]")
        _piper_voice = PiperVoice.load(PIPER_MODEL_PATH, PIPER_CONFIG_PATH)
        log("sistema", "[Voz Piper pronta!]")
    return _piper_voice


def falar(texto: str):
    """Lê o texto em voz alta gerando o áudio em RAM através do Piper."""
    if not (TTS_ENABLED and HAS_VOICE_OUTPUT):
        return
    try:
        voz = init_tts()
        texto_limpo = texto.replace("*", "").replace("#", "").replace("_", "").replace("`", "")
        if not texto_limpo.strip():
            return

        audio_stream = io.BytesIO()
        with wave.open(audio_stream, "wb") as wav_file:
            voz.synthesize_wav(texto_limpo, wav_file)

        audio_stream.seek(0)
        with wave.open(audio_stream, "rb") as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            audio_np = np.frombuffer(frames, dtype=np.int16)

        if audio_np.dtype != np.float32:
            audio_np = audio_np.astype(np.float32) / 32768.0
        if channels > 1:
            audio_np = audio_np.reshape(-1, channels)

        sd.play(audio_np, samplerate=sample_rate)
        sd.wait()
    except Exception as e:
        log("erro", f"[Erro no Piper TTS]: {e}")


def transcrever(audio_np):
    modelo = init_whisper()
    segmentos, _info = modelo.transcribe(audio_np, language=WHISPER_LANGUAGE, beam_size=5, vad_filter=True)
    return " ".join(seg.text.strip() for seg in segmentos).strip()


def _normalizar(texto: str) -> str:
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def _parece_wake_word(palavra: str) -> bool:
    if not palavra:
        return False
    if palavra in WAKE_WORD_VARIANTS:
        return True
    parecenca = difflib.SequenceMatcher(None, palavra, "max").ratio()
    return parecenca >= 0.72


def extrair_comando_apos_wake_word(texto: str):
    if not texto:
        return None
    palavras_originais = texto.split()
    palavras_normalizadas = _normalizar(texto).split()
    for i, palavra in enumerate(palavras_normalizadas):
        palavra_limpa = re.sub(r"[^\wçãõéíóúâêô]", "", palavra)
        if _parece_wake_word(palavra_limpa):
            resto = " ".join(palavras_originais[i + 1:]).strip()
            return resto
    return None


def loop_voz():
    """Corre numa thread própria: ouve continuamente e mete pedidos na fila_entrada."""
    if not HAS_VOICE_INPUT:
        return

    if WAKE_WORD_ENABLED:
        log("status", "🎙 a ouvir... (diz 'Max' antes do pedido)")
    else:
        log("status", "🎙 a ouvir...")

    bloco_seg = 0.05
    bloco_frames = int(SAMPLE_RATE * bloco_seg)
    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    stream.start()
    try:
        while True:
            buffer = []
            em_fala = False
            silencio_desde = None
            inicio_fala = None

            while True:
                dados, _overflow = stream.read(bloco_frames)
                volume = float(np.sqrt(np.mean(dados ** 2)))

                if volume > SILENCE_THRESHOLD:
                    if not em_fala:
                        em_fala = True
                        inicio_fala = time.time()
                        buffer = []
                    buffer.append(dados.copy())
                    silencio_desde = None
                elif em_fala:
                    buffer.append(dados.copy())
                    if silencio_desde is None:
                        silencio_desde = time.time()
                    elif time.time() - silencio_desde >= SILENCE_DURATION:
                        duracao_fala = time.time() - inicio_fala
                        if duracao_fala >= MIN_SPEECH_DURATION:
                            break
                        em_fala = False
                        buffer = []

            audio = np.concatenate(buffer, axis=0).flatten()
            texto = transcrever(audio)
            if not texto:
                continue

            if not WAKE_WORD_ENABLED:
                log("user", f"(voz) {texto}")
                fila_entrada.put(texto)
                continue

            comando = extrair_comando_apos_wake_word(texto)
            if comando is None:
                continue  # ignorado, sem wake word

            if not comando:
                log("max", "Diz.")
                falar("Diz.")
                continue

            log("user", f"(voz) {comando}")
            fila_entrada.put(comando)
    finally:
        stream.stop()
        stream.close()


# ============================================================
# CÉREBRO (processa pedidos vindos de voz ou texto)
# ============================================================

SYSTEM_PROMPT = (
    "Tu és o MAX, um assistente de IA local integrado no computador do "
    "Rodrigo (o script corre em Windows, macOS ou Linux — adapta o teu "
    "comportamento ao que as ferramentas te disserem, nunca assumas que "
    "estás sempre em Windows). As tuas respostas são lidas em voz alta "
    "através de síntese de voz (Piper TTS) e também aparecem escritas "
    "numa janela flutuante, portanto falas mesmo com o Rodrigo — não "
    "digas que és 'apenas texto' ou que não consegues falar. "
    "Tens ferramentas para interagir com o PC (abrir sites, pesquisar no "
    "Google, ver o tempo, ver as horas, criar notas, copiar texto, abrir "
    "o Spotify e correr comandos) E TAMBÉM ACESSO REAL À INTERNET através "
    "de pesquisar_internet e ler_pagina_web. Usa-as de forma autónoma "
    "sempre que o utilizador pedir uma ação, sem pedir confirmação extra "
    "a não ser que a própria ferramenta o exija. "
    "SOBRE A INTERNET: usa SEMPRE pesquisar_internet quando o Rodrigo "
    "perguntar sobre notícias, eventos recentes, preços, datas atuais, "
    "pessoas ou factos que possam ter mudado, ou qualquer coisa que os "
    "teus dados de treino possam não saber com precisão. Usa ler_pagina_web "
    "para leres o conteúdo real de um link específico. Nunca digas que não "
    "tens acesso à internet — tens, através destas ferramentas. "
    "REGRA CRÍTICA: o resultado devolvido por qualquer ferramenta "
    "(obter_hora, obter_tempo, pesquisar_internet, executar_comando, etc.) "
    "é sempre a verdade absoluta e atual, mesmo que contradiga o que "
    "'sabes' dos teus dados de treino. NUNCA questiones, corrijas ou digas "
    "que há uma 'inconsistência' no resultado de uma ferramenta — os teus "
    "dados de treino têm uma data de corte no passado, por isso a tua "
    "noção interna da data atual está desatualizada e deves ignorá-la "
    "completamente. Usa sempre o valor exato devolvido pela ferramenta. "
    "SOBRE O CALENDÁRIO: quando o Rodrigo pedir para marcares, criares ou "
    "veres eventos no calendário, usa as ferramentas criar_evento_calendario "
    "e listar_eventos_calendario. Se ele usar datas relativas ('amanhã', "
    "'sexta-feira', 'daqui a uma semana'), chama primeiro obter_hora para "
    "saberes a data e a hora atuais reais, e só depois calcula a data exata "
    "a passar à ferramenta, no formato ISO (ex: '2026-08-10T15:00:00'). "
    "Nunca inventes ou assumas a data de hoje sem confirmares com obter_hora "
    "primeiro. "
    "SOBRE O EMAIL: usa listar_emails_recentes para leres a caixa de "
    "entrada e enviar_email para enviares mensagens. ENVIAR EMAIL É UMA "
    "AÇÃO IRREVERSÍVEL: antes de chamares enviar_email, confirma sempre "
    "com o Rodrigo o destinatário, o assunto e o corpo do email (lê-los "
    "de volta, de forma resumida) e só envies depois de ele confirmar "
    "explicitamente ('sim', 'envia', 'confirmo', etc.). Nunca envies um "
    "email sem essa confirmação prévia, mesmo que o pedido pareça claro. "
    "IMPORTANTE sobre comandos: sempre que o Rodrigo pedir para veres, "
    "verificares, correres ou fazeres qualquer coisa no PC dele (versões "
    "de programas, ficheiros, processos, rede, etc.), usa SEMPRE a "
    "ferramenta executar_comando com o comando apropriado ao sistema "
    "operativo em que estás a correr, e diz o resultado. NÃO uses "
    "abrir_terminal para isso — abrir_terminal serve APENAS para quando "
    "ele pedir explicitamente para abrires uma janela de terminal visível "
    "para ele próprio usar. Para perguntas sobre a hora atual usa SEMPRE "
    "obter_hora, e para o estado do tempo usa SEMPRE obter_tempo, em vez "
    "de responderes de memória. Responde sempre em português de Portugal, "
    "de forma direta e concisa em conversa casual (2-3 frases, já que a "
    "resposta vai ser falada em voz alta). Quando o pedido for código, "
    "explicações técnicas, ou o utilizador pedir mais detalhe, podes "
    "responder com o comprimento necessário."
)

FALLBACK_RESPOSTA_INVALIDA = "Peço desculpa, tive uma resposta estranha agora. Podes repetir o pedido?"

def cortar_se_repetitivo(texto: str):
    padrao = re.search(r"(.{2,60}?)\1{4,}", texto, re.DOTALL)
    if not padrao:
        return texto, False
    texto_cortado = texto[:padrao.start()].strip()
    if not texto_cortado:
        texto_cortado = FALLBACK_RESPOSTA_INVALIDA
    return texto_cortado, True

def _proporcao_caracteres_validos(texto: str) -> float:
    if not texto:
        return 1.0
    validos = sum(1 for c in texto if c.isascii() or (0x00C0 <= ord(c) <= 0x017F))
    return validos / len(texto)

def validar_resposta(texto: str):
    texto, cortado_por_repeticao = cortar_se_repetitivo(texto)
    if _proporcao_caracteres_validos(texto) < 0.85:
        return FALLBACK_RESPOSTA_INVALIDA, True
    return texto, cortado_por_repeticao


def processar_pedido(user_input: str, messages: list):
    messages.append({"role": "user", "content": user_input})
    messages = podar_historico(messages)

    log("status", "💭 a pensar...")
    response = ollama.chat(
        model=MODEL_NAME, messages=messages,
        tools=list(available_tools.values()), options=OLLAMA_OPTIONS,
    )

    tool_calls = response.get("message", {}).get("tool_calls")

    if tool_calls:
        messages.append(response["message"])
        for tool in tool_calls:
            function_name = tool["function"]["name"]
            function_args = tool["function"]["arguments"]
            log("tool", f"[MAX a acionar ferramenta: {function_name}({function_args})...]")

            if function_name in available_tools:
                try:
                    output = available_tools[function_name](**function_args)
                except Exception as e:
                    output = f"Erro ao executar '{function_name}': {e}"
            else:
                output = f"Erro: Função {function_name} não encontrada."

            messages.append({"role": "tool", "content": str(output), "name": function_name})

        texto_completo = ""
        for chunk in ollama.chat(model=MODEL_NAME, messages=messages, stream=True, options=OLLAMA_OPTIONS):
            parte = chunk["message"]["content"]
            texto_completo += parte
            if re.search(r"(.{2,60}?)\1{4,}", texto_completo[-400:], re.DOTALL):
                break
            if len(texto_completo) > 60 and _proporcao_caracteres_validos(texto_completo[-120:]) < 0.7:
                break

        texto_completo, cortado = validar_resposta(texto_completo)
        if cortado:
            log("erro", "[aviso: a resposta entrou num ciclo de repetição e foi cortada]")
        log("max", texto_completo)
        messages.append({"role": "assistant", "content": texto_completo})

    else:
        texto_completo = response["message"]["content"]
        texto_completo, cortado = validar_resposta(texto_completo)
        if cortado:
            log("erro", "[aviso: a resposta entrou num ciclo de repetição e foi cortada]")
        log("max", texto_completo)
        messages.append({"role": "assistant", "content": texto_completo})

    registar_log({
        "timestamp": datetime.datetime.now().isoformat(),
        "user": user_input,
        "assistant": texto_completo,
    })

    log("status", "🎙 a ouvir..." if HAS_VOICE_INPUT else "✅ pronto")
    falar(texto_completo)
    return messages


def loop_cerebro():
    """Corre numa thread própria: processa um pedido de cada vez, vindo de voz ou texto."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    while True:
        user_input = fila_entrada.get()
        if user_input is None:
            break
        if user_input.strip().lower() in ("sair", "exit", "quit"):
            log("max", "A encerrar sistemas.")
            falar("A encerrar sistemas.")
            os._exit(0)
        try:
            messages = processar_pedido(user_input, messages)
        except ollama.ResponseError as e:
            log("erro", f"[Erro do modelo]: {e}")
        except Exception as e:
            log("erro", f"[Erro]: {e}")


# ============================================================
# JANELA FLUTUANTE (GUI)
# ============================================================

# ============================================================
# JANELA FLUTUANTE (GUI)
# ============================================================

# Constantes para cores e estilo
BG_COLOR = "#101418"
TEXT_COLOR = "#e6e6e6"
BUTTON_COLOR = "#00e676"

class MaxGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("MAX")
        self.root.geometry("480x600+80+80")  # Tamanho de janela aumentado
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG_COLOR)

        # Status Label
        self.status_var = tk.StringVar(value="a iniciar...")
        status_label = tk.Label(
            self.root, textvariable=self.status_var,
            fg="#00e676", bg=BG_COLOR, font=("Segoe UI", 12, "bold"),
            anchor="w"
        )
        status_label.pack(fill="x", padx=10, pady=(8, 4))

        # Log Box
        self.log_box = scrolledtext.ScrolledText(
            self.root, wrap="word", state="disabled",
            bg="#181c22", fg=TEXT_COLOR, insertbackground=TEXT_COLOR,
            font=("Consolas", 10), relief="flat", padx=8, pady=8
        )
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        
        # Configure tags for different log levels
        self.log_box.tag_config("user", foreground="#4fc3f7")
        self.log_box.tag_config("max", foreground="#69f0ae")
        self.log_box.tag_config("tool", foreground="#ffd54f")
        self.log_box.tag_config("erro", foreground="#ff5252")
        self.log_box.tag_config("sistema", foreground="#9e9e9e")

        # Entry for user input
        entrada_frame = tk.Frame(self.root, bg=BG_COLOR)
        entrada_frame.pack(fill="x", padx=10, pady=(4, 8))

        self.entrada = tk.Entry(
            entrada_frame, bg="#181c22", fg=TEXT_COLOR, insertbackground=TEXT_COLOR,
            font=("Consolas", 12), relief="flat"
        )
        self.entrada.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 4))
        self.entrada.bind("<Return>", self.enviar)

        # Send Button
        send_button = tk.Button(
            entrada_frame, text="Enviar", command=self.enviar,
            bg=BUTTON_COLOR, fg="#101418", relief="flat",
            font=("Segoe UI", 9, "bold")
        )
        send_button.pack(side="right")

        # Inicializa a leitura segura da fila de comunicação para o Tkinter
        self.root.after(100, self._processar_fila)

    def enviar(self, event=None):
        texto = self.entrada.get().strip()
        if not texto:
            return
        self.entrada.delete(0, tk.END)
        self._adicionar("user", f"Rodrigo (texto) > {texto}")
        
        # [CRÍTICO] Enviar o texto para a thread do cérebro (Ollama)
        fila_entrada.put(texto)

    def _adicionar(self, tag, texto):
        self.log_box.configure(state="normal")
        self.log_box.insert(tk.END, texto + "\n", tag)
        self.log_box.see(tk.END)
        self.log_box.configure(state="disabled")

    def _processar_fila(self):
        # [CRÍTICO] Receber mensagens, comandos e avisos das outras threads
        try:
            while True:
                remetente, texto = fila_saida.get_nowait()
                if remetente == "status":
                    self.status_var.set(texto)
                else:
                    prefixos = {"user": "", "max": "MAX: ", "tool": "🔧 ", "erro": "⚠ ", "sistema": ""}
                    self._adicionar(remetente, prefixos.get(remetente, "") + texto)
        except queue.Empty:
            pass
        # Agenda a próxima verificação (forma segura de fazer loops em Tkinter)
        self.root.after(100, self._processar_fila)

    def run(self):
        # Apenas o mainloop (thread UI principal)
        self.root.mainloop()


# =================================================w===========
# ARRANQUE
# ============================================================

def main():
    print(f"{C_MAX}=== MAX ONLINE ({SISTEMA_OPERATIVO}) ==={C_RESET}")

    if not verificar_ollama():
        print(f"{C_ERROR}[Erro] Não foi possível ligar ao Ollama. Verifica se o serviço está a correr.{C_RESET}")
        return

    if not HAS_WEB_SEARCH:
        print(f"{C_ERROR}[Aviso] Pesquisa na internet indisponível — instala com: pip install ddgs{C_RESET}")

    if HAS_VOICE_INPUT:
        init_whisper()
    if HAS_VOICE_OUTPUT:
        init_tts()

    threading.Thread(target=loop_cerebro, daemon=True).start()

    if HAS_VOICE_INPUT:
        threading.Thread(target=loop_voz, daemon=True).start()
    else:
        log("erro", "[Voz indisponível — instala com: pip install faster-whisper sounddevice numpy. A usar só a janela de texto.]")

    gui = MaxGUI()
    gui.run()


if __name__ == "__main__":
    main()