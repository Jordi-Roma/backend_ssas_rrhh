# 01 — ESTADO DEL PROYECTO

> **Este es el primer documento que debe leer cualquier agente.**
> Sincronizado el **2026-09-08** contra el commit `782ac60`.
> Verificar con `python scripts/verificar_documentacion.py` antes de confiar en él.
 
---

## 1. Información general

| | |
|---|---|
| Proyecto | **backend_ssas_rrhh** — Sistema de Gestión de RRHH, SaaS multi-tenant |
| Materia | Sistemas de Información 2 (INF 412-SA) · UAGRM · Grupo N.° 12 |
| Lenguaje | Python 3.12 |
| Framework | FastAPI |
| Base de datos | PostgreSQL sobre **Supabase** · 22 tablas |
| ORM | SQLAlchemy 2.0 async (`psycopg`) |
| Migraciones | Alembic |
| Paquete | `src/ssas/` |
| Prefijo de API | `/api/v1` |
| Arquitectura | Vertical Slicing + Hexagonal pragmática |
| Despliegue | Railway (`railway.json`) |

```bash
pip install -r requirements.txt
alembic upgrade head
python -m uvicorn ssas.main:app --app-dir src --reload   #  /docs
pytest && ruff check src tests
```

---

## 2. Estado por área

| Área | Estado | PA | Endpoints | Tests | Observaciones |
|---|---|---|---|---|---|
| Arquitectura | IMPLEMENTADO | — | — | 2 | Vertical slicing + hexagonal; `core/` transversal |
| Base de datos | IMPLEMENTADO | — | — | 3 | **22 tablas** · Supabase compartida entre local y Railway |
| Migraciones | IMPLEMENTADO | — | — | 1 | 13 migraciones unificadas en línea cronológica única |
| Auth | IMPLEMENTADO | PA-01 | 10 | 18 | JWT access+refresh con rotación, auto-registro empresa, verificación de correo, bloqueo por intentos |
| Usuarios | IMPLEMENTADO | PA-01 | 10 | 6 | CRUD + borrado lógico + restaurar + desbloquear + reset clave temporal |
| Roles y permisos | IMPLEMENTADO | PA-01 | 7 | 3 | **43 permisos** en catálogo agrupados por módulo. Roles base configurados |
| Empresas / Tenants | IMPLEMENTADO | PA-01 | 11 | 3 | Gestión de empresas, branding, portal público y configuración de módulos |
| Multitenencia | IMPLEMENTADO | PA-01 | — | 5 | Tenant implícito en el token; guards de doble alcance |
| Bitácora | IMPLEMENTADO | PA-01 | 2 | 1 | Auditoría de empresa y de plataforma en una sola tabla |
| Departamentos | IMPLEMENTADO | PA-04 | 4 | 0 | Estructura jerárquica con código y padre |
| Cargos | IMPLEMENTADO | PA-04 | 4 | 0 | Estructura con nivel y bandas salariales (mín/máx) |
| Vacantes | IMPLEMENTADO | PA-02 | 9 | 7 | CU-08 · T-08. Ciclo completo: crear, editar, pausar, reanudar, cerrar, eliminar + matriz de habilidades requeridas |
| Postulantes | IMPLEMENTADO | PA-02 | 3 | 0 | CU-11. Banco de talentos, alta manual y descarga de CV |
| Habilidades | IMPLEMENTADO | PA-02 | 4 | 0 | Catálogo de habilidades con CRUD completo (crear, editar, listar, eliminar) |
| Portal público | IMPLEMENTADO | PA-02 | 3 | 0 | CU-09 · T-09. Perfil público de empresa, vacantes vigentes y detalle |
| Postulaciones | IMPLEMENTADO | PA-02 | 4 | 0 | CU-10 y CU-11. Postular con CV, consultar por código y gestión interna |
| Tablero de candidatos | IMPLEMENTADO | PA-03 | 7 | 0 | CU-12 · T-12. Tablero kanban por etapas, notas internas, puntaje manual, mover y rechazar con motivo |
| Notificaciones | PENDIENTE | PA-02 | 0 | 0 | T-13. Encolamiento asíncrono para próximos sprints |
| Administración de Personal | PENDIENTE | PA-04 | 0 | 0 | Estructura organizativa lista (departamentos, cargos) |
| Capacitación | PENDIENTE | PA-05 | 0 | 0 | Próximo sprint |
| Inteligencia Artificial | PENDIENTE | PA-06 | 0 | 0 | Próximo sprint |
| Reportes e Indicadores | PENDIENTE | PA-07 | 0 | 0 | Próximo sprint |
| Tests | IMPLEMENTADO | — | — | 71 | 15 archivos, 71 pruebas (68 passed, 3 skipped, 0 failed) |
| Documentación | IMPLEMENTADO | — | — | — | Sincronizado: 86 endpoints y 44 tareas verificadas con 0 fallos |

