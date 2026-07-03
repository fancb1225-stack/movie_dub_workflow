from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4


def upload_file_to_tos(
    file_path: str | Path,
    config: dict[str, Any],
    object_prefix: str | None = None,
) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"TOS upload source does not exist: {path}")

    tos_config = config.get("tos", {})
    access_key_env = str(tos_config.get("access_key_id_env", "DOUBAO_TOS_ACCESS_KEY_ID"))
    secret_key_env = str(tos_config.get("secret_access_key_env", "DOUBAO_TOS_SECRET_ACCESS_KEY"))
    access_key = os.getenv(access_key_env, "")
    secret_key = os.getenv(secret_key_env, "")
    if not access_key or not secret_key:
        raise RuntimeError(
            "TOS upload requires environment variables "
            f"{access_key_env} and {secret_key_env}."
        )

    endpoint = str(tos_config.get("endpoint", "")).strip()
    region = str(tos_config.get("region", "")).strip()
    bucket = str(tos_config.get("bucket", "")).strip()
    if not endpoint or not region or not bucket:
        raise RuntimeError("TOS upload requires tos.endpoint, tos.region, and tos.bucket.")

    try:
        import tos  # type: ignore
    except ImportError as exc:
        raise RuntimeError("TOS upload requires the tos Python package.") from exc

    expires = int(tos_config.get("presign_expires", 3600))
    key = _build_object_key(
        path,
        object_prefix or str(tos_config.get("object_prefix", "asr")),
    )
    client = tos.TosClientV2(access_key, secret_key, endpoint, region)
    client.put_object_from_file(bucket, key, str(path))
    signed = client.pre_signed_url(tos.HttpMethodType.Http_Method_Get, bucket, key, expires)
    url = signed if isinstance(signed, str) else getattr(signed, "signed_url", "")
    if not url:
        raise RuntimeError("TOS pre_signed_url did not return a usable URL.")
    return {
        "bucket": bucket,
        "object_key": key,
        "url": str(url),
        "expires": expires,
        "source": str(path),
    }


def _build_object_key(file_path: Path, object_prefix: str) -> str:
    prefix = object_prefix.strip().strip("/")
    suffix = "".join(ch if ch.isalnum() or ch in {".", "_", "-"} else "_" for ch in file_path.name)
    key = f"{uuid4().hex}_{suffix}"
    return f"{prefix}/{key}" if prefix else key
