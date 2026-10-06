# 05 — Módulos e linha narrativa

Narrativa: **orientada ao fluxo do som** (fonte → captura → mix → encode → Discord), depois quem controla as fontes.

0. Panorama: 3 processos/entrypoints (main, janela principal, player view, janela oculta de captura) — main agent
1. [B] Fontes de som: shell Electron + navegador embutido (WebContentsView, Widevine, UA spoof, sessão)
   →[cada aba é uma fonte de áudio isolada; como tirar o som dela sem compartilhar tela?]→
2. [A] Pipeline de áudio (CENTRO): captura por aba + inputs externos → Web Audio mix → AudioWorklet PCM → WS localhost → Opus → @discordjs/voice/DAVE
   →[o som chega ao Discord; mas o mestre precisa de música local e efeitos — daí o player interno, que é só mais uma "aba"]→
3. [C] Player interno: playlists/soundboards, Redux + persistência, motor de reprodução (Howler/HTMLAudio)
   →[o player vive num web view isolado; como um Stream Deck o controla?]→
4. [D] Controle remoto: Fastify HTTP → PlayerManager → IPC → preload do player → componentes *Remote
   →[tudo isso precisa de uma UI que orquestre conexões e saídas]→
5. [E, secundário] UI shell (renderer): abas, bookmarks, conexão, input/output, settings
6. Evolução: main (JS) vs experimental (Rust Severus/WebRTC) — main agent, contraste

## Atribuição de arquivos
- A (core, foco, alvo 90%): src/main/managers/{AudioCaptureManagerMain,PlaybackManager}.ts, src/main/broadcast/DiscordBroadcast.ts, src/preload/managers/{AudioCaptureManagerPreload.ts,PCMStream.worklet.js}, src/audioCapture/*, trechos de áudio em src/preload.ts
- B (core, 60%): src/index.ts, src/preload.ts, src/main/managers/{SessionManager,BrowserViewManagerMain,WindowManager}.ts, src/preload/managers/BrowserViewManagerPreload.ts, src/main/userAgent.ts, src/menu.ts, src/bounds.ts, src/autoUpdate.ts, forge.config.js, webpack.*.js
- C (core, 60%): src/player/** exceto *Remote.tsx e player/preload.ts; src/types/player.ts
- D (core, 60%): src/main/managers/PlayerManager.ts, src/main/remote/**, src/player/preload.ts, src/player/features/*/{PlaylistRemote,SoundboardRemote}.tsx
- E (secundário, 30%): src/renderer/**
