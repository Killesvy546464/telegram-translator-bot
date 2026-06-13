import json
import re
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, MAX_CHUNK_CHARS

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

SYSTEM_PROMPT = """You are a professional literary translator translating English texts into standard, decent French (niveau soutenu). You also identify useful B2-C1 level French vocabulary for language learners.

For each paragraph in the input text:
1. Output the original paragraph wrapped in <original>...</original> tags.
2. Immediately follow with the French translation wrapped in <traduction>...</traduction> tags.

After all paragraphs, extract 8-15 essential words or expressions from your French translation that are at B2-C1 level. List them in <vocabulaire>...</vocabulaire> tags using this exact format for each entry:
<item>
<fr>French word/expression</fr>
<en>English equivalent</en>
<type>noun/verb/adjective/adverb/expression</type>
</item>

Rules:
- Translate naturally, preserving the tone and register of the original.
- Do not add explanations, commentary, or notes.
- For vocabulary: select words that are genuinely useful for an advanced learner, not basic A1-A2 words.
- Only output the tagged sections — nothing else."""


def translate_and_extract_vocab(text: str) -> dict:
    """Translate text paragraph by paragraph and extract B2-C1 vocabulary."""

    # Split into logical paragraphs
    paragraphs = _split_paragraphs(text)

    # Process in chunks if too long
    if len(text) > MAX_CHUNK_CHARS:
        return _process_chunks(paragraphs)

    return _process_single(text)


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs."""
    raw = re.split(r"\n{2,}", text.strip())
    return [p.strip() for p in raw if len(p.strip()) > 20]


def _process_single(text: str) -> dict:
    """Process a single chunk of text."""
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.3,
        max_tokens=4096,
    )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("DeepSeek returned empty response")

    return _parse_response(content)


def _process_chunks(paragraphs: list[str]) -> dict:
    """Process text in chunks, then combine results."""
    all_paragraphs = []
    all_vocab = []
    current_chunk = []
    current_len = 0

    for p in paragraphs:
        if current_len + len(p) > MAX_CHUNK_CHARS and current_chunk:
            result = _process_single("\n\n".join(current_chunk))
            all_paragraphs.extend(result["paragraphs"])
            all_vocab.extend(result["vocabulary"])
            current_chunk = [p]
            current_len = len(p)
        else:
            current_chunk.append(p)
            current_len += len(p)

    if current_chunk:
        result = _process_single("\n\n".join(current_chunk))
        all_paragraphs.extend(result["paragraphs"])
        all_vocab.extend(result["vocabulary"])

    # Deduplicate vocabulary
    seen = set()
    unique_vocab = []
    for v in all_vocab:
        key = v["french"].lower()
        if key not in seen:
            seen.add(key)
            unique_vocab.append(v)

    return {"paragraphs": all_paragraphs, "vocabulary": unique_vocab[:20]}


def _parse_response(content: str) -> dict:
    """Parse the tagged DeepSeek response into structured data."""
    paragraphs = []
    vocabulary = []

    # Extract paragraph pairs
    orig_matches = re.findall(r"<original>(.*?)</original>", content, re.DOTALL)
    trad_matches = re.findall(r"<traduction>(.*?)</traduction>", content, re.DOTALL)

    for orig, trad in zip(orig_matches, trad_matches):
        paragraphs.append({
            "original": orig.strip(),
            "translated": trad.strip(),
        })

    # Extract vocabulary
    vocab_section = re.search(r"<vocabulaire>(.*?)</vocabulaire>", content, re.DOTALL)
    if vocab_section:
        items = re.findall(r"<item>(.*?)</item>", vocab_section.group(1), re.DOTALL)
        for item in items:
            fr = _extract_tag(item, "fr")
            en = _extract_tag(item, "en")
            wtype = _extract_tag(item, "type")
            if fr and en:
                vocabulary.append({"french": fr, "english": en, "type": wtype or "expression"})

    return {"paragraphs": paragraphs, "vocabulary": vocabulary}


def _extract_tag(text: str, tag: str) -> str:
    """Extract content from an XML-like tag."""
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def format_telegram_output(result: dict, title: str, notion_url: str = None) -> str:
    """Format the translation result for Telegram message output."""
    lines = [f"📄 *{title}*\n"]

    for i, p in enumerate(result["paragraphs"], 1):
        lines.append(f"─── Paragraph {i} ───")
        lines.append(p["original"])
        lines.append("")
        lines.append(f"🇫🇷 {p['translated']}")
        lines.append("")

    if result.get("vocabulary"):
        lines.append("📚 *Vocabulaire B2-C1*")
        for v in result["vocabulary"]:
            lines.append(f"• *{v['french']}* — {v['english']} ({v['type']})")

    if notion_url:
        lines.append(f"\n📝 Notion: {notion_url}")

    return "\n".join(lines)
