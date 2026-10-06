# 07 — Validação cruzada (agente principal)

## 7.1 Portão de cobertura
Todos os rascunhos têm tabela e estão ✅ — nenhuma leitura complementar necessária.
| Módulo | Cobertura | Meta |
|---|---|---|
| Pipeline de áudio | 100% (975/975) | 90% |
| Shell Electron | 100% (1596/1596) | 60% |
| Player | 97,0% (4926/5076) | 60% |
| Controle remoto | 100% (1089/1089) | 60% |
| UI (secundário) | 98,7% (2976/3015) | 30% |

## 7.2 Checagem no código (amostras)
| Conclusão | Resultado |
|---|---|
| WS `new WebSocketServer({ port: 0 })` sem host, sem auth; toda mensagem → `encoder.write` (AudioCaptureManagerMain.ts:42,102-104,169-171) | ✅ confirmado. `ws` sem host → `server.listen(port)` → todas as interfaces |
| Buffer do worklet: lowLatency = 960 int16 intercalados = 10 ms; performance = 48000 = 500 ms (Preload.ts:82-85; worklet :14-15) | ✅ confirmado; comentários dizem 20 ms / 1 s |
| `drop.ts:13` usa `window.player`; importado por URLBar.tsx:12 e BookmarkSettings.tsx:12; janela principal só expõe `kenku` (preload.ts:183) | ✅ bug confirmado (dois agentes independentes) |
| SoundboardRemote.tsx:66-75 registra listener sem cleanup | ✅ confirmado; os outros efeitos do arquivo/PlaylistRemote têm cleanup |
| Captura disparada por BROWSER_VIEW_LOADED, 1x por view (flag `loaded`, BrowserViewManagerMain.ts:121-127); preload da UI faz o relay (preload.ts:48-51) | ✅ confirmado |
| Player capturado pelo mesmo caminho | ✅ PlayerTab cria view via mesmo `_handleCreateBrowserView` (só muda o preload) |
| Nenhum `setPermissionRequestHandler`/`setPermissionCheckHandler` em src/ | ✅ confirmado → padrão Electron (aprovar) vale para abas de terceiros |
| HTMLs sem CSP (src/index.html, player, audioCapture) | ✅ confirmado |
| SessionManager duplo no boot: `new SessionManager` após `loadURL` e de novo em `did-start-loading` (index.ts:56-69) | ✅ confirmado; destroy antes de new → nunca dois vivos simultâneos |

## 7.3 Pendências "[a verificar]" resolvidas
- Login falho deixa UI presa em `connecting`? **Não**: `_handleConnect` responde DISCORD_DISCONNECTED no catch e no `client.on("error")` (DiscordBroadcast.ts:59-104).
- Join falho → canal marcado sem conexão? **Sim** quando canal não é `joinable` (sem else, :121) — UI fica marcada sem feedback.
- Ordem de criação: SessionManager (e a janela oculta de captura) é recriado em `did-start-loading` da janela principal; o React monta depois do bundle carregar. A janela de captura carrega em paralelo — corrida teórica, normalmente vencida pela captura (HTML/preload local mínimo). Mantido como risco, não bug observado.
- Private Network Access (CSRF no remote): Chromium 138 do Electron 37 não bloqueia "simple requests" públicas→loopback por padrão (bloqueio/permissão de Local Network Access chegou depois). Não testado; risco mantido como baixo.
- Duas sessões respondendo ao remote: não ocorre (destroy precede new).
- Abas de terceiros sem preload → não conseguem forjar IPC; o risco de `event.sender` fica restrito a renderers próprios comprometidos.

## 7.4 Padrões transversais
1. **"Aba = fonte" como unidade de composição**: webContents.id é a chave compartilhada por Redux de abas, captura (`viewId`), mute e PlayerManager.
2. **Main como relé sem estado**: AudioCaptureManagerMain (7 relays), PlayerManager (remote), BrowserViewManagerMain (aplica bounds). Estado mora nos renderers (Redux).
3. **Componentes React invisíveis como adaptadores de efeito colateral**: Settings (boot!), *PlaybackSync, PlaylistMediaSession, *Remote. Elegante, mas amarra ciclo de vida de recursos ao ciclo de vida de componentes → bugs de cleanup (SoundboardRemote) e boot escondido em diálogo.
4. **Otimismo sem reconciliação**: saídas, remoteEnabled, multiple outputs — UI assume sucesso; confirmação do main às vezes não existe ou cai em campo não lido.
5. **IPC por strings duplicadas em 3–4 lugares, sem checagem de remetente e sem correlação**.
6. **Segurança "loopback é confiável"**: WS de áudio em todas as interfaces, remote sem auth, token em localStorage, sem permission handler — coerente com app pessoal, mas as bordas estão abertas.
Todos os capítulos conectam-se à filosofia (reuso do Chromium, equipe de 2) — ✅.
