from src.ai.rag_layer import dividir_em_chunks


class TestDividirEmChunks:
    def test_uma_secao_por_chunk(self, tmp_path):
        caminho = tmp_path / "exemplo.md"
        caminho.write_text(
            "# Titulo do documento\n\n"
            "## Primeira secao\n\n"
            "Paragrafo da primeira secao, em uma linha so.\n\n"
            "## Segunda secao\n\n"
            "Paragrafo da segunda secao,\n"
            "que quebra em duas linhas no markdown.\n",
            encoding="utf-8",
        )

        chunks = dividir_em_chunks(caminho)

        assert len(chunks) == 2
        assert chunks[0].secao == "Primeira secao"
        assert "Paragrafo da primeira secao" in chunks[0].texto
        assert chunks[1].secao == "Segunda secao"
        assert "que quebra em duas linhas" in chunks[1].texto
        assert all(chunk.fonte == "exemplo.md" for chunk in chunks)

    def test_titulo_do_documento_nao_gera_chunk(self, tmp_path):
        caminho = tmp_path / "exemplo.md"
        caminho.write_text("# Titulo\n\n## Secao\n\nConteudo.\n", encoding="utf-8")

        chunks = dividir_em_chunks(caminho)

        assert len(chunks) == 1
        assert all("Titulo" != chunk.secao for chunk in chunks)

    def test_secao_sem_conteudo_nao_gera_chunk_vazio(self, tmp_path):
        caminho = tmp_path / "exemplo.md"
        caminho.write_text("## Secao vazia\n\n## Secao com conteudo\n\nTexto.\n", encoding="utf-8")

        chunks = dividir_em_chunks(caminho)

        assert len(chunks) == 1
        assert chunks[0].secao == "Secao com conteudo"
