---
name: natty-sieve
description: Curates architectural patterns from analyzed repositories, filtering for Natty's ecosystem
---

# Natty-Sieve — Repository Pattern Curator

## O que é

**Natty-Sieve** é um módulo de análise e curadoria que lê relatórios gerados pelo `repo-analyzer` (skill genérica de análise de código aberto) e filtra padrões úteis especificamente para o contexto de **Natty**.

Enquanto `repo-analyzer` faz análise genérica (arquitetura geral, padrões de design, trade-offs), **Sieve** responde a pergunta: **"O que desse código pode servir pra mim?"**

---

## Fluxo de Trabalho

### 1. **Input: Repositórios Analisados**

Você fornece:
- URLs de repositórios já analisados (ex: `https://github.com/avrae/avrae`)
- Ou arquivos de análise já gerados pelo repo-analyzer

### 2. **Sieve Lê Documentação Interna de Natty**

Antes de começar, Sieve lê:
- `claude/Arquitetura-Tecnica-NAT-CORE.md` — entender a estrutura de Natty
- `CLAUDE.md` — princípios e padrões de Natty
- Qualquer documentação do módulo que você estiver expandindo

Isso garante que as recomendações sejam **contextualizadas** pra estrutura que você já tem.

### 3. **Sieve Acessa o Repositório**

Sieve pode:
- Clonar o repositório
- Ler código-fonte diretamente
- Consultar issues/PRs no GitHub se relevante

**Decisão de acesso:** Sieve **sempre perguntará** antes de acessar o repositório remoto. Tipo:
> "Quer que eu acesse o repositório `avrae/avrae` pra uma análise mais detalhada? Isso vai ajudar a validar patterns e interfaces."

### 4. **Análise e Filtragem**

Sieve procura por:

**A. Padrões de Arquitetura**
- Como o projeto organiza módulos/funcionalidades
- Layers de serviço, cogs, controllers
- Separação entre lógica de negócio e integração com framework

**B. Padrões de Design**
- Dependency injection, factories, observers
- Como gerenciam configuração
- Estratégias de erro/logging/retry

**C. Integração com APIs Externas**
- Como chamam APIs de terceiros (Google Sheets, Discord, D&D Beyond, etc)
- Rate limiting, cache, fallback strategies
- Estrutura de credenciais

**D. State Management**
- Como mantêm estado de sessão, caracteres, contexto
- Persistência (banco de dados, cache, arquivos)
- Sincronização entre módulos

**E. Escalabilidade**
- Como escalam com mais usuários/servidores
- Que trade-offs fizeram (simplicidade vs features, performance vs código)

### 5. **Output: Recomendação Contextualizada**

Sieve escreve um documento no estilo:

```markdown
# Sieve Analysis: [Repository Name]

## TL;DR (Para Natty)

[Uma frase: o que desse código é útil pra você]

## Architectural Pattern

[Como eles fazem X que Natty pode aproveitar]

## Code Example

[Snippet de como implementam, traduzido pra contexto Natty]

## Por que usar isso em Natty

[Benefício específico, problema que resolveria]

## Alternativas/Trade-offs

[O que Natty ganharia/perderia]

## Como integrar

[Passo a passo técnico, com referências ao código de Natty]

## Perguntas ainda em aberto

[O que você ainda precisa validar/decidir]
```

---

## Modo de Uso

### **Opção A: Análise de um Repositório (recomendado)**

```
Sieve, analisa: https://github.com/avrae/avrae
Contexto: Natty é um bot multipurpose de RPG que quer agregar múltiplas funcionalidades
```

Sieve vai:
1. Ler sua documentação de Natty
2. Acessar o repositório
3. Filtrar o que importa
4. Escrever recomendação contextualizada

### **Opção B: Análise Comparativa (2+ repos)**

```
Sieve, compara:
- https://github.com/avrae/avrae (arquitetura geral)
- https://github.com/jagrosh/MusicBot (audio + design patterns)
Foco: Como organizar módulos escaláveis
```

### **Opção C: Deep Dive em um Pattern Específico**

```
Sieve, investiga:
Repository: https://github.com/avrae/avrae
Pattern: Como eles gerenciam contexto de múltiplos usuários e permissões
```

---

## Princípios de Sieve

1. **Não é cópia cega** — recomenda adaptação, não copy-paste
2. **Sempre pergunta antes de escalar** — acesso remoto requer aprovação
3. **Contextualiza para Natty** — lê sua arquitetura primeiro
4. **Explica trade-offs** — por que usar X em vez de Y
5. **Valida no código** — mostra exemplos reais, não teóricos

---

## Saída de Sieve

Um documento Markdown em:
```
claude/analyses/[repo-name]-sieve-[data].md
```

Ou se mais estruturado:
```
modules/sieve/analyses/[repo-name].md
```

Contendo:
- TL;DR pra Natty
- Padrões relevantes
- Exemplos de código
- Como integrar
- Próximos passos

---

## Quando usar Sieve

✅ Quando você quer **estudar código aberto** com foco em **o que aproveitar**
✅ Quando tem um **repositório específico** que parece relevante
✅ Quando quer **comparar** 2+ abordagens diferentes
✅ Quando quer validar se um **pattern funciona** com Natty

❌ Não use para: análise genérica sem contexto (use `repo-analyzer` direto)
❌ Não use para: copy-paste de código sem entender

---

## Próximos Passos

1. **Identifique um repositório** interessante (Avrae, KarmaBot, AtlantaBot, etc)
2. **Chamar Sieve** com o repositório + contexto
3. **Ler o documento gerado**
4. **Decidir: implementar, adaptar, ou rejeitar**
5. **Documentar decisão** no projeto

---

**Sieve é seu olho crítico em código aberto — filtra ouro de lixo, e traz o que importa pro seu contexto.**
