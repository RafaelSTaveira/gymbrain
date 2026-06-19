"""Indexacao e busca semantica no corpus de conhecimento (ChromaDB + Sentence Transformers)."""

from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from src.config import CHROMA_DIR, EMBEDDING_MODEL_NAME, KNOWLEDGE_DIR

COLLECTION_NAME = "conhecimento_treino"

_modelo: SentenceTransformer | None = None


@dataclass
class Chunk:
    """Um trecho indexavel do corpus de conhecimento."""

    texto: str
    fonte: str
    secao: str


@dataclass
class ResultadoBusca:
    """Um chunk recuperado pela busca semantica, com a fonte para rastreabilidade."""

    texto: str
    fonte: str
    secao: str
    distancia: float


def _get_modelo() -> SentenceTransformer:
    """Carrega o modelo de embeddings uma unica vez (download na primeira chamada)."""
    global _modelo
    if _modelo is None:
        _modelo = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _modelo


def _get_cliente() -> chromadb.ClientAPI:
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))


def dividir_em_chunks(caminho_markdown: Path) -> list[Chunk]:
    """Divide um markdown do corpus em chunks por secao ("## Titulo" + paragrafo).

    Cada arquivo em data/knowledge/ foi escrito com uma secao por paragrafo
    autocontido, entao usar a secao como unidade de chunk preserva contexto
    sem precisar de um separador de frases mais sofisticado. O titulo do
    documento ("# ...") e ignorado - so as secoes ("## ...") geram chunks.
    """
    linhas = caminho_markdown.read_text(encoding="utf-8").splitlines()
    chunks: list[Chunk] = []
    secao_atual: str | None = None
    paragrafo_atual: list[str] = []

    def fechar_secao() -> None:
        if secao_atual is not None and paragrafo_atual:
            texto_paragrafo = " ".join(paragrafo_atual).strip()
            if texto_paragrafo:
                chunks.append(
                    Chunk(texto=f"{secao_atual}\n\n{texto_paragrafo}", fonte=caminho_markdown.name, secao=secao_atual)
                )

    for linha in linhas:
        linha = linha.strip()
        if linha.startswith("## "):
            fechar_secao()
            secao_atual = linha[3:].strip()
            paragrafo_atual = []
        elif linha.startswith("# "):
            continue
        elif linha:
            paragrafo_atual.append(linha)
        else:
            fechar_secao()
            paragrafo_atual = []

    fechar_secao()
    return chunks


def indexar_conhecimento(knowledge_dir: Path = KNOWLEDGE_DIR, cliente: chromadb.ClientAPI | None = None) -> int:
    """Le os markdowns de `knowledge_dir`, gera embeddings e popula a colecao do ChromaDB.

    Idempotente: a colecao e recriada do zero a cada chamada, entao
    reindexar nao duplica chunks de execucoes anteriores.
    """
    cliente = cliente or _get_cliente()
    try:
        cliente.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = cliente.get_or_create_collection(COLLECTION_NAME)

    todos_chunks: list[Chunk] = []
    for caminho in sorted(knowledge_dir.glob("*.md")):
        todos_chunks.extend(dividir_em_chunks(caminho))

    if not todos_chunks:
        return 0

    modelo = _get_modelo()
    embeddings = modelo.encode([chunk.texto for chunk in todos_chunks]).tolist()
    collection.add(
        ids=[f"{chunk.fonte}::{i}" for i, chunk in enumerate(todos_chunks)],
        documents=[chunk.texto for chunk in todos_chunks],
        metadatas=[{"fonte": chunk.fonte, "secao": chunk.secao} for chunk in todos_chunks],
        embeddings=embeddings,
    )
    return len(todos_chunks)


def buscar_conhecimento(pergunta: str, k: int = 3) -> list[ResultadoBusca]:
    """Busca semantica no corpus indexado: os `k` chunks mais relevantes para `pergunta`.

    Cada resultado traz a fonte (arquivo de data/knowledge/) para que a
    resposta final do orquestrador seja rastreavel a um documento real, em
    vez de uma afirmacao gerada sem origem.
    """
    cliente = _get_cliente()
    collection = cliente.get_or_create_collection(COLLECTION_NAME)

    modelo = _get_modelo()
    embedding = modelo.encode([pergunta]).tolist()
    resultado = collection.query(query_embeddings=embedding, n_results=k)

    documentos = resultado.get("documents") or [[]]
    metadados = resultado.get("metadatas") or [[]]
    distancias = resultado.get("distances") or [[]]

    return [
        ResultadoBusca(texto=texto, fonte=metadado["fonte"], secao=metadado["secao"], distancia=distancia)
        for texto, metadado, distancia in zip(documentos[0], metadados[0], distancias[0])
    ]
