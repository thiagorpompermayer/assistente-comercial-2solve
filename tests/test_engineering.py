"""Módulo de engenharia: ISA-5.1, lista de instrumentos e Mermaid (funções puras)."""

import pytest

from src.connectors.engineering import (
    analyze_isa_tag,
    build_flowchart_mermaid,
    build_instrument_list,
)


def test_tag_ft_vazao_transmissor():
    a = analyze_isa_tag("FT-101")
    assert a.valid
    assert a.variable == "Vazão"
    assert a.loop == "101"
    assert any("Transmissão" in f for f in a.functions)


def test_tag_pic_pressao_indicacao_controle():
    a = analyze_isa_tag("PIC-205")
    assert a.valid
    assert a.variable == "Pressão / vácuo"
    assert [f.split("=")[0] for f in a.functions] == ["I", "C"]


def test_tag_lsh_nivel_chave_alto():
    a = analyze_isa_tag("LSH-300")
    assert a.valid
    assert a.variable == "Nível"
    assert [f.split("=")[0] for f in a.functions] == ["S", "H"]


def test_tag_pdt_diferencial_e_modificador():
    a = analyze_isa_tag("PDT-110")
    assert a.valid
    assert a.modifier == "Diferencial"
    assert [f.split("=")[0] for f in a.functions] == ["T"]


def test_tag_com_area_e_sufixo():
    a = analyze_isa_tag("10-FT-101A")
    assert a.valid
    assert a.area == "10"
    assert a.loop == "101"
    assert a.suffix == "A"


def test_tag_formato_invalido():
    a = analyze_isa_tag("ABC")
    assert not a.valid
    assert a.errors


def test_tag_com_letra_de_funcao_invalida():
    # F é variável válida (vazão); B não é letra de função sucessora ISA-5.1
    a = analyze_isa_tag("FB-101")
    assert not a.valid
    assert any("função" in e and "'B'" in e for e in a.errors)


def test_lista_de_instrumentos_valida_e_aponta_pendencias():
    result = build_instrument_list(
        [
            {"tag": "FT-101", "servico": "Vazão de óleo", "sinal": "4-20 mA"},
            {"tag": "FT-101", "servico": "duplicada"},  # duplicada
            {"tag": "XYZ", "servico": "tag inválida"},  # formato inválido
        ]
    )
    assert result["total"] == 3
    assert any("duplicada" in p.lower() for p in result["pendencias"])
    assert any("XYZ" in p for p in result["pendencias"])
    assert result["instrumentos"][0]["tag_valida"] is True
    assert result["instrumentos"][2]["tag_valida"] is False


def test_flowchart_mermaid_valido():
    mermaid = build_flowchart_mermaid(
        nodes=[
            {"id": "TQ01", "label": "Tanque de óleo", "shape": "round"},
            {"id": "P01", "label": "Bomba P-01"},
            {"id": "FT101", "label": "FT-101", "shape": "circle"},
        ],
        edges=[
            {"from": "TQ01", "to": "P01", "label": "óleo bruto"},
            {"from": "P01", "to": "FT101"},
        ],
        direction="LR",
    )
    assert mermaid.startswith("flowchart LR")
    assert 'TQ01(["Tanque de óleo"])' in mermaid
    assert "TQ01 -->|óleo bruto| P01" in mermaid
    assert "P01 --> FT101" in mermaid


def test_flowchart_rejeita_aresta_para_no_inexistente():
    with pytest.raises(ValueError, match="inexistente"):
        build_flowchart_mermaid(
            nodes=[{"id": "A", "label": "A"}],
            edges=[{"from": "A", "to": "FANTASMA"}],
        )


def test_flowchart_rejeita_direcao_invalida():
    with pytest.raises(ValueError, match="direção"):
        build_flowchart_mermaid(nodes=[{"id": "A", "label": "A"}], edges=[], direction="XY")
