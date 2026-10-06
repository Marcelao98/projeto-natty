# Capítulo 6 — Módulos secundários: a UI que orquestra conexões, abas e saídas

> Ponte: o motor de áudio captura, o bot transmite e o controle remoto comanda o player, mas tudo isso precisa de uma UI que orquestre conexões, abas e saídas. Esse papel é do renderer principal em `src/renderer/`: umas 3 mil linhas de React, Redux Toolkit e MUI que funcionam como painel de controle do mestre de RPG.

## Visão geral do renderer

- Ponto de entrada: `index.tsx` monta `ThemeProvider > ErrorBoundary > Provider(store) > PersistGate > App`.
- `App` desenha só duas coisas: `ActionDrawer` (coluna lateral de 240px com bookmarks, entradas, saídas e configurações) e `Tabs` (barra de abas e barra de URL). O conteúdo das abas **não** é React. São `WebContentsView` nativas que o main sobrepõe à janela nas coordenadas que o renderer informa (ver `getBounds`).
- Toda a comunicação com o main passa por `window.kenku`, exposto pelo preload principal (`src/preload.ts:183`). O padrão é sempre o mesmo: comandos imperativos (`window.kenku.joinChannel(...)`) e eventos push (`window.kenku.on("DISCORD_READY", ...)`) que viram `dispatch` no Redux.
- Na maioria dos fluxos, **a UI é a fonte de verdade**. O Redux guarda o que o usuário escolheu, e o main executa sem devolver um estado consolidado. As exceções são conexão (`DISCORD_READY/DISCONNECTED`), guilds/canais (`DISCORD_GUILDS`, `DISCORD_CHANNEL_JOINED/LEFT`) e metadados de aba (`BROWSER_VIEW_*`).

---

## 6.1 `app/` — store, App, theme

1. **Responsabilidade:** montar o store Redux com persistência, a casca visual (`App`) e o tema MUI escuro.
2. **Papel no todo:** é a raiz de estado e de layout de que todas as features dependem.
3. **Implementação:** `combineReducers` de 7 slices embrulhado em `persistReducer` (redux-persist com `storage` = `localStorage` do Chromium), `whitelist: ["bookmarks", "settings"]` e migrações versionadas.
4. **Detalhes especiais:**
   - **O que é persistido:** apenas `bookmarks` e `settings` (`app/store.ts:65`). Abas, player, saídas, entradas e status de conexão são voláteis. Toda sessão começa só com a aba do Kenku Player e a saída `"local"` (`output/outputSlice.ts:22`).
   - **Token do bot em texto puro:** `settings.discordToken` (`features/settings/settingsSlice.ts:7`) entra no JSON que o redux-persist grava sob a chave `persist:root` no `localStorage` do renderer. No disco, isso fica no LevelDB `Local Storage` do diretório `userData` do Electron. O projeto não usa `safeStorage`/keychain (nenhuma ocorrência de `safeStorage` em `src/main`). Na tela, o campo é `type="password"` (`Settings.tsx:97`), o que só esconde o valor visualmente. Qualquer processo com acesso ao perfil do usuário lê o token. Para um app desktop de uso pessoal, o risco é tolerável, mas é a dívida de segurança mais concreta da UI. [a verificar pelo agente principal: se as `WebContentsView` de sites de terceiros usam partição/sessão separada da janela principal; se compartilharem origem com `localStorage`, o risco seria maior. Como o origin da UI é `file://`/webpack, o isolamento por origem deve bastar.]
   - **Migrações:** `version: 4` (`store.ts:63`), mas só existem as migrações `2` e `3` (`store.ts:33-59`). A versão 4 foi incrementada sem migração correspondente. Isso é inofensivo com `createMigrate`, mas indica que o histórico de schema não está documentado.
   - `App.tsx:33-52` trata três canais de notificação do main: `MESSAGE` (snackbar de 4s), `ERROR` (alerta de 8s) e `FATAL_ERROR`, que troca a UI inteira por uma tela de erro e não oferece como se recuperar.
   - Tema (`theme.ts`): paleta escura com roxo `#bb99ff`, `borderRadius` 16 e ripple desligado globalmente (`theme.ts:28-31`).
5. **Arquivos:** `app/store.ts`, `app/App.tsx`, `app/theme.ts`, `app/App.css`, `index.tsx`.

