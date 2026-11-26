import os
import wave
from piper.voice import PiperVoice
import pygame

# 1. Define os caminhos para os ficheiros que descarregaste
MODEL_PATH = "pt_PT-tugão-medium.onnx"
CONFIG_PATH = "pt_PT-tugão-medium.onnx.json"

def iniciar_voz_jarvis():
    """Carrega o modelo do Piper para a memória (fazer apenas 1x no arranque)"""
    print("[SISTEMA] A carregar modelo de voz neural offline...")
    
    if not os.path.exists(MODEL_PATH) or not os.path.exists(CONFIG_PATH):
        print(f"[ERRO] Ficheiros não encontrados! Verifica se tens o {MODEL_PATH} e o JSON na pasta.")
        return None
        
    # Carrega a voz na memória RAM
    voz = PiperVoice.load(MODEL_PATH, config_path=CONFIG_PATH)
    print("[SISTEMA] Voz carregada com sucesso!")
    return voz

def jarvis_falar(voz, texto):
    """Gera o áudio offline e reproduz-o"""
    if not voz:
        print("[JARVIS_TEXTO]:", texto)
        return
        
    ficheiro_temporario = "resposta_jarvis.wav"
    
    # 2. Sintetizar: Transforma o texto em áudio e guarda num WAV
    with wave.open(ficheiro_temporario, 'wb') as ficheiro_wav:
        voz.synthesize(texto, ficheiro_wav)
    
    # 3. Reproduzir o ficheiro sem bloquear o resto do computador
    pygame.mixer.init()
    pygame.mixer.music.load(ficheiro_temporario)
    pygame.mixer.music.play()
    
    # Espera que o áudio acabe de tocar
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
        
    # 4. Limpeza: liberta a memória e apaga o ficheiro temporário
    pygame.mixer.music.unload()
    try:
        os.remove(ficheiro_temporario)
    except Exception as e:
        pass # Ignora se o Windows prender o ficheiro por um momento

# ==========================================
# Exemplo de Integração (Como usar)
# ==========================================
if __name__ == "__main__":
    # Carrega a voz no início (demora 1-2 segundos)
    jarvis_voz = iniciar_voz_jarvis()
    
    # Agora podes chamar a função sempre que ele precisar de falar (Resposta instantânea!)
    if jarvis_voz:
        jarvis_falar(jarvis_voz, "Olá Rodrigo. Sistemas offline iniciados com sucesso.")
        jarvis_falar(jarvis_voz, "Latência zero confirmada. Pronto para iniciarmos os testes de software.")