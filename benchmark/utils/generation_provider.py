"""Explicit provider selection shared by ranking and artifact generation."""
import os


def provider() -> str:
    value = os.environ.get('BENCHMARK_GENERATION_PROVIDER', 'azure').strip()
    if value not in ('azure', 'openai'):
        raise ValueError('BENCHMARK_GENERATION_PROVIDER must be azure or openai')
    return value


def model_name(azure_default: str) -> str:
    if provider() == 'openai':
        return os.environ.get('OPENAI_GENERATION_MODEL', '').strip() or 'gpt-5.6-sol'
    return os.environ.get('AZURE_OPENAI_MODEL', '').strip() or azure_default


def openai_client():
    from openai import OpenAI
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        raise ValueError('OPENAI_API_KEY is required for OpenAI generation')
    return OpenAI(api_key=key, base_url='https://api.openai.com/v1')
