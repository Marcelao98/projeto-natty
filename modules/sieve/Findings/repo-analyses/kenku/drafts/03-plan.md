# 03 — Plano de análise: Kenku FM

- Repo: https://github.com/owlbear-rodeo/kenku-fm @ dd534f1 (v1.5.5, 2026-03-04)
- Modo: **Padrão** — core ≥60%, secundário ≥30%
- Foco (usuário): **pipeline de áudio no centro**
- Introdução/concorrentes: **versão curta**
- Idioma do relatório: português

## Escala (linhas efetivas; sem testes no repo)
| Diretório | Linhas | Papel |
|---|---|---|
| src/ (raiz: index, preload, menu, bounds, autoUpdate) | ~600 | entrypoints main/preload |
| src/main | 1422 | processo main: managers, Discord, API remota |
| src/preload | 398 | captura de áudio (preload), worklet PCM |
| src/audioCapture | 58 | janela oculta de captura |
| src/renderer | 2976 | UI principal (abas, conexões, settings) — React/Redux |
| src/player | 5374 | player interno (playlists, soundboards) — React/Redux |
| src/types | 64 | tipos compartilhados |
| **Total** | **~10.9k** | |
Ignorado: yarn.lock, publish/*.sh, .github workflows, webpack/forge configs (lidos só para estrutura).

## Observações iniciais
- README diz que usa Eris; código usa discord.js + @discordjs/voice (drift de documentação).
- Captura: janela oculta (sandbox:false) → Web Audio → AudioWorklet PCM → WebSocket localhost (porta 0) → main → prism Opus → AudioPlayer do Discord.
- Electron da castlabs (Widevine) para Spotify/DRM; spoof de user agent para Google.
- Política "open source, not open contribution".
