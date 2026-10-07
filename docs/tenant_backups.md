# Respaldos por empresa (R2)

Esta entrega agrega una exportacion logica por empresa. No reemplaza el respaldo
global existente en `/api/v1/respaldos` ni habilita restauracion por empresa.

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

## Activacion en Railway

1. Desplegar el codigo del backend con `boto3` y aplicar la migracion
   `20261006_0010`. Mantener `TENANT_BACKUP_ENABLED=false` hasta comprobar
   que la migracion y el volumen de CV estan disponibles.
2. En las variables privadas del **servicio backend**, configurar
   `R2_BACKUP_BUCKET=rrhh-backups`, `R2_S3_ENDPOINT_URL` (endpoint S3 Default
   exacto de Cloudflare), `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
   `R2_REGION=auto` y `TENANT_BACKUP_RETENTION_DAYS=30`. Nunca registrar ni
   enviar las dos credenciales por chat o incluirlas en Git.
3. Habilitar `TENANT_BACKUP_ENABLED=true` en el backend y desplegarlo. Probar
   primero una solicitud manual de una empresa de prueba, revisar estado,
   descargarla y comprobar el manifiesto y los CV de esa misma empresa.
4. Crear **otro servicio** Railway desde el mismo repositorio, sin volumen.
   Compartirle solo la conexion PostgreSQL y las variables de configuracion
   obligatorias para iniciar la aplicacion. Sobrescribir el comando de inicio
   con `PYTHONPATH=src python -m ssas.respaldos.infrastructure.services.tenant_schedule`,
   activar el horario Cron `0 6 * * *` (UTC) y poner
   `TENANT_BACKUP_ENABLED=true` en ese servicio. No compartir las claves R2 con
   el Cron: solo encola trabajos. Comprobar que la ejecucion termina y que la
   API procesa despues todos los trabajos.
5. Verificar dos empresas con datos y CV distintos, permisos cruzados,
   fallo de R2/archivo, retencion de 30 dias y preservacion de la ultima copia
   valida. Medir el uso y configurar alertas de presupuesto en Cloudflare.

La restauracion aislada queda **deshabilitada**: requiere previsualizacion,
respaldo previo y una prueba de ida y vuelta que demuestre que otra empresa
permanece intacta. No usar el endpoint de restauracion global para una empresa.

No se ejecutaron pruebas ni despliegue como parte de esta entrega.
