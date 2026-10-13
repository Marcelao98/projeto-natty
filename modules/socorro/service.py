"""Módulo Socorro — camada de serviço.

A Natty se apresenta e explica, em versão curta, o que cada módulo faz.
Lógica pura: sem discord.py, pra qualquer outro módulo (inclusive um futuro
módulo de LLM) poder pegar os textos de ajuda direto.

Quando um módulo ganhar ou perder comandos, o texto dele aqui precisa ser
atualizado junto.
"""

from __future__ import annotations

import re

# "@Natty socorro", "@Natty ajuda dice": o cog exige a menção de verdade e a
# tira do texto antes de chamar aqui. O pedido de ajuda tem que vir logo no
# começo, pra "@Natty toca isso, socorro" não virar pedido de ajuda.
_SOCORRO_RE = re.compile(r"^\W*(?:socorro|ajuda|help|comandos)\b(.*)$", re.IGNORECASE | re.DOTALL)

_APELIDOS = {
    "dice": re.compile(r"\b(dice|dados?|rolar|rolagem|rolagens)\b", re.IGNORECASE),
    "bardo": re.compile(r"\b(bardo|bard|m[uú]sicas?)\b", re.IGNORECASE),
    "core": re.compile(r"\b(core|nat-core|personage(m|ns)|registro|registrar|fichas?)\b", re.IGNORECASE),
    "voz": re.compile(r"\b(voz|echo|falar|falada|call|escuta|nat20)\b", re.IGNORECASE),
}

MODULOS = tuple(_APELIDOS)

_GERAL = """\
Oi, eu sou a **Natty**! 🤖 Fui achada no lixo e ainda estou aprendendo, mas já sei umas coisas.

Meus principais módulos são:
🎲 **Dice** — rolo dados pra vocês
🎵 **Bardo** — toco música no canal de voz
📜 **Core** — cuido dos personagens da Crossroads
🎙️ **Voz** — escuto a call e rolo dados ou toco música quando vocês pedem falando

Pra saber mais de um deles: `@Natty socorro dice`, `@Natty socorro bardo`, `@Natty socorro core` ou `@Natty socorro voz` (ou `/socorro`). Me chama sempre com **@Natty** — só escrever meu nome não basta."""

_TEXTOS = {
    "dice": """\
🎲 **Dice** — rolagem de dados

É só rolar no chat que eu respondo:
• `rolo 1d20+5` · `1d20 com vantagem vs 15` · `Teste de Ataque: 1d20+5 vs CD 13`
• `rolo 4d6 tiro 1` (tira o menor) · `rolo 1d6!` (explode no máximo)
• `rolo 1d8 se 8 role de novo` · `rolo 2 moedas`

Também tem `/rolar`. Mensagens começando com `!` são do Avrae, essas eu deixo pra ele.""",
    "bardo": """\
🎵 **Bardo** — música no canal de voz

Entra num canal de voz e me chama:
• `@Natty toca <link do YouTube>` — toco a música (se já tiver uma tocando, ponho na fila); link de playlist põe a playlist inteira
• `@Natty toca triste e bloodborne` · `@Natty toca Garçom` — busco no meu acervo de trilhas (e no YouTube, se não achar)
• `@Natty pula` — vai pra próxima · `@Natty fila` — mostra a fila · `@Natty limpa a fila` · `@Natty tira a 2 da fila`
• `@Natty pausa` · `@Natty continua`
• `@Natty repete` — repito a música atual até alguém pedir `@Natty para de repetir` (ou `@Natty repete` de novo) · `@Natty repete a fila` — repito a fila inteira
• `@Natty para` — paro a música e limpo a fila (continuo no canal; quando todo mundo sai da call, eu saio também)
• `@Natty volume 30` · `@Natty aumenta o volume` · `@Natty abaixa`

Som de mesa: `/som enviar` (ambiente, efeito ou música), `/som tocar`, `/som parar`, `/som cena`.
Playlists salvas: `/playlist salvar`, `/playlist tocar` (ou `@Natty toca a playlist <nome>`), `/playlist listar`.
Também tem `/tocar`, `/pular`, `/fila`, `/limpar-fila`, `/remover`, `/repetir`, `/pausar`, `/continuar`, `/parar` e `/volume`.""",
    "core": """\
📜 **Core** — personagens da Crossroads

• `/registrar-personagem` — registra seu personagem: nome, link da ficha do DiceCloud e a história, do tamanho que você quiser (uma linha já vale). Precisa do cargo **Viajante**
• `/personagens` — lista todos os viajantes registrados, com nível e data de registro
• `/deletar-personagem` — apaga um personagem seu do registro
• `/registrar-missao` — o condutor registra a missão depois da sessão (participantes com os nomes como em `/personagens`)
• `/missoes` — lista as missões registradas
• `/oi` — eu me apresento""",
    "voz": """\
🎙️ **Voz** — comandos falados na call

Entra num canal de voz e manda `@Natty escuta` — eu passo a ouvir **só você** (outra pessoa assume mandando `@Natty escuta` de novo). Aí, falando:
• **"NAT20, por favor"** → eu respondo 👂 → fala a rolagem: _"dado vinte mais cinco com vantagem contra quinze"_, _"quatro dados seis tirando o menor"_, _"três moedas"_
• **"NAT20, por favor, música"** → eu respondo 🎵 → fala a música: _"Garçom"_, _"combate de chefe"_
• **"NAT20, por favor, pare"** → paro a música (e continuo na call, escutando)
• **"NAT20, por favor, próxima"** · **"…, repete"** · **"…, para de repetir"** · **"…, pausa"** · **"…, continua"** → controlo a música
• **"NAT20, por favor, saia"** → saio da call (ou manda `@Natty, tampe os ouvidos`)
• 📝 Ata da sessão (por texto): `@Natty, grava a sessão` grava **todo mundo**; `@Natty, para de gravar` para e eu pergunto se transcrevo agora (`@Natty, sim` / `@Natty, depois`); `@Natty, transcreve a sessão` transcreve a última gravação quando quiser

Fala "dado vinte", não "um dê vinte" — o "dê" sozinho eu não ouço. E faz uma pausinha depois da senha.""",
}


def interpretar_pedido(texto: str) -> str | None:
    """Qual ajuda foi pedida: "geral", um de MODULOS, ou None se não é pedido de socorro.

    `texto` é a mensagem já SEM a menção à Natty (o cog só chama aqui quando
    houve menção de verdade — "natty socorro" escrito sem @ não conta).
    """
    m = _SOCORRO_RE.match(texto)
    if not m:
        return None
    resto = m.group(1)
    for modulo, apelidos in _APELIDOS.items():
        if apelidos.search(resto):
            return modulo
    return "geral"


def texto_de_ajuda(topico: str = "geral") -> str:
    """Texto de ajuda de um tópico ("geral" ou um de MODULOS)."""
    return _TEXTOS.get(topico, _GERAL)