---

## 6.2 `features/tabs` — abas, TabBar, URLBar, getBounds

1. **Responsabilidade:** representar no Redux as abas de navegador (cada uma com uma `WebContentsView` no main) e oferecer UI para criar, selecionar, reordenar, fechar, silenciar, favoritar e navegar.
2. **Papel no todo:** materializa a filosofia "cada fonte de som é uma aba". A aba é a unidade de captura de áudio, e esta feature é a única porta de entrada para criá-las.
3. **Implementação:** `tabsSlice` normalizado (`byId`/`allIds`). Os componentes chamam `window.kenku.createBrowserView(url, x, y, w, h)` e, com o `id` devolvido (o id da view no main), fazem `addTab` + `selectTab`.
4. **Detalhes especiais:**
   - **Como a UI informa a posição da view (`getBounds.ts:3-12`):** `x = drawerWidth` (240, constante exportada por `ActionDrawer`), `y = clientHeight` do elemento `#controls` (TabBar + URLBar), `width = innerWidth - 240` e `height = innerHeight - y`. A geometria depende do layout DOM do renderer, e o main apenas obedece. `Tabs.tsx:184-195` reenvia `setBrowserViewBounds` sempre que mudam a aba selecionada, a visibilidade da URL bar (`urlBarEnabled`) ou o fato de a aba ser o player (no player, a URL bar some e a view sobe).
   - **Redimensionamento da janela** não passa pelo renderer. O main escuta `resize` e recalcula só a `topView` a partir de `window.getBounds()` (`src/main/managers/BrowserViewManagerMain.ts:72-85`). [a verificar pelo agente principal: `getBounds()` da janela devolve o tamanho externo, com moldura, e não `getContentBounds()`, o que pode deixar a view alguns pixels maior que a área útil no Windows/Linux com moldura nativa. Como a UI usa `WindowControls` próprios (frameless?), talvez não haja diferença.] As views ocultas só recebem novos bounds quando voltam a ser selecionadas, via o efeito citado.
   - **Efeitos colaterais dentro de reducer:** `selectTab` chama `window.kenku.hideBrowserView` e `showBrowserView` dentro do reducer (`tabsSlice.ts:45-51`). Isso viola a pureza de reducers do Redux, porque replays do Redux DevTools ou time-travel disparam IPC. Funciona na prática, mas acopla o estado à ordem de dispatch. O lugar certo seria um listener middleware ou thunk.
   - **Ids falsy:** `editTab` lança erro se `!action.payload.id` (`tabsSlice.ts:53`), e `selectTab` só esconde a aba anterior `if (state.selectedTab)` (`tabsSlice.ts:46`). Um id `0` quebraria os dois. [a verificar pelo agente principal: como o main gera ids (`webContents.id` começa em 1, então o risco é baixo).]
   - **Re-registro de listeners:** o `useEffect` de `Tabs.tsx:51-182` depende de `[player.tab.id, tabs]`. A cada mudança em qualquer aba (título, favicon, contador de mídia), ele remove e re-registra os 7 listeners IPC. Isso evita closures obsoletas, mas causa churn constante, já que `BROWSER_VIEW_MEDIA_*` e `TITLE_UPDATED` chegam com frequência. Um `useRef` para o estado atual resolveria.
   - **Favicon propaga para bookmarks:** ao receber `BROWSER_VIEW_FAVICON_UPDATED`, a UI atualiza o ícone de todos os bookmarks com o mesmo **hostname** (`Tabs.tsx:95-115`). Já `TabItem` decide se a aba "está favoritada" por **URL exata** (`TabItem.tsx:37-39`). São critérios inconsistentes, embora inofensivos.
   - **Contador de mídia:** `BROWSER_VIEW_MEDIA_STARTED_PLAYING/PAUSED` incrementam ou decrementam `playingMedia`. O ícone de volume só aparece com mídia tocando e permite mudo por aba (`window.kenku.setMuted`, `TabItem.tsx:51-72`).
   - **Atalhos vindos do main:** `BROWSER_VIEW_NEW_TAB` e `BROWSER_VIEW_CLOSE_TAB` [a verificar pelo agente principal: origem provável é `window.open` e os atalhos Ctrl+T/Ctrl+W no menu do main], que nunca fecha a aba do player (`Tabs.tsx:157-171`). A mesma lógica "selecionar a anterior ou o player" está duplicada em `TabItem.tsx:106-119`.
   - **URLBar:** normaliza com `prependHttp` (acrescenta `https://`) e `@braintree/sanitize-url` antes de chamar `loadURL` (`URLBar.tsx:22-26`). O `sanitizeUrl` troca `javascript:` e similares por `about:blank`, uma defesa leve e bem-vinda.
   - **Bug: drag & drop quebrado com `over` nulo.** Em `TabBar.tsx:56`, `if (active.id !== over.id)` lança `TypeError` quando a aba é solta fora de qualquer alvo, porque o dnd-kit devolve `over: null`. O mesmo acontece em `BookmarkListItems.tsx:71`. O `dragId` fica preso, e o `DragOverlay` pode continuar visível até o próximo drag.
   - `TabBar` usa `ResizeObserver` para entrar em "modo abas pequenas" (<150px por aba, com histerese até 180px). Nesse modo, o ícone e o botão de fechar das abas não selecionadas ficam ocultos (`TabBar.tsx:71-118`).
