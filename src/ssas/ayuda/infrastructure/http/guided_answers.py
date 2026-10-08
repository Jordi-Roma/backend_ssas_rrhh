"""Deterministic, scoped answers for app guidance and live recruitment data."""

from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.ayuda.infrastructure.http.router import _rank, _tokens, _visible
from ssas.core.security.dependencies import CurrentUser
from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel
from ssas.postulantes.infrastructure.persistence.models.postulante import PostulanteModel
from ssas.roles.infrastructure.persistence.repositories.authorization_repository import (
    SqlAlchemyAuthorizationRepository,
)
from ssas.vacantes.application.use_cases.gestionar_vacantes import GestionarVacantes
from ssas.vacantes.infrastructure.persistence.repositories.vacante_repository import (
    SqlAlchemyVacanteRepository,
)


def _answer(
    text: str, links: list[dict[str, str]] | None = None, *, unavailable: bool = False
) -> dict:
    return {
        "respuesta": text,
        "fuentes": [],
        "enlaces": links or [],
        "sin_respuesta": unavailable,
    }


async def _slug(empresa_id: str, session: AsyncSession) -> str | None:
    return await session.scalar(
        select(EmpresaModel.slug).where(
            EmpresaModel.id == empresa_id,
            EmpresaModel.activo.is_(True),
            EmpresaModel.portal_publico_activo.is_(True),
            EmpresaModel.eliminado_at.is_(None),
        )
    )


async def _vacancies(slug: str, session: AsyncSession) -> dict:
    vacancies = await GestionarVacantes(SqlAlchemyVacanteRepository(session)).listar_publicas(
        slug, None, None
    )
    base = f"/empleos/{quote(slug, safe='')}"
    if not vacancies:
        return _answer("No hay vacantes publicadas y vigentes en el portal de esta empresa.")
    links = [
        {"titulo": item.titulo, "ruta": f"{base}/vacantes/{quote(str(item.id), safe='')}"}
        for item in vacancies[:5]
    ]
    links.append({"titulo": "Ver todas las vacantes", "ruta": base})
    quantity = "una vacante publicada y vigente" if len(vacancies) == 1 else (
        f"{len(vacancies)} vacantes publicadas y vigentes"
    )
    return _answer(
        f"Hay {quantity}. "
        "Abre una para ver los requisitos y postularte.",
        links,
    )


async def _candidates(user: CurrentUser | None, empresa_id: str, session: AsyncSession) -> dict:
    if user is None:
        return _answer(
            "Los datos de postulantes son privados y requieren iniciar sesión con permiso.",
            unavailable=True,
        )
    codes = await SqlAlchemyAuthorizationRepository(session).get_user_permission_codes(
        user.id, user.empresa_id
    )
    if "postulantes:ver" not in codes:
        return _answer("No tienes permiso para consultar postulantes.", unavailable=True)
    total = await session.scalar(
        select(func.count(PostulanteModel.id)).where(PostulanteModel.empresa_id == empresa_id)
    )
    quantity = "un postulante registrado" if total == 1 else f"{total or 0} postulantes registrados"
    return _answer(
        f"Hay {quantity} en esta empresa. Abre el listado para consultar sus datos.",
        [{"titulo": "Ver postulantes", "ruta": "/postulantes"}],
    )


async def guided_answer(
    question: str,
    empresa_id: str,
    slug: str | None,
    user: CurrentUser | None,
    session: AsyncSession,
) -> dict | None:
    words = _tokens(question)
    if words & {"postulantes", "candidatos", "candidatas", "aspirantes"}:
        return await _candidates(user, empresa_id, session)

    if words & {"vacantes", "ofertas", "empleos"}:
        company_slug = slug or await _slug(empresa_id, session)
        if company_slug is None:
            return _answer("El portal de empleo de esta empresa no está disponible.", unavailable=True)
        return await _vacancies(company_slug, session)

    if words & {"postulo", "postular", "postularme", "postulacion", "aplico", "aplicar"}:
        company_slug = slug or await _slug(empresa_id, session)
        if company_slug is None:
            return _answer("El portal de empleo de esta empresa no está disponible.", unavailable=True)
        return _answer(
            "Abre una vacante publicada en el portal de empleo, revisa los requisitos "
            "y utiliza el formulario de postulación. Si ya te postulaste, usa el seguimiento del portal.",
            [{"titulo": "Ir al portal de empleo", "ruta": f"/empleos/{quote(company_slug, safe='')}"}],
        )

    if user is not None:
        guides = _rank(question, await _visible(user, session))
        if guides:
            guide = guides[0]
            return _answer(
                guide["texto"], [{"titulo": guide["titulo"], "ruta": guide["ruta"]}]
            )

    if {"informacion", "brindar"} <= words or {"puedes", "hacer"} <= words:
        if user is None:
            return _answer(
                "Puedo mostrar vacantes publicadas, explicar cómo postularte y responder "
                "con artículos públicos de esta empresa. No puedo mostrar datos privados de postulantes."
            )
        return _answer(
            "Puedo ayudarte con las guías del sistema, vacantes publicadas y artículos de "
            "esta empresa. Con el permiso correspondiente, también puedo mostrarte "
            "un resumen de postulantes."
        )
    return None


async def suggested_questions(
    public_only: bool,
    user: CurrentUser | None,
    session: AsyncSession,
) -> list[str]:
    questions = ["¿Qué vacantes hay?", "¿Cómo me postulo?"]
    if not public_only and user is not None:
        guides = await _visible(user, session)
        if any(item["id"] == "reportes" for item in guides):
            questions.append("¿Cómo hago reportes?")
        codes = await SqlAlchemyAuthorizationRepository(session).get_user_permission_codes(
            user.id, user.empresa_id
        )
        if "postulantes:ver" in codes:
            questions.append("¿Cuántos postulantes hay?")
    return questions
