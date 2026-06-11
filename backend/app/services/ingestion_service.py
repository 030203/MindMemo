from __future__ import annotations

import io
import re
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse
from xml.etree import ElementTree

from fastapi import UploadFile
from pypdf import PdfReader


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    compact_lines = [line for line in lines if line]
    return "\n".join(compact_lines)


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._ignore_depth = 0
        self._ignored_tags = {"script", "style", "noscript", "svg"}
        self._capture_title = False
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        normalized = tag.lower()
        if normalized in self._ignored_tags:
            self._ignore_depth += 1
        if normalized == "title":
            self._capture_title = True

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        normalized = tag.lower()
        if normalized in self._ignored_tags and self._ignore_depth > 0:
            self._ignore_depth -= 1
        if normalized == "title":
            self._capture_title = False
        if normalized in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "br"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if not data.strip():
            return
        if self._ignore_depth == 0:
            self.text_parts.append(data)


@dataclass
class UrlIngestResult:
    title: str
    content: str
    source_url: str


@dataclass
class PdfIngestResult:
    title: str
    content: str
    file_name: str
    page_count: int


@dataclass
class DocumentIngestResult:
    title: str
    content: str
    file_name: str
    mime_type: str
    file_size: int


class IngestionService:
    def ingest_url(self, url: str, preferred_title: str | None = None) -> UrlIngestResult:
        normalized_url = self._validate_url(url)
        request = urllib.request.Request(
            normalized_url,
            headers={
                "User-Agent": "MindMemo/0.1 (+https://localhost)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.5",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                final_url = response.geturl()
                content_type = response.headers.get_content_type()
                if content_type and "html" not in content_type and not content_type.startswith("text/"):
                    raise ValueError("这个链接暂时不支持直接导入，请换成普通网页文章链接。")

                raw_bytes = response.read(2_000_000)
                charset = response.headers.get_content_charset() or "utf-8"
        except urllib.error.HTTPError as exc:
            raise ValueError(f"抓取网页失败，状态码 {exc.code}。") from exc
        except urllib.error.URLError as exc:
            raise ValueError("抓取网页失败，请检查链接是否可访问。") from exc

        html_text = raw_bytes.decode(charset, errors="ignore")
        extracted = self._extract_html_text(html_text)
        if not extracted:
            raise ValueError("网页正文提取失败，这个页面可能不适合直接导入。")

        title = (preferred_title or "").strip() or self._extract_html_title(html_text) or urlparse(final_url).netloc
        return UrlIngestResult(title=title[:255], content=extracted[:12000], source_url=final_url)

    async def ingest_pdf(self, file: UploadFile, preferred_title: str | None = None) -> PdfIngestResult:
        file_name = (file.filename or "uploaded.pdf").strip() or "uploaded.pdf"
        if not file_name.lower().endswith(".pdf"):
            raise ValueError("请上传 PDF 文件。")

        raw_bytes = await file.read()
        if not raw_bytes:
            raise ValueError("上传的 PDF 为空。")

        try:
            reader = PdfReader(io.BytesIO(raw_bytes))
        except Exception as exc:  # pragma: no cover
            raise ValueError("PDF 解析失败，请确认文件没有损坏。") from exc

        page_texts: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            normalized = _normalize_text(text)
            if normalized:
                page_texts.append(normalized)

        if not page_texts:
            raise ValueError("这个 PDF 没有可提取文本，可能是扫描版图片 PDF。")

        metadata = reader.metadata
        raw_title = getattr(metadata, "title", None) if metadata else None
        title = (preferred_title or "").strip() or (raw_title or "").strip() or file_name.rsplit(".", 1)[0]
        return PdfIngestResult(
            title=title[:255],
            content="\n\n".join(page_texts)[:16000],
            file_name=file_name,
            page_count=len(reader.pages),
        )

    async def ingest_document(self, file: UploadFile, preferred_title: str | None = None, note: str | None = None) -> DocumentIngestResult:
        file_name = (file.filename or "uploaded-document").strip() or "uploaded-document"
        suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
        raw_bytes = await file.read()
        if not raw_bytes:
            raise ValueError("上传的文件为空。")

        if suffix == "docx" or content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            extracted = self._extract_docx_text(raw_bytes)
        elif content_type.startswith("text/") or suffix in {"md", "markdown", "txt", "csv", "json", "yaml", "yml", "log"}:
            extracted = self._decode_text_bytes(raw_bytes)
        else:
            raise ValueError("这个文件类型暂时不能直接阅读。请上传 TXT、Markdown、CSV、JSON、YAML、DOCX 或 PDF。")

        normalized = _normalize_text(extracted)
        if not normalized:
            raise ValueError("文件里没有解析出可阅读正文。")

        title = (preferred_title or "").strip() or file_name.rsplit(".", 1)[0]
        attachment_line = f"附件：{file_name}（{content_type or suffix or '文件'}）"
        content = "\n\n".join(part for part in [(note or "").strip(), attachment_line, normalized] if part)
        return DocumentIngestResult(
            title=title[:255],
            content=content[:30000],
            file_name=file_name,
            mime_type=content_type or suffix or "application/octet-stream",
            file_size=len(raw_bytes),
        )

    def _validate_url(self, url: str) -> str:
        normalized = url.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("请输入完整的网页链接，例如 https://example.com 。")
        return normalized

    def _extract_html_title(self, html_text: str) -> str:
        match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        return _normalize_text(unescape(match.group(1)))

    def _extract_html_text(self, html_text: str) -> str:
        cleaned_html = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\\1>", " ", html_text)
        extractor = _HtmlTextExtractor()
        extractor.feed(cleaned_html)
        extractor.close()
        return _normalize_text(unescape(" ".join(extractor.text_parts)))

    def _decode_text_bytes(self, raw_bytes: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return raw_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode("utf-8", errors="ignore")

    def _extract_docx_text(self, raw_bytes: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
                document_xml = archive.read("word/document.xml")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ValueError("DOCX 解析失败，请确认文件没有损坏。") from exc

        try:
            root = ElementTree.fromstring(document_xml)
        except ElementTree.ParseError as exc:
            raise ValueError("DOCX 正文解析失败，请确认文件没有损坏。") from exc

        parts: list[str] = []

        def walk(element: ElementTree.Element) -> None:
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "t" and element.text:
                parts.append(element.text)
            elif tag == "tab":
                parts.append("\t")
            elif tag in {"br", "cr"}:
                parts.append("\n")

            for child in element:
                walk(child)

            if tag in {"p", "tr"}:
                parts.append("\n")
            elif tag == "tc":
                parts.append("\t")

        walk(root)
        return "".join(parts)


ingestion_service = IngestionService()