5. **Arquivos:** `features/tabs/tabsSlice.ts`, `Tabs.tsx`, `TabBar.tsx`, `TabItem.tsx`, `URLBar.tsx`, `AddTabButton.tsx`, `getBounds.ts`.

---

## 6.3 `features/bookmarks`

1. **Responsabilidade:** lista persistente de sites favoritos (título, URL, ícone), reordenável, editável e removível, que abre uma nova aba ao ser clicada.
2. **Papel no todo:** é a "biblioteca" do mestre: o atalho para as fontes de som recorrentes (Tabletop Audio, YouTube, Spotify, arquivos locais) e um dos dois únicos estados que sobrevivem ao reinício.
3. **Implementação:** `bookmarksSlice` normalizado com ids `uuid` (criados em `TabItem.tsx:80`). A lista usa dnd-kit (`SortableContext` vertical). O diálogo `BookmarkSettings` edita URL e título com dispatch a cada tecla.
4. **Detalhes especiais:**
   - Clicar num bookmark **sempre cria uma aba nova** (`BookmarkListItem.tsx:27-47`), sem checar se já existe aba aberta com a mesma URL. É coerente com "cada fonte é uma aba", mas permite duplicar fontes de áudio sem querer.
   - `editBookmark` não verifica se o id existe (`bookmarksSlice.ts:42-45`), diferente de `editTab`. Um id inexistente criaria um bookmark parcial. Hoje os chamadores só passam ids válidos.
   - O ícone (`bookmark.icon`) é uma URL remota de favicon renderizada em `<img>` (`BookmarkListItem.tsx:101`). Offline, o ícone some.
   - **Bug: drop de arquivo local.** `BookmarkSettings.tsx:32-38` e `URLBar.tsx:32-38` chamam `getDropURL`, que usa `window.player.getPathForFile` (`common/drop.ts:13`). Esse `window.player` só é exposto pelo preload **do player** (`src/player/preload.ts:81`). A janela principal usa `MAIN_WINDOW_PRELOAD_WEBPACK_ENTRY` (`src/index.ts:41`), que expõe apenas `kenku` (`src/preload.ts:183`). Soltar um arquivo na URL bar ou no campo de URL do bookmark lança `TypeError: Cannot read properties of undefined` dentro do handler. O erro é engolido silenciosamente, porque erros de handlers não chegam ao ErrorBoundary, e o `preventDefault()` já foi chamado, então nada acontece. O mais provável é que `drop.ts` tenha sido copiado de `src/player/common` sem adaptar a API.
5. **Arquivos:** `features/bookmarks/bookmarksSlice.ts`, `BookmarkListItems.tsx`, `BookmarkListItem.tsx`, `BookmarkSettings.tsx`.

---

## 6.4 `features/connection`

