# Fluxo Atual da Crossroads — Referência para o NAT-CORE

*Documento de mapeamento do estado atual (as-is) do servidor, antes de qualquer automação. Serve de base para decidir o que o NAT-CORE deve cobrir e como.*

## 1. Onboarding (fora do escopo do NAT-CORE, mas relevante como contexto)

1. Pessoa entra no servidor → canal `#Bem-Vindo` → recebe mensagem personalizada da Loritta (bot).
2. `#Quem-Atravessa` → Carl-bot pergunta a faixa etária (13 ou menos / 14–17 / 18+), resposta única, sem exigir idade exata.
3. Carl-bot posta "Comece sua jornada" → a pessoa reage com um emoji → cargo muda de **Forasteiro** para **Viajante** (reaction-role do Carl-bot).

Não existe etapa de "apresentação" formal — as pessoas seguem direto pro próximo passo depois disso.

## 2. Criação de personagem

Guia publicado pelo Mestre num canal dedicado ("Mestrando com Avrae" ou equivalente):

1. **Escolha de plataforma da ficha.** Hoje o guia aceita D&D Beyond (recomendado no texto), DiceCloud e Google Sheets. **Decisão em vigor a partir de agora: só DiceCloud será aceito**, por preferência de ter uma fonte única — não é (por enquanto) motivada por uma integração técnica futura via API, é só simplificação.
2. **Atributos via Point Buy de 29 pontos** (não o padrão de 27 do D&D 5e/2024).
3. **História livre** — sem origem obrigatória, só uma ancoragem: todo personagem "chegou a Veyra".
4. **Checklist de revisão da ficha** antes de seguir.
5. **Integração com o Avrae**, feita no mesmo canal do guia, via comando `!import [link da ficha]`. Essa etapa é **auto-declarada** — o texto do guia só pede "certifique-se de que já foi feito", não existe verificação automática ou humana que confirme que o `!import` realmente rodou.
6. **Registro no Google Forms** ("Registro de Personagem"), com os campos:
   - Nome do personagem (texto curto, obrigatório)
   - Nome do jogador (texto curto, obrigatório)
   - Link da ficha (texto curto, obrigatório)
   - Nível Inicial (texto curto, obrigatório — **sem validação de número**, apesar da suposição inicial de que houvesse)
   - Timestamp é preenchido automaticamente pelo Forms.
7. **Checklist final** confirma: ficha criada, Point Buy de 29 pontos, ficha revisada, ficha integrada ao Avrae, personagem registrado.

### Estrutura atual da aba "Personagens" (planilha NAT-CORE)

| Timestamp | Nome do personagem | Nome do jogador | Link da ficha | Nível Inicial |
|---|---|---|---|---|

## 3. Registro de missão

Feito **pelo Condutor** (mestre daquela sessão), **depois** que a sessão acontece, via Google Forms ("Registro de Missões"):

- **Nome da missão** (texto curto, obrigatório)
- **Data da missão** (campo de data)
- **Dificuldade** (múltipla escolha: Trivial / Fácil / Normal / Difícil / Extrema / Outra)
- **Quem conduziu essa aventura** (texto curto)
- **Quais personagens participaram desta missão** (texto longo, obrigatório — "digite os nomes dos personagens exatamente como estão registrados no Crossroads, separados por vírgula")
- **Conte, com suas próprias palavras, o que aconteceu durante a missão** (texto longo, relato livre)

**Importante:** a Dificuldade registrada aqui é a **classificação definitiva**, decidida pelo Condutor após ver como a sessão se desenrolou de fato — não é o mesmo valor necessariamente anunciado antes da missão começar (que é só uma estimativa de expectativa).

### Estrutura atual da aba "Missões"

| Timestamp | Nome da missão | Data da missão | Dificuldade | Quem conduziu | Participantes (nomes separados por vírgula) | Relato |
|---|---|---|---|---|---|---|

## 4. Sistema de Evolução e Recompensas (oficial — "Decreto da Guilda")

Fonte: documento oficial de lore/regras do servidor, já formaliza o que tínhamos calculado juntos.

### Missões necessárias por evolução de nível

