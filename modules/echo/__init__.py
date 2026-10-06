"""
Módulo Echo: ouve fala em canal de voz e transcreve.

    from modules.echo import reconhecer
    r = reconhecer("trecho.wav")
    if r.chamou_natty:
        print(r.comando)  # "rola 1d20", por exemplo
"""

from .service import (
    NOME_MODELO_PADRAO,
    Reconhecimento,
    Transcricao,
    extrair_comando,
    reconhecer,
    tem_wake_word,
    transcrever,
    transcrever_pcm,
)

__all__ = [
    "reconhecer",
    "Reconhecimento",
    "Transcricao",
    "transcrever",
    "transcrever_pcm",
    "tem_wake_word",
    "extrair_comando",
    "NOME_MODELO_PADRAO",
]
