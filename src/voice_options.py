from __future__ import annotations

from typing import Any, TypedDict


class VoiceOption(TypedDict):
    voice_id: str
    label: str
    original_label: str
    language: str


VOICE_OPTIONS: tuple[VoiceOption, ...] = (
    {"voice_id": "Wise_Woman", "label": "智慧女声", "original_label": "Wise Woman", "language": "英文"},
    {"voice_id": "Friendly_Person", "label": "友好人物", "original_label": "Friendly Person", "language": "英文"},
    {"voice_id": "Inspirational_girl", "label": "励志女孩", "original_label": "Inspirational Girl", "language": "英文"},
    {"voice_id": "Deep_Voice_Man", "label": "低沉男声", "original_label": "Deep Voice Man", "language": "英文"},
    {"voice_id": "Calm_Woman", "label": "沉稳女声", "original_label": "Calm Woman", "language": "英文"},
    {"voice_id": "default", "label": "默认音色", "original_label": "Default", "language": "默认"},
    {"voice_id": "Santa_Claus", "label": "圣诞老人", "original_label": "Santa Claus", "language": "英文"},
    {"voice_id": "Grinch", "label": "格林奇", "original_label": "Grinch", "language": "英文"},
    {"voice_id": "Rudolph", "label": "鲁道夫", "original_label": "Rudolph", "language": "英文"},
    {"voice_id": "Arnold", "label": "阿诺德", "original_label": "Arnold", "language": "英文"},
    {"voice_id": "Charming_Santa", "label": "迷人圣诞老人", "original_label": "Charming Santa", "language": "英文"},
    {"voice_id": "Charming_Lady", "label": "迷人女士", "original_label": "Charming Lady", "language": "英文"},
    {"voice_id": "Sweet_Girl", "label": "甜美女孩", "original_label": "Sweet Girl", "language": "英文"},
    {"voice_id": "Cute_Elf", "label": "可爱精灵", "original_label": "Cute Elf", "language": "英文"},
    {"voice_id": "Attractive_Girl", "label": "魅力女孩", "original_label": "Attractive Girl", "language": "英文"},
    {"voice_id": "Serene_Woman", "label": "宁静女声", "original_label": "Serene Woman", "language": "英文"},
    {
        "voice_id": "English_Trustworthy_Man",
        "label": "可信赖男声",
        "original_label": "Trustworthy Man",
        "language": "英文",
    },
    {
        "voice_id": "English_Graceful_Lady",
        "label": "优雅女士",
        "original_label": "Graceful Lady",
        "language": "英文",
    },
    {
        "voice_id": "English_Aussie_Bloke",
        "label": "澳洲男声",
        "original_label": "Aussie Bloke",
        "language": "英文",
    },
    {
        "voice_id": "English_Whispering_girl",
        "label": "低语女孩",
        "original_label": "Whispering girl",
        "language": "英文",
    },
    {
        "voice_id": "English_Diligent_Man",
        "label": "勤奋男声",
        "original_label": "Diligent Man",
        "language": "英文",
    },
    {
        "voice_id": "English_Gentle-voiced_man",
        "label": "温柔男声",
        "original_label": "Gentle-voiced man",
        "language": "英文",
    },
)


def list_voice_options() -> list[VoiceOption]:
    return [dict(option) for option in VOICE_OPTIONS]


def normalize_speaker_profiles(profiles: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(profiles, dict):
        return {}
    return {
        str(speaker_id): _normalize_profile(raw_profile)
        for speaker_id, raw_profile in profiles.items()
    }


def _normalize_profile(raw_profile: Any) -> dict[str, Any]:
    if isinstance(raw_profile, dict):
        profile = dict(raw_profile)
        voice_id = _resolve_voice_id(profile.get("voice_id") or profile.get("value") or profile.get("label"))
        if voice_id == "default":
            profile.pop("voice_id", None)
            profile.pop("value", None)
            profile.pop("label", None)
            return profile
        if voice_id:
            profile["voice_id"] = voice_id
        profile.pop("value", None)
        profile.pop("label", None)
        return profile

    voice_id = _resolve_voice_id(raw_profile)
    if not voice_id or voice_id == "default":
        return {}
    return {"voice_id": voice_id}


def _resolve_voice_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lookup = _voice_lookup()
    return lookup.get(_lookup_key(text), text)


def _voice_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for option in VOICE_OPTIONS:
        voice_id = option["voice_id"]
        for value in (voice_id, option["label"], option["original_label"], voice_id.replace("_", " ")):
            lookup[_lookup_key(value)] = voice_id
    return lookup


def _lookup_key(value: str) -> str:
    return value.strip().lower().replace("_", " ").replace("-", " ")
