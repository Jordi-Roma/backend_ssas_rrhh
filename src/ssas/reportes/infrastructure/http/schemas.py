from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class FiltroReporte(BaseModel):
    campo: str
    operador: Literal["igual", "contiene", "mayor_igual", "menor_igual", "entre"]
    valor: Any


class OrdenReporte(BaseModel):
    campo: str
    direccion: Literal["asc", "desc"] = "asc"


class ReporteConfig(BaseModel):
    fuente: str
    columnas: list[str] = Field(min_length=1, max_length=20)
    filtros: list[FiltroReporte] = Field(default_factory=list, max_length=10)
    orden: list[OrdenReporte] = Field(default_factory=list, max_length=5)

    @field_validator("columnas")
    @classmethod
    def columnas_unicas(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Las columnas no pueden repetirse")
        return value


class CrearReporte(ReporteConfig):
    nombre: str = Field(min_length=3, max_length=160)


class ActualizarReporte(BaseModel):
    nombre: str | None = Field(default=None, min_length=3, max_length=160)
    columnas: list[str] | None = None
    filtros: list[FiltroReporte] | None = None
    orden: list[OrdenReporte] | None = None
    activo: bool | None = None


class ReporteResponse(CrearReporte):
    id: str
    empresa_id: str
    usuario_id: str
    activo: bool
    fecha_registro: datetime
    fecha_actualizacion: datetime


class VistaPrevia(BaseModel):
    columnas: list[str]
    items: list[dict[str, Any]]
    total: int
    page: int
    per_page: int


class EnviarReporteRequest(ReporteConfig):
    destinatarios: list[str] = Field(min_length=1, max_length=10)
    formato: Literal["xlsx", "html", "pdf"]
