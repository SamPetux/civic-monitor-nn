from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from modules.pdf_report import build_district_report

router = APIRouter(prefix="/api/reports", tags=["reports"])


class PDFReportRequest(BaseModel):
    district_id: str | None = None   # None = весь город
    start: datetime
    end: datetime


@router.post(
    "/pdf",
    summary="Сгенерировать PDF-отчёт по району",
    responses={200: {"content": {"application/pdf": {}}}},
)
def generate_pdf(req: PDFReportRequest):
    try:
        pdf_bytes = build_district_report(
            output_path=None,
            district_id=req.district_id,
            start_dt=req.start,
            end_dt=req.end,
        )
    except Exception as e:
        raise HTTPException(500, detail=f"Ошибка генерации PDF: {e}") from e

    filename = (
        f"report_{req.district_id or 'city'}"
        f"_{req.start.strftime('%Y%m%d')}"
        f"-{req.end.strftime('%Y%m%d')}.pdf"
    )
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )