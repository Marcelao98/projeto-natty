# Changelog

## Bardo, etapa 7: ambientes, efeitos e cenas - 2026-10-12

- `/som enviar|tocar|parar|volume|geral|ducking|lista|apagar|cena-salvar|cena|cenas`.
- Sons em `data/som/<servidor>/<sha256>.<ext>` (fora do git), lista branca de extensão, limite de 20 MB, áudio repetido recusado; registro na tabela `sons` do `bardo.db`.
- Ambiente = loop com fade; efeito = one-shot decodificado em memória (cache), com ducking da música; som tipo música vai pra fila (`som:<servidor>/<arquivo>`).
- Volume geral (master) e profundidade do ducking por servidor; cenas salvam/aplicam ambientes, volumes, master, ducking e playlist.
- Painel: comandos de som e cena, upload (`enviar_som`) e pré-escuta (`arquivo_do_som`) no `ControleBardo`.
- Testes com ffmpeg real gerando os arquivos. **Falta ouvir o ducking ao vivo.**

## Bardo, etapa 6: mixer (música como camada) - 2026-10-12

- `modules/bardo/mixer.py`: `MixerSource(discord.AudioSource)` em numpy — soma de camadas (música, ambiente, efeito) com thread leitora e ~1 s de buffer por stream, fila de comandos sem lock no caminho quente, rampas contra clique, ducking (ataque ~50 ms, soltura ~400 ms) e limiter suave.
- O motor toca a música pelo mixer: pausar/pular/parar mexem só na camada de música, sem parar o player nem a escuta do Echo. `/volume` vira o ganho do bus de música; sai o `PCMVolumeTransformer`.
- O mixer vive no motor: reconexão (ou o Echo trocando a conexão) recebe o mesmo mixer e a música continua.
- `numpy` explícito no `requirements.txt` (o `audioop` saiu do Python 3.13).
- Testes com PCM sintético e ffmpeg real (soma, rampa, fim, pausa sem consumir, ducking, limiter, loop, stream lento não trava, tempo de mistura). Bug achado nos testes e corrigido: efeito que acabava nunca saía da mistura.
- **Falta validar ao vivo**: áudio real na call e reconexão com o Echo.

## Bardo, etapa 5: o painel controla o player - 2026-10-12

- `ControleBardo.executar`: tocar (link ou busca), pausar/continuar, pular, parar, volume, repetir (faixa/fila/desligar), remover, limpar a fila, tocar/salvar/listar playlists — pelo mesmo caminho do Discord, com argumentos validados e o cargo de mestre conferido.
- WebSocket e `POST /api/g/<id>/cmd` aceitam os comandos; autorização revista a cada mensagem (quem sai do servidor perde a conexão).
- Pedido do painel toca na call em que a Natty está; avisos da fila não vão mais pra "canal nenhum".
- Testes: Bardo 175, Painel 18.

## Bardo, etapa 4: motor separado e painel web (leitura) - 2026-10-12

- `modules/bardo/motor.py`: o player (tocar, pular, reconectar, sair da call) saiu do cog; o cog só traduz comando. `eventos.py`: pub/sub que o motor alimenta a cada mudança.
- `bot.controles["bardo"]` (`ControleBardo`): estado em JSON, assinatura de eventos e checagem de mestre — o jeito de uma superfície falar com o Bardo sem importar o módulo.
- Novo `modules/painel/`: aiohttp no mesmo loop do bot, só em 127.0.0.1; login OAuth2 do Discord com state anti-CSRF; sessão em cookie HttpOnly/SameSite=Lax; WebSocket com o estado ao vivo; origem e autorização conferidas ao vivo. Front em HTML/JS/CSS puros. Liga só com `DISCORD_CLIENT_SECRET`.
- Testes: Bardo 166, Painel 14.

## Bardo, etapa 3: banco próprio, playlists e cenas por servidor - 2026-10-12

- `data/bardo.db` (fora do git) com `storage.py` como único lugar que fala SQL: playlists, sons, cenas e descobertas, tudo por servidor.
- `/playlist salvar|tocar|listar|ver|apagar` e `@Natty toca a playlist <nome>`; apagar só quem criou ou o cargo **Condutor** (`BARDO_CARGO_MESTRE`).
- Descobertas do "era essa?" vão pra camada do servidor; a busca vê o `musicas.json` global + as do servidor.
- Cenas já gravam/carregam (usadas pelo mixer nas próximas etapas).
- Testes: Bardo 162.

## Bardo, etapa 2: outras fontes - 2026-10-12

- Qualquer link que o yt-dlp entende (SoundCloud, Bandcamp, link direto...); set do SoundCloud e álbum do Bandcamp entram como playlist; `LinkNaoSuportado` pra site desconhecido.
- `@Natty toca` com áudio anexado toca o anexo.
- Pasta local `data/musicas/` (`BARDO_PASTA_LOCAL`, fora do git): busca pelo nome do arquivo depois do dataset e antes do YouTube; caminho preso à pasta.
- Testes: Bardo 146.

## Bardo, etapa 1: fila completa - 2026-10-12

- **Playlist do YouTube**: `@Natty toca <link da playlist>` (ou `/tocar`) põe a playlist inteira na fila (até 50), pulando vídeos privados/apagados. Link de vídeo com `&list=` continua tocando só o vídeo.
- **Remover da fila**: `@Natty tira a 3 da fila` e `/remover posicao:3`.
- **Repetir a fila inteira**: `@Natty repete a fila` / `loop da playlist` / `repete tudo`. Um repetir desliga o outro; pular não desliga o da fila; música que falha não volta pro fim (senão falharia em loop).
- **`/repetir`** com `modo` (a música atual, a fila inteira, desligar).
- **Sair da call vazia**: 60 s depois da última pessoa sair, a Natty para, limpa a fila e sai. Não sai quando a conexão é do Echo (quem decide lá é o Echo).
- **Erros com motivo**: `youtube.py` traduz o yt-dlp em `VideoPrivado`, `RestricaoDeIdade`, `SoParaMembros`, `BloqueadoNaRegiao`, `VideoIndisponivel`, `PlaylistIndisponivel`, `NadaEncontrado`. A mesa vê o motivo; busca sem resultado não gera mais traceback.
- **Correções**: `@Natty toca Volta pra Casa` / `Próxima Parada` agora é busca (o verbo de tocar vindo primeiro manda); `@Natty volume 30` ia pra 100% porque os dígitos do id da menção viravam o número; `@Natty adiciona na fila Garçom` não busca mais "na fila Garçom".
- O bug do "era essa?" aceitando qualquer mensagem já estava corrigido desde 02/10 (só reply); só o README estava desatualizado.
- Socorro e READMEs atualizados.
- Testes: Bardo 135 (eram 91), Echo 125, Dice, Socorro e Core sem mudança.

## Projeto Natty público - 2026-10-06

- Repositório publicado como **Projeto Natty**, com histórico novo. Nomes e usuários reais de jogadores nos testes, exemplos e no changelog foram trocados por nomes fictícios.
- Adicionados `LICENSE` (MIT, a arte fica de fora) e o aviso de uso responsável do Bardo.
- Os registros anteriores abaixo vêm do repositório de desenvolvimento.

## README com a apresentação da Natty - 2026-10-06

- O topo do README virou a porta de entrada: arte da Natty (`docs/img/natty.jpg`), apresentação em primeira pessoa (designação NAT/20-01-XR7-∆9, origem em Nhalor, o que ela é: um bot de Discord pra facilitar a vida de quem mestra RPG de mesa), tabela do que ela faz pela mesa, linha do tempo e privacidade.
- O manual técnico anterior (comandos, arquitetura, instalação, rodar 24h) foi mantido inteiro, abaixo de "Manual completo".

## /registrar-missao e /missoes - 2026-10-05

- **`/registrar-missao`** substitui o Google Forms de missões. Comando com nome, data (DD/MM/AAAA), dificuldade (lista), XP, gold e participantes (personagens separados por vírgula); depois um formulário com relato (obrigatório), resultado, outras recompensas e observações.
- Tudo é conferido **antes** do formulário (`service.conferir_missao`, sem gravar) e de novo na transação: nome único, data válida e não futura, dificuldade, XP/gold ≥ 0, participantes registrados. Nome errado vem com sugestão ("**Aldrick** (você quis dizer **Aldric**?)").
- Condutor = quem roda o comando (cargo **Viajante**); `condutor_nome` segue o padrão das antigas (nome do jogador).
- XP e gold digitados pelo condutor: a tabela de XP base da guilda não está documentada e os valores históricos não fecham numa fórmula.
- **`/missoes`** lista as missões (mais recentes primeiro) com data, dificuldade, condutor, XP, gold e participantes.
- Erebos: "Sal Dorn" → Sal (id 11) e "Tavi" → Tomas Vale (id 5) ligados (nome histórico mantido; backup `vincular-erebos`).
- storage: `existe_missao`, `listar_participantes`. Socorro e READMEs atualizados.
- Testes: Core 91.

## Importação das missões históricas (aplicada) - 2026-10-05

**Aplicada em 05/10 às 21:09** (backup `natty-20261005-210944-importar-missoes.db`): 4 missões atualizadas, 3 inseridas, 1 participante sem personagem (Lucy, em "Pra onde foi o nosso lixo", pra cadastrar). Segunda rodada: 0 atualizadas, 0 inseridas, então é idempotente de verdade.
- Decisões (em `data/importacao/decisoes_missoes.json`): "O Neto de Tholu" é a "Vovó está preocupada" (id 3, o nome do banco foi mantido); relatos do banco mantidos nas 4 existentes; Tavi jogou com Tomas Vale em Nhalor e no Navio; Nhalor em 24/09/2026.
- Agora são 7 missões no banco: Prefeito-Cavalo, Profundezas, Vovó/Neto de Tholu, Erebos, Nhalor, Pra onde foi o nosso lixo, Navio que Grita.
- O JSON foi movido da raiz pra `data/importacao/missoes_historicas.json`.
- Herdado do Sheets e não mexido (regra: participantes de missão existente ficam intocados): na Erebos, "Sal Dorn" e "Tavi" estão sem personagem vinculado.


- `scripts/importar_missoes_historicas.py`: dry-run por padrão, grava só com `--aplicar` e recusa enquanto houver pendência. As respostas às perguntas vão num JSON de `--decisoes`. Idempotente (testado: a segunda rodada não insere nem atualiza nada) e com backup antes de gravar.
- Schema: as colunas pedidas (`resultado`, `xp`, `gold`, `outras_recompensas`, `observacoes`, `condutor_discord_id`) **já existiam** desde a migração do Sheets; nenhuma alteração de schema.
- `storage.py`: `listar_missoes_completas`, `preencher_missao` (grava só em campo vazio, nunca sobrescreve) e `sobrescrever_missao` (só com decisão explícita).
- Resolução de menção → jogador: igual ao username/apelido, depois parcial, depois dono do personagem com esse nome ("Vexil" hoje não é apelido de ninguém, é personagem do @usuario_exemplo).
- Primeiro dry-run no banco real (sem gravar; checksum do banco igual antes e depois): 3 missões a atualizar, 4 a inserir, 1 participante sem personagem (Lucy), 9 pendências. Achados: "O Neto de Tholu" é provavelmente a "Vovó está preocupada" do Forms (mesma data, dificuldade e participantes, nome diferente); os relatos do banco são versões mais longas que os do post (em 2 deles o relato do banco já contém o resultado).
- Testes: Core 85.

## Registro com história livre e data de criação - 2026-10-05

- O formulário do `/registrar-personagem` ganhou o campo **"História (escreva o quanto quiser)"**: caixa de texto grande, com a dica "Do seu jeito: uma linha já vale, ou conte tudo. Limite de 4000 caracteres." É obrigatória, mas do tamanho que o jogador quiser: uma linha já vale.
- Limite de 4000 caracteres (`MAX_HISTORIA`, o máximo de um campo de formulário do Discord), conferido no formulário e de novo no service. Vazia ou maior → mensagem clara ("Conta um pouco da história… até uma linha só já vale" / "passou do limite… a sua tem N"), sem consultar o DiceCloud.
- **Data de criação:** já era gravada sozinha (`criado_em`); agora aparece na confirmação ("**Kael** registrado em 05/10/2026 com nível **4**!") e no `/personagens` ("· desde 05/10/2026"). Nos personagens migrados, é o carimbo do Google Forms.
- Banco: schema **v3**, coluna `personagens.historia`. A Natty migra sozinha ao subir, com backup `schema-v2` antes. Ensaiado numa cópia do banco real: 14 personagens, 4 missões e as datas antigas intactos; os migrados ficam sem história.
- `registrar_personagem` recebe `historia` e devolve `criado_em`; `listar_personagens` devolve `criado_em`. Socorro atualizado.
- Testes: Core 76 (novos: história gravada, uma linha vale, limite exato, vazia, acima do limite, migração v1 → v3 com personagem).

## README reescrito - 2026-10-05

- O README raiz estava parado antes da Escriba e dos controles de música por voz. Reescrito pelo que a mesa usa: Personagens, Dados, Música, Voz, Ata da sessão (Escriba) e Ajuda, cada um com tabela de comandos e link pro README do módulo.
- Novo: aviso de que a Natty só atende com **@Natty** de verdade (menos rolagem), seção de Privacidade (gravações e banco fora do git; fora da Escriba a voz não é guardada), comandos de voz completos (próxima, repete, pausa, continua, pare), repetir do Bardo, `faster-whisper`/`large-v3-turbo` nos requisitos, contagem de testes por módulo e seção de Manutenção.
- Instalação e operação 24h mantidas; o script de criação da tarefa agendada foi pra um bloco recolhível.

## Registro barra ficha que não existe e diz o motivo de cada recusa - 2026-10-05

- Antes, qualquer problema com a ficha virava a mesma mensagem genérica ("Não consegui confirmar sua ficha…"). Agora `consultar_ficha_dicecloud` devolve o motivo e cada um tem sua mensagem (`ERROS_FICHA`): **não existe**, **privada**, **nome diferente** (mostrando o nome que está na ficha), **sem nível**, **DiceCloud fora do ar**.
- Link falso barrado na entrada: o ID da ficha tem que ter o formato do DiceCloud (17 caracteres, sem 0/1/I/O/l). Link quebrado ou inventado responde "Opa, essa ficha não existe no DiceCloud" na hora, sem ir à internet. Os 11 links do DiceCloud que já estavam no banco passam no formato.
- ID com formato certo mas inexistente: a API responde `400 "No such document exists"` → mesma mensagem, em menos de 1s.
- Erro 4xx não é mais repetido (antes, uma ficha inexistente fazia 2 chamadas); só timeout, rede e 5xx tentam de novo. A conexão do erro HTTP agora é fechada (vazava).
- **Bug achado no ensaio com a API real:** o corpo do erro vem compactado em gzip, e sem descompactar o "não existe" virava "privada". Corrigido, com teste.
- `buscar_nivel_atual_dicecloud` continua (usado pelo `sincronizar_niveis.py`), agora por cima da função nova.
- Ensaio real numa cópia do banco: link inventado → "não existe"; link quebrado e de outro site → recusados sem rede; ficha real com nome errado → mostra o nome certo; ficha real → registrada.
- A resposta da API pra uma ficha **privada de verdade** ainda não foi vista; tratada como qualquer recusa de permissão sem "No such document".
- Testes: Core 71.

