"""
Módulo Echo — remendo de DAVE no discord-ext-voice-recv.

Desde mar/2026 o Discord exige DAVE (criptografia ponta a ponta) nas calls.
O discord.py 2.7 + davey entram no grupo criptografado e cifram o áudio que a
Natty ENVIA, mas o discord-ext-voice-recv (0.5.2a179) só tira a camada de
transporte do que ela RECEBE: o Opus ganha pacote ainda cifrado e estoura
"OpusError: corrupted stream" — e esse erro derruba a thread de escuta inteira.

O conserto oficial é o PR #54, ainda aberto:
https://github.com/imayhaveborkedit/discord-ext-voice-recv/pull/54
Quando ele sair numa versão do PyPI, este arquivo pode ser apagado.

Aqui, dois remendos no PacketDecoder, aplicados uma vez (aplicar()):
1. push_packet: decifra com a sessão DAVE da própria conexão ANTES de o pacote
   entrar no buffer — assim a recuperação de pacote perdido (FEC), que espia o
   próximo pacote do buffer, também recebe áudio já decifrado.
2. _decode_packet: um pacote que ainda assim não decodifica vira perda (o Opus
   preenche com PLC) em vez de derrubar a escuta.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter

from discord.ext.voice_recv import opus as vr_opus
from discord.opus import OpusError

try:
    from davey import MediaType
except ImportError:  # sem davey não há DAVE; o remendo vira no-op
    MediaType = None

log = logging.getLogger(__name__)

# Todo frame DAVE termina com esse marcador (protocolo DAVE, "magic marker").
# Frame sem ele (silêncio, ou call que ainda não migrou pro DAVE) passa direto.
_MARCADOR_DAVE = b"\xfa\xfa"

_aplicado = False

# Diagnóstico: quantos pacotes caíram em cada caminho desde a última leitura.
# Roda na thread de leitura do voice_recv, por isso a trava.
_stats: Counter = Counter()
_stats_lock = threading.Lock()


def _contar(chave: str) -> None:
    with _stats_lock:
        _stats[chave] += 1


def estatisticas() -> dict:
    """Devolve e zera os contadores (o cog imprime isso no log periodicamente)."""
    with _stats_lock:
        copia = dict(_stats)
        _stats.clear()
    return copia


def _tentar(sessao, user_id: int, dado: bytes):
    # PanicException do davey (Rust) herda de BaseException, não de Exception.
    try:
        return sessao.decrypt(user_id, MediaType.audio, dado)
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        log.debug("DAVE: falha ao decifrar pacote de %s: %r", user_id, e)
        return None


def _descobrir_dono(decoder, vc, sessao, dado: bytes):
    """
    SSRC sem dono conhecido (o evento SPEAKING do Discord não chegou, ou chegou
    tarde): testa a chave de cada participante da sessão DAVE. A que decifrar
    é a de quem está falando — aí registra o SSRC -> usuário pro resto da call.
    """
    proprio = getattr(sessao, "user_id", None)
    for uid in sessao.get_user_ids():
        if str(uid) == str(proprio):
            continue
        claro = _tentar(sessao, int(uid), dado)
        if claro is not None:
            vc._add_ssrc(int(uid), decoder.ssrc)  # RLock do router: reentrante, sem deadlock
            decoder._cached_id = int(uid)
            log.info("DAVE: SSRC %s identificado como usuário %s", decoder.ssrc, uid)
            _contar("dono_descoberto")
            return claro
    return None


def _decifrar(decoder: vr_opus.PacketDecoder, packet) -> None:
    dado = packet.decrypted_data
    if not dado or not bytes(dado).endswith(_MARCADOR_DAVE):
        _contar("sem_dave")
        return
    dado = bytes(dado)

    vc = decoder.sink.voice_client
    sessao = getattr(vc._connection, "dave_session", None) if vc else None
    if sessao is None or not sessao.ready:
        packet.decrypted_data = None  # ainda sem chave: trata como pacote perdido
        _contar("sessao_nao_pronta")
        return

    user_id = decoder._cached_id or vc._get_id_from_ssrc(decoder.ssrc)
    claro = _tentar(sessao, user_id, dado) if user_id is not None else None
    if claro is None:
        # Sem dono, ou o dono registrado não decifra (SSRC reaproveitado): procura.
        claro = _descobrir_dono(decoder, vc, sessao, dado)

    if claro is None:
        packet.decrypted_data = None
        _contar("falha_decifrar" if user_id is not None else "sem_dono")
    else:
        packet.decrypted_data = claro
        _contar("decifrado")


def aplicar() -> None:
    """Instala os remendos no PacketDecoder. Idempotente."""
    global _aplicado
    if _aplicado or MediaType is None:
        return

    push_original = vr_opus.PacketDecoder.push_packet
    decode_original = vr_opus.PacketDecoder._decode_packet

    def push_packet(self, packet):
        if packet:  # FakePacket (pacote perdido) é falsy e não tem dado
            try:
                _decifrar(self, packet)
            except Exception:
                # Nunca deixar o remendo derrubar a thread de leitura.
                log.exception("DAVE: erro inesperado no remendo")
                packet.decrypted_data = None
                _contar("erro_remendo")
        return push_original(self, packet)

    def _decode_packet(self, packet):
        try:
            return decode_original(self, packet)
        except OpusError:
            _contar("opus_corrompido")
            return packet, self._decoder.decode(None, fec=False)

    vr_opus.PacketDecoder.push_packet = push_packet
    vr_opus.PacketDecoder._decode_packet = _decode_packet
    _aplicado = True
