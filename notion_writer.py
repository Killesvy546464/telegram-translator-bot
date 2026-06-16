import logging
from datetime import datetime
from notion_client import Client
from notion_client.errors import APIResponseError
from config import NOTION_API_KEY, NOTION_PARENT_PAGE_ID

logger = logging.getLogger(__name__)

notion = Client(auth=NOTION_API_KEY)

# Notion rich_text content limit is 2000 chars per text object
MAX_TEXT_LENGTH = 1900


def validate_config() -> dict:
    """Validate Notion configuration at startup. Returns dict with status info."""
    if not NOTION_API_KEY:
        raise ValueError("NOTION_API_KEY is not set")
    if not NOTION_PARENT_PAGE_ID:
        raise ValueError("NOTION_PARENT_PAGE_ID is not set")

    try:
        page = notion.pages.retrieve(page_id=NOTION_PARENT_PAGE_ID)
        title_prop = page.get("properties", {}).get("title", {})
        title = ""
        if title_prop:
            title_items = title_prop.get("title", [])
            if title_items:
                title = title_items[0].get("text", {}).get("content", "")
        return {"url": page.get("url", ""), "title": title}
    except APIResponseError as e:
        raise RuntimeError(
            f"Cannot access Notion parent page. "
            f"Make sure the integration is connected to the page. "
            f"API error (HTTP {e.status}): {e.code} — {e.body}"
        )


def _truncate(text: str, max_len: int = MAX_TEXT_LENGTH) -> str:
    """Truncate text that exceeds Notion's content length limit."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def create_notion_page(title: str, result: dict, parent_page_id: str = None) -> str:
    """Create a Notion page with the translated content and vocabulary."""
    page_id = parent_page_id or NOTION_PARENT_PAGE_ID
    if not page_id:
        raise ValueError("No Notion parent page ID configured")

    # Notion page titles are limited to ~2000 chars
    date_str = datetime.now().strftime("%Y-%m-%d")
    full_title = f"{title} — {date_str}"
    page_title = _truncate(full_title, 200)

    all_blocks = _build_blocks(result)

    logger.info(
        f"create_notion_page: {len(all_blocks)} blocks to send to Notion"
    )
    if all_blocks:
        for bi, blk in enumerate(all_blocks[:5]):
            bt = blk.get("type", "unknown")
            rt = blk.get(bt, {}).get("rich_text", [])
            txt = "".join(t.get("text", {}).get("content", "") for t in rt)
            logger.info(f"  block[{bi}] {bt}: '{txt[:80]}...'" if len(txt) > 80 else f"  block[{bi}] {bt}: '{txt}'")
        if len(all_blocks) > 5:
            logger.info(f"  ... and {len(all_blocks) - 5} more blocks")

    # Notion API allows max 100 children per page create / append call
    MAX_BLOCKS_PER_CALL = 100
    first_chunk = all_blocks[:MAX_BLOCKS_PER_CALL]
    remaining = all_blocks[MAX_BLOCKS_PER_CALL:]

    try:
        page = notion.pages.create(
            parent={"page_id": page_id},
            properties={
                "title": {
                    "title": [{"type": "text", "text": {"content": page_title}}]
                }
            },
            children=first_chunk,
        )
        page_url = page.get("url", "")
        if page_url:
            logger.info(f"Notion page created: {page_url}")

        # Append remaining blocks in batches
        page_id_created = page["id"]
        for i in range(0, len(remaining), MAX_BLOCKS_PER_CALL):
            batch = remaining[i : i + MAX_BLOCKS_PER_CALL]
            try:
                notion.blocks.children.append(
                    block_id=page_id_created, children=batch
                )
                logger.info(f"Appended batch {i // MAX_BLOCKS_PER_CALL + 1} ({len(batch)} blocks)")
            except APIResponseError as e:
                logger.error(f"Notion batch append error: {e}")
                # Page exists, so return the URL even if a batch fails

        return page_url
    except APIResponseError as e:
        logger.error(f"Notion API error (status={e.status}, code={e.code}): {e.body}")
        raise RuntimeError(
            f"Notion API error (HTTP {e.status}): {e.code} — {e.body}"
        )
    except Exception as e:
        logger.error(f"Unexpected Notion error: {type(e).__name__}: {e}")
        raise


def _build_blocks(result: dict) -> list:
    """Build Notion blocks from the translation result."""
    para_count = len(result.get("paragraphs", []))
    vocab_count = len(result.get("vocabulary", []))
    logger.info(
        f"_build_blocks input: {para_count} paragraphs, {vocab_count} vocab items"
    )

    blocks = []

    # Header
    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {
            "rich_text": [{"type": "text", "text": {"content": "Traduction française"}}]
        }
    })

    blocks.append({"object": "block", "type": "divider", "divider": {}})

    # Interleaved paragraphs
    for i, p in enumerate(result.get("paragraphs", []), 1):
        # Paragraph number heading
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": [{"type": "text", "text": {"content": f"Paragraphe {i}"}}]
            }
        })

        # Original text as quote
        orig_text = _truncate(p.get("original", ""))
        blocks.append({
            "object": "block",
            "type": "quote",
            "quote": {
                "rich_text": [{"type": "text", "text": {"content": orig_text}}]
            }
        })

        # French translation
        trad_text = _truncate(p.get("translated", ""))
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": "🇫🇷 "}},
                    {"type": "text", "text": {"content": trad_text}},
                ]
            }
        })

        # Spacer
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": []
            }
        })

    # Vocabulary section
    if result.get("vocabulary"):
        blocks.append({"object": "block", "type": "divider", "divider": {}})
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Vocabulaire B2-C1"}}]
            }
        })
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": "Mots et expressions utiles extraits du texte :"}}]
            }
        })

        # Vocabulary as bulleted list
        for v in result["vocabulary"]:
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [
                        {"type": "text", "text": {"content": v["french"], "bold": True}},
                        {"type": "text", "text": {"content": f" — {v['english']} "}},
                        {"type": "text", "text": {"content": f"({v['type']})", "italic": True}},
                    ]
                }
            })

    return blocks