**Resumen:** **86 endpoints** en 14 módulos. El alcance funcional del Sprint 1 y la integración completa están operativos.

---

## 2 bis. Alcance del Sprint 1 y su estado real

Según el Capítulo 4 del perfil, el Sprint 1 entrega *«el primer flujo completo de valor:
publicar una vacante, exponerla en un portal público, permitir la postulación con carga de
hoja de vida desde web y móvil, y visualizar a los postulantes en el tablero»*.

| CU | Caso de uso | Tarea | HU | Endpoints | Código | Tests | Qué falta |
|---|---|---|---|---|---|---|---|
| CU-07 | Gestionar departamentos y cargos | T-07 | HU-02 | 8 | **sí** | **0** | `TEST-002` |
| CU-08 | Gestionar vacantes | T-08 | HU-03 | 6 | **sí** | **0** | `TEST-004` |
| CU-09 | Explorar el portal público | T-09 | HU-04 | 2 | **sí** | **0** | `TEST-004` |
| CU-10 | Postular con hoja de vida | T-10 | HU-05 | 1 | sí | **0** | Almacenamiento persistente de CV (el disco de Railway es efímero) |
| CU-11 | Consultar estado de la postulación | T-11 | HU-09 | 1 | sí | **0** | — |
| CU-11 | Banco de talentos (postulantes) | T-10 | HU-06 | 2 | **sí** | **0** | Tests |
| CU-12 | Gestionar tablero de candidatos | T-12 | HU-06 | 5 | **sí** | **0** | `TEST-005` (cierra `CP-S1-21`) · `ARCH-001` · `TAB-004` |
| — | Catálogo de habilidades | T-08 | — | 3 | **sí** | **0** | Contrato de `DELETE` en `02` |
| — | Notificaciones y cola asíncrona | T-13 | — | 0 | no | — | `NOT-001` (BLOQUEADO, fuera del Sprint 1) |

**Balance:** el flujo de valor del Sprint 1 **está entregado**: se puede crear una vacante,
publicarla, verla en el portal público, postularse con CV desde web o móvil, consultar el
estado por código y gestionar a los postulantes en el tablero.

> Lo que falta no es funcionalidad, es lo que la vuelve entregable: **cero pruebas** sobre
> los 19 endpoints nuevos, `alembic upgrade head` roto, el rol RECLUTADOR sin permisos y el
> trabajo sin commitear. Ver §2 ter.

## 2 ter. Verificación ejecutada — 2026-09-07

Resultado real de los comandos del protocolo, **sobre el árbol de trabajo** (no sobre
`782ac60`: el árbol está muy por delante del último commit).

**El Sprint 1 quedó funcionalmente terminado mientras se redactaba esta sección.** La API
pasó de 46 a **65 operaciones**: los 18 endpoints que figuraban como pendientes existen,
más un `DELETE /habilidades/{id}` que no está en el contrato de `02`. El catálogo de
permisos pasó de 28 a **43**.

| Comando | Resultado | Tarea |
|---|---|---|
| `APP_SECRET_KEY=x PYTHONPATH=src python -c "from ssas.main import app"` | **OK** — 65 operaciones (55 protegidas, 10 públicas) | — |
| `PYTHONPATH=src pytest -q` | **OK** — 39 passed, 3 skipped — **los mismos 39 de antes del sprint** | `TEST-004`…`TEST-006` |
| `pytest -q` | **FALLA** — 8 errores: `ModuleNotFoundError: No module named 'ssas'` | `TOOL-001` |
| `ruff check src tests` | **FALLA** — 15 errores, **8 en archivos del Sprint 1** | `TOOL-002` |
| `alembic upgrade head` | **FALLA** — `Multiple head revisions are present` | `MIG-002` |
| `alembic heads` | **DOS cabezas** — `20260825_0002` y `20260907_0007` | `MIG-002` |
| `git log` | El trabajo del sprint **no está commiteado**: 17 archivos sin versionar | `DOC-003` |

