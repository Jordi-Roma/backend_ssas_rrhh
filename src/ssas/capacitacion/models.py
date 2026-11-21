from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ssas.infrastructure.database.base import Base


def pk():
    return mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))


def tenant():
    return mapped_column(UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="RESTRICT"), nullable=False)


class CursoModel(Base):
    __tablename__ = "curso"
    __table_args__ = (Index("ix_curso_empresa_estado", "empresa_id", "estado"), CheckConstraint("nota_minima BETWEEN 0 AND 100", name="ck_curso_nota_minima"))

    id: Mapped[str] = pk()
    empresa_id: Mapped[str] = tenant()
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    categoria: Mapped[str | None] = mapped_column(String(100))
    duracion_horas: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    es_obligatorio: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    imagen_url: Mapped[str | None] = mapped_column(Text)
    instructor: Mapped[str | None] = mapped_column(String(160))
    habilidad_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("habilidad.id", ondelete="SET NULL"))
    nota_minima: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="70")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="BORRADOR")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LeccionModel(Base):
    __tablename__ = "leccion"
    __table_args__ = (UniqueConstraint("curso_id", "orden", name="uq_leccion_curso_orden"), CheckConstraint("tipo IN ('VIDEO','DOCUMENTO','MANUAL','QUIZ','ENLACE')", name="ck_leccion_tipo"), CheckConstraint("orden > 0 AND (duracion_minutos IS NULL OR duracion_minutos >= 0)", name="ck_leccion_orden_duracion"))

    id: Mapped[str] = pk()
    empresa_id: Mapped[str] = tenant()
    curso_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("curso.id", ondelete="CASCADE"), nullable=False, index=True)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    contenido_url: Mapped[str | None] = mapped_column(Text)
    contenido_texto: Mapped[str | None] = mapped_column(Text)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    duracion_minutos: Mapped[int | None] = mapped_column(Integer)


class InscripcionModel(Base):
    __tablename__ = "inscripcion"
    __table_args__ = (UniqueConstraint("curso_id", "empleado_id", name="uq_inscripcion_curso_empleado"), Index("ix_inscripcion_empresa_empleado", "empresa_id", "empleado_id"), CheckConstraint("progreso BETWEEN 0 AND 100 AND (calificacion IS NULL OR calificacion BETWEEN 0 AND 100)", name="ck_inscripcion_notas"), CheckConstraint("estado IN ('INSCRITO','EN_CURSO','COMPLETADO','ABANDONADO','VENCIDO')", name="ck_inscripcion_estado"))

    id: Mapped[str] = pk()
    empresa_id: Mapped[str] = tenant()
    curso_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("curso.id", ondelete="RESTRICT"), nullable=False)
    empleado_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empleado.id", ondelete="RESTRICT"), nullable=False)
    fecha_limite: Mapped[date | None] = mapped_column(Date)
    progreso: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    calificacion: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    aprobado: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="INSCRITO")
    certificado_url: Mapped[str | None] = mapped_column(Text)
    inscrito_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProgresoLeccionModel(Base):
    __tablename__ = "progreso_leccion"
    __table_args__ = (UniqueConstraint("inscripcion_id", "leccion_id", name="uq_progreso_inscripcion_leccion"),)

    id: Mapped[str] = pk()
    empresa_id: Mapped[str] = tenant()
    inscripcion_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("inscripcion.id", ondelete="CASCADE"), nullable=False)
    leccion_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("leccion.id", ondelete="RESTRICT"), nullable=False)
    completada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    calificacion: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


class EmpleadoHabilidadModel(Base):
    __tablename__ = "empleado_habilidad"
    __table_args__ = (UniqueConstraint("empleado_id", "habilidad_id", name="uq_empleado_habilidad"),)

    id: Mapped[str] = pk()
    empresa_id: Mapped[str] = tenant()
    empleado_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empleado.id", ondelete="CASCADE"), nullable=False)
    habilidad_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("habilidad.id", ondelete="RESTRICT"), nullable=False)
    nivel: Mapped[str | None] = mapped_column(String(30))
    adquirida_en: Mapped[date | None] = mapped_column(Date)
    fecha_evaluacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    certificado_por: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="SET NULL"))
    curso_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("curso.id", ondelete="SET NULL"))
