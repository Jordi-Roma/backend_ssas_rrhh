"""Tenant-scoped knowledge articles and grounded chatbot responses."""

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.ayuda.infrastructure.http.router import _limit
from ssas.ayuda.infrastructure.persistence.models import KnowledgeArticle, KnowledgeChunk
from ssas.ayuda.infrastructure.providers.gemini_chat_provider import (
    ChatProviderError,
    GeminiChatProvider,
    cosine,
)
from ssas.config.settings import settings
from ssas.core.api.request_metadata import get_client_ip
from ssas.core.security.dependencies import CurrentUser, get_current_user, require_permission
from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel
from ssas.infrastructure.database.session import get_session

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])


class ArticleInput(BaseModel):
    titulo: str = Field(min_length=3, max_length=160)
    contenido: str = Field(min_length=15, max_length=12000)
    categoria: str = Field(default="General", min_length=1, max_length=80)
    publico: bool = False
    publicado: bool = False


class ChatInput(BaseModel):
    pregunta: str = Field(min_length=3, max_length=350)


def _article(item: KnowledgeArticle) -> dict:
    return {
        "id": item.id,
        "titulo": item.titulo,
        "contenido": item.contenido,
        "categoria": item.categoria,
        "publico": item.publico,
        "publicado": item.publicado,
        "actualizado_en": item.actualizado_en,
    }


def _chunks(text: str) -> list[str]:
    words = text.split()
    size = 160
    step = 130
    return [
        " ".join(words[index : index + size])
        for index in range(0, len(words), step)
        if words[index : index + size]
    ]


async def _index(article: KnowledgeArticle, session: AsyncSession) -> None:
    provider = GeminiChatProvider(settings)
    fragments = _chunks(f"{article.titulo}. {article.contenido}") if article.publicado else []
    vectors = [await provider.embed(fragment) for fragment in fragments]
    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.articulo_id == article.id))
    session.add_all(
        [
            KnowledgeChunk(
                articulo_id=article.id,
                empresa_id=article.empresa_id,
                orden=index,
                texto=fragment,
                vector=vector,
                modelo=settings.gemini_help_embedding_model,
            )
            for index, (fragment, vector) in enumerate(zip(fragments, vectors))
        ]
    )


def _tenant(user: CurrentUser) -> str:
    if user.empresa_id is None:
        raise HTTPException(403, "Selecciona una cuenta de empresa")
    return user.empresa_id


