"""
Formata um RollResult (ou CoinRollResult) como texto para o Discord (markdown).
"""

from .coins import CoinFlip
from .service import CONTRARIO, CoinRollResult, RollResult

_STATUS = {
    "crítico": "✨ **Crítico!**",
    "sucesso": "✅ Sucesso",
    "falha": "❌ Falha",
}


def _termos(result: RollResult) -> str:
    partes = []
    for i, t in enumerate(result.termos):
        dados = [str(r) for r in t.rolagens]
        riscados = set()
        if t.descartado is not None:
            # Risca o d20 descartado pela vantagem/desvantagem.
            idx = 1 if t.rolagens[1] == t.descartado else 0
            dados[idx] = f"~~{t.descartado}~~"
            riscados.add(idx)
        valores = t.rolagens + t.explosoes
        dados += [f"💥{v}" for v in t.explosoes]
        # Risca os tirados pelo filtro (valores iguais são indistinguíveis).
        removidos = list(t.removidos)
        for idx, v in enumerate(valores):
            if idx not in riscados and v in removidos:
                removidos.remove(v)
                dados[idx] = f"~~{dados[idx]}~~"
        sinal = "- " if t.sinal < 0 else ("+ " if i else "")
        partes.append(f"{sinal}{t.expressao} [{', '.join(dados)}]")
    if result.bonus:
        partes.append(f"{'-' if result.bonus < 0 else '+'} {abs(result.bonus)}")
    return " ".join(partes)


def _reroll(result: RollResult) -> str:
    r = result.conditional_reroll_result
    if not r:
        return ""
    return f" + ✨ {r.expressao} [{', '.join(map(str, r.rolagens))}]"


# Acima disso, o teste por dado mostra só a contagem (os dados já estão na 1ª linha).
MAX_LISTA_LIMIAR = 20

_SIMBOLOS = {">": ">", ">=": "≥", "<": "<", "<=": "≤", "=": "=", "!=": "≠"}
_POR_EXTENSO = {">": "maior que", ">=": "maior ou igual a", "<": "menor que",
                "<=": "menor ou igual a", "=": "igual a"}


def _lista(dados) -> str:
    return f"[{', '.join(map(str, dados))}]" if dados else "nenhum"


def _threshold(result: RollResult) -> list:
    """Linhas de sucessos/falhas e contagem do teste por dado."""
    th = result.threshold
    linhas = []
    if len(th.dados) <= MAX_LISTA_LIMIAR:
        ok, nao = _SIMBOLOS[th.operador], _SIMBOLOS[CONTRARIO[th.operador]]
        linhas.append(f"✅ Sucessos ({ok}{th.valor}): {_lista(th.sucessos)}")
        linhas.append(f"❌ Falhas ({nao}{th.valor}): {_lista(th.falhas)}")
    n = th.success_count
    linhas.append(f"📊 **{n} sucesso{'' if n == 1 else 's'} de {len(th.dados)}** ({th.percentual}%)")
    return linhas


def describe_roll_compact(result: RollResult) -> str:
    """
    Uma linha: 🎲 Ataque: 1d20 (vantagem) [17, ~~4~~] + 5 = **22** · CD 15 ✅ Sucesso
    Com teste por dado, mais as linhas de sucessos/falhas e a contagem.
    """
    titulo = f"{result.teste.capitalize()}: " if result.teste else ""
    mod = f" ({result.modificador})" if result.modificador else ""
    linha = f"🎲 {titulo}{_termos(result)}{mod}{_reroll(result)}"
    th = result.threshold
    if th:
        linha += f" · {_POR_EXTENSO[th.operador]} {th.valor}"
        # O total só importa se ainda houver CD para comparar.
        if result.dc is not None:
            linha += f" · total **{result.final}**"
    else:
        linha += f" = **{result.final}**"
    if result.dc is not None:
        linha += f" · CD {result.dc} {_STATUS[result.resultado]}"
    if th:
        linha += "\n" + "\n".join(_threshold(result))
    if result.conditional_reroll_result:
        linha += f"\n-# ✨ Reroll ativado ({result.conditional_reroll_result.trigger_value})"
    for aviso in result.avisos:
        linha += f"\n-# {aviso}"
    return linha


def describe_roll(result: RollResult) -> str:
    """Várias linhas: dados, total, CD e teste."""
    linhas = [f"🎲 {_termos(result)}"]
    if result.modificador:
        linhas.append(f"Com {result.modificador}")
    r = result.conditional_reroll_result
    if r:
        linhas.append(f"✨ Reroll ativado ({r.trigger_value})!")
        linhas.append(f"🎲 Reroll: {r.expressao} [{', '.join(map(str, r.rolagens))}]")
    if result.threshold:
        linhas.extend(_threshold(result))
    else:
        linhas.append(f"**Total: {result.final}**")
    if result.dc is not None:
        linhas.append(f"CD {result.dc}: {_STATUS[result.resultado]}")
    if result.teste:
        linhas.append(f"📝 Teste de {result.teste.capitalize()}")
    linhas.extend(result.avisos)
    return "\n".join(linhas)


def _plural(n: int, palavra: str) -> str:
    return f"{n} {palavra}{'' if n == 1 else 's'}"


def describe_coin_flip(flip: CoinFlip) -> str:
    """🪙 Moeda = **Cara**  /  🪙 3 moedas (70% cara) = [Cara, Coroa, Cara] + contagem"""
    peso = f" ({flip.bias * 100:g}% cara)" if flip.bias != 0.5 else ""
    if flip.count == 1:
        return f"🪙 Moeda{peso} = **{flip.results[0]}**"
    return (
        f"🪙 {flip.count} moedas{peso} = [{', '.join(flip.results)}]\n"
        f"**{_plural(flip.heads_count, 'cara')}** · {_plural(flip.tails_count, 'coroa')}"
    )


def describe_coin_roll(result: CoinRollResult) -> str:
    """Moedas e, se houver condicional, se ativou e a rolagem."""
    linhas = [describe_coin_flip(result.flip)]
    if result.target_heads is None:
        return linhas[0]
    if result.reroll:
        linhas.append("✨ Condição ativada!")
        linhas.append(describe_roll_compact(result.reroll))
    else:
        caras = _plural(result.flip.heads_count, "cara")
        linhas.append(f"❌ Condição não ativada ({caras}, precisava {result.target_heads})")
    return "\n".join(linhas)
