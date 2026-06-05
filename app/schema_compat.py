"""Compat de schema p/ LLMs com function-calling estrito (ex.: Google Gemini).

O Gemini (generativelanguage API) usa um subconjunto do OpenAPI 3.0 e NÃO aceita
`anyOf`/union nos parâmetros das tools. FastMCP/Pydantic geram
`{"anyOf": [{"type": "X"}, {"type": "null"}]}` para TODO parâmetro Optional — o
adapter do n8n achata isso em `{"type": ["X", "null"]}` e o Gemini rejeita com
"Invalid JSON payload ... Proto field is not repeating, cannot start list".

Este módulo colapsa esses unions nullable para um tipo único, IN-PLACE no schema
que o MCP anuncia (tools/list). A validação Pydantic da função NÃO muda — continua
aceitando None / param ausente; só o schema publicado fica compatível. OpenAI e
Claude já aceitam `anyOf`, então a mudança é inócua para eles.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("uvicorn.error")


def _collapse(node: object) -> bool:
    """Colapsa `anyOf:[{type:X,...},{type:null}]` -> `{type:X,...}`, recursivo. True se mudou."""
    changed = False
    if isinstance(node, dict):
        subs = node.get("anyOf")
        if isinstance(subs, list):
            non_null = [s for s in subs if isinstance(s, dict) and s.get("type") != "null"]
            if non_null:
                chosen = non_null[0]  # union real (raro): fica o 1º tipo concreto
                del node["anyOf"]
                for key, val in chosen.items():
                    node.setdefault(key, val)
                if node.get("default", "__keep__") is None:
                    node.pop("default", None)  # `default: null` vira ruído num tipo único
                changed = True
        for val in node.values():
            changed = _collapse(val) or changed
    elif isinstance(node, list):
        for val in node:
            changed = _collapse(val) or changed
    return changed


def make_tools_gemini_safe(mcp) -> int:
    """Sanitiza os schemas das tools registradas no `mcp`. Retorna nº de tools alteradas.

    Acessa o registro síncrono do FastMCP (`mcp._local_provider._components`). Se a
    estrutura interna mudar numa versão futura, faz no-op (não derruba o servidor).
    """
    provider = getattr(mcp, "_local_provider", None)
    components = getattr(provider, "_components", None)
    if not isinstance(components, dict):
        logger.warning("schema_compat: registro de tools nao encontrado (FastMCP mudou?); pulando")
        return 0
    touched = 0
    for comp in components.values():
        schema = getattr(comp, "parameters", None)
        if isinstance(schema, dict) and _collapse(schema):
            touched += 1
    if touched:
        logger.info("schema_compat: %d tools com anyOf nullable colapsado (Gemini-safe)", touched)
    return touched
