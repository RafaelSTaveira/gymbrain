"""Regras de dominio deterministicas (sem LLM) para validar e ajustar recomendacoes."""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from src.ai.sql_layer import dias_desde_ultimo_treino
from src.silver.exercise_dictionary import EXERCISE_DICTIONARY
from src.silver.standardizer import normalize_exercise_name

# Tempo medio (em segundos) usado para estimar a duracao de um treino.
# Valores de referencia, nao medidos: execucao de uma serie, descanso entre
# series (ver data/knowledge/faixas_repeticao.md) e troca/ajuste de
# equipamento ao mudar de exercicio.
SEGUNDOS_POR_SERIE = 45
SEGUNDOS_DESCANSO_ENTRE_SERIES = 90
SEGUNDOS_TROCA_EXERCICIO = 60

# Palavras-chave (ja normalizadas: minusculas, sem acento) usadas para
# inferir o equipamento exigido por um exercicio a partir do seu nome
# canonico. O dicionario canonico nao tem um campo de equipamento dedicado,
# mas funciona como heuristica porque boa parte dos nomes ja descreve o
# equipamento ("com Barra", "no Smith", "no Cabo"...). A ordem importa:
# padroes mais especificos devem vir antes dos mais genericos.
_PALAVRAS_EQUIPAMENTO: tuple[tuple[str, str], ...] = (
    ("smith", "Smith"),
    ("halter", "Halter"),
    ("kettlebell", "Kettlebell"),
    ("com peso", "Peso Livre"),
    ("barra", "Barra"),
    ("cabo", "Cabo/Polia"),
    ("pulley", "Cabo/Polia"),
    ("cross", "Cabo/Polia"),
    ("corda", "Cabo/Polia"),
    ("leg press", "Máquina"),
    ("cadeira", "Máquina"),
    ("mesa flexora", "Máquina"),
    ("hack squat", "Máquina"),
    ("graviton", "Máquina"),
    ("maquina", "Máquina"),
    ("step", "Step"),
    ("bola", "Bola Suíça"),
    ("esteira", "Cardio"),
    ("eliptico", "Cardio"),
    ("bicicleta ergometrica", "Cardio"),
    ("remoergometro", "Cardio"),
)

# Exercicios cujo nome canonico NAO menciona o equipamento mas que, na
# pratica de musculacao, tem um equipamento padrao bem estabelecido (ex:
# "Levantamento Terra" e convencionalmente feito com barra, "Rosca
# Concentrada" com halter). Curado manualmente a partir dos ~140 nomes
# canonicos do dicionario; checado antes das palavras-chave genericas.
# Continuam como PESO_DO_CORPO (sem entrada aqui) os exercicios realmente
# sem equipamento: Flexao de Braco, Prancha Abdominal, Paralelas, Avanco,
# Escalador, Afundo, a maioria dos abdominais e variantes "Livre".
_EQUIPAMENTO_OVERRIDE: dict[str, str] = {
    "levantamento terra": "Barra",
    "agachamento livre": "Barra",
    "stiff": "Barra",
    "supino reto": "Barra",
    "supino declinado": "Barra",
    "remada curvada pronada": "Barra",
    "rosca concentrada": "Halter",
    "rosca martelo": "Halter",
    "rosca neutra": "Halter",
    "rosca 21": "Halter",
    "rosca 90 graus": "Halter",
    "rosca alternada com isometria": "Halter",
    "rosca spider banco 45": "Halter",
    "triceps coice": "Halter",
    "triceps testa": "Halter",
    "triceps frances sentado": "Halter",
    "triceps frances sentado unilateral": "Halter",
    "crucifixo reto": "Halter",
    "posterior de ombro": "Halter",
    "panturrilha no banco": "Halter",
    "remada serrote": "Cabo/Polia",
    "pulldown": "Cabo/Polia",
    "pullover": "Cabo/Polia",
    "puxador alto aberto pegada pronada": "Cabo/Polia",
    "puxador alto fechado pegada supinada": "Cabo/Polia",
    "puxador alto com triangulo": "Cabo/Polia",
    "remada baixa com triangulo": "Cabo/Polia",
    "remada cavalinho": "Cabo/Polia",
    "remada unilateral": "Cabo/Polia",
    "remada com alca": "Cabo/Polia",
    "hiperextensao lombar": "Máquina",
    "s force": "Máquina",
    "panturrilha em pe": "Máquina",
    "panturrilha sentado": "Máquina",
    "aquecimento de manguito rotador": "Elástico",
    "box jump": "Caixa (Box)",
}