## NAT-CORE sai do Google Sheets e vai pra SQLite local - 2026-10-05

**1. Banco novo (`data/natty.db`).**
- `modules/core/storage.py` substitui o `sheets.py` (apagado). Tabelas: `jogadores`, `personagens`, `missoes`, `missao_participantes`. Schema versionado (`PRAGMA user_version`, hoje v2) com migrações automáticas e backup antes de migrar.
- Escritas em `BEGIN IMMEDIATE`, chaves estrangeiras ligadas, WAL. O registro de personagem busca o nível no DiceCloud fora da transação e confere limite e nome de novo dentro dela (dois registros ao mesmo tempo não furam o limite de 2).
- Caminho configurável por `NATTY_DB_PATH`. O banco e os backups ficam fora do git (`.gitignore`), porque têm Discord IDs.

**2. Backups e recuperação.**
- Backup automático em `data/backups/` ao subir, antes de deletar personagem, antes de migrar schema e nos scripts que gravam. Ficam os 20 mais recentes.
- Banco corrompido, com versão desconhecida, ou que sumiu tendo backups → a Natty **não sobe** ("BANCO ILEGÍVEL" no log, código de saída 3) em vez de criar um banco vazio por cima. O `rodar_natty.bat` para o loop no código 3.
- `scripts/restaurar_banco.py` restaura um backup; o arquivo ruim é guardado como `data/natty.ilegivel-<data>.db`, nunca apagado.

**3. Tabela `jogadores` = todos os membros do servidor.**
- Ao subir e a cada 24h a Natty espelha a lista completa de membros (sem bots); `on_member_join/update/remove` e `on_user_update` cuidam do dia a dia. Quem sai fica com `ativo = 0`, não é apagado. Lista vazia é recusada pra uma falha da API não marcar todo mundo como "saiu".
- Precisa de `intents.members` (no `bot.py`) e do **Server Members Intent** no Developer Portal. `GUILD_ID` no `.env` se o bot estiver em mais de um servidor.

**4. Migração dos dados antigos (feita).**
- `scripts/migrar_sheets_para_sqlite.py` (`--simular`, `--recriar`) leu as abas Personagens e Missões; a planilha não foi alterada e fica de histórico. É o único lugar que ainda usa `gspread`/`credentials.json`.
- `scripts/sincronizar_membros.py` (+ `.bat` de duplo clique) e `scripts/vincular_jogadores.py` (interativo, com backup) ligaram os personagens e os condutores antigos aos Discord IDs.
- Resultado: 46 jogadores, 14 personagens (todos vinculados), 4 missões com 20 participantes.

**5. Documentação e consertos.**
- `modules/core/README.md` novo (banco, backups, "BANCO ILEGÍVEL", scripts). CLAUDE.md, README e `.env.example` atualizados; Socorro fala em "registro" em vez de "planilha".
- `rodar_natty.bat`: os caminhos `data\natty.db` e `scripts\restaurar_banco.py` tinham sido gravados com as barras invertidas viradas em quebra de linha (`\n`, `\r`), o que deixava um comentário partido virar um comando solto. Corrigido, com o arquivo em CRLF.

**Bardo:** duas faixas descobertas em mesa entraram no dataset como "não classificado" (Return of the Obra Dinn – Theme; Spectral Sails OST).

- Testes: Core 57 (novos: storage, service, scripts), Echo 125, Bardo 91, Socorro 7, Dice 107.

## Escriba mais rápida: 1 hipótese, todos os núcleos, fila e progresso - 2026-10-02

- Na 1ª sessão real, duas gravações (38 e 75 min de fala) passaram de 2h transcrevendo ao mesmo tempo, com o notebook 75% ocioso.
- `beam_size=1` (o padrão testava 5 hipóteses por trecho) e `cpu_threads` = núcleos físicos (6, era 4). Ganho esperado: 2-3x; falta medir numa gravação real.
- Uma transcrição por vez: a segunda pedida fica na fila ("📝 Na fila…"), e a mesma sessão não entra duas vezes.
- Progresso no log a cada 10%, com estimativa de quanto falta.
- **Causa principal achada:** o Whisper processa janelas de 30s e ~80% dos blocos tinham menos de 10s (336 chamadas pra 40 min de fala). Blocos seguidos da mesma pessoa agora vão em pacotes de até 28s, e `word_timestamps` devolve cada palavra pro horário do seu bloco. Ainda não medido com áudio real (o teste parou por falta de RAM).
- Idioma fixo em português: com idioma livre, o faster-whisper rodava a parte pesada do modelo duas vezes por chamada (uma só pra detectar o idioma).
- Transcrição retomável: cada pacote vai na hora pra `parcial.jsonl`, e uma nova tentativa continua de onde a anterior caiu, em vez de recomeçar do zero. Visto em 03/10: a transcrição caiu por falta de RAM (`mkl_malloc: failed to allocate memory`) com o Chrome e o Discord abertos num notebook de 7.4 GB.
- Testes: Echo 125.

## Menção obrigatória, reply no "era essa?" e Escriba com large-v3-turbo - 2026-10-02

**1. Só menção de verdade chama a Natty (exceto rolagem).**
- Bardo, Socorro e Echo agora exigem **@Natty** (usuário ou cargo). Escrever "natty toca…" sem @ não faz mais nada. Rolagem no chat continua sem precisar chamar ninguém.
- Saíram `chamou_a_natty`/`_CHAMOU_NATTY_RE` do Bardo (e os testes `ChamouANatty`); o Socorro ficou com uma regex só.
- Exceção pra voz: o Echo posta `🎙️ natty …` como mensagem da própria Natty, e o Bardo aceita essas mensagens (marcador 🎙) como se fossem menção — senão os comandos falados quebrariam.
- Textos de ajuda e READMEs passaram a ensinar `@Natty …`.

**2. A pergunta "Era essa mesmo?" do Bardo só aceita reply.**
- A resposta com os temas tem que ser **reply direto à mensagem da pergunta** (`mensagem_pergunta_id` na pendência, `registrar_pergunta_da_pendencia`, `eh_resposta_da_pendencia`). O reply não precisa de @. Mensagem solta ou reply a outra mensagem não conta.
- Motivo: um "transcrever" da conversa virou tema da faixa "Weight of the World: Piano Collections Version" — limpo no `musicas.json`.
- Pedidos normais continuam funcionando com a pergunta aberta (não bloqueia o Bardo).

**3. Escriba: comandos novos, confirmação, modelo melhor e parágrafos.**
- Comandos: `@Natty, grava a sessão` (ou "grava", "começa a gravar") → 🔴; `@Natty, para de gravar` (ou "pare a gravação") → 🛑 com a duração e a pergunta "transcrevo agora?". `@Natty, sim`/`pode`/`transcreve` transcreve; `@Natty, depois`/`não` deixa guardado. A pergunta vale 15 min.
- `@Natty, transcreve a sessão` a qualquer hora transcreve a gravação mais recente sem `ata.txt`.
- Modelo `large-v3-turbo` (int8) no lugar do `small`. O `distil-large-v3` pedido é só inglês, por isso não foi usado. Nomes da campanha vão como `hotwords` (`TERMOS_DA_CAMPANHA`). `condition_on_previous_text=False`: com `True` o turbo repetiu frase e pulou o fim de uma gravação real.
- A transcrição é feita em blocos cortados nas pausas reais ≥ 4.5s, e falas seguidas da mesma pessoa com pausa < 4.5s viram um parágrafo só na ata.
- Teste real (leitura de ~3 min): bem melhor que o `small` ("Natty", "Crossroads", "rolo os dados" certos), 110s pra transcrever, RAM ~833MB carregado / pico ~1.2GB. Ainda erra "Nhalor" → "Naylor".
- Parágrafo da ata limitado a 60s (`DURACAO_MAX_PARAGRAFO_SEGUNDO`): quem narra sem pausa vira vários parágrafos.

