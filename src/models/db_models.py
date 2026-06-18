from sqlalchemy import Column, Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

# Sintaxe declarativa "classica" (Column + declarative_base), compativel tanto
# com SQLAlchemy 1.4 quanto 2.0: a imagem apache/airflow:2.9.3 ainda empacota
# SQLAlchemy 1.4 internamente, e usar a API Mapped/mapped_column (exclusiva do
# 2.0) quebraria a importacao destes modelos dentro do container do Airflow.
Base = declarative_base()


class Exercicio(Base):
    __tablename__ = "exercicios"
    __table_args__ = (UniqueConstraint("nome_canonico", name="uq_exercicios_nome_canonico"),)

    id = Column(Integer, primary_key=True)
    nome_canonico = Column(String(120), nullable=False)
    grupo_muscular = Column(String(60), nullable=True)

    registros = relationship("Registro", back_populates="exercicio")


class Treino(Base):
    __tablename__ = "treinos"
    __table_args__ = (UniqueConstraint("origem", name="uq_treinos_origem"),)

    id = Column(Integer, primary_key=True)
    data_treino = Column(Date, nullable=True)
    origem = Column(String(255), nullable=False)

    registros = relationship("Registro", back_populates="treino")


class Registro(Base):
    __tablename__ = "registros"

    id = Column(Integer, primary_key=True)
    treino_id = Column(ForeignKey("treinos.id"), nullable=False)
    exercicio_id = Column(ForeignKey("exercicios.id"), nullable=False)
    nome_original = Column(String(255), nullable=True)
    series = Column(Integer, nullable=True)
    repeticoes = Column(String(255), nullable=True)
    carga_kg = Column(Float, nullable=True)

    treino = relationship("Treino", back_populates="registros")
    exercicio = relationship("Exercicio", back_populates="registros")
