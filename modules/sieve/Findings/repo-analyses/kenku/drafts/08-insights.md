# 08 — Insights de arquitetura

## Filosofia sistêmica
"O Chromium é o motor; nós escrevemos a cola." Três corolários:
1. **Aba = fonte** — composição por isolamento de processo. Toda capacidade nova (player local, efeitos) vira "mais uma aba", herdando captura, mute e mix sem código de áudio novo.
2. **Main sem estado, renderers com Redux** — o main é roteador de IPC e dono de recursos nativos (janelas, sockets, Discord). Estado de produto vive em 2 stores Redux (UI, player).
3. **Zero nativo** — opusscript (WASM) em vez de @discordjs/opus, tab capture em vez de loopback do SO, Howler/HTML5 em vez de decodificadores. Resultado: 3 SOs × 2 arquiteturas com equipe de 2.

## Consistência da filosofia
- Consistente: pipeline, player, remote seguem o padrão.
- Onde ela range: (a) tempo real — reuso do Chromium dá captura mas não dá relógio/jitter buffer; (b) DRM exige fork castlabs (dependência de terceiro); (c) o experimento Severus rompe o "zero nativo" exatamente onde a filosofia cobra seu preço (latência/CPU) — e continua experimental há anos, o que é revelador.

## Dívidas sistêmicas (não bugs isolados)
- Bordas abertas (WS de áudio, remote HTTP, IPC sem sender, token em claro, sem permission handler).
- Ciclo de vida acoplado a componentes React (boot em Settings, listeners em *Remote).
- Estado otimista sem reconciliação.
- Zero testes/lint no CI.

## Se eu redesenhasse (prioridade por custo/benefício)
1. Endurecer bordas (1 dia): WS `host:127.0.0.1` + token (ou MessagePortMain); remote com token + checagem Host/Origin; `safeStorage` para token; `setPermissionRequestHandler`; validar `event.sender`.
2. Contrato IPC tipado único (`invoke` genérico) + `requestId` no remote.
3. `useBootstrap`/`AppController` fora do diálogo de Settings; handlers remotos fora do React (store.getState()).
4. Tempo real sem sair do Chromium: WebCodecs `AudioEncoder` (Opus nativo do Chromium) + MessagePort; jitter buffer adaptativo no main; recriar AudioResource em Idle. Captura ~80% do ganho do Severus sem Rust.
5. Player: modelo `Collection` genérico, fila com uma semântica, listener middleware.