**Dataset do Bardo:** removida a faixa-lixo "【ENG DUB】 Useless? I Made My Village Unstoppable" (tema "escuta"), que entrou por engano como descoberta em mesa.

- Testes: Echo 117, Bardo 91, Socorro 7, Dice 107.

## Escriba: ata da sessão (grava tudo, transcreve no fim) - 2026-10-02

- **`@Natty transcreve`** começa a gravar a call — **todo mundo**, não só o dono da sessão — num `.wav` por pessoa em `logs/sessoes/<data-hora>/`; **`@Natty para de transcrever`** para e transcreve tudo de uma vez com faster-whisper `small` (int8, idioma livre, `vad_filter`), escrevendo `ata.txt` em ordem cronológica: `[HH:MM:SS] Nome: texto`. Sair da call com a gravação ligada fecha os arquivos e **não** transcreve (o áudio fica; dá pra transcrever à mão).
- **Por que grava e transcreve no fim, e não ao vivo:** a ata é lida depois; transcrever durante a sessão disputaria CPU com tudo, sem ganho nenhum. Substitui a versão "transcreve ao vivo" da branch `echo-transcricao` (que fica arquivada no GitHub).
- **Liga/desliga só por texto:** é coisa de começo e fim de sessão, e assim "pare/para/parar" não entram na grammar da senha.
- **Marcas de horário (`marcas.json`):** o Discord só manda áudio enquanto a pessoa fala, então o `.wav` de cada um é fala colada com fala — a posição no arquivo não é o horário. A cada volta da fala depois de uma pausa, o cog guarda `[posição, horário real]`, e a ata converte cada segmento por elas. Sem isso, horários errados e ordem embaralhada entre pessoas. (Preencher silêncio com zeros custaria ~115MB por pessoa por hora.)
- **faster-whisper recebe array, não caminho:** o 1.2.1 com o PyAV 19 quebra ao abrir arquivo (`TypeError: metadata_errors`).
- **Bug na regex de parar (da especificação):** procurava "transcri", mas "transcrever" é trans-cre-ver — "para de transcrever" caía no "transcrev" e LIGAVA a gravação. Agora `transcr`.
- **Bardo:** "@Natty para de transcrever" parava a música (o "para" é dele). Agora "para de X" só para a música se X for tocar/cantar/música.
- Testado offline de ponta a ponta (cog + modelo real, 2 vozes com pausas reais): ata certa e em ordem, ~32KB por segundo de fala, 25s pra transcrever 17s de fala contando a carga do modelo. Testes: Echo 104, Bardo 84.
- Socorro (ajuda "voz"), README do Echo, `CLAUDE.md` e `.gitignore` atualizados. Na branch `escriba`.
- Pendente: teste em call (2 pessoas, Bardo tocando junto, RAM no Gerenciador de Tarefas, tamanho dos `.wav`).

## Echo: controles do Bardo por voz (próxima, repete, pausa, continua) - 2026-10-02

- Depois da senha, **"próxima"/"pula"**, **"repete"**, **"para de repetir"**, **"pausa"** e **"continua"** postam `🎙️ natty <comando>` e o Bardo executa — ele já entendia todos por texto, então o Echo só traduz a palavra falada (`COMANDOS_DO_BARDO_POR_VOZ`). Antes, "próxima" falada virava `[unk]` e caía em "não entendi a rolagem": o Echo só repassava tocar e parar.
- **"para de repetir" é checado antes de "para"**: as duas começam igual, e sem isso desligar o loop pararia a música.
- Palavras conferidas no vocabulário do modelo: "loop" e "proxima" sem acento não existem — por voz é "repete" e "próxima".
- Testado com o Vosk real (voz sintética): 6 de 6 comandos certos; "Pula essa parte, vamos continuar" sem a senha não fez nada. Falta call real.
- Ficou de fora: volume por voz. Socorro (ajuda "voz"), READMEs do Echo e do Bardo atualizados. Testes do Echo: 94.
- **Validado em call (02/10, tarde):** "pausa", "continua" e "próxima" por voz funcionaram. "repete" ainda não foi testado por voz.
- A mensagem do "@Natty escuta" passou a listar todos os comandos de voz (rolagem, música, controles da música, sair).
- Achado no teste: "NAT20, por favor, para" falado **enquanto a janela de música está aberta** vira pedido de música (`Nativante para`) — a janela grava tudo. Pendência no README do Echo.

## Bardo: repetir a faixa atual ("natty repete") - 2026-10-02

- `natty repete` (ou `repetir`, `repita`, `loop`) liga a repetição da música que está tocando: quando ela acaba sozinha, volta do começo em vez de seguir a fila. Pedir de novo desliga; `natty para de repetir`, `repete não`, `chega de loop`, `desliga o repetir` desligam sempre. A Natty sempre diz qual estado ficou, e a `natty fila` mostra 🔁.
- Só a faixa atual — loop da fila inteira fica pra quando fizer falta.
- Pular desliga o repetir (senão a próxima também entraria em loop sem ninguém pedir); parar também. A cada volta a URL do YouTube é resolvida de novo (ela expira).
- "Repetir" é reconhecido antes de "parar" ("natty para de repetir" desliga o loop, não para a música), e depois de "toca" vira busca ("natty toca Repete Comigo").
- **Por voz ainda não funciona** — nem o repetir, nem "próxima": o Echo não repassa comando livre pro Bardo, só as palavras da grammar dele (tocar música, parar). Registrado como pendência no README do Echo, com o caminho pra fazer.
- Socorro (ajuda do Bardo) e README do Bardo atualizados. Testes do Bardo: 82 (16 novos).

## "NAT20, por favor, pare" para a música sem tirar a Natty da call - 2026-10-02

- **Echo:** depois da senha, "pare"/"para"/"parar" posta `🎙️ natty para` e o Bardo para a música; a Natty continua na call, escutando. As três palavras entraram na grammar da senha (fora dela virariam `[unk]` e sumiriam, como o "dê").
- **Bardo: "parar" não sai mais da call** (`natty para`, `natty chega`, `natty sai`, `/parar`): só para a música e limpa a fila. Quem tira a Natty da call agora é só o Echo ("saia" / "tampe os ouvidos").
- **Bug achado no caminho:** com o Echo escutando, a conexão é um `VoiceRecvClient`, e nele `stop()` para a música **e a escuta**. O Bardo usava `stop()` no parar e no pular — então até "natty pula" deixava a Natty surda pra senha. Agora os dois usam `_parar_audio()`, que chama `stop_playing()` quando existe (só na conexão do Echo) e `stop()` quando não; o Bardo continua sem importar o Echo.
- Efeito colateral: usando só o Bardo, sem o Echo, a Natty fica no canal depois de "natty para" (até alguém tirar). "Sair sozinha quando o canal esvaziar" segue pendente.
- **Pedido de música detecta o idioma** (`idioma=None` no Whisper) em vez de forçar português — pra nome em inglês ("Another Brick in the Wall") não sair aportuguesado.
- Socorro (ajuda do Bardo e da voz), README do Echo e do Bardo atualizados. Testes: Echo 88, Bardo 66 (novo `test_cog.py`: parar não desconecta, parar/pular não derrubam a escuta).
- **Validado em call (02/10, 11h):** "NAT20, por favor, para" parou a música e a Natty seguiu na call; "Take on me" saiu em inglês. Efeito colateral da detecção de idioma: com uma palavra só o Whisper chuta o idioma — "Garçom" saiu `Garçon` (grafia francesa). O primeiro pedido da sessão ainda levou 28.8s (modelo carregando na hora).
- **Bug registrado no Bardo (não corrigido):** o "era essa?" da busca livre aceita como resposta qualquer mensagem que chame a Natty — um "@Natty escuta" foi lido como "sim, tema: escuta" e gravou no acervo um vídeo errado (`【ENG DUB】 Useless? I Made My Village Unstoppable`), vindo de um pedido de música mal transcrito. Está no commit do dataset, à espera de decidir se sai. Pendência no README do Bardo.