1. **Responsabilidade:** guardar o status da conexão do bot Discord (`disconnected | connecting | ready`).
2. **Papel no todo:** é o semáforo que habilita o campo de token, alterna o botão Connect/Disconnect e exibe o convite "Connect Discord for more outputs" no drawer.
3. **Implementação:** slice de 25 linhas com um único reducer, `setStatus`. Quem dispara a conexão é o componente `Settings` (6.7), não esta feature.
4. **Detalhes especiais:**
   - Transições: a UI marca `connecting` de forma otimista (`Settings.tsx:57,66`). O main confirma com `DISCORD_READY` e sinaliza queda com `DISCORD_DISCONNECTED` (`Settings.tsx:75-87`). [a verificar pelo agente principal: se o main emite `DISCORD_DISCONNECTED` quando o login falha (token inválido); se não emitir, a UI fica presa em `connecting`, com o botão desabilitado e o campo de token bloqueado, sem como corrigir o token até reiniciar.]
   - O status **não é persistido**. O reconnect automático ao abrir o app vem do token persistido (6.7).
   - O tipo `ConnectionStatus` está duplicado em `settingsSlice.ts:3`, sem uso ali.
5. **Arquivos:** `features/connection/connectionSlice.ts`.

---

## 6.5 `features/output` — canais de voz e "This Computer"

1. **Responsabilidade:** listar guilds e canais de voz do bot e deixar o usuário escolher para onde o áudio mixado vai: canais do Discord e/ou a saída local (`"local"` = loopback nos alto-falantes).
2. **Papel no todo:** fecha o circuito do produto, ligando a captura das abas ao destino do som. É onde a UI dispara `joinChannel`, `leaveChannel` e `setLoopback`.
3. **Implementação:** `outputSlice` guarda `guilds` (recebidas por `DISCORD_GUILDS`) e `outputs: string[]` (ids de canal ou `"local"`). `OutputListItems.handleChannelChange` traduz cliques em comandos IPC, com dois modos conforme `settings.multipleOutputsEnabled`.
4. **Detalhes especiais:**
   - **Múltiplas saídas: sim.** Com `multipleOutputsEnabled`, cada clique alterna o canal (`OutputListItems.tsx:55-94`). A UI conhece a regra do Discord de que um bot só pode estar em **um canal de voz por guild**: antes de entrar num canal, ela monta o mapa `canal → guild` e sai do canal já selecionado na mesma guild (`OutputListItems.tsx:70-90`). É conhecimento de domínio do Discord vivendo no renderer.
   - **Modo simples:** sai do canal anterior (ou desliga o loopback) e entra no novo (`OutputListItems.tsx:95-117`). O comentário "Only leave channel if selecting a different guild" (`:107`) não bate com o código, que sempre chama `leaveChannel(prev)`.
   - **Fonte de verdade híbrida:** a UI aplica a seleção de forma otimista (`setOutput`/`addOutput` antes do IPC), e o main confirma ou corrige via `DISCORD_CHANNEL_JOINED` (que chama `addOutput`) e `DISCORD_CHANNEL_LEFT` (que chama `removeOutput`) (`:38-45`). [a verificar pelo agente principal: se uma falha em `joinChannel` (falta de permissão, por exemplo) resulta em `DISCORD_CHANNEL_LEFT` ou só em `ERROR`; no segundo caso, o canal fica marcado como selecionado sem estar conectado.]
   - **Problema: desligar "Multiple Outputs" não reconcilia.** `Settings.tsx:270-272` só inverte a flag. Se houver 3 saídas ativas, as três continuam conectadas e destacadas (`selected`), o `tick` some, e o próximo clique no modo simples só sai de `outputs[0]` (`OutputListItems.tsx:96,108`). As outras saídas ficam "órfãs" até o usuário religar o modo múltiplo. O mesmo problema existe em "Multiple Inputs".
   - `outputs` começa como `["local"]` e não é persistido. [a verificar pelo agente principal: se o main inicia com loopback ligado para ficar coerente com esse estado inicial da UI.]
5. **Arquivos:** `features/output/outputSlice.ts`, `OutputListItems.tsx`, `OutputListItem.tsx`.

---

## 6.6 `features/input` — entradas externas (microfone, interface de áudio)

