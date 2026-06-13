import re
import trafilatura


def extract_content(url: str) -> dict:
    """Extract title and paragraphs from a URL. Returns {title, text, paragraphs}."""
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ValueError(f"Could not fetch content from: {url}")

    text = trafilatura.extract(
        downloaded,
        include_links=False,
        include_images=False,
        include_tables=False,
        output_format="txt",
    )

    if not text or len(text.strip()) < 50:
        raise ValueError(f"Extracted content is too short or empty from: {url}")

    title = _extract_title(downloaded) or "Untitled"

    # Split into paragraphs and clean
    raw_paragraphs = re.split(r"\n{2,}", text.strip())
    paragraphs = [p.strip() for p in raw_paragraphs if len(p.strip()) > 20]

    return {
        "title": title,
        "text": text.strip(),
        "paragraphs": paragraphs,
    }


def _extract_title(html: str) -> str:
    """Try to extract the article title from HTML."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        title = match.group(1).strip()
        # Clean common suffixes
        title = re.sub(r"\s*[-|]\s*.+$", "", title)
        return title
    return ""
