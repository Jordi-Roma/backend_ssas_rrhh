import hashlib
import json
import os
from base64 import b64encode
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class AuditEncryptionError(RuntimeError):
    pass


def audit_key_bytes(value: str | None) -> bytes:
    if not value:
        raise AuditEncryptionError(
            "Falta APP_AUDIT_ENCRYPTION_KEY; configura una llave hexadecimal de 64 caracteres"
        )
    try:
        key = bytes.fromhex(value)
    except ValueError as exc:
        raise AuditEncryptionError("APP_AUDIT_ENCRYPTION_KEY debe ser hexadecimal") from exc
    if len(key) != 32:
        raise AuditEncryptionError(
            "APP_AUDIT_ENCRYPTION_KEY debe representar exactamente 32 bytes"
        )
    return key


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


class AuditCipher:
    version = 1

    def __init__(self, key: str | None):
        self._aes = AESGCM(audit_key_bytes(key))

    def encrypt(self, payload: dict[str, Any], metadata: dict[str, Any]) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        ciphertext = self._aes.encrypt(nonce, canonical_json(payload), canonical_json(metadata))
        return ciphertext, nonce

    def decrypt(
        self, ciphertext: bytes, nonce: bytes, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            plaintext = self._aes.decrypt(nonce, ciphertext, canonical_json(metadata))
            result = json.loads(plaintext)
        except Exception as exc:
            raise AuditEncryptionError(
                "No se pudo autenticar o descifrar el evento de bitácora"
            ) from exc
        if not isinstance(result, dict):
            raise AuditEncryptionError("El contenido descifrado de bitácora no es válido")
        return result


def record_hash(
    previous_hash: str | None,
    metadata: dict[str, Any],
    nonce: bytes,
    ciphertext: bytes,
) -> str:
    digest = hashlib.sha256()
    digest.update((previous_hash or "").encode("ascii"))
    digest.update(canonical_json(metadata))
    digest.update(nonce)
    digest.update(ciphertext)
    return digest.hexdigest()


def encrypted_line(model: Any) -> bytes:
    document = {
        "version": model.version_cifrado,
        "id": model.id,
        "empresa_id": model.empresa_id,
        "usuario_id": model.user_id,
        "modulo": model.module,
        "accion": model.action,
        "nivel": model.level,
        "tabla_afectada": model.tabla_afectada,
        "registro_id": model.registro_id,
        "fecha": model.fecha.isoformat(),
        "nonce": b64encode(model.nonce_cifrado).decode("ascii"),
        "datos_cifrados": b64encode(model.datos_cifrados).decode("ascii"),
        "hash_anterior": model.hash_anterior,
        "hash_registro": model.hash_registro,
    }
    return canonical_json(document) + b"\n"
