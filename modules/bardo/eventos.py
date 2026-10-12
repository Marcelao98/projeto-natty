"""Pub/sub mínimo do Bardo: quem quer saber que o estado de um servidor mudou.

O motor publica (`publicar(guild_id)`) a cada mudança — música começou,
pulou, pausou, volume, fila, repetir, saiu da call — venha o pedido do
Discord, da voz (Echo) ou do painel. Quem assina (o painel web) recebe só o
guild_id e pede o estado de novo: assim não tem estado duplicado pra ficar
velho. Sem dependência de discord.py.
"""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger(__name__)

Assinante = Callable[[int], None]


class Publicador:
    def __init__(self):
        self._assinantes: list[Assinante] = []

    def assinar(self, assinante: Assinante) -> None:
        if assinante not in self._assinantes:
            self._assinantes.append(assinante)

    def cancelar(self, assinante: Assinante) -> None:
        if assinante in self._assinantes:
            self._assinantes.remove(assinante)

    def publicar(self, guild_id: int) -> None:
        """Avisa todo mundo. Um assinante que quebra não impede os outros nem quem publicou."""
        for assinante in list(self._assinantes):
            try:
                assinante(guild_id)
            except Exception:
                log.exception("Bardo: assinante de eventos falhou")
