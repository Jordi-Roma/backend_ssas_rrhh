# Backup / Restore

El módulo `/api/v1/respaldos` empaqueta un volcado PostgreSQL en formato custom junto a
los CV de `uploads/cv`, lo guarda en un bucket privado y registra un hash SHA-256. Solo una cuenta de
plataforma con permisos `platform:backup:*` puede utilizarlo.

## Variables de Railway

```ini
SUPABASE_URL=https://ID_PROYECTO.supabase.co
SUPABASE_SERVICE_ROLE_KEY=CLAVE_PRIVADA_DEL_SERVIDOR
BACKUP_STORAGE_BUCKET=respaldos
BACKUP_RESTORE_ENABLED=false
BACKUP_RESTORE_CONFIRMATION=RESTAURAR BASE DE DATOS
BACKUP_FILES_DIRECTORY=uploads/cv
RAILPACK_DEPLOY_APT_PACKAGES=postgresql-client
```

La clave privada se obtiene en Supabase, **Project Settings > API Keys**. Debe utilizarse
una clave secreta del servidor (`service_role` o secret key), nunca la `anon`/publishable.
No debe configurarse en el frontend ni guardarse en Git.

El bucket se crea automáticamente como privado durante el primer respaldo. La cuenta
asociada a la clave debe poder administrar Storage.

## Despliegue

El pre-deploy de Railway debe ejecutar:

```bash
PYTHONPATH=src alembic upgrade head
```

Después del despliegue, inicia sesión nuevamente para renovar los permisos del
`SUPER_ADMIN`. Crea un respaldo y espera el estado `COMPLETADO`; descarga el archivo y
conserva una copia fuera del proyecto.

## Restauración

Primero demuestra el procedimiento en una base de prueba. Para habilitarlo en el entorno
elegido configura `BACKUP_RESTORE_ENABLED=true` y vuelve a desplegar. La interfaz exige la
frase configurada en `BACKUP_RESTORE_CONFIRMATION`, valida el SHA-256 y ejecuta
`pg_restore --clean --if-exists --single-transaction` sobre el esquema `public` y luego
recupera los archivos incluidos.

Mientras el estado sea `RESTAURANDO`, no deben realizarse otras operaciones. Una
restauración reemplaza usuarios, permisos, bitácora y datos actuales por los incluidos en
el respaldo. El bucket privado que contiene los propios paquetes no se modifica durante
la restauración.
