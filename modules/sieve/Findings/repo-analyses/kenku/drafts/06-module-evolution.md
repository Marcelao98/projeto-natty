# 06 — Evolução: motor JS (main) vs Severus (experimental/v1.6.7) — notas do agente principal

Fonte: branch experimental/v1.6.7 (último commit 2026-03-04, mesmo dia do v1.5.5), blog "Kenku FM Discord Derby".

## Diferença essencial de arquitetura
- main: Chromium mixa (Web Audio) → AudioWorklet emite PCM → WebSocket localhost → main Node codifica Opus (prism-media/opusscript) → @discordjs/voice empacota RTP, criptografa, DAVE (@snazzah/davey) → UDP Discord.
- experimental: Chromium mixa → **o próprio WebRTC do Chromium codifica Opus** (RTCPeerConnection local, src/audioCapture/RTCConnection.ts/RTCStream.ts) → peer WebRTC em **Rust** (crate `webrtc` 0.11, severus/src/rtc.rs:36-110) recebe RTP Opus → `Broadcast` (severus/src/broadcast.rs) faz fan-out via DashMap<u32, flume::Sender<Packet>> para N conexões de voz → `rtc_udp` reempacota/criptografa (encrypt.rs: aes-gcm/xchacha20; dave.rs com crate davey) e envia UDP ao Discord.
  - Sem reencode: o pacote Opus produzido pelo Chromium é repassado. Isso elimina o encoder JS/WASM e o buffering do worklet — exatamente as dores descritas no blog (latência + CPU).
  - Fan-out nativo: um stream → várias guilds/canais (o "multiple outputs").
- experimental também abandona discord.js: gateway e voice gateway próprios em TS (src/discord/gateway/*, src/discord/voice/{VoiceGateway,VoiceConnection,DaveControlPlane}.ts), permissões e REST mínimos (src/discord/http/*). Controle (sinalização/gateway) em TS; plano de dados (RTP/UDP/crypto) em Rust.
- Exportações Neon (severus/src/lib.rs:14-77): voiceConnection*, daveSession*, rtc*, broadcast, log*.

## Leitura
- Separação clássica control plane (TS) / data plane (Rust). Mesmo padrão de Lavalink e de SFUs.
- Custo: toolchain Rust + Neon por plataforma (Windows ARM sem assinatura no 1.5.5; Linux ARM), reimplementar gateway Discord e DAVE (MLS) — alto para equipe de 2 pessoas. Explica por que o "stable" continua em JS: discord.js absorve mudanças do Discord (DAVE veio "de graça" com @discordjs/voice 0.19 + davey).
- Duas linhas mantidas em paralelo (~15 branches experimental/v1.6.x) = custo de manutenção dobrado; releases experimentais com os mesmos fixes.
- Branches de exploração no remoto contam a história: feature/stream-worklet, feature/stream-sender-worker, feature/stream-worker-2, feature/SAB (SharedArrayBuffer), buffer-scaling, fix/audio-slowdown, feature/rtc-stream, disgo, experimental/severus-{SAB,librtc,opus-buffer}.
