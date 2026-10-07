"""Local, read-only help for authenticated users."""

import re
import time
import unicodedata
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.ayuda.infrastructure.providers.openai_help_provider import (
    HelpProviderError,
    OpenAIHelpProvider,
)
from ssas.config.settings import settings
from ssas.core.security.dependencies import CurrentUser, get_current_user
from ssas.infrastructure.database.session import get_session
from ssas.roles.infrastructure.persistence.repositories.authorization_repository import (
    SqlAlchemyAuthorizationRepository,
)

router = APIRouter(prefix="/ayuda", tags=["Ayuda"])

ARTICLES = (
    {
        "id": "acceso",
        "titulo": "Acceso y contraseña",
        "texto": "En la pantalla de inicio de sesión elige Empresa e introduce su código, usuario y contraseña. La cuenta de plataforma utiliza la opción Plataforma. Puedes cambiar tu contraseña desde Mi perfil.",
        "ruta": "/perfil",
        "permiso": None,
    },
    {
        "id": "usuarios",
        "titulo": "Usuarios y roles",
        "texto": "En Usuarios puedes crear y gestionar cuentas de la empresa. En Roles y permisos asignas los privilegios necesarios. Los cambios de permisos deben hacerlos administradores autorizados.",
        "ruta": "/usuarios",
        "permiso": "usuarios:ver",
    },
    {
        "id": "organizacion",
        "titulo": "Departamentos y cargos",
        "texto": "En Organización puedes consultar departamentos y cargos. Un cargo debe pertenecer a un departamento de la misma empresa.",
        "ruta": "/organizacion",
        "permiso": "departamentos:ver",
    },
    {
        "id": "importacion",
        "titulo": "Importar catálogos",
        "texto": "En Importar datos descarga una plantilla CSV o Excel, carga el archivo, revisa la vista previa y confirma. Puedes cargar catálogos y, con permiso adicional, usuarios con un rol activo de la empresa. El archivo de usuarios contiene contraseñas iniciales: protégelo y elimínalo después. Las filas con errores bloquean la importación.",
        "ruta": "/importaciones",
        "permiso": "importacion:gestionar",
    },
    {
        "id": "vacantes",
        "titulo": "Vacantes",
        "texto": "En Vacantes puedes consultar las ofertas de empleo. Quien tenga permisos de edición puede crear y publicar vacantes.",
        "ruta": "/vacantes",
        "permiso": "vacantes:ver",
    },
    {
        "id": "seleccion",
        "titulo": "Selección de candidatos",
        "texto": "En Selección eliges una vacante, revisas su ranking y comparas entre dos y cuatro postulaciones. La decisión de contratación corresponde al personal autorizado, no a la IA.",
        "ruta": "/seleccion",
        "permiso": "postulaciones:ver",
    },
    {
        "id": "entrevistas",
        "titulo": "Entrevistas",
        "texto": "En Entrevistas puedes consultar la agenda. Con permisos adecuados puedes programar, confirmar, cancelar y registrar resultados.",
        "ruta": "/entrevistas",
        "permiso": "entrevistas:ver",
    },
    {
        "id": "reportes",
        "titulo": "Reportes",
        "texto": "En Reportes seleccionas columnas, filtros y orden antes de exportar. Los formatos disponibles son Excel, HTML y PDF; enviar por correo requiere SMTP configurado.",
        "ruta": "/reportes",
        "permiso": "reportes:ver",
    },
    {
        "id": "respaldo",
        "titulo": "Backup y restauración",
        "texto": "Backup / Restore permite crear, descargar y consultar copias completas. La restauración es destructiva y está deshabilitada salvo configuración explícita.",
        "ruta": "/respaldos",
        "permiso": "platform:backup:ver",
    },
)

_requests: dict[str, deque[float]] = defaultdict(deque)


class Question(BaseModel):
    pregunta: str = Field(min_length=3, max_length=350)


def _limit(user_id: str) -> None:
    now = time.monotonic()
    entries = _requests[user_id]
    while entries and now - entries[0] > 60:
        entries.popleft()
    if len(entries) >= 10:
        raise HTTPException(429, "Espera antes de hacer más preguntas")
    entries.append(now)


