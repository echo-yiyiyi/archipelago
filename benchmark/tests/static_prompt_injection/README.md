Run offline validation from the repository root:

```bash
python3 -m unittest discover -s benchmark/tests/static_prompt_injection -v
```

The pipeline test mocks the external generator; it does not invoke Azure OpenAI.
