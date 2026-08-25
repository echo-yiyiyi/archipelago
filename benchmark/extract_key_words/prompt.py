KEYWORD_EXTRACTION_PROMPT = """You are a task-keyword extraction engine.

Given a complete task prompt, extract exactly 3 or 4 concise keyword phrases that best identify the task and would be useful for constructing task-relevant filenames and reference-file content.

Selection rules:
1. Prefer the named company, organization, product, or primary subject.
2. Include the main task, analysis type, or target metric.
3. Include the most important source document, workbook, sheet, scenario driver, or business object.
4. Preserve specific wording and capitalization from the input when useful.
5. Do not select dates, numeric values, rounding instructions, generic action verbs, sensitivity parameter values, or output-format instructions unless they are essential to identifying the task.

Return only a valid JSON array containing 3 or 4 strings. Do not add explanations, labels, or Markdown.

Example input:
Conduct a 5-year IRR sensitivity analysis using Planet Fitness' financial model. Model the impact if, starting Q1 2026, Planet Fitness opens 10 additional Franchisee-owned stores each quarter, compared to the same quarter in the prior year, and continues this trend each quarter until Q4 2030.

1. Using the "Copy of LBO" tab, calculate the 5-year IRR when share price premiums are 10%, 15% and exit multiples are 16x, 17x, 18x.
2. Round all calculated results to one decimal place.

REQUEST: Put in a sensitivity table to a new Sheet with these values.

Example output:
["Planet Fitness", "IRR sensitivity", "Copy of LBO", "Franchisee-owned stores"]

Task prompt:
{{TASK_PROMPT}}

Output:
"""


def build_keyword_extraction_prompt(task_prompt: str) -> str:
    """Insert a complete task prompt into the keyword-extraction template."""
    return KEYWORD_EXTRACTION_PROMPT.replace("{{TASK_PROMPT}}", task_prompt.strip())