1. **Responsabilidade:** listar dispositivos `audioinput` do sistema e iniciar ou parar a captura de cada um para mixá-lo ao stream.
2. **Papel no todo:** estende "cada fonte de som é uma aba" para fontes físicas (mesa de som, microfone, loopback virtual). É uma feature opcional, atrás da flag `externalInputsEnabled`.
3. **Implementação:** `navigator.mediaDevices.enumerateDevices()` no próprio renderer (`InputListItems.tsx:28-34`) e, para cada seleção, `window.kenku.startExternalAudioCapture(deviceId)` / `stopExternalAudioCapture`. [a verificar pelo agente principal: a captura em si acontece na janela oculta de `AudioCaptureManagerMain`, e o renderer só envia o `deviceId`.]
4. **Detalhes especiais:**
   - O componente só é montado quando `externalInputsEnabled` está ligado (`ActionDrawer.tsx:77`). O cleanup do `useEffect` de montagem **para todas as capturas** ao desligar a flag (`InputListItems.tsx:36-48`). Esse é o único lugar em que o ciclo de vida de um componente React desliga recursos no main, o que é elegante mas frágil, porque qualquer remontagem acidental interrompe a captura.
   - Sem listener de `devicechange`, dispositivos conectados depois da montagem não aparecem até o usuário desligar e religar a flag.
   - `enumerateDevices` só devolve `label` se houver permissão de mídia concedida. [a verificar pelo agente principal: se o main concede automaticamente via `setPermissionRequestHandler`; senão, os rótulos podem vir vazios.]
   - Modo simples: clicar de novo no mesmo dispositivo o desliga (toggle), diferente das saídas, em que o segundo clique não faz nada (`InputListItems.tsx:64-68` vs `OutputListItems.tsx:99-101`).
   - Nome de tipo copiado: `inputSlice.ts:8` declara `interface OutputState` para o estado de entrada.
5. **Arquivos:** `features/input/inputSlice.ts`, `InputListItems.tsx`, `InputListItem.tsx`.

---

## 6.7 `features/settings` — token, remote, streaming mode e flags

1. **Responsabilidade:** persistir as preferências do usuário (token, endereço e porta do remote, modo de streaming, URL bar, entradas e saídas múltiplas) e exibir o diálogo de configurações.
2. **Papel no todo:** na prática, é o **orquestrador de boot** da UI. Além de configurar, o componente `Settings` inicia a conexão Discord, o servidor remoto e a captura de áudio ao montar.
3. **Implementação:** `settingsSlice` (9 campos, todos persistidos) mais o componente `Settings`, um `Dialog` fullscreen de 240px. Ele fica **sempre montado** dentro da `Toolbar` do `ActionDrawer` (`ActionDrawer.tsx:69-72`) e só alterna `open`.
4. **Detalhes especiais:**
   - **Efeitos de boot escondidos num diálogo:**
     - `Settings.tsx:64-73`: se houver token salvo, marca `connecting` e chama `window.kenku.connect(token)`. No unmount, chama `disconnect()`.
     - `Settings.tsx:160-167`: se `remoteEnabled` estiver salvo, chama `playerStartRemote(address, port)`.
     - `Settings.tsx:234-236`: `window.kenku.startAudioCapture(settings.streamingMode)`, ou seja, **toda a captura de áudio do app começa porque o diálogo de configurações foi montado**.
     Funciona porque o componente nunca é desmontado. Ainda assim, é um acoplamento surpreendente: mover `<Settings>` para renderização condicional (`{open && <Settings/>}`) derrubaria o bot, o remote e a captura. Esses efeitos deveriam morar em `App` ou num hook `useBootstrap`.
   - **Streaming mode** (`lowLatency | performance`, default `performance` desde a migração 3): só vale após reiniciar (`Settings.tsx:250-253`, "Restart to apply change"), porque `startAudioCapture` roda uma única vez. [a verificar pelo agente principal: o que cada modo muda no motor de áudio (tamanho de buffer, codec, caminho de IPC); esse é o elo com o próximo capítulo.]
   - **Remote, fonte de verdade dupla:** `handleRemoteToggle` grava `settings.remoteEnabled` antes de saber se o servidor subiu (`Settings.tsx:137-148`). O main responde `PLAYER_REMOTE_ENABLED`, que atualiza **outro** campo, `player.remoteEnabled` (`PlayerTab.tsx:38-41`), e esse campo não é lido por nenhum componente do renderer. Se a porta estiver ocupada, a UI mostra "Stop Remote" com o servidor parado. [a verificar pelo agente principal: se o main emite `PLAYER_REMOTE_ENABLED(false)` ou `ERROR` quando `listen` falha.]
   - **Bug: validação de endereço e porta inócua.** `inputProps={{ pattern: "d{1,3}.d{1,3}.d{1,3}.d{1,3}" }}` (`Settings.tsx:182`) e `pattern: "d+"` (`:198`) perderam a barra invertida: casam a letra `d`, não dígitos. Além disso, os campos não estão dentro de um `<form>`, então `pattern` nunca é avaliado. Na prática, não existe validação, e qualquer string vai para `playerStartRemote`. O endereço padrão `127.0.0.1` é seguro, mas o usuário pode trocar para `0.0.0.0` e expor o remote na LAN. [a verificar pelo agente principal: o capítulo do remote deve dizer se há autenticação.]
   - **Token:** campo `password`, desabilitado enquanto não está `disconnected` (`Settings.tsx:91-108`), e cada tecla faz um dispatch que o redux-persist grava. O token vai inteiro para o main via `window.kenku.connect(token)` a cada boot. Veja 6.1 sobre o armazenamento em texto puro.
   - **Clear Cache:** `await window.kenku.clearCache()` (`Settings.tsx:275-279`), sem `try/finally`. Se a promise rejeitar, o spinner fica girando para sempre.
   - Nome copiado: o slice exporta `connectionSlice` (`settingsSlice.ts:30`), mas o `name` é `"settings"`.
