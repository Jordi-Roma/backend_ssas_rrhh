# Respaldos por empresa (R2)

Esta entrega agrega una exportacion logica por empresa. No reemplaza el respaldo
global existente en `/api/v1/respaldos`.

## Alcance

- La API nueva usa `/api/v1/respaldos-empresa`: listado, ultimo resultado,
  solicitud manual (`202`), detalle, descarga verificada por SHA-256 y
  configuracion automatica para plataforma.
- El usuario de empresa solo opera sobre la empresa de su sesion. El administrador
  global puede seleccionar empresa. Los permisos `backup:*` se asignan al rol
  `ADMIN_EMPRESA` con la migracion; `platform:backup:configurar` al `SUPER_ADMIN`.
- El paquete incluye filas de empresa de los modulos actuales, bitacora cifrada
  y CV locales referenciados, con manifiesto, conteos y hashes. No incluye
  planes, suscripciones, secretos de plataforma, catalogos globales ni los
  archivos a los que solo se apunta con una URL externa (`archivo_url`).
- La exportacion falla si aparece una tabla nueva sin clasificar, una referencia
  a otra empresa o falta un CV. Un paquete incompleto no queda como exitoso.
- El worker de la API toma trabajos de PostgreSQL y lee el volumen de CV.
  El servicio Cron separado solo encola; no necesita montar el volumen.
- La hora diaria se configura por empresa desde la plataforma, en zona
  `America/La_Paz`. El valor inicial es `02:00`; el worker de la API revisa
  horarios pendientes cada 30 segundos y encola una sola copia automatica por
  dia local. Una copia fallida conserva sus reintentos normales, pero no se
  crea otra solicitud automatica para el mismo dia.

## Activacion en Railway

1. Desplegar el codigo del backend con `boto3` y aplicar las migraciones
   hasta `20261030_0012`. Mantener `TENANT_BACKUP_ENABLED=false` hasta comprobar
   que la migracion y el volumen de CV estan disponibles.
2. En las variables privadas del **servicio backend**, configurar
   `R2_BACKUP_BUCKET=rrhh-backups`, `R2_S3_ENDPOINT_URL` (endpoint S3 Default
   exacto de Cloudflare), `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
   `R2_REGION=auto` y `TENANT_BACKUP_RETENTION_DAYS=30`. Nunca registrar ni
   enviar las dos credenciales por chat o incluirlas en Git.
3. Habilitar `TENANT_BACKUP_ENABLED=true` en el backend y desplegarlo. Probar
   primero una solicitud manual de una empresa de prueba, revisar estado,
   descargarla y comprobar el manifiesto y los CV de esa misma empresa.
4. Despues de comprobar el respaldo manual tambien en movil, crear **otro
   servicio** Railway desde el mismo repositorio y rama del backend, sin volumen
   ni dominio publico. En este servicio nuevo, configurar desde Settings el
   Custom Start Command como
   `PYTHONPATH=src python -m ssas.respaldos.infrastructure.services.tenant_schedule`.
   Dejar Config File Path sin configurar, quitar cualquier healthcheck y no
   configurar un Pre-deploy Command. El `railway.json` del servicio API
   existente inicia Uvicorn y comprueba `/health`; no debe aplicarse al Cron.
   Antes de activar el horario, verificar en los detalles del despliegue que
   el comando efectivo es el del programador y que no inicia la API.
5. Configurar solo `APP_ENV=production`, `APP_SECRET_KEY`,
   `APP_AUDIT_ENCRYPTION_KEY`, `DATABASE_URL` (la misma base de datos del
   backend) y `TENANT_BACKUP_ENABLED=true` en el servicio Cron. Usar las
   mismas claves de aplicacion y auditoria del backend mediante variables
   privadas o referencias de Railway. No copiar claves R2 ni montar el
   volumen de CV: el Cron solo encola trabajos; la API los procesa.
6. El Cron existente `0 6 * * *` puede permanecer como comprobacion diaria,
   pero **ya no define la hora de las copias**. No hace falta modificar su
   horario al cambiar la hora de una empresa. El backend debe permanecer
   activo con `TENANT_BACKUP_ENABLED=true` para revisar la programacion.
   Tras desplegar la migracion `20261030_0012`, elegir la hora desde
   Respaldos por empresa > Programacion automatica y comprobar en el historial
   que la copia se crea una vez en el dia local previsto.
7. Verificar dos empresas con datos y CV distintos, permisos cruzados,
   fallo de R2/archivo, retencion de 30 dias y preservacion de la ultima copia
   valida. Medir el uso y configurar alertas de presupuesto en Cloudflare.

Railway ya no permite activar Config as Code (`railway.json`) en servicios
nuevos; por eso el Cron usa Settings del panel. Si Railway muestra que el
servicio Cron esta usando el archivo de configuracion de la API, detener la
activacion y corregir el comando y el healthcheck antes de programarlo.

## Restauracion por empresa

- Solo el administrador global con `platform:backup:configurar` puede previsualizar
  y solicitar la restauracion. Una cuenta de empresa no puede hacerlo.
- `GET /api/v1/respaldos-empresa/{id}/restauracion/preview` descarga el paquete
  desde R2 y verifica el SHA-256 externo, manifiesto, version del esquema,
  pertenencia de filas, conteos y archivos. La interfaz muestra el alcance y
  exige escribir `RESTAURAR <empresa_id>` antes de confirmar.
- `POST /api/v1/respaldos-empresa/{id}/restaurar` solo funciona con
  `TENANT_RESTORE_ENABLED=true` en el backend. Permanece `false` por defecto.
  Primero genera y guarda en R2 una copia del estado actual de la misma empresa.
  Luego sustituye sus filas en una transaccion y recupera sus CV y documentos.
- La operacion conserva la empresa, plan, suscripcion, configuracion de backup y
  datos de otras empresas. Conserva la bitacora inmutable como historial; sus
  eventos posteriores a la copia no se borran. Si un usuario creado despues
  de la copia figura en esa bitacora, la restauracion se rechaza sin cambios.
  Revoca las sesiones de usuarios de la empresa al reemplazarlos. Los archivos antiguos no referenciados pueden quedar en el
  volumen y requieren limpieza administrada posterior.
- Antes de habilitarlo en produccion, ejecutar una prueba de ida y vuelta en una
  base descartable con dos empresas y archivos distintos, y comprobar las
  descargas, permisos y el punto de retorno. No usar el endpoint de
  restauracion global para una sola empresa.

La migracion y la programacion nueva deben probarse antes de desplegarse en
produccion. Cambiar la hora despues de que ya se creo la copia automatica de
ese dia no genera una segunda copia: el cambio aplica desde el dia siguiente.