PESO_DO_CORPO = "Peso do Corpo"


def equipamento_necessario(nome_canonico: str) -> str:
    """Infere o equipamento exigido a partir do nome canonico do exercicio.

    Resolve em tres passos: (1) override curado manualmente para nomes
    ambiguos mas com equipamento convencional conhecido (`_EQUIPAMENTO_OVERRIDE`);
    (2) palavras-chave no proprio nome (`_PALAVRAS_EQUIPAMENTO`); (3) por
    fim, `PESO_DO_CORPO` para o que restar (flexao, prancha, paralelas...).
    Nao e um cadastro verificado de equipamentos, e uma heuristica.
    """
    normalizado = normalize_exercise_name(nome_canonico)
    if normalizado in _EQUIPAMENTO_OVERRIDE:
        return _EQUIPAMENTO_OVERRIDE[normalizado]
    for palavra, equipamento in _PALAVRAS_EQUIPAMENTO:
        if palavra in normalizado:
            return equipamento
    return PESO_DO_CORPO


_INFO_POR_NOME_CANONICO: dict[str, dict[str, str]] = {
    info["nome_canonico"]: info for info in EXERCISE_DICTIONARY.values()
}


def _info_exercicio(nome: str) -> dict[str, str] | None:
    """Busca um exercicio no dicionario canonico a partir do nome.

    Aceita tanto o nome canonico exato (ex: o que vem armazenado na tabela
    `exercicios` do Gold) quanto qualquer variante reconhecida pelo
    standardizer (ex: "SUPINO RETO C/ BARRA" como aparece numa ficha crua).
    As chaves do dicionario sao variantes abreviadas, nem sempre iguais ao
    nome canonico normalizado - por isso o nome canonico e checado primeiro.
    """
    if nome in _INFO_POR_NOME_CANONICO:
        return _INFO_POR_NOME_CANONICO[nome]
    return EXERCISE_DICTIONARY.get(normalize_exercise_name(nome))


def _exercicios_por_grupo() -> dict[str, list[str]]:
    grupos: dict[str, set[str]] = {}
    for info in EXERCISE_DICTIONARY.values():
        grupos.setdefault(info["grupo_muscular"], set()).add(info["nome_canonico"])
    return {grupo: sorted(nomes) for grupo, nomes in grupos.items()}


_EXERCICIOS_POR_GRUPO = _exercicios_por_grupo()


def _todos_grupos_musculares() -> list[str]:
    return sorted(_EXERCICIOS_POR_GRUPO.keys())


def estimar_tempo_minutos(series: int) -> float:
    """Estima quantos minutos um exercicio com `series` series deve consumir."""
    segundos = series * (SEGUNDOS_POR_SERIE + SEGUNDOS_DESCANSO_ENTRE_SERIES) + SEGUNDOS_TROCA_EXERCICIO
    return segundos / 60


@dataclass
class AdaptacaoExercicio:
    """Resultado da avaliacao de um exercicio quanto ao equipamento disponivel."""

    exercicio_original: str
    equipamento_necessario: str | None
    precisa_adaptar: bool
    alternativa: str | None = None
    motivo: str = ""


