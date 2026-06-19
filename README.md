# GymBrain

Pipeline de dados que transforma fichas de treino de musculação heterogêneas
— fotos de papel avulso, PDFs e prints de ficha completa — em uma base
relacional limpa, padronizada e consultável.

Este é o projeto de portfólio para vagas de **Engenharia de Dados, Análise
de Dados e IA**. O repositório cobre duas fases: a **Fase 1**, a fundação de
dados e o pipeline de ETL, e a **Fase 2**, a camada de IA que responde
perguntas sobre o histórico de treinos e gera recomendações explicáveis. Uma
interface gráfica (Fase 3) fica fora do escopo aqui.

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

## Arquitetura da Fase 2 — camada de IA

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│  pergunta   │ --> │              src/ai/orchestrator.py            │
│  do usuario │     │  classifica intencao (heuristica -> Gemini)    │
└─────────────┘     │  roteia para 1+ fontes e sintetiza a resposta  │
                     └───────┬───────────────┬───────────────┬──────┘
                             │               │               │
                  historico  │  conhecimento │  recomendacao  │
                             v               v               v
                   ┌──────────────┐ ┌───────────────┐ ┌──────────────────┐
                   │ sql_layer.py │ │  rag_layer.py  │ │ domain_rules.py   │
                   │ Pandas sobre │ │ ChromaDB +     │ │ regras            │
                   │ o Postgres   │ │ Sentence       │ │ deterministicas   │
                   │ (Gold)       │ │ Transformers   │ │ (sem LLM)         │
                   └──────────────┘ └───────────────┘ └──────────────────┘
                             │               │               │
                             └───────────────┴───────────────┘
                                             v
                                  src/ai/explainer.py
                          explica a resposta rastreando aos
                          dados e regras que a geraram
