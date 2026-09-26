"""Prompt template for ranking task-relevant file types."""

from __future__ import annotations


FILE_TYPE_RANKING_PROMPT = """Infer the likely question or task represented by the keywords below. Based on that inferred question or task, rank all seven file types—md, xlsx, html, txt, chat, email, and calendar—from most likely to least likely to contain the information needed to answer or complete it.

Allowed file types:
- md: Markdown documents, notes, reports, and written reference material
- xlsx: spreadsheets, financial models, tables, calculations, and datasets
- html: web pages, exported reports, filings, and browser-based reference pages
- txt: plain-text notes, transcripts, summaries, and instructions
- chat: chat messages, channels, and conversational records
- email: email messages, threads, and attachments described by correspondence
- calendar: calendar events, schedules, invitations, and meeting metadata

<task_keywords>
{{TASK_KEYWORDS}}
</task_keywords>
"""


def build_file_type_ranking_prompt(task_keywords: list[str]) -> str:
    if (
        not isinstance(task_keywords, list)
        or not task_keywords
        or any(not isinstance(keyword, str) or not keyword.strip() for keyword in task_keywords)
    ):
        raise ValueError("task keywords must be a non-empty list of strings")
    formatted_keywords = "\n".join(f"- {keyword.strip()}" for keyword in task_keywords)
    return FILE_TYPE_RANKING_PROMPT.replace("{{TASK_KEYWORDS}}", formatted_keywords)
