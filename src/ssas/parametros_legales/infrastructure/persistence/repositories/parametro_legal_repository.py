from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.parametros_legales.domain.entities.parametro_legal import ParametroLegal
from ssas.parametros_legales.domain.exceptions import ParametroLegalNotFoundError
from ssas.parametros_legales.infrastructure.persistence.models.parametro_legal import (
    ParametroLegalModel,
    ParametroValorModel,
)
from ssas.parametros_legales.ports.outgoing.parametro_legal_repository import (
    ParametroLegalRepository,
)

CATALOGO_CODIGO = "PARAMETROS_LABORALES_BO"
PORCENTAJES = ("afp", "aporte_solidario", "rc_iva", "aguinaldo", "prima")


class SqlAlchemyParametroLegalRepository(ParametroLegalRepository):
    """Adapta la API historica de periodos al catalogo/valor del diagrama Sprint 1."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _catalogo(self) -> ParametroLegalModel:
        model = (
            await self.session.execute(
                select(ParametroLegalModel).where(ParametroLegalModel.codigo == CATALOGO_CODIGO)
            )
        ).scalar_one_or_none()
        if model is None:
            model = ParametroLegalModel(
                codigo=CATALOGO_CODIGO,
                nombre="Parametros laborales de Bolivia",
                descripcion="Porcentajes laborales vigentes usados por el sistema",
                tipo_valor="JSON",
                pais="BO",
            )
            self.session.add(model)
            await self.session.flush()
        return model

    async def list_by_empresa(self, empresa_id: str) -> list[ParametroLegal]:
        result = await self.session.execute(
            select(ParametroValorModel)
            .join(ParametroValorModel.parametro)
            .where(ParametroLegalModel.codigo == CATALOGO_CODIGO)
            .order_by(ParametroValorModel.vigente_desde.desc())
        )
        return [self._to_entity(model, empresa_id) for model in result.scalars().all()]

    async def get_by_id(self, periodo_id: str, empresa_id: str) -> ParametroLegal | None:
        model = (
            await self.session.execute(
                select(ParametroValorModel)
                .join(ParametroValorModel.parametro)
                .where(
                    ParametroValorModel.id == periodo_id,
                    ParametroLegalModel.codigo == CATALOGO_CODIGO,
                )
            )
        ).scalar_one_or_none()
        return self._to_entity(model, empresa_id) if model else None

    async def find_overlap(
        self,
        empresa_id: str,
        vigencia_desde: date,
        vigencia_hasta: date,
        exclude_id: str | None = None,
    ) -> ParametroLegal | None:
        conditions = [
            ParametroLegalModel.codigo == CATALOGO_CODIGO,
            ParametroValorModel.vigente_desde <= vigencia_hasta,
            ParametroValorModel.vigente_hasta >= vigencia_desde,
        ]
        if exclude_id is not None:
            conditions.append(ParametroValorModel.id != exclude_id)
        model = (
            await self.session.execute(
                select(ParametroValorModel)
                .join(ParametroValorModel.parametro)
                .where(and_(*conditions))
                .order_by(ParametroValorModel.vigente_desde.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return self._to_entity(model, empresa_id) if model else None

    async def create(self, empresa_id: str, values: dict[str, Any]) -> ParametroLegal:
        catalogo = await self._catalogo()
        model = ParametroValorModel(
            parametro_id=catalogo.id,
            valor={campo: self._json_value(values.get(campo)) for campo in PORCENTAJES},
            vigente_desde=values["vigencia_desde"],
            vigente_hasta=values["vigencia_hasta"],
            norma_legal=values.get("norma_legal"),
        )
        self.session.add(model)
        await self.session.flush()
        return self._to_entity(model, empresa_id)

    async def update(
        self, periodo_id: str, empresa_id: str, values: dict[str, Any]
    ) -> ParametroLegal:
        model = (
            await self.session.execute(
                select(ParametroValorModel)
                .join(ParametroValorModel.parametro)
                .where(
                    ParametroValorModel.id == periodo_id,
                    ParametroLegalModel.codigo == CATALOGO_CODIGO,
                )
            )
        ).scalar_one_or_none()
        if model is None:
            raise ParametroLegalNotFoundError("Periodo de parametros no encontrado")
        if "vigencia_desde" in values:
            model.vigente_desde = values["vigencia_desde"]
        if "vigencia_hasta" in values:
            model.vigente_hasta = values["vigencia_hasta"]
        if "norma_legal" in values:
            model.norma_legal = values["norma_legal"]
        payload = dict(model.valor)
        for campo in PORCENTAJES:
            if campo in values:
                payload[campo] = self._json_value(values[campo])
        model.valor = payload
        await self.session.flush()
        return self._to_entity(model, empresa_id)

    @staticmethod
    def _json_value(value: Any) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _to_entity(model: ParametroValorModel, empresa_id: str) -> ParametroLegal:
        def decimal_value(campo: str) -> Decimal | None:
            value = model.valor.get(campo)
            return None if value is None else Decimal(str(value))

        return ParametroLegal(
            id=model.id,
            empresa_id=empresa_id,
            vigencia_desde=model.vigente_desde,
            vigencia_hasta=model.vigente_hasta,
            afp=decimal_value("afp"),
            aporte_solidario=decimal_value("aporte_solidario"),
            rc_iva=decimal_value("rc_iva"),
            aguinaldo=decimal_value("aguinaldo"),
            prima=decimal_value("prima"),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
