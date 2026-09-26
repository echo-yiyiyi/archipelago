"""Monkey-patches for litellm bugs. Remove when upgrading past the fix."""

from importlib.metadata import version as _pkg_version
from typing import Any

from litellm.llms.openai.chat.gpt_5_transformation import OpenAIGPT5Config
from packaging.version import Version

# LiteLLM 1.92.0's bundled model map predates GPT-5.6. Its GPT-5 transform
# therefore rejects xhigh locally for both the canonical model name and Azure
# deployment aliases, before the request can reach the provider. The Azure
# deployment used by this repository accepts xhigh, so fill this single missing
# capability until LiteLLM's bundled model map includes GPT-5.6.
_original_supports_reasoning_effort_level = (
    OpenAIGPT5Config._supports_reasoning_effort_level
)


def _supports_gpt_5_6_reasoning_effort(
    model: str,
    level: str,
) -> bool:
    if "gpt-5.6" in model.lower() and level == "xhigh":
        return True
    return _original_supports_reasoning_effort_level(model, level)


OpenAIGPT5Config._supports_reasoning_effort_level = classmethod(  # type: ignore[method-assign]
    lambda cls, model, level: _supports_gpt_5_6_reasoning_effort(model, level)
)

# litellm <= 1.82.1 incorrectly rejects xhigh reasoning_effort for gpt-5.4.
# The hardcoded check only allows gpt-5.1-codex-max and gpt-5.2, but OpenAI's
# model card confirms gpt-5.4 supports xhigh. Patch until litellm ships the fix.
_LITELLM_MAX_BUGGY_VERSION = Version("1.82.1")

if Version(_pkg_version("litellm")) <= _LITELLM_MAX_BUGGY_VERSION:
    _original_map = OpenAIGPT5Config.map_openai_params

    def _patched_map(
        self: OpenAIGPT5Config,
        non_default_params: dict[str, Any],
        optional_params: dict[str, Any],
        model: str,
        drop_params: bool,
    ) -> dict[str, Any]:
        # Temporarily make gpt-5.4 look like gpt-5.2 so the xhigh check passes.
        fake_model = False
        reasoning_effort = non_default_params.get(
            "reasoning_effort"
        ) or optional_params.get("reasoning_effort")
        if "gpt-5.4" in model and reasoning_effort == "xhigh":
            fake_model = True
            model = model.replace("gpt-5.4", "gpt-5.2")

        result = _original_map(
            self, non_default_params, optional_params, model, drop_params
        )

        # Restore the real model — callers may inspect optional_params["model"] downstream.
        if fake_model:
            result["model"] = result.get("model", "").replace("gpt-5.2", "gpt-5.4")

        return result

    OpenAIGPT5Config.map_openai_params = _patched_map  # type: ignore[assignment]
