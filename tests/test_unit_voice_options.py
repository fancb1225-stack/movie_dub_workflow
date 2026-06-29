import unittest

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.routes import _build_workflow_overrides
from src.voice_options import list_voice_options, normalize_speaker_profiles


class VoiceOptionsTests(unittest.TestCase):
    def test_list_voice_options_exposes_translated_labels(self) -> None:
        voices = list_voice_options()

        santa = next(item for item in voices if item["voice_id"] == "Santa_Claus")

        self.assertEqual(santa["label"], "圣诞老人")
        self.assertEqual(santa["original_label"], "Santa Claus")

    def test_normalize_speaker_profiles_maps_voice_id_to_model_profile(self) -> None:
        profiles = normalize_speaker_profiles({"speaker_1": "Santa_Claus"})

        self.assertEqual(profiles["speaker_1"]["voice_id"], "Santa_Claus")

    def test_normalize_speaker_profiles_maps_display_name_to_model_voice_id(self) -> None:
        profiles = normalize_speaker_profiles({"speaker_1": "Santa Claus"})

        self.assertEqual(profiles["speaker_1"]["voice_id"], "Santa_Claus")

    def test_normalize_speaker_profiles_preserves_extra_model_parameters(self) -> None:
        profiles = normalize_speaker_profiles(
            {"speaker_1": {"voice_id": "English_Diligent_Man", "speed": 1.2, "pitch": -1}}
        )

        self.assertEqual(
            profiles["speaker_1"],
            {"voice_id": "English_Diligent_Man", "speed": 1.2, "pitch": -1},
        )

    def test_workflow_overrides_normalize_speaker_profiles_for_tts(self) -> None:
        overrides = _build_workflow_overrides(
            None,
            None,
            None,
            None,
            {"speaker_profiles": {"speaker_1": "Santa Claus"}},
        )

        self.assertEqual(
            overrides["tts.speaker_profiles"],
            {"speaker_1": {"voice_id": "Santa_Claus"}},
        )

    def test_workflow_overrides_normalize_default_speaker_profile_for_tts(self) -> None:
        overrides = _build_workflow_overrides(
            None,
            None,
            None,
            None,
            {"speaker_profiles": {"speaker_1": "Wise_Woman", "default": "Wise_Woman"}},
        )

        self.assertEqual(
            overrides["tts.speaker_profiles"],
            {"speaker_1": {"voice_id": "Wise_Woman"}, "default": {"voice_id": "Wise_Woman"}},
        )

    def test_voice_options_api_returns_model_id_and_translated_label(self) -> None:
        client = TestClient(create_app())

        response = client.get("/api/tts/voices")

        self.assertEqual(response.status_code, 200)
        voices = response.json()["voices"]
        santa = next(item for item in voices if item["voice_id"] == "Santa_Claus")
        self.assertEqual(santa["label"], "圣诞老人")


if __name__ == "__main__":
    unittest.main()
