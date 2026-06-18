# GymBrain

Pipeline de dados que transforma fichas de treino de musculação heterogêneas
— fotos de papel avulso, PDFs e prints de ficha completa — em uma base
relacional limpa, padronizada e consultável.

Este é o projeto de portfólio para vagas de **Engenharia de Dados, Análise
de Dados e IA**. Este repositório cobre a **Fase 1**: a fundação de dados e
o pipeline de ETL. Fases futuras (RAG sobre o histórico de treinos, motor de
regras de domínio e interface) ficam fora do escopo aqui.

## O problema

Histórico real de ~20-30 fichas de treino acumuladas ao longo de anos, vindas
de personal trainers e academias diferentes, em formatos sem padrão nenhum:

- PDFs de um programa estruturado de 60 dias (Adaptação → Iniciante →
  Intermediário → Avançado), com exercícios divididos em tabelas por dia.
- Fotos de recibos de academia (Smart Fit / X Prime), com abreviações
  agressivas ("C/", "S/", "4X12 A 15-BISET").
- Prints de ficha manuscrita digitalizada.

O objetivo é extrair, padronizar e consolidar tudo isso em um banco
relacional único, sem perder a rastreabilidade do dado original — inclusive
para os casos em que um exercício não é reconhecido automaticamente.

## Arquitetura: Bronze → Silver → Gold

```
┌────────────────┐     ┌─────────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│   data/raw/     │     │   BRONZE              │     │   SILVER               │     │   GOLD            │
│                 │     │                       │     │                        │     │                   │
│  PDFs e fotos   │ --> │  src/bronze/          │ --> │  src/silver/           │ --> │  src/gold/        │
│  originais      │     │  extractor.py         │     │  standardizer.py       │     │  loader.py        │
│  (input)        │     │                       │     │  + validator.py        │     │                   │
│                 │     │  Gemini Vision extrai  │     │  Normaliza nomes,      │     │  Carrega no       │
│                 │     │  JSON bruto por ficha  │     │  busca no dicionario   │     │  PostgreSQL,      │
│                 │     │                       │     │  canonico, valida com  │     │  evitando         │
│                 │     │                       │     │  Pydantic              │     │  duplicatas       │
└────────────────┘     └─────────────────────┘     └──────────────────────┘     └─────────────────┘
                          data/bronze/*.json           data/silver/*.json           tabelas:
                          (JSON bruto, 1 por ficha)     (JSON padronizado +          treinos
                                                          validado)                  exercicios
                                                          data/silver/                registros
                                                          rejeitados.jsonl
                                                          (log de rejeitados)
```

Orquestrado por uma DAG do Airflow (`dags/pipeline_fichas.py`) com três
tasks encadeadas — `extract_bronze >> transform_silver >> load_gold` —
disparada manualmente, já que é um processamento batch das fichas
históricas, não uma rotina recorrente.

### Bronze — extração

`src/bronze/extractor.py` envia cada imagem/PDF para a **Gemini API**
(modelo multimodal, free tier) com um prompt que exige retorno em JSON
estrito: data do treino, exercícios, séries, repetições, carga e grupo
muscular (quando a ficha indicar). O resultado bruto é salvo em
`data/bronze/`. Erros de API e arquivos corrompidos são logados e não
interrompem o processamento dos demais arquivos do lote.

### Silver — padronização e validação

`src/silver/standardizer.py` normaliza cada `nome_original` (minúsculas,
remove acentos, **expande abreviações reais das fichas** — `C/` → "com",
`S/` → "sem", `P/` → "para" — e converte hífens/parênteses/pontuação em
espaço) e busca o resultado em um **dicionário canônico** de 213 variações
(`src/silver/exercise_dictionary.py`), construído a partir dos exercícios
reais das minhas próprias fichas e validado com 100% de cobertura contra
elas, cobrindo 10 grupos musculares (Peito, Costas, Ombro, Bíceps, Tríceps,
Perna, Glúteo, Panturrilha, Abdômen, Cardio).

Exercícios não encontrados no dicionário **não são descartados** — ficam
marcados como `"Não Mapeado"` para revisão manual posterior.

`src/silver/validator.py` valida cada registro padronizado com Pydantic
(série inteira positiva, carga não-negativa, nome canônico obrigatório).
Registros que violam essas regras vão para um log de rejeitados
(`data/silver/rejeitados.jsonl`) em vez de seguir para o Gold — sem
interromper a carga dos demais exercícios da mesma ficha.

### Gold — carga relacional

`src/gold/loader.py` carrega os dados validados no PostgreSQL com um
modelo relacional simples:

- `exercicios` (id, nome_canonico, grupo_muscular) — nome canônico único.
- `treinos` (id, data_treino, origem) — origem (nome do arquivo) único, o
  que torna a carga **idempotente**: reprocessar a mesma ficha não duplica
  o treino.