## Echo escuta só quem mandou "escuta" - 2026-10-02

- Primeira sessão real com 4 pessoas na call (01/10/2026): saída por voz 4 de 4, "Garçom" e "Ela Partiu" tocaram, rolagem ok, e **nenhum disparo falso** — as 12 senhas foram todas de quem estava testando.
- O Discord já entrega o áudio de cada pessoa separado e o Echo já tinha um reconhecedor por pessoa, então as vozes nunca se misturaram. Mas ouvir a sala inteira gerou 332 frases de ruído (a conversa da mesa forçada em "favor", "rolo", "sai", "música" — palavras da grammar da senha), sujando o log e gastando CPU.
- Agora quem manda "@Natty escuta" vira o dono da sessão: só a voz dele é processada, e o áudio dos outros é descartado antes do Vosk. Outra pessoa assume mandando "@Natty escuta" de novo. A mensagem de entrada e a ajuda "voz" do Socorro avisam.
- Pedido de música: o "música" falado antes do nome não vai mais junto pro Bardo ("Música combate." → `combate`).
- Ainda aberto, visto no mesmo teste: o Whisper `base` erra nomes ("Trio Parada Dura" → `Tril para a da dura`, nome em inglês vira lixo) e o primeiro pedido da sessão levou 46s (o modelo carrega na hora, e o bot roda com prioridade baixa no Agendador). Opções registradas: carregar o Whisper no "escuta", subir a prioridade do processo, modelo `small`.
- Toda a voz (branch `echo-experimento`) entrou no `main` por fast-forward.
- Revisão da documentação: o README do Echo ganhou uma **lista única de pendências** (validar em call / melhorar / calibrar / remendo temporário) e marca como histórico as seções da época em que o Whisper detectava a senha; o status de música e "saia" passou a "validado em call". O README do Bardo registra a busca e o aprendizado em mesa como em uso real (17 faixas descobertas em mesa, 596 no total) e ganhou duas pendências vistas nos logs (busca livre sem resultado só gera traceback; título com "volta"/"próxima"/"fila" vira outro comando). A ajuda do Bardo no Socorro passou a mostrar a busca por texto ("natty toca Garçom"), não só link.
- Pendente: testar "escutar só o dono" com mais gente na call; revalidar reroll, moedas e nome do teste por voz.

## Comandos por voz: rolagem, música e saída da call - 2026-10-01

Depois da senha "NAT20, por favor", a Natty agora entende o que vem em seguida, falado na call:

- **Rolagem falada → Dice.** "dado vinte mais cinco com vantagem contra quinze" vira `🎙️ rolo 1d20+5 com vantagem contra 15` no canal, e o Dice rola. Cobre tudo que o Dice entende por texto: vários dados, bônus, vantagem, CD, explosivo, filtros (tirar/manter), teste por dado, reroll condicional, moedas (com peso e condicional) e nome do teste. Validado em call real: dado, bônus, vantagem, CD, vários dados, filtro, explosivo e teste por dado. O reconhecimento é um segundo Vosk com vocabulário de rolagem (`PALAVRAS_COMANDO_DADO`), e um parser estrito (`normalizar_comando_dado`) converte pro formato do Dice — se sobrar palavra que ele não entende, a Natty diz "não entendi" em vez de rolar errado.
- **Pedido de música → Bardo.** "NAT20, por favor, música" (ou "música" depois da senha) → a Natty grava o pedido, transcreve com Whisper quando a pessoa para de falar e posta `🎙️ natty toca <pedido>`; o Bardo toca como se alguém tivesse digitado (dataset, ou YouTube se não achar). Whisper aqui e não Vosk porque nome de música não cabe em lista fechada; como o Whisper não é streaming, o áudio é gravado e transcrito de uma vez. Testado offline com Whisper e busca reais; falta call real.
- **"NAT20, por favor, saia"** tira a Natty da call, igual ao "@Natty, tampe os ouvidos" (mesma função). "saia/sai/sair" sozinhos não fazem nada — "saia daqui, goblin" na conversa da mesa não derruba ninguém.
- **Por que o Echo posta texto em vez de chamar Dice/Bardo:** nenhum módulo importa outro (princípio do projeto, agora escrito no `CLAUDE.md`). Dice e Bardo ignoravam mensagem de bot; os dois passaram a aceitar **só** mensagem da própria Natty que comece com 🎙 (`MARCADOR_VOZ`). As respostas deles nunca começam com 🎙, então não há laço.
- **Por que o nome de quem falou não vai na mensagem da rolagem:** o Dice lê a mensagem inteira e reconhece "vantagem" até por abreviação (`vant`, `adv`, `dis`) — um apelido "Dis" viraria desvantagem. A rolagem é postada como resposta ao "👂 fala a rolagem, Fulano!", e o nome fica no encadeamento.

O que os testes em call ensinaram (e mudou o código):

- **"dado vinte", não "um dê vinte".** O "dê" nunca chegava no texto ("rola um dê vinte" saiu `rola vinte`): existe no vocabulário do modelo, mas uma letra sozinha é curta demais pra ele ouvir. "dado" é palavra comum e é como a mesa fala.
- **A senha engolia o começo da rolagem** (`'nate vinte por favor nate vinte'`). Na pausa o Discord para de mandar pacotes, então o Vosk não "ouvia" o silêncio e a frase da senha só fechava quando a pessoa voltava a falar. Agora quem fecha é a vigia, depois de 0.5s sem voz.
- **A rolagem era cortada em qualquer respiração** ("dado vinte… se vinte rola… dado cem" virava só `dado vinte`): o Vosk devolve "fim de frase" a cada pausa curta. Agora os pedaços se acumulam e a rolagem só fecha depois de 1.2s de silêncio.
- **"dados seis" é ouvido como "dezesseis"** (e "dados oito" como "dezoito"): como d16/d18 não são dados de mesa, "cinco dezesseis" vira `5d6`. Em CD e bônus, 16/18 continuam 16/18.
- **"três" é ouvido como "treze"** ("três moedas" saiu `treze moedas`): em posição de quantidade (dados, moedas, quantos tirar/manter) 13 vira 3; em CD e bônus continua 13.
- **O "e" do número some** ("vinte e dois" saiu `vinte dois`): dezena + unidade junta com ou sem o "e".
- Palavras novas da grammar sempre conferidas no vocabulário do modelo antes de usar ("arcanismo" e "furtividade" não existem; "saia", "música" e "dado" existem).

Também:

- **Socorro ganhou o tópico "voz"** (`natty socorro voz`, `/socorro modulo:voz`) com o guia dos comandos falados.
- `transcrever`/`transcrever_pcm` aceitam `dica` (o `initial_prompt` do Whisper); o pedido de música passa `dica=None`, porque a dica da senha atrapalharia o nome da música.
- `README.md`, `CLAUDE.md` (escopo, estrutura, convenção do 🎙, testes) e os READMEs de Echo, Dice, Bardo e Socorro atualizados.
- Testes: Echo 81 (dublês de Vosk e Whisper; ponta a ponta com o `roll()` do Dice e o `interpretar_pedido()` do Bardo de verdade), Dice, Bardo e Socorro passando.
- Pendente: validar em call a música, o "saia", o reroll depois da correção do corte, moedas e nome do teste; senha e comando numa frase só (hoje precisa de pausa depois da senha); a primeira transcrição de música da sessão é mais lenta (o Whisper carrega).

## Echo: senha detectada com Vosk em vez de Whisper - 2026-10-01

- A detecção de "NAT20, por favor" passou do Whisper (transcrição livre de todo trecho de fala) para o Vosk com grammar restrita: o reconhecedor só escolhe entre poucas frases fechadas + `[unk]`. Validado em call real: 3 de 3 ativações, sem falso positivo, resposta logo depois da pausa (antes a primeira transcrição da sessão levava 17-29s). CPU medida offline: ~2-3% do tempo de fala.
- Streaming: cada pacote de áudio vai para o `KaldiRecognizer` da pessoa (um por pessoa), e o próprio Vosk decide quando a frase terminou — saiu o buffer por silêncio e o laço de checagem. A regex `tem_wake_word` continua decidindo se o texto é a senha.
- "nat" não existe no vocabulário do modelo pt (o Vosk descartaria a palavra calado), então a grammar usa palavras existentes que soam parecido: nate, net, nata, neto, nathan. Em call real a voz caiu em "nate vinte por favor".
- A biblioteca do Vosk não abre caminho com acento no Windows (o projeto fica em "Repositórios"): `_caminho_ascii()` usa o caminho relativo ou o nome curto 8.3.
- Privacidade: com grammar fechada, conversa normal da mesa vira `[unk]` e é descartada — nada vira texto livre.
- O modelo `vosk-model-small-pt-0.3` (31MB) é baixado à mão em alphacephei.com/vosk/models para `modules/echo/assets/` e fica fora do git (README do Echo, "Como ativar"). `vosk` entrou no `requirements.txt`.
- Whisper e a regex continuam no `service.py`, para o futuro comando livre depois da senha.
- Antes do Vosk foi tentado o Porcupine (wake-word engine), descartado sem chegar ao main: a Picovoice encerrou o plano gratuito.

## Echo escutando em call real: DAVE decifrado e senha calibrada - 2026-09-30

- Módulo Echo ativado no `bot.py` e validado em call real: a Natty entra com "@Natty escuta", reconhece "NAT20, por favor" falado na call e responde a saudação (3 de 3 tentativas, nenhum falso positivo), e sai com "@Natty, tampe os ouvidos".
- **DAVE**: o `discord-ext-voice-recv` do PyPI não decifra a criptografia ponta a ponta que o Discord exige desde mar/2026 — o Opus recebia pacote cifrado (`OpusError: corrupted stream`), e o erro matava a thread de escuta. Novo `modules/echo/dave.py` decifra cada pacote com a sessão DAVE da própria conexão antes do buffer, descobre de quem é um SSRC pela chave que decifra (quando o evento SPEAKING não chegou), e transforma pacote ruim em silêncio em vez de derrubar a escuta. Faz o mesmo que o PR #54 do voice-recv (ainda aberto), sem instalar fork; apagar quando o PR sair no PyPI.
- **Senha**: sem ajuda, o Whisper escrevia o "NAT" errado ("NAA-20", "Enheá-te 20"). Agora a transcrição recebe a dica `"NAT20, por favor."` (`initial_prompt`), testado que silêncio/ruído continuam vazios; e a regex aceita qualquer palavra curta com "n" antes de "20, por favor" (pegou "Nath20, por favor" em call real).
- **Captura mais robusta** (`cog.py`): áudio sem dono conhecido é transcrito agrupado por SSRC em vez de descartado; trava no buffer entre a thread do voice-recv e o loop do bot; um trecho por vez no Whisper; trechos < 0.3s ignorados e fala contínua cortada em 15s; laço de checagem protegido; o modelo carrega em segundo plano no "@Natty escuta"; aceita a menção ao cargo @Natty.
- **Log `[echo]`** em `logs/natty.log`: texto que o Whisper ouviu em cada trecho, início/fim da escuta, erros com traceback, e contadores de diagnóstico a cada 5s (como ler no README do Echo).
- Frase de saída aceita também "tapa" e "tampem os ouvidos" (o comentário já prometia "tapa").
- Correções de Windows: `NamedTemporaryFile` aberto não pode ser reaberto pelo wave/ffmpeg — quebrava 100% das transcrições em silêncio; e `discord-ext-voice-recv` fixado em `>=0.5.2a179`, porque o PyPI só tem pré-release.
- Testes do Echo: 29 (novo `test_dave.py`, grafias reais do Whisper na senha).
- Pendente: a primeira transcrição de cada sessão levou 17-29s (depois 1-4s) — suspeita de modelo carregando e da prioridade baixa da tarefa agendada.

## Feminino no vocabulário e tags das descobertas do Bardo - 2026-09-29

- O vocabulário da busca passa a aceitar o feminino das palavras ("animada", "sombria", "assustadora"), tanto no que se digita quanto nos temas das faixas, sem precisar listar no `vocabulario.json`.
- Tags corrigidas nas 5 músicas aprendidas em mesa: Ragnar the Red, Clube da Esquina Nº2, Song of Storms, Garçom (Reginaldo Rossi, brega) e I Will Survive (disco, anos 70).

## Busca livre no YouTube e aprendizado por confirmação no Bardo - 2026-09-29

- "natty toca <texto>" que não acha nada no dataset busca o texto no YouTube (`ytsearch1:` do yt-dlp), toca o primeiro resultado (ou põe na fila, como um link) e pergunta no canal se era essa e quais temas ela tem.
- A próxima mensagem naquele canal que chama a Natty (nome ou menção), de qualquer pessoa, em até 3 minutos, é a resposta — conversa normal da mesa não conta: "não" descarta; "sim, é triste e épico" grava a faixa no `musicas.json` com esses temas (origem "Descoberta em mesa"); "sim" sem tema grava como "não classificado". A busca já acha a faixa nova sem reiniciar, e vídeo que já está no dataset não é duplicado.
- `formatar_dataset`, `slug` e `video_id` foram dos scripts para o `service.py`, pra o bot e os scripts de manutenção gravarem o dataset do mesmo jeito.

## Hollow Knight e NieR:Automata no dataset do Bardo; pipeline chips - 2026-09-29

- +43 faixas de Hollow Knight (OST, DLCs e duas amostras de Silksong) e +46 de NieR:Automata, tagueadas pelo contexto onde tocam no jogo; 9 da NieR ficaram "não classificado" por falta de fonte. Dataset: 579 faixas.
- `scripts/bardo_extrair_playlist.py` (playlist do YouTube → staging) e `scripts/bardo_mesclar_dataset.py` (staging → `musicas.json`, pulando duplicadas), documentados na skill `.claude/skills/chips/`.
- Merge com uma versão paralela do pipeline feita numa sessão na nuvem: ficaram os scripts locais, e vieram de lá 6 faixas de Umineko/FE3H reclassificadas.