Cuatro hallazgos más, verificados ejecutando y leyendo el código:

- **`alembic upgrade head` roto bloquea los permisos nuevos.** Las migraciones `0005`,
  `0006` y `0007` no se pueden aplicar, así que los 15 permisos nuevos existen en el código
  y no en la base: los 19 endpoints nuevos están protegidos por permisos que nadie tiene.
- **El rol RECLUTADOR sigue con 0 permisos.** Las migraciones crearon los granulares
  (`vacantes:ver|crear|editar|publicar|eliminar`) y `provision_empresa.py` no se tocó:
  sigue pidiendo `vacantes:gestionar` y `candidatos:gestionar`, que no existen entre los 43.
  El filtro descarta los códigos desconocidos en silencio → `SEC-001` (CRÍTICA).
- **19 endpoints nuevos con cero tests.** `CP-S1-21` sigue sin verificarse, y ningún
  endpoint nuevo tiene prueba de aislamiento entre empresas → Ola 1.
- **`tablero_router.py` hace 8 llamadas directas a `session.execute`/`session.scalar` y no
  usa ningún repositorio**, contra la regla 7 de este documento → `ARCH-001`.
- **`provision_empresa.py` no siembra etapas de reclutamiento.** Una empresa nueva nace sin
  ninguna, así que su tablero arranca vacío → `TAB-004`.

El plan de ejecución está en
[`04_EJECUCION_MULTIAGENTE_SPRINT1.md`](04_EJECUCION_MULTIAGENTE_SPRINT1.md) y los textos
para lanzar cada agente en
[`PROMPT_INICIO_MULTIAGENTE.md`](PROMPT_INICIO_MULTIAGENTE.md).

## 2 quater. Corrección integral de alcance, Habilidades y Portal — 2026-09-08

Corrección sistémica tras la auditoría de `05_AUDITORIA_SISTEMICA_Y_CORRECCION_INTEGRAL.md`
(`CORR-001`): un único selector de empresa activa en el encabezado (el sidebar dejó de
tener selector propio y el tenant resuelve su empresa dentro de `CompanyScopeContext`),
`/api/v1/habilidades` opera siempre con `empresa_id` y la UI distingue error de lista
vacía, Organización pasó a pestañas con modales y confirmaciones, los cargos validan
`salario_min <= salario_max` en la API, y el Portal público separa el fallo de red (con
reintento) de la ausencia de vacantes. CORS ampliado con regex para subdominios de
Railway. Resultado: `pytest` 71 passed / 3 skipped, `ruff` y build del frontend en cero
errores, documentación sincronizada (86/86). Además, `CORR-002` corrige el perfil público
de empresa (`GET /publico/{empresa_slug}`), que devolvía 500 por usar `empresa.nombre`
(inexistente) y pasar `id` como UUID: en producción ese 500 sin cabeceras CORS se mostraba
al usuario como «No se pudo contactar con el servidor».

## 3. Arquitectura real

```text
src/ssas/
├── main.py                  FastAPI · CORS · middleware de tenant · router /api/v1
├── config/settings.py       24 variables, todas en uso
├── core/
│   ├── api/router.py        agrega los routers de cada módulo
│   ├── security/            JWT · hashing · dependencias de autorización
│   └── tenancy/             ContextVar del tenant + middleware
├── infrastructure/database/ Base declarativa única · sesión async
│
├── auth/                 PA-01 · 9 endpoints
├── usuarios/             PA-01 · 10 endpoints
├── roles/                PA-01 · 6 endpoints
├── platform/             PA-01 · 8 endpoints
├── bitacora/             PA-01 · 2 endpoints
├── departamentos/        PA-04 · 4 endpoints
├── cargos/               PA-04 · 4 endpoints
├── vacantes/             PA-02 · SIN endpoints
├── postulantes/          PA-02 · SIN endpoints
├── habilidades/          PA-02 · SIN endpoints
├── postulaciones/        PA-02 · 2 endpoints
```

Cada módulo repite la misma disposición interna:

```text
<modulo>/
├── domain/           entidades y excepciones · sin FastAPI, SQLAlchemy ni Pydantic
├── application/      casos de uso
├── ports/            contratos hacia dependencias externas
└── infrastructure/   http/ (router, schemas) · persistence/ (models, repositories)
```

---

## 4. Reglas que los agentes deben respetar

