import os
import glob
import json
import html
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to add 'Page X of Y' footers and a running header.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Header (on page 2 and later)
        if self._pageNumber > 1:
            self.drawString(54, 750, "Psychotherapy LLM Benchmark — Session Transcript")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(54, 742, 558, 742)
            
        # Footer (on all pages)
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 36, page_text)
        self.drawString(54, 36, "Confidential Clinical Dialogue Simulation")
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(54, 48, 558, 48)
        
        self.restoreState()

def create_transcript_pdf(json_path, pdf_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    session_id = str(data.get("session_id", "Unknown"))
    condition = str(data.get("condition", "Unknown"))
    therapist_model = str(data.get("therapist_model", "Unknown"))
    patient_model = str(data.get("patient_model", "Unknown"))
    timestamp = str(data.get("timestamp", "Unknown"))[:19].replace("T", " ")
    turns = data.get("turns", [])

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=64
    )

    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=15
    )
    
    meta_label_style = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#334155")
    )
    
    meta_val_style = ParagraphStyle(
        "MetaValue",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#0F172A")
    )

    therapist_header = ParagraphStyle(
        "TherapistHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0369A1"), # Blue/Teal
        spaceAfter=4
    )
    
    patient_header = ParagraphStyle(
        "PatientHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#B45309"), # Amber/Brown
        spaceAfter=4
    )

    body_style = ParagraphStyle(
        "TurnBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#1E293B")
    )

    story = []

    # Title
    story.append(Paragraph(f"Clinical Dialogue Transcript — {html.escape(condition)}", title_style))
    story.append(Spacer(1, 5))

    # Metadata Table
    meta_data = [
        [Paragraph("Therapist Model:", meta_label_style), Paragraph(html.escape(therapist_model), meta_val_style)],
        [Paragraph("Patient Model:", meta_label_style), Paragraph(html.escape(patient_model), meta_val_style)],
        [Paragraph("Condition / DSM-5:", meta_label_style), Paragraph(html.escape(condition), meta_val_style)],
        [Paragraph("Session ID:", meta_label_style), Paragraph(html.escape(session_id), meta_val_style)],
        [Paragraph("Date / Time:", meta_label_style), Paragraph(html.escape(timestamp), meta_val_style)],
        [Paragraph("Total Dialogue Turns:", meta_label_style), Paragraph(str(len(turns)), meta_val_style)],
    ]
    
    meta_table = Table(meta_data, colWidths=[130, 374])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#E2E8F0")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#F1F5F9")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    
    story.append(meta_table)
    story.append(Spacer(1, 20))

    # Dialogue Turns
    for idx, turn in enumerate(turns, 1):
        speaker = str(turn.get("speaker", "")).lower()
        raw_text = str(turn.get("text", "")).strip()
        escaped_text = html.escape(raw_text).replace("\n", "<br/>")

        if speaker == "therapist":
            header_text = f"THERAPIST (Turn {idx})"
            header_style = therapist_header
            bg_color = colors.HexColor("#F0F9FF") # Very light blue tint
            border_color = colors.HexColor("#BAE6FD")
        else:
            header_text = f"PATIENT (Turn {idx})"
            header_style = patient_header
            bg_color = colors.HexColor("#FFFBEB") # Very light amber tint
            border_color = colors.HexColor("#FDE68A")

        # Split text by line breaks so no single table cell is ever larger than a page
        turn_rows = [[Paragraph(header_text, header_style)]]
        for chunk in escaped_text.split("<br/>"):
            if chunk.strip():
                turn_rows.append([Paragraph(chunk, body_style)])
            else:
                turn_rows.append([Spacer(1, 4)])

        turn_table = Table(turn_rows, colWidths=[504])
        turn_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), bg_color),
            ('BOX', (0, 0), (-1, -1), 1, border_color),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ]))

        story.append(turn_table)
        story.append(Spacer(1, 10))

    doc.build(story, canvasmaker=NumberedCanvas)

def main():
    src_dir = os.path.join("logs", "transcripts")
    out_dir = os.path.join("logs", "transcripts_pdf")
    os.makedirs(out_dir, exist_ok=True)

    json_files = sorted(glob.glob(os.path.join(src_dir, "*.json")))
    print(f"Found {len(json_files)} transcript JSON files in {src_dir}.")

    count = 0
    for fp in json_files:
        base_name = os.path.splitext(os.path.basename(fp))[0]
        pdf_path = os.path.join(out_dir, f"{base_name}.pdf")
        try:
            create_transcript_pdf(fp, pdf_path)
            count += 1
            print(f"  [{count}/{len(json_files)}] Generated: {pdf_path}")
        except Exception as e:
            print(f"  ERROR generating PDF for {fp}: {e}")

    print(f"\nSuccessfully generated {count} PDFs in -> {out_dir}")

if __name__ == "__main__":
    main()
