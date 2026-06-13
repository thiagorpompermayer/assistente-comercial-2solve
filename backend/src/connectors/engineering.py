"""Geração de conteúdo técnico de engenharia — funções puras e testáveis.

Sem I/O externo: o engineering_agent chama estas funções e persiste o
resultado localmente. Cobre:
- Análise/validação de TAGs no padrão ISA-5.1.
- Normalização de lista de instrumentos (valida cada TAG).
- Montagem de fluxograma de processo em Mermaid.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

# ----- ISA-5.1: tabelas de letras -----

# Primeira letra: variável medida / iniciadora.
FIRST_LETTERS: dict[str, str] = {
    "A": "Análise",
    "B": "Chama / combustão",
    "C": "Condutividade (escolha do usuário)",
    "D": "Densidade (escolha do usuário)",
    "E": "Tensão elétrica",
    "F": "Vazão",
    "G": "Dimensional / posição (medição)",
    "H": "Comando manual",
    "I": "Corrente elétrica",
    "J": "Potência",
    "K": "Tempo / programa",
    "L": "Nível",
    "M": "Umidade (escolha do usuário)",
    "N": "Escolha do usuário",
    "O": "Escolha do usuário",
    "P": "Pressão / vácuo",
    "Q": "Quantidade",
    "R": "Radiação",
    "S": "Velocidade / frequência",
    "T": "Temperatura",
    "U": "Multivariável",
    "V": "Vibração / análise mecânica",
    "W": "Peso / força",
    "X": "Não classificada",
    "Y": "Evento / estado / presença",
    "Z": "Posição / dimensão",
}

# Letras modificadoras inequívocas (não são letras de função sucessoras).
MODIFIERS: dict[str, str] = {
    "D": "Diferencial",
    "K": "Taxa de variação no tempo",
}

# Letras sucessoras: função do instrumento.
SUCCEEDING_LETTERS: dict[str, str] = {
    "A": "Alarme",
    "C": "Controle",
    "E": "Elemento primário / sensor",
    "G": "Visor / indicação local",
    "H": "Alto",
    "I": "Indicação",
    "K": "Estação de controle",
    "L": "Baixo / lâmpada",
    "M": "Médio / intermediário",
    "O": "Restrição / orifício",
    "P": "Ponto de teste / tomada",
    "Q": "Totalização / integração",
    "R": "Registro",
    "S": "Chave (switch)",
    "T": "Transmissão",
    "U": "Multifunção",
    "V": "Válvula / elemento final",
    "W": "Poço / bulbo",
    "X": "Não classificada",
    "Y": "Relé / cálculo / conversão",
    "Z": "Atuador / elemento final de controle",
}

_TAG_RE = re.compile(r"^(?:(\d+)-)?([A-Z]+)-?(\d+)([A-Z]*)$")


class TagAnalysis(BaseModel):
    tag: str
    valid: bool
    variable: str | None = None
    modifier: str | None = None
    functions: list[str] = []
    loop: str | None = None
    area: str | None = None
    suffix: str | None = None
    description: str = ""
    errors: list[str] = []


def analyze_isa_tag(tag: str) -> TagAnalysis:
    """Decompõe e valida uma TAG ISA-5.1 (ex.: FIC-101, PDT-205, LSH-300A)."""
    raw = (tag or "").strip().upper()
    match = _TAG_RE.match(raw)
    if not match:
        return TagAnalysis(
            tag=tag,
            valid=False,
            errors=["formato inválido — esperado LETRAS + número (ex.: FT-101)"],
        )

    area, letters, loop, suffix = match.groups()
    errors: list[str] = []

    variable_letter = letters[0]
    variable = FIRST_LETTERS.get(variable_letter)
    if variable is None:
        errors.append(f"primeira letra '{variable_letter}' não é variável ISA-5.1 válida")

    rest = letters[1:]
    modifier: str | None = None
    func_letters = rest
    if rest and rest[0] in MODIFIERS:
        modifier = MODIFIERS[rest[0]]
        func_letters = rest[1:]

    functions: list[str] = []
    for ch in func_letters:
        meaning = SUCCEEDING_LETTERS.get(ch)
        if meaning is None:
            errors.append(f"letra de função '{ch}' não reconhecida")
        else:
            functions.append(f"{ch}={meaning}")

    valid = not errors
    parts = [variable or f"?{variable_letter}"]
    if modifier:
        parts.append(modifier)
    parts.extend(f.split("=", 1)[1] for f in functions)
    description = " · ".join(parts) + f" (malha {loop})"

    return TagAnalysis(
        tag=raw,
        valid=valid,
        variable=variable,
        modifier=modifier,
        functions=functions,
        loop=loop,
        area=area,
        suffix=suffix or None,
        description=description,
        errors=errors,
    )


class Instrument(BaseModel):
    tag: str
    servico: str = ""  # descrição do serviço/medição
    tipo: str = ""  # ex.: transmissor, válvula de controle
    faixa: str = ""  # ex.: 0-10 bar
    sinal: str = ""  # ex.: 4-20 mA / HART
    pid: str = ""  # referência ao P&ID / malha


def build_instrument_list(instruments: list[dict[str, Any]]) -> dict[str, Any]:
    """Normaliza uma lista de instrumentos e valida cada TAG (ISA-5.1)."""
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: set[str] = set()
    for item in instruments:
        inst = Instrument(**item)
        analysis = analyze_isa_tag(inst.tag)
        tag = analysis.tag
        if tag in seen:
            issues.append(f"TAG duplicada: {tag}")
        seen.add(tag)
        if not analysis.valid:
            issues.append(f"{inst.tag}: " + "; ".join(analysis.errors))
        rows.append(
            {
                **inst.model_dump(),
                "tag": tag,
                "tag_valida": analysis.valid,
                "interpretacao": analysis.description,
            }
        )
    return {"instrumentos": rows, "total": len(rows), "pendencias": issues}


# ----- fluxograma de processo (Mermaid) -----

_MERMAID_DIRECTIONS = {"TB", "TD", "BT", "LR", "RL"}


def build_flowchart_mermaid(
    nodes: list[dict[str, str]],
    edges: list[dict[str, str]],
    direction: str = "LR",
) -> str:
    """Monta um flowchart Mermaid a partir de nós e conexões.

    nodes: [{"id": "TQ01", "label": "Tanque de óleo", "shape": "round"?}]
    edges: [{"from": "TQ01", "to": "P01", "label": "óleo bruto"?}]
    """
    if direction not in _MERMAID_DIRECTIONS:
        raise ValueError(f"direção Mermaid inválida: {direction!r}")
    ids = {n["id"] for n in nodes}
    for edge in edges:
        for side in ("from", "to"):
            if edge[side] not in ids:
                raise ValueError(f"aresta referencia nó inexistente: {edge[side]!r}")

    lines = [f"flowchart {direction}"]
    for node in nodes:
        label = node.get("label", node["id"]).replace('"', "'")
        shape = node.get("shape", "rect")
        if shape == "round":
            lines.append(f'    {node["id"]}(["{label}"])')
        elif shape == "circle":
            lines.append(f'    {node["id"]}(("{label}"))')
        elif shape == "diamond":
            lines.append(f'    {node["id"]}{{"{label}"}}')
        else:
            lines.append(f'    {node["id"]}["{label}"]')
    for edge in edges:
        label = edge.get("label", "")
        arrow = f'-->|{label}|' if label else "-->"
        lines.append(f'    {edge["from"]} {arrow} {edge["to"]}')
    return "\n".join(lines)