### Multitenencia — el invariante central

```text
usuario.empresa_id  IS NULL  ->  administrador de la plataforma
rol.empresa_id      IS NULL  ->  rol global (SUPER_ADMIN)
bitacora.empresa_id IS NULL  ->  evento de la plataforma
```

1. El tenant es **implícito en el token**, nunca viaja en la URL.
2. Login único `POST /api/v1/auth/login`: **con** `empresa_slug` para usuarios de
   empresa, **sin** él para administradores de plataforma.
3. Un rol de empresa **nunca** recibe permisos `platform:*`. Bloqueado en
   `AssignPermissions` y en `ProvisionEmpresa`.
4. `require_platform_permission` exige además `es_plataforma`: defensa en profundidad.
5. `SUPER_ADMIN` no tiene excepción codificada; sus permisos están en la base.
6. PostgreSQL trata dos `NULL` como distintos: los índices únicos de email, username,
   código y nombre de rol son **parciales** (`WHERE empresa_id IS NULL`).
7. Todo repositorio de un recurso de empresa filtra por `empresa_id`. **En el
   repositorio, no en el router.**

### Guards de autorización disponibles

| Guard | Uso | Endpoints |
|---|---|---|
| `require_scoped_permission(emp, plat)` | El actor de empresa usa el 1.º, el de plataforma el 2.º | 26 |
| `require_platform_permission(perm)` | Solo plataforma | 6 |
| `require_empresa_permission(emp, plat)` | Recurso de empresa accesible por plataforma | 2 |
| `get_authenticated_user` | Solo autenticación, sin permiso | 4 |
| — | Público, declarado en `PUBLIC_PATHS` del middleware | 8 |

### Arquitectura

- La lógica de negocio no vive en los routers.
- Entidad de dominio ≠ modelo ORM. Adaptadores: `SqlAlchemy<Cosa>Repository`.
- Nombres de negocio en español; capas técnicas en inglés.
- No agregar capas nuevas ni renombrar las existentes sin autorización.
- Un módulo se crea cuando entra su primera historia de usuario, no antes.

### Operación — el riesgo más grande del proyecto

- **Local y Railway usan la MISMA base de Supabase.** Cualquier `alembic upgrade`,
  seed o prueba local impacta producción.
- Las pruebas e2e ejecutan `TRUNCATE` y llevan un freno que las saltea si
  `DATABASE_URL` no apunta a un host local. **No quitar ese freno.**
- `scripts/reiniciar_base.py` borra tabla por tabla dentro de `public` y nunca hace
  `DROP SCHEMA`: eso destruiría los esquemas propios de Supabase.
- Para migraciones, conexión directa (5432), no el pooler de transacciones (6543).

---

## 5. Mapa de módulos

| ID | Módulo | Responsabilidad | PA / CU | Estado | Endpoints | Ruta |
|---|---|---|---|---|---|---|
| MOD-001 | auth | Autenticación y sesión | PA-01 / CU-03 | IMPLEMENTADO | 9 | `src/ssas/auth/` |
| MOD-002 | usuarios | Gestión de usuarios | PA-01 / CU-04 | IMPLEMENTADO | 10 | `src/ssas/usuarios/` |
| MOD-003 | roles | Roles y permisos | PA-01 / CU-05 | IMPLEMENTADO | 6 | `src/ssas/roles/` |
| MOD-004 | platform | Empresas, planes y suscripciones | PA-01 / CU-01, CU-02 | IMPLEMENTADO | 8 | `src/ssas/platform/` |
| MOD-005 | bitacora | Auditoría | PA-01 / CU-06 | IMPLEMENTADO | 2 | `src/ssas/bitacora/` |
| MOD-006 | departamentos | Estructura organizativa | PA-04 / CU-19 | IMPLEMENTADO | 4 | `src/ssas/departamentos/` |
| MOD-007 | cargos | Cargos | PA-04 / CU-19 | IMPLEMENTADO | 4 | `src/ssas/cargos/` |
| MOD-008 | vacantes | Vacantes | PA-02 / CU-07 | PARCIAL | 0 | `src/ssas/vacantes/` |
| MOD-009 | postulantes | Banco de talentos | PA-02 / CU-11 | PARCIAL | 0 | `src/ssas/postulantes/` |
| MOD-010 | habilidades | Catálogo de habilidades | PA-02 / DESCONOCIDO | PARCIAL | 0 | `src/ssas/habilidades/` |
| MOD-011 | postulaciones | Postulaciones | PA-02 / CU-09, CU-12 | PARCIAL | 2 | `src/ssas/postulaciones/` |