def adaptar_exercicio(exercicio: str, equipamento_disponivel: list[str]) -> AdaptacaoExercicio:
    """Verifica se `exercicio` pode ser feito com o equipamento disponivel.

    Quando o equipamento exigido nao esta disponivel, busca uma alternativa
    do mesmo grupo muscular no dicionario canonico que use um equipamento
    disponivel (ou que nao exija equipamento). Exercicios nao reconhecidos
    pelo dicionario nao podem ser avaliados.
    """
    info = _info_exercicio(exercicio)
    if info is None:
        return AdaptacaoExercicio(
            exercicio_original=exercicio,
            equipamento_necessario=None,
            precisa_adaptar=False,
            motivo="Exercicio nao reconhecido no dicionario canonico; nao foi possivel avaliar o equipamento.",
        )

    nome_canonico = info["nome_canonico"]
    grupo_muscular = info["grupo_muscular"]
    equipamento = equipamento_necessario(nome_canonico)

    if equipamento == PESO_DO_CORPO or equipamento in equipamento_disponivel:
        return AdaptacaoExercicio(
            exercicio_original=exercicio,
            equipamento_necessario=equipamento,
            precisa_adaptar=False,
            motivo="Equipamento disponivel.",
        )

    for candidato in _EXERCICIOS_POR_GRUPO.get(grupo_muscular, []):
        if candidato == nome_canonico:
            continue
        equipamento_candidato = equipamento_necessario(candidato)
        if equipamento_candidato == PESO_DO_CORPO or equipamento_candidato in equipamento_disponivel:
            return AdaptacaoExercicio(
                exercicio_original=exercicio,
                equipamento_necessario=equipamento,
                precisa_adaptar=True,
                alternativa=candidato,
                motivo=f"'{nome_canonico}' exige {equipamento}, indisponivel. Sugerido '{candidato}' "
                f"({equipamento_candidato}) do mesmo grupo muscular ({grupo_muscular}).",
            )

    return AdaptacaoExercicio(
        exercicio_original=exercicio,
        equipamento_necessario=equipamento,
        precisa_adaptar=True,
        alternativa=None,
        motivo=f"'{nome_canonico}' exige {equipamento}, indisponivel, e nenhuma alternativa de "
        f"{grupo_muscular} no dicionario usa o equipamento disponivel.",
    )


def grupos_descansados(dias_minimo: int = 2, session: Session | None = None) -> list[str]:
    """Grupos musculares prontos para treinar (nao treinados nos ultimos `dias_minimo` dias).

    Um grupo nunca treinado, ou registrado apenas em fichas sem data, e
    considerado descansado por padrao: a ausencia de evidencia de treino
    recente nao e evidencia de treino recente.
    """
    descansados = []
    for grupo in _todos_grupos_musculares():
        dias = dias_desde_ultimo_treino(grupo, session=session)
        if dias is None or dias >= dias_minimo:
            descansados.append(grupo)
    return descansados


@dataclass
class ItemTreino:
    """Um exercicio dentro de um treino proposto, para validacao."""

    nome: str
    series: int = 3


@dataclass
class ValidacaoTreino:
    """Resultado da validacao de um treino proposto."""

    cabe_no_tempo: bool
    tempo_estimado_min: float
    tempo_disponivel_min: int
    grupos_sobrecarregados: list[str] = field(default_factory=list)
    motivos: list[str] = field(default_factory=list)


def validar_treino(
    exercicios: list[ItemTreino],
    tempo_disponivel_min: int,
    dias_minimo_descanso: int = 2,
    session: Session | None = None,
) -> ValidacaoTreino:
    """Verifica se um treino proposto cabe no tempo disponivel e nao sobrecarrega grupos recentes."""
    tempo_estimado = sum(estimar_tempo_minutos(item.series) for item in exercicios)
    motivos = []

    cabe_no_tempo = tempo_estimado <= tempo_disponivel_min
    if not cabe_no_tempo:
        motivos.append(
            f"Tempo estimado ({tempo_estimado:.0f} min) excede o disponivel ({tempo_disponivel_min} min)."
        )

    grupos_no_treino: set[str] = set()
    for item in exercicios:
        info = _info_exercicio(item.nome)
        if info is not None:
            grupos_no_treino.add(info["grupo_muscular"])

    grupos_sobrecarregados = []
    for grupo in sorted(grupos_no_treino):
        dias = dias_desde_ultimo_treino(grupo, session=session)
        if dias is not None and dias < dias_minimo_descanso:
            grupos_sobrecarregados.append(grupo)
            motivos.append(
                f"{grupo} foi treinado ha {dias} dia(s), menos que o minimo de descanso "
                f"de {dias_minimo_descanso} dia(s)."
            )

    return ValidacaoTreino(
        cabe_no_tempo=cabe_no_tempo,
        tempo_estimado_min=round(tempo_estimado, 1),
        tempo_disponivel_min=tempo_disponivel_min,
        grupos_sobrecarregados=grupos_sobrecarregados,
        motivos=motivos,
    )