| Evolução | Missões (dificuldade Normal) | Evolução | Missões (dificuldade Normal) |
|---|---|---|---|
| 1 → 2 | 1 | 11 → 12 | 6 |
| 2 → 3 | 1 | 12 → 13 | 6 |
| 3 → 4 | 2 | 13 → 14 | 7 |
| 4 → 5 | 2 | 14 → 15 | 7 |
| 5 → 6 | 3 | 15 → 16 | 8 |
| 6 → 7 | 3 | 16 → 17 | 8 |
| 7 → 8 | 4 | 17 → 18 | 9 |
| 8 → 9 | 4 | 18 → 19 | 9 |
| 9 → 10 | 5 | 19 → 20 | 10 |
| 10 → 11 | 5 | | |

### Regra de cálculo de XP

A XP concedida por uma missão depende do **nível médio dos personagens envolvidos**, não do nível nominal anunciado da missão. Grupos que aceitam contratos acima do recomendado evoluem mais rápido — se sobreviverem.

### Gold Base por nível (dificuldade Normal como referência)

| Nível | Gold Base | Nível | Gold Base |
|---|---|---|---|
| 1 | 50 GP | 11 | 5.000 GP |
| 2 | 100 GP | 12 | 7.500 GP |
| 3 | 150 GP | 13 | 10.000 GP |
| 4 | 250 GP | 14 | 15.000 GP |
| 5 | 500 GP | 15 | 20.000 GP |
| 6 | 750 GP | 16 | 30.000 GP |
| 7 | 1.000 GP | 17 | 40.000 GP |
| 8 | 1.500 GP | 18 | 60.000 GP |
| 9 | 2.000 GP | 19 | 80.000 GP |
| 10 | 3.000 GP | 20 | 100.000 GP |

Condutores podem ajustar a recompensa final por circunstância do contrato (tesouros, pagamentos especiais, itens). Estes valores são referência inicial da economia do multiverso.

### Multiplicador por dificuldade

| Dificuldade | Multiplicador | Descrição |
|---|---|---|
| Trivial | ×0,25 | Risco nulo ou praticamente inexistente |
| Fácil | ×0,5 | Baixo risco, adequada para iniciantes |
| Normal | ×1 | Desafio compatível com grupo preparado |
| Difícil | ×2 | Perigosa; exige preparo real |
| Extrema | ×4 | TPK é possibilidade concreta |

**High Risk, High Reward:** um grupo de nível baixo pode tentar acompanhar uma missão anunciada como Extrema. A Guilda não impede a tentativa — só registra o resultado.

## 5. Aba "Calculadora" (estado atual, já implementado em fórmulas do Sheets)

| Coluna | Conteúdo | Automatizado? |
|---|---|---|
| Missão | Nome (deve bater com a aba Missões) | Manual |
| Level médio | Nível médio do grupo naquela missão | **Manual** — Mestre calcula e digita à mão (decisão consciente: automatizar isso exigiria reconstruir o histórico de XP acumulado por personagem, o que foi considerado desnecessário nesse estágio) |
| Dificuldade | Dropdown com as 5 opções | Manual (seleção) |
| Multiplicador | Lookup da tabela de multiplicadores | Automático |
| Exp | `Exp base do nível × multiplicador` | Automático |
| Gold | `Gold base do nível × multiplicador` | Automático |

⚠️ Ver nota acima sobre possível inconsistência na coluna "Multiplicador" da linha "Resgate e Coleta em Erebos" — vale conferir na planilha real.

## 6. Decisões de escopo do NAT-CORE já tomadas nesta conversa

- Registro de personagem **via bot substitui o Google Forms** — usa Discord Modals, captura automática do Discord ID do jogador (sem digitação manual do nome).
- Ficha aceita **só do DiceCloud** a partir de agora (decisão de simplificação, não de integração técnica futura).
- Limite de personagens por jogador: pendente confirmar se o bot vai **bloquear automaticamente** no ato do registro (agora que é tecnicamente possível) ou continuar só sinalizando.
- "Level médio" da missão continua **manual** por enquanto — automatizar isso é considerado o passo "mais chato" e fica para depois, por decisão explícita.

## 7. Perguntas em aberto (ainda não respondidas)

1. O NAT-CORE precisa checar se a pessoa já tem o cargo **Viajante** antes de aceitar um registro de personagem, ou o registro fica aberto pra qualquer membro do servidor?
2. A integração com o Avrae continua **auto-declarada** (sem verificação nenhuma pelo bot), ou isso deve virar uma checagem futura do NAT-CORE?
