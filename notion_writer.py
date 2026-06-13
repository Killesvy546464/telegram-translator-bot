from datetime import datetime
from notion_client import Client
from notion_client.errors import APIResponseError
from config import NOTION_API_KEY, NOTION_PARENT_PAGE_ID

notion = Client(auth=NOTION_API_KEY)


def create_notion_page(title: str, result: dict, parent_page_id: str = None) -> str:
    """Create a Notion page with the translated content and vocabulary."""
    page_id = parent_page_id or NOTION_PARENT_PAGE_ID
    if not page_id:
        raise ValueError("No Notion parent page ID configured")

    date_str = datetime.now().strftime("%Y-%m-%d")
    page_title = f"{title} — {date_str}"

    children = _build_blocks(result)

    try:
        page = notion.pages.create(
            parent={"page_id": page_id},
            properties={
                "title": {
                    "title": [{"type": "text", "text": {"content": page_title}}]
                }
            },
            children=children,
        )
        page_url = page.get("url", "")
        return page_url
    except APIResponseError as e:
        raise RuntimeError(f"Notion API error: {e}")


def _build_blocks(result: dict) -> list:
    """Build Notion blocks from the translation result."""
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
        blocks.append({
            "object": "block",
            "type": "quote",
            "quote": {
                "rich_text": [{"type": "text", "text": {"content": p["original"]}}]
            }
        })

        # French translation
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": "🇫🇷 "}},
                    {"type": "text", "text": {"content": p["translated"]}},
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
