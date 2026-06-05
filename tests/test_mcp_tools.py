"""Enforça o PADRÃO de autoria de tools (ver app/mcp_server.py).

Roda contra o servidor MCP via client in-memory, então vale para qualquer
MCP gerado a partir deste template — não deixa subir tool sem descrição.
"""
import re

from fastmcp import Client

from app.mcp_server import mcp

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")  # verbo_substantivo snake_case


async def _list():
    async with Client(mcp) as client:
        return await client.list_tools()


async def _list_server_tools():
    """Retorna FunctionTool objects do servidor (tem .tags e .annotations)."""
    # mcp.list_tools() é a API pública do FastMCP 3.0 que retorna objetos com
    # metadados completos incluindo tags (não trafegam no protocolo MCP).
    return await mcp.list_tools()


async def test_servidor_tem_tools():
    tools = await _list()
    assert tools, "servidor MCP sem nenhuma tool registrada"


async def test_toda_tool_tem_descricao():
    for t in await _list():
        desc = (t.description or "").strip()
        assert desc, f"tool '{t.name}' SEM descrição (docstring obrigatória)"
        assert len(desc) >= 12, f"descrição de '{t.name}' curta/genérica demais: {desc!r}"


async def test_nome_no_padrao_snake_case():
    for t in await _list():
        assert NAME_RE.match(t.name), f"nome fora do padrão snake_case: {t.name!r}"


async def test_parametros_tem_descricao():
    # Todo parâmetro de entrada precisa de description no input schema
    # (Annotated[..., Field(description=...)]).
    for t in await _list():
        props = (t.inputSchema or {}).get("properties", {})
        for param, spec in props.items():
            assert spec.get("description", "").strip(), (
                f"tool '{t.name}': parâmetro '{param}' sem description"
            )


async def test_toda_tool_tem_tags():
    """Toda tool deve ter tags não vazio (read | write | admin)."""
    # tags não trafega no protocolo MCP — inspeciona via mcp.list_tools() (API pública).
    for t in await _list_server_tools():
        assert t.tags, f"tool '{t.name}' sem tags (obrigatório: read/write/admin)"


async def test_toda_tool_tem_annotations():
    """Toda tool deve ter pelo menos uma annotation MCP definida (não toda None)."""
    for t in await _list_server_tools():
        ann = t.annotations
        ann_dict = ann.model_dump() if hasattr(ann, "model_dump") else vars(ann)
        non_none = {k: v for k, v in ann_dict.items() if v is not None and k != "title"}
        assert non_none, (
            f"tool '{t.name}' sem nenhuma annotation definida "
            f"(readOnlyHint/destructiveHint/idempotentHint/openWorldHint obrigatório)"
        )


async def test_toda_tool_tem_output_schema():
    """Toda tool deve ter outputSchema (retorno tipado → structured output)."""
    for t in await _list():
        assert t.outputSchema, (
            f"tool '{t.name}' sem outputSchema — adicione anotação de retorno (dict/Pydantic)"
        )