## Correção: Bardo mudo quando o YouTube recusa o áudio - 2026-09-28

- O YouTube às vezes responde 403 à URL de áudio; o FFmpeg saía em 2s sem erro e a Natty ficava muda com o nome já anunciado.
- O FFmpeg agora manda os mesmos headers que o yt-dlp usou (`service.opcoes_ffmpeg()`), o que torna a recusa mais rara.
- Música que "acaba" em menos de 5s sem ninguém pular ou parar é tratada como falha: a Natty resolve uma URL nova e tenta de novo uma vez; se falhar de novo, avisa no chat e segue a fila.

## Categorias e sinônimos na busca do Bardo - 2026-09-28

- Novo `modules/bardo/dataset/vocabulario.json`: ~27 categorias do jeito que se pede numa mesa (triste, combate, chefe, taverna/cidade, masmorra, assustador/terror, acampamento/descanso...), cada uma com os sinônimos que as pessoas digitam e os temas crus do dataset que ela cobre.
- Cada faixa do `musicas.json` ganhou o campo `categorias`, gerado a partir dos temas por `scripts/categorizar_musicas.py` (rodar de novo ao mexer no vocabulário; categorias postas à mão são mantidas).
- A busca aceita sinônimos: "triste e bloodborne" passou de 0 para 8 faixas; "tragico", "melancolico" e "tristeza" levam à mesma categoria.
- Termos de várias palavras que não batem como frase são quebrados em palavras ("luta de chefe" = luta e chefe), e mais palavras de preenchimento são ignoradas ("para", "clima", "trilha"...).
- Continuam sem categoria as 33 faixas "não classificado", que precisam ser ouvidas.

## Busca booleana no módulo Bardo - 2026-09-28

- "natty toca <texto>" sem link busca no dataset `modules/bardo/dataset/musicas.json` (~490 faixas taggeadas) e põe o resultado na fila; se nada tocava, a primeira já começa. `e` = E, `ou` = OU (grupos inteiros), `sem`/`não` = exclui. Mais de 15 resultados: sorteia 15. Vale também no `/tocar`, cujo parâmetro virou `pedido` (link ou busca).
- Junção de duas implementações paralelas: a busca (`buscar_por_tags`, `_parse_query`, dataset) veio do commit `7555702`; a fila é a do `78203a1` (classe `Fila`, com pular/pausar/volume). A fila por dict do `7555702` foi descartada, e link direto continua indo pra fila em vez de interromper.
- O dataset agora é versionado: o `*.json` do `.gitignore` escondia ele, e o `7555702` subiu sem o arquivo.
- `.gitignore`: ignora os repositórios clonados pelo Sieve (`modules/sieve/Findings/repo-analyses/*/repo/`) e o `settings.local.json` do Claude Code.
- Limitação conhecida: a busca não entende sinônimos ("triste e bloodborne" não acha nada, as faixas estão como trágico/melancólico).

## Fila, controles e volume no módulo Bardo - 2026-09-28

- Fila por servidor (até 50 músicas, só em memória): tocar com música já tocando põe no fim da fila, e a próxima toca sozinha quando a atual acaba, com aviso no canal do último pedido. A fila guarda o link e resolve a URL de áudio de novo na hora de tocar, porque a do YouTube expira.
- Novos pedidos em linguagem natural: pular, ver a fila, limpar a fila, pausar, continuar, parar (limpa a fila e sai do canal) e volume (0-100%, começa em 50%, "aumenta"/"abaixa" mexe 20%).
- Slash commands: `/tocar`, `/pular`, `/fila`, `/limpar-fila`, `/pausar`, `/continuar`, `/parar`, `/volume`. Não dependem de menção nem da Message Content Intent.
- A Natty também atende pela menção ao cargo automático @Natty, além do usuário @Natty e do nome.
- Correção: "natty toca uma música para relaxar" (sem link) parava a música, porque o "para" virava o comando parar. Agora vale o que vem primeiro na frase.
- `davey` adicionado ao `requirements.txt`: é a criptografia de voz (DAVE) que o Discord passou a exigir.
- Testes do reconhecimento de pedidos e da fila em `modules/bardo/test_service.py`.

## Módulo Bardo (MVP) - 2026-09-27

- Novo módulo `modules/bardo/`: "natty toca <link do YouTube>" toca o áudio no canal de voz de quem pediu, via `voice_client` do discord.py + `yt-dlp` + FFmpeg. Sem Lavalink (decisão em `modules/sieve/Findings/natty-reports/lavalink-perspective.md`).

## Natty-Sieve: Repository Analysis Module - 2026-09-26

