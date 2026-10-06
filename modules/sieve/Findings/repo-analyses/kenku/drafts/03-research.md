# 03 — Pesquisa externa: Kenku FM

## Metadados
- GitHub owlbear-rodeo/kenku-fm: ~358★, 97 forks, 73 issues abertas; criado 2021-08; último push 2026-03-04 (v1.5.5).
- Contribuidores: nthouliss (506 commits), mitchemmc (425) — projeto de fato de 2 pessoas (Owlbear Rodeo). Licença GPL-3.0.
- Política "open source, not open contribution" (só PRs de bugfix) — .github/CONTRIBUTING.md.

## Problema central
- Cenário: mestre de RPG de mesa jogando online via Discord quer trilha sonora + efeitos para os jogadores.
  Bots de música na nuvem (Rythm, Groovy) sofreram derrubadas por copyright e não tocam arquivos locais/Spotify;
  compartilhar tela com áudio tem qualidade ruim e trava o canal de vídeo; cabos virtuais (VB-Cable/Voicemeeter) são complicados.
- Kenku roda localmente como "navegador + player" e injeta o áudio em um bot do próprio usuário (token fornecido pelo usuário).

## Concorrentes / vizinhos
| Alternativa | Rota técnica | Diferença |
|---|---|---|
| Bots de música (Rythm, Jockie, Groovy) | servidor na nuvem baixa/transmite streams | sem arquivos locais, sem DRM (Spotify), sujeito a takedown |
| Syrinscape / Tabletop Audio / Soncraft | conteúdo curado + player próprio (web/app) | são fontes de conteúdo; Kenku pode tocá-los dentro do navegador embutido |
| VB-Cable / Voicemeeter + conta pessoal | roteamento de áudio do SO | genérico, difícil de configurar, mistura voz do mestre |
| Screen share do Discord | captura de aba/tela | qualidade/bitrate limitados, ocupa o stream |
Posição do Kenku: "cola" local entre qualquer fonte de áudio web/local e um bot de voz Discord.

## Por que um projeto próprio
- Nenhuma combinação existente dá: navegador com DRM (Widevine via Electron castlabs) + mixagem de várias abas + entrada no Discord como bot + soundboard controlável por Stream Deck.
- Organizacional: Owlbear Rodeo (VTT) — Kenku complementa o ecossistema de ferramentas de mesa virtual; gratuito.

## História técnica (blog "Kenku FM Discord Derby", blog.owlbear.rodeo)
- Pipeline original: Web Audio mix → buffer em thread separada → WebSocket → Opus (WASM) → Discord. Problemas: latência pelo buffering e CPU alto em máquinas fracas.
- Tentativa: WebRTC (Opus nativo, UDP). Lib WebRTC Node sem ARM → protótipos em Go ("Disgo") e Rust ("Severus", via Neon). Rust venceu pela integração com Electron; teste em i5-6500 sob 50% de stress sem engasgos.
- No repositório: branch `main` (v1.5.x estável) mantém pipeline JS (AudioWorklet → WS → prism-media Opus → @discordjs/voice); branches `experimental/v1.6.x` contêm `severus/` (Rust: rtc.rs, voice_connection.rs, dave.rs, encrypt.rs) e gateway Discord próprio em `src/discord/`.
- v1.5.5 (2026-03): suporte ao protocolo DAVE (E2EE do Discord) — via @snazzah/davey + discord.js/@discordjs/voice 0.19.
- README ainda cita Eris, mas o código usa discord.js — documentação defasada.

## Fontes
- https://github.com/owlbear-rodeo/kenku-fm , /releases
- https://blog.owlbear.rodeo/kenku-fm-discord-derby/
- https://alternativeto.net/software/kenku-fm/about/
- https://startplaying.games/blog/posts/best-dnd-audio-tools-software-app
- Site kenku.fm/docs não renderizou via fetch (SPA) — "não encontrado".