5. **Arquivos:** `features/settings/settingsSlice.ts`, `features/settings/Settings.tsx`.

---

## 6.8 `features/player` — PlayerTab

1. **Responsabilidade:** criar e representar a aba fixa "Kenku Player" (o player interno de playlists e soundboards) na TabBar.
2. **Papel no todo:** é a primeira fonte de som do app, sempre presente e impossível de fechar, e a aba que o controle remoto comanda.
3. **Implementação:** `playerSlice` inicializa a aba com `url` e `preload` obtidos **de forma síncrona** do main no carregamento do módulo (`playerSlice.ts:16-17`: `window.kenku.playerGetURL()` / `playerGetPreloadURL()`, via `ipcRenderer.sendSync`, que responde com `event.returnValue` em `PlayerManager.ts:91`). `PlayerTab` cria a view com esse preload, registra a view no main (`playerRegisterView`) e a seleciona (`PlayerTab.tsx:16-35`).
4. **Detalhes especiais:**
   - A aba do player é a **única view com preload próprio** (`player.tab.preload`). As outras abas são Chromium puro, o que materializa a separação "player nosso vs. web de terceiros".
   - O id `-1` serve de sentinela até a view existir. Os handlers de `Tabs.tsx` comparam `viewId === player.tab.id` para desviar título, favicon e contador de mídia para o `playerSlice`, e assim o título da aba do player nunca é sobrescrito.
   - Mudo do player: `setMuted` no `playerSlice` (`TabItem.tsx:59-60`).
   - `remoteEnabled` do playerSlice: ver o problema de fonte dupla em 6.7.
   - `sendSync` durante o import bloqueia o renderer até o main responder, mas acontece uma única vez no boot e tem custo desprezível.
5. **Arquivos:** `features/player/PlayerTab.tsx`, `features/player/playerSlice.ts`.

---

## 6.9 `common/` — ErrorBoundary, ActionDrawer, WindowControls, drop e utilitários

