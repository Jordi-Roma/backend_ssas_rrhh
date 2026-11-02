# SSAS RRHH — Backend

API REST multiempresa para la gestión de recursos humanos. Está construida con FastAPI y sirve a la aplicación web y a la app móvil.

## Funciones implementadas

- Autenticación, usuarios, roles, permisos, empresas y bitácora.
- Organización, vacantes, postulantes, selección, entrevistas e importación de datos.
- Planes, suscripciones y pagos mediante Stripe.
- Personal: legajo, contratos, documentos, asistencia, ausencias y solicitudes.
- Nómina: periodos, cálculo, aprobaciones, parámetros legales y boletas. **Antes de usarla para pagos reales, el responsable debe validar las reglas y los datos**; ver [Sprint 3 backend](docs/sprint3_backend.md).
- Reportes, ayuda y chatbot, con funciones de IA sujetas a su configuración.
- Respaldos globales y respaldos aislados por empresa; ver [guía de respaldos](docs/tenant_backups.md). La restauración individual por empresa no está implementada.

El aislamiento entre empresas se aplica a las operaciones y los datos asociados a `empresa_id`. El acceso depende de autenticación, permisos y, donde corresponde, el plan contratado.

## Tecnologías

Python 3.12, FastAPI, SQLAlchemy asíncrono, PostgreSQL, Psycopg 3, Alembic, JWT, Argon2id, pytest y Ruff. Las integraciones opcionales se configuran mediante variables privadas del backend.

## Inicio local

```powershell
git clone https://github.com/Jordi-Roma/backend_ssas_rrhh.git
cd backend_ssas_rrhh
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
# Configurar DATABASE_URL y APP_SECRET_KEY en .env; usar una base de desarrollo.
python -m alembic upgrade head
python -m uvicorn ssas.main:app --app-dir src --reload
```

El archivo `.env` es local y no se debe subir a Git. Las variables disponibles y sus valores de ejemplo están en [.env.example](.env.example).

## Endpoints de la API

La API usa el prefijo `/api/v1`. Con el servidor en marcha, [Swagger UI](http://127.0.0.1:8000/docs) permite consultar cada endpoint, sus parámetros, respuestas y requisitos de autorización. El contrato completo está en [OpenAPI JSON](http://127.0.0.1:8000/openapi.json); [ReDoc](http://127.0.0.1:8000/redoc) ofrece otra vista. En Railway, sustituir `http://127.0.0.1:8000` por el dominio del backend.

| Área | Rutas principales |
|---|---|
| Acceso y administración | `/auth`, `/usuarios`, `/roles`, `/permisos`, `/empresas`, `/modulos`, `/bitacora` |
| Organización y reclutamiento | `/departamentos`, `/cargos`, `/habilidades`, `/vacantes`, `/postulantes`, `/publico` |
| Personal y nómina | `/personal`, `/nomina`, `/parametros-legales` |
| Suscripciones | `/planes`, `/suscripcion`, `/webhooks` |
| Reportes e IA | `/dashboard`, `/reportes`, `/ayuda`, `/chatbot` |
| Datos y respaldos | `/importaciones`, `/respaldos`, `/respaldos-empresa` |

Ejemplos: `GET /api/v1/auth/me` consulta el usuario autenticado; `GET /api/v1/respaldos-empresa` lista respaldos según los permisos; `POST /api/v1/respaldos-empresa` solicita uno. Las rutas públicas, los métodos admitidos y los cuerpos de las solicitudes se consultan en Swagger/OpenAPI. No todas las rutas son accesibles con el mismo rol.

## Comprobaciones de desarrollo

```powershell
python -m pytest
python -m ruff check src tests migrations scripts
python -m alembic current
```

Para pruebas de integración, configurar una base separada antes de ejecutar pruebas que escriban datos.

## Documentación adicional

- [Índice de documentación](docs/README.md). Algunos documentos históricos describen el estado de su fecha y no sustituyen el OpenAPI actual.
- [Implementación y límites del Sprint 3](docs/sprint3_backend.md).
- [Respaldos por empresa](docs/tenant_backups.md).
- [Funciones por plan](docs/funciones_por_plan.md).
- [Contrato OpenAPI y versionado](docs/arquitectura/CONTRATO_OPENAPI_Y_VERSIONADO.md).

## Licencia

MIT. Ver [LICENSE](LICENSE).
