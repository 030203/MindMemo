from __future__ import annotations

import asyncio
import io
import sys
import unittest
import zipfile
from pathlib import Path

from fastapi import UploadFile

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ingestion_service import ingestion_service  # noqa: E402


def _make_docx_bytes(*paragraphs: str) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body>"
        "</w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


class DocumentIngestionTest(unittest.TestCase):
    def test_docx_upload_extracts_readable_text(self) -> None:
        raw_docx = _make_docx_bytes("第一段：项目背景", "第二段：后续计划")
        upload = UploadFile(
            filename="思想汇报20260201.docx",
            file=io.BytesIO(raw_docx),
            headers=None,
        )

        result = asyncio.run(ingestion_service.ingest_document(upload, note="导入备注"))

        self.assertEqual(result.file_name, "思想汇报20260201.docx")
        self.assertIn("附件：思想汇报20260201.docx", result.content)
        self.assertIn("第一段：项目背景", result.content)
        self.assertIn("第二段：后续计划", result.content)
        self.assertIn("导入备注", result.content)

    def test_text_upload_extracts_readable_text(self) -> None:
        upload = UploadFile(
            filename="notes.md",
            file=io.BytesIO("# 标题\n正文内容".encode("utf-8")),
            headers=None,
        )

        result = asyncio.run(ingestion_service.ingest_document(upload))

        self.assertEqual(result.file_name, "notes.md")
        self.assertIn("# 标题", result.content)
        self.assertIn("正文内容", result.content)


if __name__ == "__main__":
    unittest.main()
