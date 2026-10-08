"""Tenant-scoped knowledge articles and grounded chatbot responses."""

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.ayuda.infrastructure.http.guided_answers import guided_answer, suggested_questions
from ssas.ayuda.infrastructure.http.router import _limit, _tokens
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
            func.lower(EmpresaModel.slug) == slug.strip().lower(),
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
    empresa_id = _tenant(user)
    guided = await suggested_questions(False, user, session)
    return list(dict.fromkeys(guided + await _suggestions(empresa_id, False, session)))[:8]


@router.get("/publico/{slug}/sugerencias", description="Sugiere preguntas públicas de una empresa activa.")
async def public_suggestions(slug: str, session: AsyncSession = Depends(get_session)):
    empresa_id = await _public_company(slug, session)
    guided = await suggested_questions(True, None, session)
    return list(dict.fromkeys(guided + await _suggestions(empresa_id, True, session)))[:8]


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


def _reject_personal_data(question: str) -> None:
    if re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b\d{8,}\b", question, re.IGNORECASE):
        raise HTTPException(422, "No incluyas datos personales en la pregunta")


async def _respond(question: str, empresa_id: str, public_only: bool, session: AsyncSession):
    _reject_personal_data(question)
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
        return await _article_fallback(question, empresa_id, public_only, session)
    provider = GeminiChatProvider(settings)
    try:
        query_vector = await provider.embed(question)
    except ChatProviderError as exc:
        fallback = await _article_fallback(question, empresa_id, public_only, session)
        if not fallback["sin_respuesta"]:
            return fallback
        raise HTTPException(503, str(exc)) from exc
    matches = sorted(
        ((cosine(query_vector, chunk.vector), chunk, article) for chunk, article in rows),
        key=lambda item: item[0],
        reverse=True,
    )
    relevant = [item for item in matches[:3] if item[0] >= 0.58]
    if not relevant:
        return await _article_fallback(question, empresa_id, public_only, session)
    sources = list(dict.fromkeys((article.id, article.titulo) for _, _, article in relevant))
    try:
        answer = await provider.answer(
            question, [(article.titulo, chunk.text) for _, chunk, article in relevant]
        )
    except ChatProviderError as exc:
        fallback = await _article_fallback(question, empresa_id, public_only, session)
        if not fallback["sin_respuesta"]:
            return fallback
        raise HTTPException(503, str(exc)) from exc
    return {
        "respuesta": answer,
        "fuentes": [{"id": article_id, "titulo": title} for article_id, title in sources],
        "sin_respuesta": False,
    }


async def _article_fallback(
    question: str, empresa_id: str, public_only: bool, session: AsyncSession
) -> dict:
    stmt = select(KnowledgeArticle).where(
        KnowledgeArticle.empresa_id == empresa_id,
        KnowledgeArticle.publicado.is_(True),
    )
    if public_only:
        stmt = stmt.where(KnowledgeArticle.publico.is_(True))
    articles = (await session.scalars(stmt.order_by(KnowledgeArticle.titulo).limit(100))).all()
    terms = _tokens(question) - {"como", "puedo", "hacer", "tienes", "para", "sobre", "informacion"}
    matches = sorted(
        (
            (
                len(terms & _tokens(article.titulo)) * 3
                + len(terms & _tokens(article.contenido)),
                article,
            )
            for article in articles
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if matches and matches[0][0] >= 2:
        article = matches[0][1]
        return {
            "respuesta": "Encontré un artículo relacionado. Ábrelo para consultar el contenido aprobado.",
            "fuentes": [{"id": article.id, "titulo": article.titulo}],
            "sin_respuesta": False,
        }
    return {
        "respuesta": "No encuentro esa información en la base de conocimiento.",
        "fuentes": [],
        "sin_respuesta": True,
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
    question = body.pregunta.strip()
    _reject_personal_data(question)
    empresa_id = _tenant(user)
    guided = await guided_answer(question, empresa_id, None, user, session)
    return guided if guided is not None else await _respond(question, empresa_id, False, session)


@router.post("/publico/{slug}/mensajes", description="Responde con conocimiento público publicado por la empresa.")
async def public_message(
    slug: str,
    body: ChatInput,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    _limit(f"public:{get_client_ip(request) or 'unknown'}")
    question = body.pregunta.strip()
    _reject_personal_data(question)
    empresa_id = await _public_company(slug, session)
    guided = await guided_answer(question, empresa_id, slug, None, session)
    return guided if guided is not None else await _respond(question, empresa_id, True, session)
