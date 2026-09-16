import json
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


class BackupStorageError(RuntimeError):
    pass


class SupabaseBackupStorage:
    def __init__(self, url: str | None, service_key: str | None, bucket: str):
        if not url or not service_key:
            raise BackupStorageError(
                "Configura SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY para usar respaldos"
            )
        self.base_url = url.rstrip("/")
        self.service_key = service_key
        self.bucket = bucket

    def _request(
        self,
        method: str,
        path: str,
        data: bytes | None = None,
        content_type: str = "application/json",
    ) -> bytes:
        request = Request(
            f"{self.base_url}/storage/v1{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.service_key}",
                "apikey": self.service_key,
                "Content-Type": content_type,
            },
        )
        try:
            with urlopen(request, timeout=120) as response:
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BackupStorageError(f"Supabase Storage respondió {exc.code}: {detail}") from exc

    def ensure_private_bucket(self) -> None:
        try:
            self._request("GET", f"/bucket/{quote(self.bucket, safe='')}")
        except BackupStorageError as exc:
            if "404" not in str(exc):
                raise
            payload = json.dumps(
                {"id": self.bucket, "name": self.bucket, "public": False}
            ).encode()
            self._request("POST", "/bucket", payload)

    def upload(self, path: str, content: bytes) -> None:
        self.ensure_private_bucket()
        target = quote(path, safe="/")
        self._request(
            "POST",
            f"/object/{quote(self.bucket, safe='')}/{target}",
            content,
            "application/octet-stream",
        )

    def download(self, path: str) -> bytes:
        target = quote(path, safe="/")
        return self._request("GET", f"/object/{quote(self.bucket, safe='')}/{target}")

    def delete(self, path: str) -> None:
        target = quote(path, safe="/")
        self._request("DELETE", f"/object/{quote(self.bucket, safe='')}/{target}")
