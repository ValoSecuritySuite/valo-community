"""PDF generation service."""

from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.core.exceptions import ServiceError
from app.core.logging import get_logger
from app.schemas import PdfRequest

logger = get_logger(__name__)


def generate_pdf(payload: PdfRequest) -> bytes:
    """Generate a PDF from the given request payload."""
    try:
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        y = height - 72
        pdf.setTitle(payload.title)
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(72, y, payload.title)

        y -= 36
        pdf.setFont("Helvetica", 12)
        for line in payload.lines:
            if y < 72:
                pdf.showPage()
                y = height - 72
                pdf.setFont("Helvetica", 12)
            pdf.drawString(72, y, line)
            y -= 18

        pdf.save()
        result = buffer.getvalue()
        logger.debug("Generated PDF: %d bytes, title=%s", len(result), payload.title)
        return result
    except Exception as e:
        logger.error("PDF generation failed", exc_info=True)
        raise ServiceError(
            message="PDF generation failed",
            detail={"error": str(e)},
        ) from e
