curl -sS https://api.openai.com/v1/responses \
    -H "Authorization: Bearer $OPENAI_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "model": "gpt-5.4",
      "reasoning": {"effort": "xhigh"},
      "input": "Reply with exactly: API works"
    }'