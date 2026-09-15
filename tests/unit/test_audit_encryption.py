from copy import deepcopy

import pytest

from ssas.bitacora.infrastructure.crypto import (
    AuditCipher,
    AuditEncryptionError,
    audit_key_bytes,
    record_hash,
)

KEY = "11" * 32
METADATA = {
    "id": "evento-1",
    "empresa_id": "empresa-1",
    "usuario_id": "usuario-1",
    "modulo": "USUARIOS",
    "accion": "UPDATE",
    "nivel": "INFO",
    "tabla_afectada": "usuario",
    "registro_id": "registro-1",
    "fecha": "2026-09-14T12:00:00+00:00",
}


def test_aes_gcm_round_trip_keeps_audit_detail_confidential() -> None:
    payload = {
        "actor_label": "admin@example.com",
        "description": "Usuario actualizado",
        "previous_data": {"activo": False},
        "new_data": {"activo": True},
        "source_ip": "127.0.0.1",
        "user_agent": "pytest",
    }
    cipher = AuditCipher(KEY)

    encrypted, nonce = cipher.encrypt(payload, METADATA)

    assert b"admin@example.com" not in encrypted
    assert cipher.decrypt(encrypted, nonce, METADATA) == payload


def test_aes_gcm_rejects_modified_ciphertext_or_metadata() -> None:
    cipher = AuditCipher(KEY)
    encrypted, nonce = cipher.encrypt({"description": "original"}, METADATA)
    altered = bytearray(encrypted)
    altered[0] ^= 1

    with pytest.raises(AuditEncryptionError):
        cipher.decrypt(bytes(altered), nonce, METADATA)

    changed_metadata = deepcopy(METADATA)
    changed_metadata["accion"] = "DELETE"
    with pytest.raises(AuditEncryptionError):
        cipher.decrypt(encrypted, nonce, changed_metadata)


def test_hash_chain_detects_order_or_content_changes() -> None:
    cipher = AuditCipher(KEY)
    encrypted_one, nonce_one = cipher.encrypt({"value": 1}, METADATA)
    hash_one = record_hash(None, METADATA, nonce_one, encrypted_one)
    second_metadata = {**METADATA, "id": "evento-2"}
    encrypted_two, nonce_two = cipher.encrypt({"value": 2}, second_metadata)
    hash_two = record_hash(hash_one, second_metadata, nonce_two, encrypted_two)

    assert hash_two != record_hash(None, second_metadata, nonce_two, encrypted_two)
    assert hash_two != record_hash(hash_one, second_metadata, nonce_two, encrypted_two + b"x")


@pytest.mark.parametrize("value", [None, "", "abcd", "zz" * 32])
def test_invalid_audit_keys_are_rejected(value: str | None) -> None:
    with pytest.raises(AuditEncryptionError):
        audit_key_bytes(value)