1. **Responsabilidade:** componentes transversais: o drawer lateral, os controles de janela customizados, o boundary de erro, o wrapper de item ordenável e os helpers de drag & drop de arquivos e de scrollbar.
2. **Papel no todo:** a moldura visual e de segurança dentro da qual as features vivem.
3. **Implementação:** componentes MUI simples. `showWindowControls = platform !== "darwin"` decide entre botões próprios de minimizar, maximizar e fechar (Windows/Linux) e os "semáforos" nativos (macOS).
4. **Detalhes especiais:**
   - **ErrorBoundary** (`ErrorBoundary.tsx:42-45`): além de exibir o stack, chama `window.kenku.removeAllBrowserViews()`. Isso é essencial, porque as `WebContentsView` são nativas e ficam **por cima** do DOM. Sem essa limpeza, a tela de erro ficaria escondida atrás das páginas. É um detalhe que só quem entende o modelo de janela composta lembraria.
   - Ele fica **fora** do `Provider` e do `PersistGate` (`index.tsx:21-22`), então também captura erros de reidratação.
   - **ActionDrawer:** a toolbar tem `WebkitAppRegion: "drag"` (a janela é arrastada por ela) e, com duplo clique, maximiza (`ActionDrawer.tsx:49-56`). Também exporta a constante `drawerWidth = 240`, que `getBounds` usa, e é aí que o layout CSS e a geometria nativa ficam acoplados.
   - **drop.ts:** `encodeFilePath` gera `file://` URLs a partir de caminhos locais (inclusive `\` do Windows). No renderer principal, porém, `getDropURL` depende de `window.player`, que não existe ali (bug descrito em 6.3). `cleanFileName` não é usado no renderer principal, o que indica cópia do módulo equivalente do player.
   - `useHideScrollbar`: esconde a scrollbar do drawer quando o ponteiro sai.
5. **Arquivos:** `common/ActionDrawer.tsx`, `ErrorBoundary.tsx`, `WindowControls.tsx`, `SortableItem.tsx`, `drop.ts`, `showWindowControls.ts`, `useHideScrollbar.ts`.

---

## Síntese: onde mora a verdade

| Estado | Fonte de verdade | Persistido? | Sincronização |
|---|---|---|---|
| Token, flags, remote, streaming mode | Redux (`settings`) | Sim, localStorage em texto puro | UI → main em comandos no boot (`connect`, `playerStartRemote`, `startAudioCapture`) |
| Bookmarks | Redux | Sim | Nenhuma com o main (só abrem abas) |
| Abas (lista, ordem, seleção) | Redux | Não | UI → main (`create/show/hide/remove/setBounds`), main → UI (`BROWSER_VIEW_*` para título, URL, favicon e mídia) |
| Geometria das views | DOM do renderer (`getBounds`) | — | UI → main por aba selecionada; o main redimensiona só a `topView` no `resize` |
| Status Discord | Main | Não | Main → UI (`DISCORD_READY/DISCONNECTED`), com `connecting` otimista |
| Guilds/canais | Main | Não | Main → UI (`DISCORD_GUILDS`) |
| Saídas selecionadas | Redux (otimista) | Não | UI → main (`join/leave/setLoopback`), main → UI (`CHANNEL_JOINED/LEFT`) |
| Entradas externas | Redux | Não | UI → main (`start/stopExternalAudioCapture`), sem confirmação |
| Remote ativo | Ambíguo (`settings.remoteEnabled` × `player.remoteEnabled`) | Parcial | A confirmação do main vai para um campo que ninguém lê |

## Problemas encontrados (resumo)

| # | Severidade | Local | Problema |
|---|---|---|---|
| 1 | Média (segurança) | `app/store.ts:65`, `settings/settingsSlice.ts:7` | Token do bot persistido em texto puro no localStorage; sem `safeStorage` |
| 2 | Média (bug) | `common/drop.ts:13` | `window.player` indefinido no renderer principal; drop de arquivo na URL bar e no bookmark falha em silêncio |
| 3 | Baixa (bug) | `tabs/TabBar.tsx:56`, `bookmarks/BookmarkListItems.tsx:71` | `over.id` com `over === null` quando o item é solto fora do alvo, gerando TypeError |
| 4 | Baixa (bug) | `settings/Settings.tsx:182,198` | Regex de `pattern` sem `\`, e os campos estão fora de `<form>`: nenhuma validação de endereço e porta |
| 5 | Média (design) | `settings/Settings.tsx:64-73,160-167,234-236` | Boot de Discord, remote e captura de áudio dentro de um diálogo de configurações |
| 6 | Média (estado) | `settings/Settings.tsx:137-148`, `player/PlayerTab.tsx:38-41` | `remoteEnabled` otimista; a confirmação do main vai para um campo não lido |
| 7 | Baixa (estado) | `settings/Settings.tsx:266-272` | Desligar "Multiple Outputs/Inputs" não reconcilia as saídas e entradas já ativas |
| 8 | Baixa (arquitetura) | `tabs/tabsSlice.ts:45-51` | IPC dentro de reducer (`selectTab`) |
| 9 | Baixa (desempenho) | `tabs/Tabs.tsx:182` | Os 7 listeners IPC são re-registrados a cada mudança em `tabs` |
| 10 | Baixa | `settings/Settings.tsx:275-279` | `clearCache` sem `finally`; o spinner pode travar |
| 11 | Cosmética | `store.ts:63`, `settingsSlice.ts:30`, `inputSlice.ts:8`, `OutputListItems.tsx:107` | Versão 4 sem migração, nomes copiados (`connectionSlice`, `OutputState`), comentário que contradiz o código |

## Avaliação

A UI é **pragmática e legível**: slices pequenos, componentes diretos e zero abstração além do necessário, o retrato de uma equipe pequena. Três decisões merecem destaque. A **geometria nativa controlada pelo DOM** (`getBounds`) é simples, mas acopla CSS e posição de views. O **ErrorBoundary que remove as views nativas** mostra entendimento fino do modelo de janela composta. A **regra de "um canal por guild" codificada no renderer** coloca uma restrição do Discord na camada de apresentação. A fraqueza recorrente é a **sincronização otimista sem reconciliação**: saídas, remote e flags múltiplas confiam que o main fez o que foi pedido, e a confirmação, quando existe, nem sempre volta para o lugar certo.

## Cobertura de leitura (modo Padrão, mínimo 30%)

| Arquivo (src/renderer/) | Linhas totais | Linhas lidas | Cobertura % | Motivo não lido |
|---|---|---|---|---|
| app/App.css | 39 | 0 | 0% | CSS de layout, irrelevante para a arquitetura |
| app/App.tsx | 104 | 104 | 100% | — |
| app/store.ts | 84 | 84 | 100% | — |
| app/theme.ts | 70 | 70 | 100% | — |
| common/ActionDrawer.tsx | 97 | 97 | 100% | — |
| common/ErrorBoundary.tsx | 87 | 87 | 100% | — |
| common/SortableItem.tsx | 36 | 36 | 100% | — |
| common/WindowControls.tsx | 39 | 39 | 100% | — |
| common/drop.ts | 30 | 30 | 100% | — |
| common/showWindowControls.ts | 2 | 2 | 100% | — |
| common/useHideScrollbar.ts | 30 | 30 | 100% | — |
| features/bookmarks/BookmarkListItem.tsx | 134 | 134 | 100% | — |
| features/bookmarks/BookmarkListItems.tsx | 115 | 115 | 100% | — |
| features/bookmarks/BookmarkSettings.tsx | 108 | 108 | 100% | — |
| features/bookmarks/bookmarksSlice.ts | 62 | 62 | 100% | — |
| features/connection/connectionSlice.ts | 25 | 25 | 100% | — |
| features/input/InputListItem.tsx | 60 | 60 | 100% | — |
| features/input/InputListItems.tsx | 106 | 106 | 100% | — |
| features/input/inputSlice.ts | 43 | 43 | 100% | — |
| features/output/OutputListItem.tsx | 60 | 60 | 100% | — |
| features/output/OutputListItems.tsx | 187 | 187 | 100% | — |
| features/output/outputSlice.ts | 52 | 52 | 100% | — |
| features/player/PlayerTab.tsx | 51 | 51 | 100% | — |
| features/player/playerSlice.ts | 55 | 55 | 100% | — |
| features/settings/Settings.tsx | 387 | 387 | 100% | — |
| features/settings/settingsSlice.ts | 76 | 76 | 100% | — |
| features/tabs/AddTabButton.tsx | 45 | 45 | 100% | — |
| features/tabs/TabBar.tsx | 180 | 180 | 100% | — |
| features/tabs/TabItem.tsx | 179 | 179 | 100% | — |
| features/tabs/Tabs.tsx | 214 | 214 | 100% | — |
| features/tabs/URLBar.tsx | 111 | 111 | 100% | — |
| features/tabs/getBounds.ts | 12 | 12 | 100% | — |
| features/tabs/tabsSlice.ts | 98 | 98 | 100% | — |
| index.tsx | 37 | 37 | 100% | — |
| **Total** | **3015** | **2976** | **98,7%** | ✅ (mínimo 30%) |

Leituras de apoio fora do escopo, para confirmar hipóteses: `src/main/managers/BrowserViewManagerMain.ts:68-92` (listener de resize), além de buscas por `exposeInMainWorld`/`getPathForFile`/`preload:` em `src/` (confirmam o bug de `drop.ts`).

> Até aqui, a UI trata o áudio como uma caixa-preta: chama `startAudioCapture(streamingMode)` e confia que o som chegará ao Discord. No próximo capítulo, abrimos essa caixa e acompanhamos a evolução do motor de áudio, do pipeline em JavaScript no processo main da v1.5.5 às reescritas em Rust nas branches experimentais.
