from pathlib import Path

import boto3
from botocore.config import Config

from ssas.config.settings import settings
from ssas.respaldos.infrastructure.services.errors import TenantBackupError


class R2BackupStorage:
    def __init__(self) -> None:
        if not (
            settings.r2_s3_endpoint_url
            and settings.r2_access_key_id
            and settings.r2_secret_access_key
        ):
            raise TenantBackupError("Faltan las variables R2 del backend")
        self.bucket = settings.r2_backup_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.r2_s3_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(),
            region_name=settings.r2_region,
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        )

    def upload(self, path: Path, key: str) -> None:
        self.client.upload_file(str(path), self.bucket, key)
        if self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"] != path.stat().st_size:
            raise TenantBackupError("R2 no confirmó el tamaño del respaldo")

    def download(self, key: str, path: Path) -> None:
        self.client.download_file(self.bucket, key, str(path))

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)
