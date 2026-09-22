import os
import logging
from typing import Any
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

from models.company import CompanyIntelligenceReport, EnrichedField

logger = logging.getLogger("company_intelligence.exporters.docx_exporter")

# Harmonious Color Palette
COLOR_PRIMARY = RGBColor(31, 56, 92)       # Dark Slate Blue
COLOR_SECONDARY = RGBColor(74, 112, 139)   # Cool Grey Blue
COLOR_TEXT = RGBColor(51, 51, 51)          # Dark Charcoal
COLOR_LIGHT = "F0F4F8"                     # Very Light Tint (for table headers / boxes)
COLOR_BORDER = "CCCCCC"

class DocxExporter:
    @classmethod
    def export(cls, report: CompanyIntelligenceReport, output_dir: str):
        """
        Generates and saves the formatted company report.
        """
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, "company_report.docx")
        
        try:
            doc = Document()
            cls._setup_document_margins(doc)
            cls._write_report(doc, report)
            doc.save(file_path)
            logger.info(f"DOCX saved successfully: {file_path}")
        except Exception as e:
            logger.error(f"Failed to export DOCX report: {e}")

    @staticmethod
    def _setup_document_margins(doc: Document):
        """
        Standardizes margins for professional layout.
        """
        sections = doc.sections
        for section in sections:
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)

    @classmethod
    def _write_report(cls, doc: Document, report: CompanyIntelligenceReport):
        co = report.company
        
        # --- TITLE BLOCK ---
        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_run = title.add_run("Company Intelligence Report")
        title_run.font.name = "Arial"
        title_run.font.size = Pt(28)
        title_run.font.bold = True
        title_run.font.color.rgb = COLOR_PRIMARY
        title.paragraph_format.space_after = Pt(6)
        
        subtitle = doc.add_paragraph()
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub_text = co.name.value or report.metadata.domain
        subtitle_run = subtitle.add_run(f"Comprehensive Profile for {sub_text}")
        subtitle_run.font.name = "Arial"
        subtitle_run.font.size = Pt(14)
        subtitle_run.font.italic = True
        subtitle_run.font.color.rgb = COLOR_SECONDARY
        subtitle.paragraph_format.space_after = Pt(36)
        
        # --- 1. EXECUTIVE SUMMARY ---
        cls._add_heading(doc, "1. Executive Summary", level=1)
        desc = co.description.value or "No company description available."
        p = doc.add_paragraph()
        cls._add_text(p, desc)
        cls._add_source_footnote(doc, co.description)
        
        # --- 2. COMPANY OVERVIEW ---
        cls._add_heading(doc, "2. Company Overview", level=1)
        p = doc.add_paragraph()
        cls._add_text(p, f"The company, officially known as ")
        cls._add_text(p, f"{co.name.value or 'N/A'}", bold=True)
        if co.legal_name.value:
            cls._add_text(p, f" (Legal Name: {co.legal_name.value})")
            cls._add_source_footnote(doc, co.legal_name)
        cls._add_text(p, f", operates primarily in the ")
        cls._add_text(p, f"{co.industry.value or 'N/A'}", bold=True)
        cls._add_text(p, f" industry")
        if co.sub_industry.value:
            cls._add_text(p, f" (specifically focusing on {co.sub_industry.value})")
            cls._add_source_footnote(doc, co.sub_industry)
        cls._add_text(p, ". Founded in ")
        cls._add_text(p, f"{co.founded_year.value or 'N/A'}", bold=True)
        if co.founded_year.value:
            cls._add_source_footnote(doc, co.founded_year)
        cls._add_text(p, f", it is headquartered in ")
        cls._add_text(p, f"{co.headquarters.value or 'N/A'}", bold=True)
        if co.headquarters.value:
            cls._add_source_footnote(doc, co.headquarters)
        cls._add_text(p, ".")
        
        # --- 3. COMPANY DETAILS (TABLE) ---
        cls._add_heading(doc, "3. Company Details", level=1)
        
        details_data = [
            ("Company Name", co.name.value, cls._get_field_source_lbl(co.name)),
            ("Legal Name", co.legal_name.value, cls._get_field_source_lbl(co.legal_name)),
            ("Industry", co.industry.value, cls._get_field_source_lbl(co.industry)),
            ("Sub-Industry", co.sub_industry.value, cls._get_field_source_lbl(co.sub_industry)),
            ("Company Type", co.company_type.value, cls._get_field_source_lbl(co.company_type)),
            ("Founded Year", str(co.founded_year.value) if co.founded_year.value else None, cls._get_field_source_lbl(co.founded_year)),
            ("Headquarters", co.headquarters.value, cls._get_field_source_lbl(co.headquarters)),
            ("Employee Range", co.company_size.value, cls._get_field_source_lbl(co.company_size)),
            ("Revenue Est.", co.revenue.value, cls._get_field_source_lbl(co.revenue)),
            ("Parent Company", co.parent_company.value, cls._get_field_source_lbl(co.parent_company))
        ]
        
        cls._add_details_table(doc, details_data)

        # --- 4. PRODUCTS ---
        cls._add_heading(doc, "4. Products", level=1)
        if report.products:
            for prod in report.products:
                p = doc.add_paragraph(style="List Bullet")
                cls._add_text(p, f"{prod.name}", bold=True)
                if prod.description:
                    cls._add_text(p, f": {prod.description}")
                cls._add_text(p, f" (Source: {prod.source})", italic=True)
        else:
            doc.add_paragraph("No detailed product information discovered.")

        # --- 5. SERVICES ---
        cls._add_heading(doc, "5. Services", level=1)
        if report.services:
            for serv in report.services:
                p = doc.add_paragraph(style="List Bullet")
                cls._add_text(p, f"{serv.name}", bold=True)
                if serv.description:
                    cls._add_text(p, f": {serv.description}")
                cls._add_text(p, f" (Source: {serv.source})", italic=True)
        else:
            doc.add_paragraph("No detailed service offerings discovered.")

        # --- 6. SOLUTIONS ---
        cls._add_heading(doc, "6. Solutions", level=1)
        if report.solutions:
            for sol in report.solutions:
                p = doc.add_paragraph(style="List Bullet")
                cls._add_text(p, f"{sol.name}", bold=True)
                if sol.description:
                    cls._add_text(p, f": {sol.description}")
                cls._add_text(p, f" (Source: {sol.source})", italic=True)
        else:
            doc.add_paragraph("No tailored solution configurations discovered.")

        # --- 7. INDUSTRIES SERVED ---
        cls._add_heading(doc, "7. Industries Served", level=1)
        if report.industries_served:
            p = doc.add_paragraph()
            cls._add_text(p, ", ".join(report.industries_served))
        else:
            doc.add_paragraph("No explicit list of served industries detected.")

        # --- 8. TECHNOLOGIES ---
        cls._add_heading(doc, "8. Technologies", level=1)
        if report.technologies:
            p = doc.add_paragraph()
            cls._add_text(p, ", ".join(report.technologies))
        else:
            doc.add_paragraph("No specific technology stack identified in page contents.")

        # --- 9. CUSTOMERS ---
        cls._add_heading(doc, "9. Customers", level=1)
        if report.customers:
            for cust in report.customers:
                p = doc.add_paragraph(style="List Bullet")
                cls._add_text(p, f"{cust.name} (Source: {cust.source})")
        else:
            doc.add_paragraph("No publicly mentioned customer names extracted.")

        # --- 10. CASE STUDIES ---
        cls._add_heading(doc, "10. Case Studies", level=1)
        if report.case_studies:
            for cs in report.case_studies:
                p = doc.add_paragraph(style="List Bullet")
                cls._add_text(p, f"{cs.title}", bold=True)
                if cs.description:
                    cls._add_text(p, f": {cs.description}")
                if cs.url:
                    cls._add_text(p, f" (Link: {cs.url})")
        else:
            doc.add_paragraph("No success stories or case studies identified.")

        # --- 11. LEADERSHIP ---
        cls._add_heading(doc, "11. Leadership", level=1)
        if report.leadership:
            # Create a simple table
            table = doc.add_table(rows=1, cols=3)
            table.autofit = True
            hdr_cells = table.rows[0].cells
            hdr_cells[0].text = 'Name'
            hdr_cells[1].text = 'Role'
            hdr_cells[2].text = 'Source'
            cls._style_table_header(table.rows[0])
            
            for person in report.leadership:
                row_cells = table.add_row().cells
                row_cells[0].text = person.name
                row_cells[1].text = person.role
                row_cells[2].text = person.source
        else:
            doc.add_paragraph("No executive or board members identified.")

        # --- 12. LOCATIONS ---
        cls._add_heading(doc, "12. Locations", level=1)
        locs = report.company.locations.value
        if locs:
            for l in locs:
                doc.add_paragraph(l, style="List Bullet")
        else:
            doc.add_paragraph(co.headquarters.value or "No office locations listed.")

        # --- 13. CONTACT INFORMATION ---
        cls._add_heading(doc, "13. Contact Information", level=1)
        contacts = report.contact_information
        has_contact = False
        
        if contacts.emails:
            p = doc.add_paragraph()
            cls._add_text(p, "Emails: ", bold=True)
            cls._add_text(p, ", ".join(contacts.emails))
            has_contact = True
            
        if contacts.phones:
            p = doc.add_paragraph()
            cls._add_text(p, "Phones: ", bold=True)
            cls._add_text(p, ", ".join(contacts.phones))
            has_contact = True
            
        if contacts.addresses:
            p = doc.add_paragraph()
            cls._add_text(p, "Addresses: ", bold=True)
            cls._add_text(p, " | ".join(contacts.addresses))
            has_contact = True
            
        if not has_contact:
            doc.add_paragraph("No official contact points extracted.")

        # --- 14. SOCIAL MEDIA ---
        cls._add_heading(doc, "14. Social Media", level=1)
        if report.social_media:
            for platform, url in report.social_media.items():
                p = doc.add_paragraph()
                cls._add_text(p, f"{platform}: ", bold=True)
                cls._add_text(p, url)
        else:
            doc.add_paragraph("No active social profiles discovered.")

        # --- 15. PARTNERS ---
        cls._add_heading(doc, "15. Partners", level=1)
        if report.partners:
            for part in report.partners:
                p = doc.add_paragraph(style="List Bullet")
                cls._add_text(p, f"{part.name}")
                if part.type:
                    cls._add_text(p, f" ({part.type})")
                cls._add_text(p, f" (Source: {part.source})", italic=True)
        else:
            doc.add_paragraph("No certifications or partner relations detected.")

        # --- 16. COMPETITORS ---
        cls._add_heading(doc, "16. Competitors", level=1)
        if report.competitors:
            table = doc.add_table(rows=1, cols=3)
            table.autofit = True
            hdr_cells = table.rows[0].cells
            hdr_cells[0].text = 'Competitor'
            hdr_cells[1].text = 'Why Classified'
            hdr_cells[2].text = 'Source'
            cls._style_table_header(table.rows[0])
            
            for comp in report.competitors:
                row_cells = table.add_row().cells
                row_cells[0].text = comp.name
                row_cells[1].text = comp.reason or "Industry segment overlap"
                row_cells[2].text = comp.source
        else:
            doc.add_paragraph("No direct competitors detected in official domain content.")

        # --- 17. NEWS & EVENTS ---
        cls._add_heading(doc, "17. News & Events", level=1)
        has_news_events = False
        if report.news:
            has_news_events = True
            doc.add_paragraph("Recent News:", style="Heading 2")
            for item in report.news:
                p = doc.add_paragraph(style="List Bullet")
                cls._add_text(p, f"{item.title}")
                if item.date:
                    cls._add_text(p, f" ({item.date})")
                    
        if report.events:
            has_news_events = True
            doc.add_paragraph("Upcoming Events:", style="Heading 2")
            for item in report.events:
                p = doc.add_paragraph(style="List Bullet")
                cls._add_text(p, f"{item.title}")
                if item.date:
                    cls._add_text(p, f" ({item.date})")
                    
        if not has_news_events:
            doc.add_paragraph("No blog postings or press releases crawled.")

        # --- 18. CERTIFICATIONS & AWARDS ---
        cls._add_heading(doc, "18. Certifications & Awards", level=1)
        has_certs_awards = False
        if report.certifications:
            has_certs_awards = True
            for c in report.certifications:
                p = doc.add_paragraph(style="List Bullet")
                cls._add_text(p, f"Certification: {c.name}")
                
        if report.awards:
            has_certs_awards = True
            for a in report.awards:
                p = doc.add_paragraph(style="List Bullet")
                cls._add_text(p, f"Award: {a.name}")
                if a.year:
                    cls._add_text(p, f" ({a.year})")
                    
        if not has_certs_awards:
            doc.add_paragraph("No official certifications or industry awards listed.")

        # --- 19. ICP QUALIFICATION ---
        cls._add_heading(doc, "19. ICP Qualification", level=1)
        if report.icp:
            icp = report.icp
            p = doc.add_paragraph()
            cls._add_text(p, "ICP Match Status: ", bold=True)
            status_run = p.add_run("MATCHED" if icp.get("icp_match") else "DOES NOT MATCH")
            status_run.bold = True
            status_run.font.color.rgb = RGBColor(34, 139, 34) if icp.get("icp_match") else RGBColor(178, 34, 34)
            
            p = doc.add_paragraph()
            cls._add_text(p, f"ICP Score: {icp.get('score', 0)}/100\n", bold=True)
            
            doc.add_paragraph("ICP Match Reasoning:", style="Heading 2")
            for reason in icp.get("reasoning", []):
                doc.add_paragraph(reason, style="List Bullet")
        else:
            doc.add_paragraph("ICP evaluation criteria were not provided.")

        # --- 20. DATA SOURCES ---
        cls._add_heading(doc, "20. Data Sources", level=1)
        doc.add_paragraph("The company profile was built by aggregating the following data sources:")
        
        # List internal URLs crawled
        doc.add_paragraph("Internal Website Pages:", style="Heading 2")
        for pg in report.pages[:10]: # Max 10 for readability
            p = doc.add_paragraph(style="List Bullet")
            cls._add_text(p, f"{pg.url} (Type: {pg.page_type})")
            
        if len(report.pages) > 10:
            doc.add_paragraph(f"... and {len(report.pages) - 10} additional internal pages.", style="Normal")

        if report.external_sources:
            doc.add_paragraph("External Public Sources:", style="Heading 2")
            seen_ext = set()
            for src in report.external_sources:
                if src.url not in seen_ext:
                    seen_ext.add(src.url)
                    p = doc.add_paragraph(style="List Bullet")
                    cls._add_text(p, f"{src.url}")
                    if src.title:
                        cls._add_text(p, f" - {src.title}")

        # --- 21. CRAWL STATISTICS ---
        cls._add_heading(doc, "21. Crawl Statistics", level=1)
        stat_p = doc.add_paragraph()
        cls._add_text(stat_p, f"Crawl Starting URL: {report.metadata.input_url}\n")
        cls._add_text(stat_p, f"Target Domain: {report.metadata.domain}\n")
        cls._add_text(stat_p, f"Crawl Started: {report.metadata.crawl_started}\n")
        cls._add_text(stat_p, f"Crawl Completed: {report.metadata.crawl_completed}\n")
        cls._add_text(stat_p, f"Pages Discovered: {report.metadata.pages_discovered}\n")
        cls._add_text(stat_p, f"Pages Crawled: {report.metadata.pages_crawled}\n")
        cls._add_text(stat_p, f"Pages Failed: {report.metadata.pages_failed}\n")

        # --- 22. DATA QUALITY / CONFIDENCE ---
        cls._add_heading(doc, "22. Data Quality / Confidence", level=1)
        if report.confidence_summary:
            table = doc.add_table(rows=1, cols=2)
            table.autofit = True
            hdr_cells = table.rows[0].cells
            hdr_cells[0].text = 'Data Section'
            hdr_cells[1].text = 'Confidence Score (0-1.0)'
            cls._style_table_header(table.rows[0])
            
            for key, val in report.confidence_summary.items():
                row_cells = table.add_row().cells
                row_cells[0].text = key.replace("_", " ").title()
                row_cells[1].text = f"{val:.2f}"
        else:
            doc.add_paragraph("Confidence calculations were not performed.")

    # --- FORMATTING HELPERS ---
    @staticmethod
    def _add_heading(doc: Document, text: str, level: int = 1):
        """
        Adds a styled heading with the primary/secondary colors.
        """
        h = doc.add_paragraph()
        h.paragraph_format.keep_with_next = True
        h_run = h.add_run(text)
        h_run.font.name = "Arial"
        
        if level == 1:
            h_run.font.size = Pt(18)
            h_run.font.bold = True
            h_run.font.color.rgb = COLOR_PRIMARY
            h.paragraph_format.space_before = Pt(24)
            h.paragraph_format.space_after = Pt(12)
            # Add bottom border XML style for Heading 1
            pPr = h._p.get_or_add_pPr()
            pBdr = parse_xml(r'<w:pBdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                             r'<w:bottom w:val="single" w:sz="6" w:space="4" w:color="1F385C"/>'
                             r'</w:pBdr>')
            pPr.append(pBdr)
        elif level == 2:
            h_run.font.size = Pt(14)
            h_run.font.bold = True
            h_run.font.color.rgb = COLOR_SECONDARY
            h.paragraph_format.space_before = Pt(16)
            h.paragraph_format.space_after = Pt(6)

    @staticmethod
    def _add_text(p: Any, text: str, bold: bool = False, italic: bool = False):
        """
        Adds formatted text run.
        """
        r = p.add_run(text)
        r.font.name = "Arial"
        r.font.size = Pt(10.5)
        r.font.bold = bold
        r.font.italic = italic
        r.font.color.rgb = COLOR_TEXT

    @staticmethod
    def _get_field_source_lbl(field: EnrichedField) -> str:
        if not field or field.value is None:
            return "N/A"
        lbl = field.source_type or "unknown"
        if field.status == "conflicting_sources":
            lbl += " (conflict)"
        return lbl

    @staticmethod
    def _add_source_footnote(doc: Document, field: EnrichedField):
        """
        Adds an inline source attribution string if source exists.
        """
        if field and field.value is not None and field.source:
            p = doc.paragraphs[-1]
            p.add_run(f" [{field.source}]").font.size = Pt(8.5)

    @staticmethod
    def _style_table_header(row: Any):
        """
        Styles the first row of a table as a header.
        """
        trPr = row._tr.get_or_add_trPr()
        trPr.append(parse_xml(r'<w:tblHeader xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'))
        for cell in row.cells:
            # Set background color
            tcPr = cell._tc.get_or_add_tcPr()
            shd = parse_xml(f'<w:shd xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:fill="{COLOR_LIGHT}"/>')
            tcPr.append(shd)
            
            # Format text inside
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.name = "Arial"
                    r.font.bold = True
                    r.font.size = Pt(9.5)
                    r.font.color.rgb = COLOR_PRIMARY

    @classmethod
    def _add_details_table(cls, doc: Document, data: list):
        """
        Generates a clean two-column grid.
        """
        table = doc.add_table(rows=1, cols=3)
        table.autofit = True
        
        # Headers
        hdr = table.rows[0].cells
        hdr[0].text = "Attribute"
        hdr[1].text = "Value"
        hdr[2].text = "Source Type"
        cls._style_table_header(table.rows[0])
        
        # Populate
        for key, val, src in data:
            if val is not None and val != "[]" and val != "":
                row = table.add_row().cells
                row[0].text = key
                row[1].text = str(val)
                row[2].text = src
                
                # Alternate row shading could be implemented here, but simple borders are clean.
        
        # Add thin borders XML
        tblPr = table._tbl.tblPr
        borders = parse_xml(
            f'<w:tblBorders xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:top w:val="single" w:sz="4" w:space="0" w:color="{COLOR_BORDER}"/>'
            f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="{COLOR_BORDER}"/>'
            f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{COLOR_BORDER}"/>'
            f'<w:left w:val="none"/>'
            f'<w:right w:val="none"/>'
            f'<w:insideV w:val="none"/>'
            f'</w:tblBorders>'
        )
        tblPr.append(borders)
        
        doc.add_paragraph().paragraph_format.space_after = Pt(12)