- Created `modules/natty-sieve/` — specialized module for analyzing open-source repositories through Natty's architectural lens.
- **Purpose:** Extract design patterns and architectural decisions from public repositories, contextualize them for Natty's needs, and propose adaptations.
- **SKILL.md:** Defines Sieve's workflow: read repository, cross-reference with Natty architecture, ask permission for deeper analysis, extract relevant patterns, document findings in "How can this be employed in Natty?" format.
- **repo-analyses/** folder: Storage for all analyzed repositories (`[RepoName]-Analysis.md` files).
- **TEMPLATE.md:** Standard analysis format covering overview, patterns, architectural insights, applicability to Natty domains, implementation ideas, risk assessment, and code references.
- **README.md:** Documents the purpose and usage of repository analyses.
- Integration point: Sieve always reads `Arquitetura-Tecnica-NAT-CORE.md` to contextualize findings. Always asks user before performing deeper analysis (GitHub API calls, code inspection).

## Teste por dado no módulo Dice - 2026-09-26

- "rolo 10d8, maior que 5" compara cada dado e lista sucessos e falhas, na ordem em que saíram, com a contagem e o percentual. Aceita `maior que`, `menor que`, `igual a`, `maior/menor ou igual (a)` e `>`, `<`, `=`, `>=`, `<=`, `≥`, `≤`.
- Conta só os dados mantidos, depois de vantagem, explosões e tira/mantém. Os bônus fixos não entram (com aviso).
- Com mais de 20 dados, mostra só a contagem, para caber no limite de mensagem do Discord.
- `RollResult.threshold` (`ThresholdTest`) guarda o resultado; `parse_threshold_test()` é exportado. O `_preparar()` agora também devolve onde a expressão termina.

## Explosivos e tira/mantém no módulo Dice - 2026-09-26

- Dados explosivos: `1d6!` rola mais um dado quando cai o máximo. O número de `!` é o limite de explosões em cadeia por dado (`2d10!!` = até 2). **Mudança:** "rolo 1d20!" agora é um d20 explosivo, não pontuação.
- Filtros: tira os menores (`4d6t1`, "tiro 1", "tiro o menor") ou mantém os maiores (`4d6m3`, `4d6kh3`, `4d6k3`, "mantenho 3"). Por extenso, vale para o último dado da expressão.
- Combinam entre si e com o resto: explode antes de filtrar, e a vantagem continua só no 1d20. O limite de 100 dados conta o pior caso das explosões.
- `Termo` ganhou `lados`, `explosoes`, `filtro`, `filtro_qtd`, `removidos` e `mantidos`. O reroll condicional passou a olhar `mantidos`, então dados tirados pelo filtro não ativam o reroll.
- Formatação: explosões aparecem com 💥 e os dados tirados ficam riscados: `🎲 4d6!t1 [4, 6, 5, 3, ~~💥2~~] = **18**`.

## Moedas no módulo Dice - 2026-09-26

- Novo `modules/dice/coins.py`: "rolo uma moeda", "rolo 5 moedas" (com contagem), "moeda ponderada 70% cara".
- Condicional com moedas: "rolo 3 moedas se 2 caras role 1d100" rola se der pelo menos 2 caras. A rolagem depois de "role" passa pelo `roll()`, então aceita vantagem, CD e "se 8 role de novo".
- `service.roll_coins()` joga as moedas e valida o condicional antes (o erro não depende da sorte). A validação da expressão saiu do `roll()` para `_preparar()`, sem mudar o comportamento.
- Detector: joga moedas só quando a mensagem começa com a moeda ou quando ela vem logo depois de um verbo ("rolo", "jogo", "lanço"...). Mensagens com dados fora do condicional continuam sendo rolagens de dados. Vale no chat e no `/rolar`.

## Módulo Dice - 2026-09-26

- Novo módulo `modules/dice/`, a partir do pacote `dice_modulo.rar`, com correções:
  - Desvantagem virava vantagem ("desvantagem" contém "vantagem"). Agora desvantagem é testada primeiro, e "sem vantagem" não ativa nada.
  - Limites de 100 dados, d1000 e 20 termos por rolagem. Antes, "rolo 99999999d99999999" travava o processo inteiro, NAT-CORE incluído.
  - Ignora mensagens de bots (antes rolava em cima das respostas do Avrae) e comandos do Avrae (`!r`, `!roll`).
  - Bônus e dados negativos (`1d20-2`, `1d20-1d4`), `d20` sem quantidade e termos repetidos (`1d20+1d20` rolava um d20 só).
  - Vantagem sem d20 é ignorada com aviso. O crítico usa o d20 que ficou depois da vantagem/desvantagem.
  - Detector: rola com palavra de rolagem ("rolo", "teste"...) ou quando a mensagem é só a rolagem ("1d20"). Dados soltos numa frase ("a espada dá 1d8") não rolam. Aceita `cd 15` e `vs DC 15`.
  - O comando `rolar` era de prefixo (só funcionava como `@Natty rolar`). Virou o slash command `/rolar`.
  - Os testes imprimiam ✅ sem verificar nada. Viraram `unittest` com rng falso e resultados exatos (23 testes).
- Rerolls condicionais na mensagem (`conditional_rerolls.py`): "rolo 1d8 se 8 role de novo", "rolo 1d20 se 20 role 1d100", "se o d6 der 6 role 1d8". Se algum dado cair no gatilho, rola o reroll uma vez (sem cascata) e soma no total, antes de comparar com a CD. Com vantagem/desvantagem, só o d20 que ficou conta. Vale no chat e no `/rolar`.
- `bot.py`: carrega `modules.dice.cog` e liga `intents.message_content`, que também precisa estar ligada no Developer Portal.

## Registro via DiceCloud e /personagens - 2026-09-24

- `/registrar` e `/remover` substituídos por `/registrar-personagem` (formulário com nome e link) e `/deletar-personagem nome` (com confirmação). Removidos o campo Sistema, o suporte a D&D Beyond, o nível digitado e a remoção por admin.
- Registro só aceita ficha pública do DiceCloud; o Nível Inicial vem da ficha e o nome precisa bater com o da ficha. Se não der para confirmar a ficha, o registro é bloqueado. Continua exigindo o cargo Viajante, limite de 2 por jogador e nome único.
- Só o dono (Discord ID) deleta o próprio personagem.
- Novo `/personagens`: lista todos os personagens ("Existem N viajantes nas Encruzilhadas") com nome, nível (Atual, ou Inicial como fallback), jogador e link da ficha. `service.listar_personagens(discord_id=None)` filtra por jogador quando recebe o ID.
- `service.py`: `registrar_personagem()`, `deletar_personagem()` e `listar_personagens()` retornam dicts (`{"sucesso", "erro"}`), sem exceção de regra. `buscar_nivel_atual_dicecloud()` ganhou `nome_esperado` opcional (a sincronização não usa).
- Discord ID e nomes são gravados como texto (antes o ID virava número e perdia dígitos; nome começando com `=` virava fórmula).

## Execução 24h no Windows - 2026-09-24

- Novo `scripts/rodar_natty.bat`: vai para a raiz do projeto (`cd /d`, para `credentials.json` ser achado de qualquer diretório), usa o `.venv` se existir e roda `bot.py` em loop, reiniciando 10s após qualquer queda.
- Saída do bot vai para `logs/natty.log` (ignorado no git), com horário de cada início/queda. `PYTHONUTF8=1` evita crash ao gravar acentos/emoji no log.
- Espera entre reinícios usa `ping` em vez de `timeout`, que falha sem console (Agendador de Tarefas).
- Rodado pela tarefa agendada "Natty" (na inicialização, logon S4U: roda sem login, sem janela e com o PC bloqueado).

## Comando /registrar - 2026-09-21

- Novo comando `/registrar nome sistema link nivel`, que substitui o Google Forms no registro de personagens.
- Exige o cargo **Viajante**. Limite de **2 personagens por jogador** (por Discord ID) e nome único (sem diferenciar maiúsculas).
- Sistemas: D&D 5e, Pathfinder 2e, Call of Cthulhu, Tormenta20, Vampire: The Masquerade. Link aceito: DiceCloud ou D&D Beyond. Nível de 1 a 20.
- Jogador e Discord ID vêm direto do Discord. A aba Personagens ganha as colunas "Sistema" e "Discord ID".
- Novo comando `/remover nome` (com confirmação por botão): apaga a linha do personagem. Só o dono (Discord ID) ou admin; personagens antigos sem Discord ID só por admin. Libera a vaga do limite de 2.
- Lógica em `service.registrar_personagem()` e `service.remover_personagem()` (erros de regra via `RegistroErro`); o `cog.py` só traduz o comando.

## Sincronização de Nível Atual - 2026-09-21

- `service.py`: `buscar_nivel_atual_dicecloud(link)` e `sincronizar_niveis_atuais()`. A segunda cria a coluna "Nível Atual" na aba Personagens (se não existir) e a preenche com o nível total de cada ficha DiceCloud.
- Fonte dos dados: API pública do DiceCloud v2 (`dicecloud.com/api/creature/<id>`, fichas públicas). O endpoint v1 usado pelo Avrae não serve para os links atuais (devolve HTML ou exige API key). Nível lido de `creatureVariables[0].level.value`, com soma das classes como fallback.
- A API v2 é lenta (20-45s e ~2 MB por ficha): timeout de 120s, 2 tentativas, gzip e busca de até 8 fichas em paralelo. Uma rodada com 8 fichas leva ~30s.
- Links de outras plataformas (ex: D&D Beyond) são pulados. Falha individual não interrompe as demais e não sobrescreve o valor anterior da célula.
- Novo `scripts/sincronizar_niveis.py` para rodar a sincronização manualmente.

## Reestruturação modular - 2026-09-19

- Reestruturação para arquitetura modular (modules/core/), separando camada de serviço (service.py) e camada de interface Discord (cog.py).
- Criado CLAUDE.md com a arquitetura documentada.
- Removido bot_completo.py.bak (código antigo fica no histórico do git).
- Adicionado Fluxo-Atual-Crossroads.md com o mapeamento completo do fluxo do servidor.

## v0 - Totalmente Inútil - 2026-09-19

- Primeira resposta funcional da Natty no Discord: comando `/oi`
- Estrutura de projeto inicial (`bot.py`, `sheets.py`, `requirements.txt`, `.env.example`)
- Integração com Google Sheets implementada (`sheets.py`), ainda não conectada ao bot ativo
- Correção de escopo OAuth2 (`applications.commands`) necessário para os slash commands funcionarem no servidor