- `registros` (id, treino_id, exercicio_id, nome_original, series,
  repeticoes, carga_kg) — guarda o texto original de cada exercício, então
  mesmo os marcados como `"Não Mapeado"` (que compartilham um único
  `exercicio_id` genérico) ficam rastreáveis individualmente direto via SQL.

## Stack técnica

- **Python 3.11+**
- **Apache Airflow** — orquestração da DAG
- **Google Gemini API** — extração multimodal de imagens/PDFs
- **Pydantic** — validação de schema (Bronze e Silver)
- **PostgreSQL** + **SQLAlchemy** — banco relacional final
- **Docker + docker-compose** — Airflow e PostgreSQL locais
- **pytest** — testes automatizados (25 testes em standardizer e validator)

## Estrutura de pastas

```
gymbrain/
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── dags/
│   └── pipeline_fichas.py          # DAG do Airflow (extract >> transform >> load)
├── src/
│   ├── bronze/
│   │   └── extractor.py            # extracao via Gemini Vision
│   ├── silver/
│   │   ├── standardizer.py         # normalizacao + dicionario canonico
│   │   ├── validator.py            # validacao Pydantic + log de rejeitados
│   │   └── exercise_dictionary.py  # dicionario canonico de exercicios
│   ├── gold/
│   │   └── loader.py               # carga no PostgreSQL
│   ├── models/
│   │   ├── schemas.py              # modelos Pydantic (Bronze/Silver)
│   │   └── db_models.py            # modelos SQLAlchemy (Gold)
│   └── config.py                   # configuracoes e variaveis de ambiente
├── data/
│   ├── raw/                        # PDFs e fotos originais (input, gitignored)
│   ├── sample/                     # fichas ficticias/anonimizadas, versionadas
│   ├── bronze/                     # JSON bruto extraido
│   └── silver/                     # JSON padronizado, validado + log de rejeitados
└── tests/
    ├── test_standardizer.py
    └── test_validator.py
```

### Sobre `data/raw/` vs. `data/sample/`

`data/raw/` contém as fichas reais que usei para construir e testar este
projeto — são dados pessoais, então a pasta está no `.gitignore` e não é
versionada.

Para que qualquer pessoa consiga rodar o pipeline sem precisar das minhas
fichas, `data/sample/` traz 3 fichas **fictícias** (aluno e treinador com
nomes inventados, geradas programaticamente), cobrindo Peito/Costas,
Pernas e Ombro/Bíceps — incluindo um exercício proposital fora do
dicionário canônico, para demonstrar o fluxo de `"Não Mapeado"`. Essa
pasta é versionada normalmente.

## Como executar

### 1. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Preencha `GEMINI_API_KEY` no `.env` com uma chave gerada em
[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
(free tier).

### 2. Subir os serviços

```bash
docker compose up airflow-init   # cria o banco de metadados e o usuario admin
docker compose up -d             # sobe postgres, webserver e scheduler
```

Acesse o Airflow em [localhost:8080](http://localhost:8080)
(usuário/senha: `admin` / `admin`).

### 3. Disparar o pipeline

A DAG `pipeline_fichas` aparece com trigger manual (`schedule=None`). Coloque
as fichas a processar em `data/raw/` e dispare a DAG pela UI ou via:

```bash
docker compose exec airflow-scheduler airflow dags trigger pipeline_fichas
```

Não tem fichas próprias à mão para testar? Use as fictícias versionadas no
repositório:

```bash
cp data/sample/*.png data/raw/
```

### 4. Rodar os testes

```bash
pip install -r requirements.txt
pytest tests/ -v
```

## Qualidade de dados

Duas camadas de rede de segurança evitam que dados ruins cheguem ao banco
final sem visibilidade:

1. **"Não Mapeado"** — exercício extraído mas não reconhecido pelo
   dicionário canônico. Não é descartado; é carregado normalmente, mas
   fica fácil de localizar para revisão (`SELECT * FROM registros WHERE
   exercicio_id = (SELECT id FROM exercicios WHERE nome_canonico = 'Não
   Mapeado')`).
2. **Rejeitados** — registros que violam regras de negócio (série ≤ 0,
   carga negativa) nunca chegam ao Gold; ficam logados em
   `data/silver/rejeitados.jsonl` com o motivo exato da rejeição.

## Roadmap (fora do escopo desta fase)

- **Fase 2** — RAG sobre o histórico consolidado de treinos.
- **Fase 3** — motor de regras de domínio (progressão de carga, alertas de
  estagnação, sugestão de variação de exercício).
- **Fase 4** — interface para consulta e acompanhamento.
