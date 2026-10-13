# Painel web — a música da mesa no navegador

**Status:** 12/10/2026: login, estado do Bardo ao vivo e controle (tocar,
pausar, pular, parar, volume, repetir, remover, playlists). Testado com dublês
(aiohttp de verdade, Discord falso); falta o login real.

O painel é uma **superfície**, como o Discord: não é uma capacidade nova.
Ele não toca nada nem guarda nada do Bardo — fala com ele por
`bot.controles["bardo"]` (registrado pelo cog do Bardo) e não importa o
módulo. Mesma regra de "módulos não importam uns aos outros" do `CLAUDE.md`.

## Ligar

1. No Discord Developer Portal, app da Natty → **OAuth2**: copie o *Client
   Secret* e adicione o redirect `http://localhost:8710/auth/callback`.
2. No `.env`: `DISCORD_CLIENT_SECRET=...` (e, se quiser,
   `NATTY_PAINEL_PORT` / `NATTY_PAINEL_URL`). O client id vem do próprio bot.
3. Reinicia a Natty e abre `http://localhost:8710` **na máquina dela**.

Sem `DISCORD_CLIENT_SECRET` o painel simplesmente não sobe.

## Como funciona

- **aiohttp, não FastAPI**: já vem com o discord.py e roda no mesmo loop
  asyncio do bot — o painel enxerga o estado direto, sem IPC nem segunda
  porta pra sincronizar.
- **Ao vivo por WebSocket**: o motor do Bardo publica (`eventos.py`) a cada
  mudança — venha do Discord, da voz ou do painel — e o painel empurra o
  estado novo pra todas as telas abertas.
- **Front sem build**: `static/index.html`, `app.js`, `style.css`. Paleta
  amostrada da arte da Natty.

| Rota | O que faz |
|---|---|
| `GET /auth/login` → `GET /auth/callback` | OAuth2 do Discord (`identify guilds`), com `state` anti-CSRF (uso único, 10 min, conferido também por cookie) |
| `POST /auth/logout` | encerra a sessão |
| `GET /api/me`, `GET /api/guilds` | quem é você; servidores em comum com a Natty |
| `GET /ws?guild=<id>` | estado do Bardo ao vivo |
| `POST /api/g/<id>/cmd` | comando pro Bardo (o WebSocket aceita os mesmos: `{"id", "cmd", "args"}`) |

## Comandos

`tocar {pedido}`, `pular`, `pausar`, `continuar`, `parar`, `volume {nivel}`,
`repetir {modo: faixa|fila|desligar}`, `remover {posicao}`, `limpar_fila`,
`playlists`, `tocar_playlist {nome}`, `salvar_playlist {nome}`. Rodam pelo
**mesmo caminho** dos comandos do Discord (`ControleBardo.executar` no
`motor.py` do Bardo), com os argumentos validados lá. Pedido do painel toca
na call em que a Natty já está; se ela não está em nenhuma, na de quem pediu.
O "era essa?" da busca livre só acontece no Discord.

Quem não tem o cargo de mestre vê tudo, mas os controles somem.

## Segurança

- Escuta **só em 127.0.0.1**. Pra abrir pra rede, precisa de HTTPS (o
  Discord exige no redirect fora de localhost) — não está feito.
- Sessão em memória, cookie `HttpOnly` + `SameSite=Lax`; reiniciar a Natty
  desloga todo mundo.
- WebSocket e POST conferem a **origem** (tem que ser a página do painel).
- Autorização **ao vivo no bot**, a cada requisição e a cada mensagem do
  WebSocket: precisa ser membro do servidor agora; comandar pede o cargo de
  mestre (**Condutor**, `BARDO_CARGO_MESTRE`) ou ser dono do servidor. A lista
  de servidores do OAuth não é usada pra isso (fica velha).
- CSP sem script inline; títulos de música entram na página só como texto.

## Estrutura

```
modules/painel/
├── cog.py       # sobe/derruba o servidor junto com a Natty
├── web.py       # rotas aiohttp (só validam e chamam service/controles)
├── service.py   # sessões, state do OAuth, origem — lógica pura
├── oauth.py     # HTTP cru com o Discord (token, users/@me)
├── static/      # index.html, app.js, style.css
└── test_painel.py
```

## Testes

```
python -m unittest discover -s modules/painel -t .
```