---

## 6. Dependencias entre módulos

```text
core (security · tenancy)
 └── auth ── usuarios ── roles ── permisos
                │
           platform (empresas)
                │
        departamentos ── cargos
                │
     vacantes ── habilidades
         │
   postulaciones ── postulantes

bitacora  <- transversal: todos los módulos generan eventos, ninguno depende de él
```

---

## 7. Inconsistencias detectadas

| # | Inconsistencia | Impacto |
|---|---|---|
| 1 | Migraciones con numeración duplicada: dos `0002` (`20260825_0002_borrado_logico` y `20260830_0002_crear_departamentos_y_cargos`) | Confunde el orden real; Alembic se guía por `down_revision`, no por el nombre |
| 2 | Dos migraciones conservan el hash autogenerado (`0d142a1a7539`, `7694bb109d4b`) | Rompe la convención de nombres del resto |
| 3 | `docs/database/schema_sprint0_sprint1.sql` documenta **23 tablas**; el ORM define 19. Cuatro (`parametro_legal`, `parametro_valor`, `plan_suscripcion`, `suscripcion`) no existen ni en las migraciones ni en el código | Segunda fuente de verdad ya desincronizada. Archivado en `docs/_archivo/` |
| 3b | La funcionalidad de **planes y suscripciones** se retiró: `/platform/planes` y `/platform/suscripciones` ya no existen entre los 46 endpoints | Si el alcance del SaaS los necesita, es una `DECISIÓN PENDIENTE`; si no, hay que quitarlos del perfil del proyecto |
| 4 | La colección Postman se llama `SSAH_RRHH` y el proyecto es `SSAS` | Nombre heredado del rename |
| 5 | `vacantes`, `postulantes` y `habilidades` tienen modelos y migración aplicada pero ninguna capa de aplicación | Tablas en producción sin forma de usarlas |
| 6 | 6 de 9 módulos con endpoints no tienen ningún test | El aislamiento entre empresas no está verificado en la mayoría |
| 7 | **El perfil usa dos numeraciones de CU distintas.** En §3.10.2: CU-07 Gestionar vacante, CU-08 Consultar portal, CU-09 Postularse, CU-10 Cargar hoja de vida, CU-11 Banco de talentos. En el Capítulo 4 (Sprint 1): CU-07 Departamentos y cargos, CU-08 Vacantes, CU-09 Portal, CU-10 Postular, CU-11 Estado, CU-12 Tablero | **El defecto más grave.** Impide verificar qué se entregó; es el primer error que detecta la docente. Esta documentación usa la numeración del **Capítulo 4**, por ser la del sprint en ejecución → `PERF-001` |
| 8 | **CP-S1-21 figura como FALLA** en el reporte de pruebas del perfil (05/09/2026): un usuario de la empresa B accede al tablero de la empresa A sin recibir 404 | Fallo de aislamiento multi-tenant documentado y sin resolver → `BUG-001` (CRÍTICA) |
| 9 | El diseño de datos del Sprint 1 en el perfil todavía crea `plan_suscripcion` y `suscripcion`, y el código las eliminó | El script del perfil no se puede ejecutar contra el esquema actual → `PERF-001` |
| 10 | El portal público del perfil es `/publico/{empresa_slug}/vacantes`; el código solo expone `/publico/postulaciones` | La ruta documentada no existe → `POR-001` |
| 11 | **El grafo de Alembic tiene dos cabezas.** `alembic upgrade head` falla con `Multiple head revisions are present`; `alembic heads` devuelve `20260825_0002` y `20260907_0007`, ambas descendientes de `20260825_0001`. Las migraciones de permisos del sprint extendieron una de las dos ramas sin unirlas | **Bloqueador duro.** Un clon nuevo no puede construir el esquema, y ninguna migración nueva se puede añadir sin elegir cabeza. Es más grave que la numeración de la inconsistencia 1 → `MIG-002` (CRÍTICA) |
| 12 | **El rol RECLUTADOR se aprovisiona con cero permisos.** `ROLE_DEFINITIONS` le pide `vacantes:gestionar` y `candidatos:gestionar`; ninguno existe en el catálogo de 28, y `if code_ in permission_by_code` los descarta en silencio | El actor de CU-08, CU-09 y CU-12 no puede operar, y no hay error visible → `SEC-001` (CRÍTICA) |
| 13 | El backlog planea permisos granulares (`vacantes:ver|crear|…`) y `provision_empresa.py` espera uno grueso (`vacantes:gestionar`) | Si `VAC-004` y `SEC-001` no usan el mismo vocabulario, el rol vuelve a quedar vacío. `DECISIÓN PENDIENTE` → §6 del documento 04 |
| 14 | `pytest` a secas falla con 8 errores de colección; sólo funciona con `PYTHONPATH=src`. `pip install -e .` no lo arregla | El paso 8 de este protocolo es inejecutable como está escrito → `TOOL-001` |
| 15 | `ruff check src tests` devuelve 15 errores preexistentes | Un agente no puede distinguir sus errores de los heredados → `TOOL-002` |
| 16 | Los documentos `01`, `02`, `03`, `04` y `scripts/` **no están versionados** en git | Un agente que clona el repositorio no ve la documentación que este protocolo le manda leer → `DOC-003` |
| 17 | 157 archivos de `src/` aparecen modificados sólo por el final de línea (CRLF frente a LF); falta `.gitattributes` | Los diffs de los agentes son ilegibles y cada commit arrastra ruido → `DOC-003` |
| 18 | **19 endpoints del Sprint 1 con cero tests.** `pytest` devuelve los mismos 39 de antes del sprint | `IMPLEMENTADO` sin `VALIDADO`. `CP-S1-21` sigue sin verificar y ningún endpoint nuevo prueba el aislamiento entre empresas → Ola 1 del documento 04 |
| 19 | **`tablero_router.py` hace 8 llamadas directas a `session.execute`/`session.scalar`** y no usa ningún repositorio | Contra la regla 7 de este documento: el filtro por `empresa_id` —lo único que separa los datos de dos clientes— vive en el router → `ARCH-001` |
| 20 | **`provision_empresa.py` no siembra etapas de reclutamiento** (0 menciones de `etapa`) | Una empresa nueva nace sin etapas: su tablero arranca vacío y `PATCH /postulaciones/{id}/etapa` responde 404 para cualquier etapa → `TAB-004` |
| 21 | `DELETE /api/v1/habilidades/{id}` existe en el código y no en el contrato de `02` | Endpoint sin contrato documentado → `DOC-002` |