def _tokens(value: str) -> set[str]:
    plain = unicodedata.normalize("NFD", value.casefold())
    plain = "".join(char for char in plain if unicodedata.category(char) != "Mn")
    return {token for token in re.findall(r"[a-z0-9]+", plain) if len(token) > 2}


def _rank(question: str, articles: list[dict]) -> list[dict]:
    tokens = _tokens(question)
    scored = [
        (len(tokens & _tokens(item["titulo"])) * 3 + len(tokens & _tokens(item["texto"])), item)
        for item in articles
    ]
    return [
        item for score, item in sorted(scored, key=lambda pair: pair[0], reverse=True) if score > 0
    ][:2]


async def _visible(user: CurrentUser, session: AsyncSession) -> list[dict]:
    codes = await SqlAlchemyAuthorizationRepository(session).get_user_permission_codes(
        user.id, user.empresa_id
    )
    platform_codes = {
        "usuarios:ver": "platform:usuarios:gestionar",
        "departamentos:ver": "platform:organizacion:gestionar",
        "importacion:gestionar": "platform:importacion:gestionar",
        "vacantes:ver": "platform:vacantes:gestionar",
        "postulaciones:ver": "platform:postulaciones:ver",
        "entrevistas:ver": "platform:entrevistas:ver",
        "reportes:ver": "platform:reportes:gestionar",
    }
    return [
        article
        for article in ARTICLES
        if article["permiso"] is None
        or (
            platform_codes.get(article["permiso"], article["permiso"])
            if user.es_plataforma
            else article["permiso"]
        )
        in codes
    ]


@router.get("/preguntas", description="Lista las guías de ayuda visibles para la cuenta autenticada.")
async def preguntas(
    user: CurrentUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    if user.must_change_password:
        raise HTTPException(403, "Debes cambiar tu contraseña antes de continuar")
    return [
        {"id": item["id"], "titulo": item["titulo"], "ruta": item["ruta"]}
        for item in await _visible(user, session)
    ]


@router.post("/consultar", description="Responde una consulta usando las guías locales autorizadas.")
async def consultar(
    question: Question,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.must_change_password:
        raise HTTPException(403, "Debes cambiar tu contraseña antes de continuar")
    _limit(user.id)
    text = question.pregunta.strip()
    if re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", text, re.IGNORECASE) or re.search(
        r"\b\d{8,}\b", text
    ):
        raise HTTPException(
            422, "No incluyas correos, documentos ni datos personales en la pregunta"
        )
    articles = _rank(text, await _visible(user, session))
    if not articles:
        return {
            "respuesta": "No encuentro esa información en la ayuda disponible.",
            "fuentes": [],
            "modo": "sin_resultado",
        }
    article = articles[0]
    return {
        "respuesta": article["texto"],
        "fuentes": [{"titulo": article["titulo"], "ruta": article["ruta"]}],
        "modo": "guia",
    }


@router.post("/articulos/{article_id}/explicar", description="Explica una guía visible, con IA cuando está habilitada.")
async def explicar_articulo(
    article_id: str,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.must_change_password:
        raise HTTPException(403, "Debes cambiar tu contraseña antes de continuar")
    _limit(user.id)
    article = next(
        (item for item in await _visible(user, session) if item["id"] == article_id), None
    )
    if article is None:
        raise HTTPException(404, "Guía no disponible")
    source = [{"titulo": article["titulo"], "ruta": article["ruta"]}]
    if settings.help_ai_enabled and settings.openai_api_key:
        try:
            answer = await OpenAIHelpProvider(settings).explain(article)
            return {"respuesta": answer, "fuentes": source, "modo": "ia"}
        except HelpProviderError:
            pass
    return {
        "respuesta": article["texto"],
        "fuentes": source,
        "modo": "guia",
        "aviso": "La IA no está disponible; se muestra la guía local.",
    }


for route in router.routes:
    route.description = (
        "Consulta guías autorizadas. La IA optativa recibe solo contenido fijo de la guía."
    )
