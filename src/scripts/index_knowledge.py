"""Le data/knowledge/*.md e popula a colecao do ChromaDB persistente.

Uso: python -m src.scripts.index_knowledge
"""

import logging

from src.ai.rag_layer import indexar_conhecimento

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    total = indexar_conhecimento()
    logger.info("%d chunk(s) indexado(s) no ChromaDB.", total)


if __name__ == "__main__":
    main()
