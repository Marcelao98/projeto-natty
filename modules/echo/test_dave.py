"""Testes do remendo DAVE (dave.py), com sessão e voice client falsos — sem Discord."""

import unittest
from types import SimpleNamespace

from discord.opus import OpusError

from modules.echo import dave


class SessaoFalsa:
    """Só decifra pacote de quem é o dono (dono=None: decifra de qualquer um)."""

    def __init__(self, ready=True, falha=False, dono=None, participantes=("1", "42")):
        self.ready = ready
        self.falha = falha
        self.dono = dono
        self.user_id = "1"  # a própria Natty
        self.participantes = list(participantes)
        self.chamadas = []

    def get_user_ids(self):
        return self.participantes

    def decrypt(self, user_id, media_type, packet):
        self.chamadas.append((user_id, media_type, packet))
        if self.falha or (self.dono is not None and user_id != self.dono):
            raise RuntimeError("DecryptionFailed")
        return b"opus-decifrado"


def _decoder(sessao, ssrc_para_id=None, cached_id=None):
    mapa = dict(ssrc_para_id or {})
    vc = SimpleNamespace(
        _connection=SimpleNamespace(dave_session=sessao),
        _get_id_from_ssrc=mapa.get,
        _add_ssrc=lambda uid, ssrc: mapa.__setitem__(ssrc, uid),
        mapa=mapa,
    )
    return SimpleNamespace(sink=SimpleNamespace(voice_client=vc), ssrc=7, _cached_id=cached_id)


def _pacote(dado):
    return SimpleNamespace(decrypted_data=dado)


class TestDecifrar(unittest.TestCase):
    def setUp(self):
        dave.estatisticas()  # zera contadores

    def test_decifra_frame_dave_com_id_do_ssrc(self):
        sessao = SessaoFalsa()
        p = _pacote(b"cifrado\xfa\xfa")
        dave._decifrar(_decoder(sessao, {7: 42}), p)
        self.assertEqual(p.decrypted_data, b"opus-decifrado")
        self.assertEqual(sessao.chamadas[0][0], 42)
        self.assertEqual(sessao.chamadas[0][2], b"cifrado\xfa\xfa")
        self.assertEqual(dave.estatisticas(), {"decifrado": 1})

    def test_frame_sem_marcador_passa_direto(self):
        sessao = SessaoFalsa()
        p = _pacote(b"\xf8\xff\xfe")  # silêncio Opus
        dave._decifrar(_decoder(sessao, {7: 42}), p)
        self.assertEqual(p.decrypted_data, b"\xf8\xff\xfe")
        self.assertEqual(sessao.chamadas, [])

    def test_falha_de_decifragem_vira_pacote_perdido(self):
        p = _pacote(b"cifrado\xfa\xfa")
        dave._decifrar(_decoder(SessaoFalsa(falha=True), {7: 42}), p)
        self.assertIsNone(p.decrypted_data)
        self.assertEqual(dave.estatisticas(), {"falha_decifrar": 1})

    def test_sessao_nao_pronta_vira_pacote_perdido(self):
        p = _pacote(b"cifrado\xfa\xfa")
        dave._decifrar(_decoder(SessaoFalsa(ready=False), {7: 42}), p)
        self.assertIsNone(p.decrypted_data)

    def test_ssrc_sem_dono_descobre_pela_chave_e_registra(self):
        sessao = SessaoFalsa(dono=42, participantes=["1", "13", "42"])
        dec = _decoder(sessao, {})
        p = _pacote(b"cifrado\xfa\xfa")
        dave._decifrar(dec, p)
        self.assertEqual(p.decrypted_data, b"opus-decifrado")
        self.assertEqual(dec.sink.voice_client.mapa, {7: 42})
        self.assertEqual(dec._cached_id, 42)
        # Nunca tenta a chave da própria Natty.
        self.assertNotIn(1, [c[0] for c in sessao.chamadas])

    def test_ssrc_reaproveitado_redescobre_dono(self):
        sessao = SessaoFalsa(dono=42)
        dec = _decoder(sessao, {7: 13})  # mapa velho aponta pra outra pessoa
        p = _pacote(b"cifrado\xfa\xfa")
        dave._decifrar(dec, p)
        self.assertEqual(p.decrypted_data, b"opus-decifrado")
        self.assertEqual(dec.sink.voice_client.mapa[7], 42)

    def test_ninguem_decifra_vira_pacote_perdido(self):
        p = _pacote(b"cifrado\xfa\xfa")
        dave._decifrar(_decoder(SessaoFalsa(falha=True), {}), p)
        self.assertIsNone(p.decrypted_data)
        self.assertEqual(dave.estatisticas(), {"sem_dono": 1})


class TestDecodeNaoDerrubaEscuta(unittest.TestCase):
    def test_opus_error_vira_plc(self):
        dave.aplicar()
        from discord.ext.voice_recv import opus as vr_opus

        class DecoderOpusFalso:
            def decode(self, data, fec=False):
                if data is not None:
                    # "corrupted stream"; sem __init__ porque ele exige a libopus carregada
                    raise OpusError.__new__(OpusError)
                return b"plc"

        falso = SimpleNamespace(_decoder=DecoderOpusFalso(), _buffer=None)
        pacote = SimpleNamespace(decrypted_data=b"lixo")
        _, pcm = vr_opus.PacketDecoder._decode_packet(falso, pacote)
        self.assertEqual(pcm, b"plc")


if __name__ == "__main__":
    unittest.main()