---

## 8. Protocolo para agentes

1. `git fetch` y confirmar que trabajás sobre el HEAD actual.
2. Leer este documento.
3. Leer la TASK asignada completa en `03_BACKLOG_IMPLEMENTACION.md`.
4. Leer el endpoint relacionado en `02_API_ENDPOINTS.md`.
5. Revisar solo el módulo afectado y sus dependencias.
6. Verificar a qué base apunta `DATABASE_URL` antes de cualquier comando que escriba.
7. Implementar solo el alcance de la tarea.
8. `pytest` · `ruff check` · `python scripts/verificar_documentacion.py`.
9. Actualizar los tres documentos.
10. No modificar tareas ajenas ni reformatear archivos completos.

---

## 9. Documentación relacionada

| Documento | Contenido |
|---|---|
| `02_API_ENDPOINTS.md` | Contrato de los endpoints. **Desactualizado: documenta 46 y hay 65** → `DOC-002` |
| `03_BACKLOG_IMPLEMENTACION.md` | Las 41 tareas, dependencias y criterios de aceptación |
| `04_EJECUCION_MULTIAGENTE_SPRINT1.md` | Olas, reparto de archivos entre agentes, contrato del agente y decisiones pendientes |
| `PROMPT_INICIO_MULTIAGENTE.md` | Textos listos para pegarle a cada agente, por ola |
| `tareas_sprint1.json` | Las tareas en formato consumible por un orquestador |
| `arquitectura/ARQUITECTURA_BACKEND_FASTAPI.md` | Documento de diseño (entregable del Capítulo 2) |
| `arquitectura/CONTRATO_OPENAPI_Y_VERSIONADO.md` | Convenciones de OpenAPI y versionado |
| `guias/GUIA_DESARROLLO.md` | Puesta en marcha y flujo de trabajo |
| `guias/AUTH_Y_USUARIOS.md` · `guias/PLATFORM_ADMINISTRACION.md` | Guías funcionales |
| `sprints/SPRINT_0_ADAPTACION_ORM.md` | Registro histórico |