@router.get("/articulos", description="Lista artículos de conocimiento de la empresa autenticada.")
async def list_articles(
    user: CurrentUser = Depends(require_permission("roles:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(KnowledgeArticle)
        .where(KnowledgeArticle.empresa_id == _tenant(user))
        .order_by(KnowledgeArticle.titulo)
    )
    return [_article(item) for item in rows]


@router.get("/articulos/{article_id}", description="Consulta un artículo publicado de la empresa.")
async def read_article(
    article_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.must_change_password:
        raise HTTPException(403, "Debes cambiar tu contrasena")
    article = await session.scalar(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == str(article_id),
            KnowledgeArticle.empresa_id == _tenant(user),
            KnowledgeArticle.publicado.is_(True),
        )
    )
    if article is None:
        raise HTTPException(404, "Articulo no encontrado")
    return _article(article)


@router.post("/articulos", status_code=201, description="Crea e indexa un artículo de conocimiento de la empresa.")
async def create_article(
    body: ArticleInput,
    user: CurrentUser = Depends(require_permission("roles:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    article = KnowledgeArticle(empresa_id=_tenant(user), **body.model_dump())
    session.add(article)
    await session.flush()
    try:
        await _index(article, session)
    except ChatProviderError as exc:
        raise HTTPException(503, str(exc)) from exc
    return _article(article)


@router.put("/articulos/{article_id}", description="Actualiza y reindexa un artículo de conocimiento de la empresa.")
async def update_article(
    article_id: UUID,
    body: ArticleInput,
    user: CurrentUser = Depends(require_permission("roles:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    article = await session.scalar(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == str(article_id),
            KnowledgeArticle.empresa_id == _tenant(user),
        )
    )
    if article is None:
        raise HTTPException(404, "Articulo no encontrado")
    for key, value in body.model_dump().items():
        setattr(article, key, value)
    try:
        await _index(article, session)
    except ChatProviderError as exc:
        raise HTTPException(503, str(exc)) from exc
    return _article(article)


@router.delete("/articulos/{article_id}", status_code=204, description="Elimina un artículo y sus fragmentos indexados.")
async def delete_article(
    article_id: UUID,
    user: CurrentUser = Depends(require_permission("roles:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    article = await session.scalar(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == str(article_id),
            KnowledgeArticle.empresa_id == _tenant(user),
        )
    )
    if article is None:
        raise HTTPException(404, "Articulo no encontrado")
    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.articulo_id == article.id))
    await session.delete(article)


async def _public_company(slug: str, session: AsyncSession) -> str:
    company = await session.scalar(
        select(EmpresaModel).where(
            EmpresaModel.slug == slug,
            EmpresaModel.activo.is_(True),
            EmpresaModel.portal_publico_activo.is_(True),
            EmpresaModel.eliminado_at.is_(None),
        )
    )
    if company is None:
        raise HTTPException(404, "Portal no disponible")
    return company.id


async def _suggestions(empresa_id: str, public_only: bool, session: AsyncSession) -> list[str]:
    stmt = select(KnowledgeArticle.titulo).where(
        KnowledgeArticle.empresa_id == empresa_id,
        KnowledgeArticle.publicado.is_(True),
    )
    if public_only:
        stmt = stmt.where(KnowledgeArticle.publico.is_(True))
    rows = await session.scalars(stmt.order_by(KnowledgeArticle.titulo).limit(8))
    return list(rows)


@router.get("/sugerencias", description="Sugiere preguntas basadas en artículos publicados de la empresa.")
async def suggestions(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.must_change_password:
        raise HTTPException(403, "Debes cambiar tu contrasena")
    return await _suggestions(_tenant(user), False, session)


@router.get("/publico/{slug}/sugerencias", description="Sugiere preguntas públicas de una empresa activa.")
async def public_suggestions(slug: str, session: AsyncSession = Depends(get_session)):
    return await _suggestions(await _public_company(slug, session), True, session)


@router.get("/publico/{slug}/articulos/{article_id}", description="Consulta un artículo público publicado por la empresa.")
async def public_read_article(
    slug: str,
    article_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    empresa_id = await _public_company(slug, session)
    article = await session.scalar(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == str(article_id),
            KnowledgeArticle.empresa_id == empresa_id,
            KnowledgeArticle.publicado.is_(True),
            KnowledgeArticle.publico.is_(True),
        )
    )
    if article is None:
        raise HTTPException(404, "Articulo no encontrado")
    return _article(article)


async def _respond(question: str, empresa_id: str, public_only: bool, session: AsyncSession):
    if re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b\d{8,}\b", question, re.IGNORECASE):
        raise HTTPException(422, "No incluyas datos personales en la pregunta")
    stmt = (
        select(KnowledgeChunk, KnowledgeArticle)
        .join(KnowledgeArticle, KnowledgeArticle.id == KnowledgeChunk.articulo_id)
        .where(
            KnowledgeChunk.empresa_id == empresa_id,
            KnowledgeArticle.empresa_id == empresa_id,
            KnowledgeArticle.publicado.is_(True),
            KnowledgeChunk.modelo == settings.gemini_help_embedding_model,
        )
        .limit(1000)
    )
    if public_only:
        stmt = stmt.where(KnowledgeArticle.publico.is_(True))
    rows = (await session.execute(stmt)).all()
    if not rows:
        return {
            "respuesta": "No encuentro esa informacion en la base de conocimiento.",
            "fuentes": [],
            "sin_respuesta": True,
        }
    provider = GeminiChatProvider(settings)
    try:
        query_vector = await provider.embed(question)
    except ChatProviderError as exc:
        raise HTTPException(503, str(exc)) from exc
    matches = sorted(
        ((cosine(query_vector, chunk.vector), chunk, article) for chunk, article in rows),
        key=lambda item: item[0],
        reverse=True,
    )
    relevant = [item for item in matches[:3] if item[0] >= 0.58]
    if not relevant:
        return {
            "respuesta": "No encuentro esa informacion en la base de conocimiento.",
            "fuentes": [],
            "sin_respuesta": True,
        }
    sources = list(dict.fromkeys((article.id, article.titulo) for _, _, article in relevant))
    try:
        answer = await provider.answer(
            question, [(article.titulo, chunk.text) for _, chunk, article in relevant]
        )
    except ChatProviderError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "respuesta": answer,
        "fuentes": [{"id": article_id, "titulo": title} for article_id, title in sources],
        "sin_respuesta": False,
    }


@router.post("/mensajes", description="Responde con conocimiento publicado de la empresa autenticada.")
async def message(
    body: ChatInput,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.must_change_password:
        raise HTTPException(403, "Debes cambiar tu contrasena")
    _limit(user.id)
    return await _respond(body.pregunta.strip(), _tenant(user), False, session)


@router.post("/publico/{slug}/mensajes", description="Responde con conocimiento público publicado por la empresa.")
async def public_message(
    slug: str,
    body: ChatInput,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    _limit(f"public:{get_client_ip(request) or 'unknown'}")
    return await _respond(
        body.pregunta.strip(), await _public_company(slug, session), True, session
    )
