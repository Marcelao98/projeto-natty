# Lógica de negócio do módulo core: registrar personagem, listar personagens,
# registrar e listar missões, sincronizar níveis. Sem dependência de discord.py; os dados
# ficam no SQLite (storage.py).
import difflib
import gzip
import json
import logging
import re
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from modules.core import storage
from modules.core.storage import BancoIlegivel  # noqa: F401  (a cog captura este erro)

log = logging.getLogger(__name__)

DICECLOUD_LINK_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?dicecloud\.com/character/([A-Za-z0-9]+)(?:[/?#].*)?$"
)
# Todo ID de ficha do DiceCloud é um ID do Meteor: 17 caracteres desse alfabeto
# (sem 0, 1, I, O, l). Fora disso a ficha não existe: barra sem ir à API.
DICECLOUD_ID_RE = re.compile(r"^[23456789ABCDEFGHJKLMNPQRSTWXYZabcdefghijkmnopqrstuvwxyz]{17}$")
DICECLOUD_API_URL = "https://dicecloud.com/api/creature/{id}"
DICECLOUD_TIMEOUT = 120  # a API v2 pode levar ~1 min em fichas grandes
DICECLOUD_TENTATIVAS = 2
DICECLOUD_PARALELO = 8

MAX_PERSONAGENS_POR_JOGADOR = 2
# História livre: do tamanho que o jogador quiser, de uma linha até o máximo
# que um campo de formulário do Discord aceita.
MAX_HISTORIA = 4000

ERRO_HISTORIA_VAZIA = (
    "Conta um pouco da história do personagem: do tamanho que você quiser, "
    "até uma linha só já vale."
)
ERRO_HISTORIA_LONGA = (
    "A história passou do limite de " + str(MAX_HISTORIA) + " caracteres "
    "(a sua tem {tamanho}). Escreva o quanto quiser, só dentro desse limite."
)

ERRO_LINK = "Só aceito ficha do DiceCloud (link no formato dicecloud.com/character/...)."
# Motivo de consultar_ficha_dicecloud → mensagem pro jogador.
ERROS_FICHA = {
    "inexistente": (
        "Opa, essa ficha não existe no DiceCloud. Confira se copiou o link inteiro, "
        "direto da barra de endereço com a ficha aberta."
    ),
    "privada": (
        "Achei a ficha, mas ela está privada. No DiceCloud, abra o compartilhamento da "
        "ficha, deixe qualquer pessoa com o link ver e tente de novo."
    ),
    "nome": (
        "A ficha existe, mas o nome nela é **{nome_ficha}**. Registre com o nome "
        "exatamente como está na ficha."
    ),
    "sem_nivel": (
        "A ficha existe, mas não consegui ler o nível dela. Confira se a classe está "
        "na ficha e tente de novo."
    ),
    "indisponivel": "O DiceCloud não respondeu agora. Tente de novo daqui a alguns minutos.",
}


def _extrair_id_dicecloud(link: str) -> str | None:
    match = DICECLOUD_LINK_RE.match((link or "").strip())
    return match.group(1) if match else None


def _nivel_do_json(dados: dict) -> int | None:
    """Nível total: variável 'level' calculada pelo DiceCloud; senão soma das classes."""
    variaveis = (dados.get("creatureVariables") or [{}])[0]
    nivel = (variaveis.get("level") or {}).get("value")
    if isinstance(nivel, (int, float)) and not isinstance(nivel, bool):
        return int(nivel)

    classes = [
        p for p in dados.get("creatureProperties", [])
        if p.get("type") == "class" and not p.get("removed")
    ]
    if not classes:
        return None
    return sum(int(c.get("level") or 0) for c in classes)


def _chave_nome(nome: str) -> str:
    """Forma de comparação de nomes: sem acento, sem maiúsculas, espaços únicos."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", nome or "") if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.casefold().split())


def _baixar_ficha(char_id: str) -> dict:
    """JSON da ficha. HTTPError 4xx sobe na hora (repetir não muda a resposta);
    timeout, rede e 5xx tentam DICECLOUD_TENTATIVAS vezes antes de subir."""
    req = urllib.request.Request(
        DICECLOUD_API_URL.format(id=char_id),
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": "Natty-Bot",
        },
    )
    for tentativa in range(DICECLOUD_TENTATIVAS):
        try:
            with urllib.request.urlopen(req, timeout=DICECLOUD_TIMEOUT) as resp:
                corpo = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    corpo = gzip.decompress(corpo)
            return json.loads(corpo)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or tentativa == DICECLOUD_TENTATIVAS - 1:
                raise
            exc.close()
        except Exception:
            if tentativa == DICECLOUD_TENTATIVAS - 1:
                raise


def _motivo_http(exc: urllib.error.HTTPError) -> str:
    """O DiceCloud responde 400 "Permission denied: No such document exists" pra
    ID que não existe; qualquer outra recusa (401/403/400) é tratada como privada."""
    try:
        corpo = exc.read()
        if exc.headers and exc.headers.get("Content-Encoding") == "gzip":
            corpo = gzip.decompress(corpo)  # o erro também vem compactado
        corpo = corpo.decode("utf-8", "replace")
    except Exception:
        corpo = ""
    finally:
        exc.close()
    if exc.code == 404 or "no such document" in corpo.casefold():
        return "inexistente"
    if exc.code in (400, 401, 403):
        return "privada"
    return "indisponivel"


def consultar_ficha_dicecloud(link: str, nome_esperado: str | None = None) -> dict:
    """Confere a ficha no DiceCloud. Nunca levanta exceção.

    Retorna {"nivel": n} ou {"erro": motivo}, com motivo em ERROS_FICHA:
    inexistente (link quebrado ou ID que não existe), privada, nome (o nome da
    ficha não bate com `nome_esperado`, ignorando acento e maiúscula; vem junto
    "nome_ficha"), sem_nivel, indisponivel (timeout, rede, 5xx).
    """
    char_id = _extrair_id_dicecloud(link)
    if not char_id or not DICECLOUD_ID_RE.match(char_id):
        return {"erro": "inexistente"}
    try:
        dados = _baixar_ficha(char_id)
    except urllib.error.HTTPError as exc:
        motivo = _motivo_http(exc)
        log.warning("DiceCloud recusou %s: HTTP %s (%s)", link, exc.code, motivo)
        return {"erro": motivo}
    except Exception as exc:
        log.warning("Falha ao buscar ficha no DiceCloud (%s): %s", link, exc)
        return {"erro": "indisponivel"}

    try:
        if nome_esperado is not None:
            nome_ficha = ((dados.get("creatures") or [{}])[0]).get("name") or ""
            if _chave_nome(nome_ficha) != _chave_nome(nome_esperado):
                return {"erro": "nome", "nome_ficha": nome_ficha}
        nivel = _nivel_do_json(dados)
    except Exception as exc:
        log.warning("Ficha do DiceCloud em formato inesperado (%s): %s", link, exc)
        nivel = None
    return {"nivel": nivel} if nivel is not None else {"erro": "sem_nivel"}


def buscar_nivel_atual_dicecloud(link: str, nome_esperado: str | None = None) -> int | None:
    """Só o nível (ou None se a consulta falhar, por qualquer motivo)."""
    return consultar_ficha_dicecloud(link, nome_esperado).get("nivel")




def preparar_banco() -> None:
    """Confere o banco (cria se for novo) e faz o backup de início do bot.
    Levanta BancoIlegivel se o arquivo existir e não for confiável."""
    storage.inicializar()
    storage.fazer_backup("inicio")


def garantir_jogador(discord_id: str, username: str, nome_exibicao: str) -> None:
    """Cria ou atualiza o jogador (username e apelido sempre os mais recentes).
    Quem usa um comando está no servidor, então fica ativo."""
    membro_entrou(discord_id, username, nome_exibicao)


def membro_entrou(discord_id: str, username: str, nome_exibicao: str) -> None:
    """Membro entrou no servidor ou mudou username/apelido: cria ou atualiza, ativo=1.
    Não mexe no campo `nome` (o nome dos registros antigos)."""
    storage.salvar_jogador(str(discord_id), username or None, nome_exibicao or None, ativo=True)


def membro_saiu(discord_id: str) -> None:
    """Membro saiu do servidor: fica com ativo=0, nunca é apagado (personagens e
    missões antigas continuam apontando pra ele)."""
    storage.marcar_saida(str(discord_id))


def sincronizar_membros(membros: list[dict]) -> dict:
    """Espelha a lista completa de membros do servidor (sem bots) na tabela jogadores.

    Cada item: {"discord_id", "username", "nome_exibicao"} (apelido no servidor,
    ou nome global se não tiver apelido). Cria os novos, atualiza username e
    apelido dos existentes (o campo `nome` não é tocado) e marca ativo=0 em quem
    está no banco e não veio na lista. Tudo numa transação.

    Lista vazia levanta ValueError sem gravar nada: uma busca que falhou não pode
    marcar o servidor inteiro como "saiu".
    Retorna {"novos", "atualizados", "saíram", "total"}; "atualizados" conta só
    quem mudou de fato (inclusive quem voltou ao servidor).
    """
    if not membros:
        raise ValueError("Lista de membros vazia: nada foi alterado.")
    resumo = {"novos": 0, "atualizados": 0, "saíram": 0, "total": 0}
    vistos = set()
    with storage.transacao() as con:
        for m in membros:
            discord_id = str(m["discord_id"])
            if discord_id in vistos:
                continue
            vistos.add(discord_id)
            mudou = storage.salvar_jogador(
                discord_id, m.get("username") or None, m.get("nome_exibicao") or None,
                ativo=True, con=con,
            )
            if mudou == "novo":
                resumo["novos"] += 1
            elif mudou == "atualizado":
                resumo["atualizados"] += 1
        resumo["saíram"] = storage.marcar_ausentes(vistos, con=con)
    resumo["total"] = len(vistos)
    return resumo


def sincronizar_niveis_atuais() -> dict:
    """Preenche o nível atual dos personagens a partir do DiceCloud.

    Retorna {"atualizados": int, "pulados": int, "falhas": [nomes]}.
    Personagens que não são do DiceCloud são pulados sem busca; falha individual
    não interrompe os demais (e não sobrescreve o valor anterior).
    """
    resumo = {"atualizados": 0, "pulados": 0, "falhas": []}
    pendentes = []  # (id, nome, link)
    for p in storage.listar_personagens():
        if _extrair_id_dicecloud(p["link_ficha"] or ""):
            pendentes.append((p["id"], p["nome"], p["link_ficha"]))
        else:
            resumo["pulados"] += 1

    with ThreadPoolExecutor(max_workers=DICECLOUD_PARALELO) as pool:
        niveis = list(pool.map(lambda p: buscar_nivel_atual_dicecloud(p[2]), pendentes))

    novos = {}
    for (pid, nome, _), nivel in zip(pendentes, niveis):
        if nivel is None:
            resumo["falhas"].append(nome)
            continue
        novos[pid] = nivel
        resumo["atualizados"] += 1

    if novos:
        storage.atualizar_niveis(novos)
    return resumo


def _erro(motivo: str) -> dict:
    return {"sucesso": False, "erro": motivo}


def _checar_limite_e_nome(discord_id: str, nome: str, con=None) -> str | None:
    """Motivo do bloqueio (limite por jogador ou nome já usado), ou None se ok."""
    if storage.contar_personagens(discord_id, con=con) >= MAX_PERSONAGENS_POR_JOGADOR:
        return (
            f"Você já tem {MAX_PERSONAGENS_POR_JOGADOR} personagens registrados, que é o "
            "limite. Delete um com /deletar-personagem antes de registrar outro."
        )
    if storage.existe_personagem(_chave_nome(nome), con=con):
        return f"Já existe um personagem chamado **{nome}**."
    return None


def registrar_personagem(
    discord_id: str, nome_jogador: str, nome_personagem: str, link_ficha: str, historia: str
) -> dict:
    """Registra um personagem, com o nível buscado no DiceCloud.

    Ordem: nome e história preenchidos → limite de personagens do jogador (e
    nome único) → link é DiceCloud → ficha existe, é pública e tem o mesmo nome
    (consultar_ficha_dicecloud; link quebrado é barrado sem ir à API) → grava.
    Cada falha tem sua mensagem. A história é do tamanho que o jogador quiser
    (uma linha já vale), só não pode ser vazia nem passar de MAX_HISTORIA.
    A data de criação é a do registro, automática.
    Retorna {"sucesso": True, "nivel": n, "criado_em": iso} ou
    {"sucesso": False, "erro": motivo}; em caso de erro nada é gravado.
    """
    discord_id = str(discord_id)
    nome = (nome_personagem or "").strip()
    link = (link_ficha or "").strip()
    jogador = (nome_jogador or "").strip()
    historia = (historia or "").strip()
    if not nome:
        return _erro("Informe o nome do personagem.")
    if not historia:
        return _erro(ERRO_HISTORIA_VAZIA)
    if len(historia) > MAX_HISTORIA:
        return _erro(ERRO_HISTORIA_LONGA.format(tamanho=len(historia)))

    motivo = _checar_limite_e_nome(discord_id, nome)
    if motivo:
        return _erro(motivo)

    if not _extrair_id_dicecloud(link):
        return _erro(ERRO_LINK)

    ficha = consultar_ficha_dicecloud(link, nome)  # lento (até ~1 min): fora da transação
    if "erro" in ficha:
        return _erro(ERROS_FICHA[ficha["erro"]].format(nome_ficha=ficha.get("nome_ficha", "")))
    nivel = ficha["nivel"]

    criado_em = storage.agora()
    with storage.transacao() as con:
        # Confere de novo: outro registro pode ter entrado enquanto o DiceCloud respondia.
        motivo = _checar_limite_e_nome(discord_id, nome, con=con)
        if motivo:
            return _erro(motivo)
        storage.inserir_personagem(
            nome=nome,
            nome_chave=_chave_nome(nome),
            nome_jogador=jogador or None,
            jogador_discord_id=discord_id,
            link_ficha=link,
            nivel_inicial=nivel,
            criado_em=criado_em,
            historia=historia,
            con=con,
        )

    return {"sucesso": True, "nivel": nivel, "criado_em": criado_em}


def deletar_personagem(discord_id: str, nome_personagem: str) -> dict:
    """Remove o personagem `nome_personagem` que pertence a `discord_id`.

    Só o dono deleta: se o personagem não existir ou for de outro jogador, nada
    é alterado. Faz backup do banco antes de apagar. O histórico de missões
    continua (o participante fica sem personagem_id, com o nome guardado).
    Retorna {"sucesso": True} ou {"sucesso": False, "erro": motivo}.
    """
    discord_id = str(discord_id)
    nome = (nome_personagem or "").strip()
    chave = _chave_nome(nome)
    erro = _erro(f"Você não tem nenhum personagem registrado chamado **{nome}**.")

    if not storage.personagem_do_jogador(discord_id, chave):
        return erro
    storage.fazer_backup("deletar")
    if not storage.remover_personagem(discord_id, chave):
        return erro
    return {"sucesso": True}


def listar_personagens(discord_id: str | None = None) -> list[dict]:
    """Personagens registrados, em ordem alfabética (lista vazia se nenhum).

    Sem `discord_id`, lista todos; com ele, só os desse jogador.
    Cada item: {"nome", "jogador", "link", "nivel", "criado_em"}; "nivel" é o
    nível atual, ou o inicial se o atual estiver vazio (None se nenhum dos dois
    existir); "criado_em" é a data do registro em ISO ("" se não houver).
    """
    personagens = storage.listar_personagens(None if discord_id is None else str(discord_id))
    return [
        {
            "nome": p["nome"],
            "jogador": p["nome_jogador"] or "",
            "link": p["link_ficha"] or "",
            "nivel": p["nivel_atual"] if p["nivel_atual"] is not None else p["nivel_inicial"],
            "criado_em": p["criado_em"] or "",
        }
        for p in personagens
    ]


# --- missões ------------------------------------------------------------------

DIFICULDADES = ("Trivial", "Fácil", "Normal", "Difícil", "Extrema")
MAX_NOME_MISSAO = 100
MAX_RELATO = 4000
MAX_PARTICIPANTES = 20


def separar_participantes(texto: str) -> list[str]:
    """'Aldric, Orin; Ed Brandt' → nomes, sem vazios nem repetidos
    (repetição comparada sem acento e maiúscula). Aceita vírgula, ; e quebra de linha."""
    nomes, vistos = [], set()
    for parte in re.split(r"[,;\n]", texto or ""):
        nome = " ".join(parte.split())
        if nome and _chave_nome(nome) not in vistos:
            vistos.add(_chave_nome(nome))
            nomes.append(nome)
    return nomes


def _data_da_missao(texto: str, hoje: date | None = None) -> str:
    """'03/09/2026' (ou 3/9/2026) → '2026-09-03'. ValueError com a mensagem pro jogador."""
    try:
        data = datetime.strptime((texto or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        raise ValueError("Data inválida: use o formato DD/MM/AAAA (ex: 03/09/2026).") from None
    if data > (hoje or date.today()):
        raise ValueError("A data da missão não pode ser no futuro.")
    return data.isoformat()


def conferir_missao(nome: str, data: str, dificuldade: str, xp: int, gold: int,
                    participantes: str, hoje: date | None = None, con=None) -> dict:
    """Tudo que dá pra checar antes do relato (o cog chama antes de abrir o
    formulário, e registrar_missao chama de novo dentro da transação).

    Retorna {"sucesso": True, "dados": {...}, "participantes": [(id, nome)]}
    ou {"sucesso": False, "erro": motivo}.
    """
    nome = " ".join((nome or "").split())
    if not nome:
        return _erro("Informe o nome da missão.")
    if len(nome) > MAX_NOME_MISSAO:
        return _erro(f"O nome da missão passou de {MAX_NOME_MISSAO} caracteres.")
    if storage.existe_missao(_chave_nome(nome), con=con):
        return _erro(f"Já existe uma missão chamada **{nome}**.")
    try:
        data_iso = _data_da_missao(data, hoje)
    except ValueError as exc:
        return _erro(str(exc))
    if dificuldade not in DIFICULDADES:
        return _erro(f"Dificuldade inválida. Use uma destas: {', '.join(DIFICULDADES)}.")
    if not isinstance(xp, int) or not isinstance(gold, int) or xp < 0 or gold < 0:
        return _erro("XP e gold têm que ser números inteiros, zero ou mais.")

    nomes = separar_participantes(participantes)
    if not nomes:
        return _erro("Informe pelo menos um participante (nomes dos personagens, separados por vírgula).")
    if len(nomes) > MAX_PARTICIPANTES:
        return _erro(f"No máximo {MAX_PARTICIPANTES} participantes por missão.")
    registrados = {_chave_nome(p["nome"]): p for p in storage.listar_personagens(con=con)}
    achados, faltando = [], []
    for n in nomes:
        p = registrados.get(_chave_nome(n))
        if p:
            achados.append((p["id"], p["nome"]))
        else:
            faltando.append(n)
    if faltando:
        partes = []
        for n in faltando:
            parecido = difflib.get_close_matches(_chave_nome(n), list(registrados), n=1, cutoff=0.6)
            dica = f" (você quis dizer **{registrados[parecido[0]]['nome']}**?)" if parecido else ""
            partes.append(f"**{n}**{dica}")
        return _erro(
            "Não achei estes personagens registrados: " + ", ".join(partes)
            + ". Use os nomes como aparecem em /personagens."
        )

    dados = {"nome": nome, "nome_chave": _chave_nome(nome), "data": data_iso,
             "dificuldade": dificuldade, "xp": xp, "gold": gold}
    return {"sucesso": True, "dados": dados, "participantes": achados}


def _texto_opcional(texto: str | None) -> str | None:
    texto = (texto or "").strip()
    return texto or None


def registrar_missao(
    condutor_discord_id: str, condutor_nome: str, nome: str, data: str, dificuldade: str,
    xp: int, gold: int, participantes: str, relato: str, resultado: str | None = None,
    outras_recompensas: str | None = None, observacoes: str | None = None, hoje: date | None = None,
) -> dict:
    """Registra uma missão conduzida por `condutor_discord_id`.

    Os participantes têm que ser personagens registrados (nome como em
    /personagens, sem diferenciar acento e maiúscula). XP e gold são os que o
    condutor decidiu (a tabela de XP base da guilda ainda não está no sistema).
    Relato obrigatório, até MAX_RELATO; resultado, outras recompensas e
    observações opcionais. Tudo é conferido de novo dentro da transação.
    Retorna {"sucesso": True, "id", "nome", "data", "participantes": [nomes]}
    ou {"sucesso": False, "erro": motivo}; em caso de erro nada é gravado.
    """
    relato = (relato or "").strip()
    if not relato:
        return _erro("Conte o que aconteceu na missão (o relato é obrigatório).")
    if len(relato) > MAX_RELATO:
        return _erro(f"O relato passou de {MAX_RELATO} caracteres (o seu tem {len(relato)}).")

    condutor_discord_id = str(condutor_discord_id)
    jogador = storage.buscar_jogador(condutor_discord_id)
    nome_condutor = (jogador and (jogador["nome"] or jogador["nome_exibicao"])) or condutor_nome

    with storage.transacao() as con:
        conferido = conferir_missao(nome, data, dificuldade, xp, gold, participantes, hoje, con=con)
        if not conferido["sucesso"]:
            return conferido
        dados = dict(conferido["dados"])
        dados.update({
            "criado_em": storage.agora(),
            "condutor_discord_id": condutor_discord_id if jogador else None,
            "condutor_nome": nome_condutor,
            "relato": relato,
            "resultado": _texto_opcional(resultado),
            "outras_recompensas": _texto_opcional(outras_recompensas),
            "observacoes": _texto_opcional(observacoes),
        })
        missao_id = storage.inserir_missao(dados, conferido["participantes"], con=con)

    return {"sucesso": True, "id": missao_id, "nome": dados["nome"], "data": dados["data"],
            "participantes": [n for _, n in conferido["participantes"]]}


def listar_missoes() -> list[dict]:
    """Missões por data: {"nome", "data", "dificuldade", "condutor", "xp", "gold",
    "participantes": [nomes]}."""
    participantes = storage.listar_participantes()
    return [
        {
            "nome": m["nome"],
            "data": m["data"] or "",
            "dificuldade": m["dificuldade"] or "",
            "condutor": m["condutor_nome"] or "",
            "xp": m["xp"],
            "gold": m["gold"],
            "participantes": participantes.get(m["id"], []),
        }
        for m in storage.listar_missoes_completas()
    ]
