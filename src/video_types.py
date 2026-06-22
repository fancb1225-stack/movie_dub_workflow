from __future__ import annotations

VIDEO_TYPE_MOVIE_COMMENTARY = "movie_commentary"
VIDEO_TYPE_MANJU = "manju"
DEFAULT_VIDEO_TYPE = VIDEO_TYPE_MOVIE_COMMENTARY
ALLOWED_VIDEO_TYPES = {VIDEO_TYPE_MOVIE_COMMENTARY, VIDEO_TYPE_MANJU}


def normalize_video_type(value: str | None) -> str:
    if value is None:
        return DEFAULT_VIDEO_TYPE
    normalized = value.strip().lower()
    if not normalized:
        return DEFAULT_VIDEO_TYPE
    if normalized not in ALLOWED_VIDEO_TYPES:
        allowed = ", ".join(sorted(ALLOWED_VIDEO_TYPES))
        raise ValueError(f"Unsupported video_type '{value}'. Allowed: {allowed}")
    return normalized