```

O orquestrador nunca chama o LLM mais do que o necessário: a classificação
de intenção tenta primeiro uma heurística por palavras-chave (custo zero de
cota) e só recorre à Gemini API quando a pergunta é ambígua. Na pior
hipótese, uma pergunta consome 2 chamadas (classificação + síntese da
resposta final) - dentro do limite de ~20 requisições/dia do free tier.

### Consultas estruturadas (src/ai/sql_layer.py)

Funções com Pandas/SQLAlchemy sobre as tabelas do Gold: volume e frequência
por grupo muscular, último treino de cada grupo, exercícios mais frequentes
e dias desde o último treino de um grupo. Como muitas fichas reais não
trazem data, toda função baseada em tempo ignora explicitamente os treinos
sem `data_treino` e informa quantos foram ignorados (`treinos_sem_data_ignorados`),
em vez de fingir que a análise é completa.

### Conhecimento (src/ai/rag_layer.py + src/scripts/index_knowledge.py)

Um corpus curado de 4 documentos (`data/knowledge/*.md` — hipertrofia,
periodização, faixas de repetição, descanso/recuperação) é dividido em
chunks por seção, transformado em embeddings com o modelo Sentence
Transformers `paraphrase-multilingual-MiniLM-L12-v2` e indexado num ChromaDB
persistente local (`data/chroma/`). `buscar_conhecimento(pergunta, k=3)` faz
a busca semântica e devolve cada chunk com a fonte (qual arquivo), para que
toda afirmação conceitual seja rastreável a um documento real.

### Regras de domínio (src/ai/domain_rules.py)

Regras deterministicas, sem LLM: `grupos_descansados` (grupos sem treino
recente no histórico), `adaptar_exercicio` (sugere alternativa do mesmo
grupo muscular quando falta equipamento) e `validar_treino` (checa se um
treino proposto cabe no tempo disponível e não sobrecarrega um grupo
recém-treinado). O dicionário canônico não tem um campo de equipamento
dedicado, então `adaptar_exercicio` infere o equipamento a partir do nome do
exercício: por palavra-chave ("com Barra", "no Smith", "no Cabo"...) e, para
os ~40 nomes que não mencionam o equipamento no texto (ex: "Levantamento
Terra", "Rosca Concentrada", "Pulldown"), por uma lista curada manualmente
com o equipamento convencional de cada um. É uma heurística documentada, não
um cadastro de equipamentos verificado.

### Orquestrador e explicabilidade (orchestrator.py + explainer.py)

`responder(pergunta)` classifica a intenção, roteia para SQL/RAG/regras
conforme o tipo de pergunta, e sintetiza a resposta final via Gemini a
partir dos dados coletados — nunca a partir do conhecimento geral do
modelo. `explicar(resposta)` percorre os dados brutos guardados na resposta
(`RespostaGymBrain.dados_brutos`) e gera uma explicação em texto simples do
porquê: quais grupos estavam descansados, qual foi o último treino de cada
grupo, quais documentos do corpus foram consultados. A recomendação nunca é
uma caixa-preta.

## Stack técnica

- **Python 3.11+**
- **Apache Airflow** — orquestração da DAG do ETL (Fase 1)
- **Google Gemini API** — extração multimodal de imagens/PDFs e orquestrador/síntese da camada de IA
- **Pydantic** — validação de schema (Bronze e Silver)
- **PostgreSQL** + **SQLAlchemy** — banco relacional final
- **Pandas** — consultas estruturadas sobre o histórico (Fase 2)
- **ChromaDB** + **Sentence Transformers** — busca semântica (RAG) no corpus de conhecimento (Fase 2)
- **Docker + docker-compose** — Airflow e PostgreSQL locais
- **pytest** — testes automatizados

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
│   ├── ai/                         # camada de IA (Fase 2)
│   │   ├── sql_layer.py            # consultas estruturadas (Pandas) sobre o Gold
│   │   ├── rag_layer.py            # indexacao e busca semantica (ChromaDB)
│   │   ├── domain_rules.py         # regras deterministicas (sem LLM)
│   │   ├── orchestrator.py         # classifica intencao, roteia, sintetiza
│   │   └── explainer.py            # explicabilidade da resposta
│   ├── scripts/
│   │   └── index_knowledge.py      # le data/knowledge/ e popula o ChromaDB
│   ├── models/
│   │   ├── schemas.py              # modelos Pydantic (Bronze/Silver)
│   │   └── db_models.py            # modelos SQLAlchemy (Gold)
│   ├── config.py                   # configuracoes e variaveis de ambiente
│   ├── gemini_client.py            # chamadas a Gemini com rate limit/retry/cota
│   └── init_db.py                  # cria o schema do Gold (idempotente)
├── data/
│   ├── raw/                        # PDFs e fotos originais (input, gitignored)
│   ├── sample/                     # fichas ficticias/anonimizadas, versionadas
│   ├── bronze/                     # JSON bruto extraido
│   ├── silver/                     # JSON padronizado, validado + log de rejeitados
│   ├── knowledge/                  # corpus de conhecimento curado (Fase 2, versionado)
│   └── chroma/                     # banco vetorial persistente (gitignored, gerado)
└── tests/
    ├── test_standardizer.py
    ├── test_validator.py
    ├── test_sql_layer.py
    ├── test_domain_rules.py
    ├── test_rag_layer.py
    ├── test_orchestrator.py
    └── test_explainer.py
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

### 5. Usar a camada de IA (Fase 2)

Indexe o corpus de conhecimento uma vez (gera `data/chroma/`, local e
persistente):

```bash
python -m src.scripts.index_knowledge
```

Depois, pergunte pelo terminal:

```python
from src.ai.orchestrator import responder
from src.ai.explainer import explicar

resposta = responder("Quantas séries eu fiz de peito no último mês?")
print(resposta.resposta)
print(explicar(resposta))
```

`responder()` precisa do banco do Gold populado (`python -m src.init_db` cria
o schema, se ainda não existir) e da mesma `GEMINI_API_KEY` usada na Fase 1 —
o free tier compartilha a cota diária entre a extração Bronze e a camada de
IA, então rodar as duas no mesmo dia pode esgotar a cota mais rápido.

## Qualidade de dados

Três camadas de rede de segurança evitam que dados ruins ou incompletos
sejam tratados como se não tivessem problema:

1. **"Não Mapeado"** — exercício extraído mas não reconhecido pelo
   dicionário canônico. Não é descartado; é carregado normalmente, mas
   fica fácil de localizar para revisão (`SELECT * FROM registros WHERE
   exercicio_id = (SELECT id FROM exercicios WHERE nome_canonico = 'Não
   Mapeado')`).
2. **Rejeitados** — registros que violam regras de negócio (série ≤ 0,
   carga negativa) nunca chegam ao Gold; ficam logados em
   `data/silver/rejeitados.jsonl` com o motivo exato da rejeição.
3. **Treinos sem data** — boa parte das fichas reais não traz a data do
   treino. Toda função de análise temporal da camada de IA (`src/ai/sql_layer.py`)
   ignora esses treinos explicitamente e informa quantos foram ignorados, em
   vez de aparentar uma análise completa que na verdade está incompleta.

## Roadmap (fora do escopo desta fase)

- **Fase 3** — interface para consulta e acompanhamento.
- Possíveis extensões da Fase 2: alertas de estagnação de carga ao longo do
  tempo, sugestão automática de variação de exercício por repetição
  excessiva, e um cadastro de equipamento verificado (hoje inferido por
  heurística a partir do nome do exercício).
