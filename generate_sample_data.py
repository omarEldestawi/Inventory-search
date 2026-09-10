# -*- coding: utf-8 -*-
"""
Helper script to generate realistic Arabic sample PDF catalogs and purchase orders for testing.
"""
import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import openpyxl
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import pandas as pd

def create_sample_pdf(filepath: str, title: str, items_data: list):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    doc = SimpleDocTemplate(filepath, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=14,
        alignment=1,
        spaceAfter=15
    )
    elements.append(Paragraph(title, title_style))
    
    # Table headers and rows
    table_data = [["كود الصنف", "اسم الصنف والتركيز", "السعر الرسمي", "نسبة الخصم", "حالة الصنف"]]
    for item in items_data:
        table_data.append([item[0], item[1], str(item[2]), f"{item[3]}%", item[4]])
        
    t = Table(table_data, colWidths=[60, 220, 70, 70, 80])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')])
    ]))
    elements.append(t)
    doc.build(elements)

def generate_samples():
    print("[+] Generating sample test Arabic PDF catalogs...")
    
    # Warehouse 1: ابن سينا (Ibn Sina)
    ibn_sina_items = [
        ("101", "Panadol Extra 24 Tab", 45.0, 22.0, "متوفر"),
        ("102", "Augmentin 1gm 14 Tab", 120.0, 25.0, "متوفر"),
        ("103", "Cataflam 50mg 20 Tab", 55.0, 20.0, "متوفر"),
        ("104", "Concor 5mg 30 Tab", 80.0, 18.0, "متوفر"),
        ("105", "Brufen 400mg 30 Tab", 60.0, 15.0, "متوفر"),
        ("106", "Nexium 40mg 28 Tab", 280.0, 26.0, "متوفر"),
        ("107", "Antinal 24 Cap", 35.0, 24.0, "متوفر"),
    ]
    
    # Warehouse 2: الشركة المتحدة (United)
    united_items = [
        ("201", "Panadol Extra 24 Tab", 45.0, 25.5, "متوفر"), # Higher discount
        ("202", "Augmentin 1gm 14 Tab", 120.0, 23.0, "متوفر"),
        ("203", "Cataflam 50mg 20 Tab", 55.0, 24.0, "متوفر"), # Higher discount
        ("204", "Concor 5mg 30 Tab", 80.0, 21.0, "متوفر"),   # Higher discount
        ("205", "Brufen 400mg 30 Tab", 60.0, 15.0, "متوفر"), # Tie with Ibn Sina
        ("208", "Voltaren 100mg 10 Supp", 40.0, 20.0, "متوفر"),
        ("209", "Flagyl 500mg 20 Tab", 30.0, 25.0, "متوفر"),
    ]

    # Warehouse 3: فارما أوفرسيز (Pharma Overseas)
    pharma_items = [
        ("301", "Panadol Extra 24 Tab", 45.0, 20.0, "متوفر"),
        ("302", "Augmentin 1gm 14 Tab", 120.0, 28.0, "متوفر"), # Winning discount
        ("305", "Brufen 400mg 30 Tab", 60.0, 19.0, "متوفر"),   # Winning discount
        ("306", "Nexium 40mg 28 Tab", 280.0, 28.5, "متوفر"),  # Winning discount
        ("310", "Congestal 20 Tab", 35.0, 22.0, "متوفر"),
    ]

    create_sample_pdf("input/catalogs/مخزن_ابن_سينا.pdf", "Ibn Sina Pharma Catalog", ibn_sina_items)
    create_sample_pdf("input/catalogs/الشركة_المتحدة.pdf", "United Company Catalog", united_items)
    create_sample_pdf("input/catalogs/فارما_اوفرسيز.pdf", "Pharma Overseas Catalog", pharma_items)

    print("[+] Generating sample purchase order Excel...")
    order_items = [
        {"اسم الصنف": "Panadol Extra 24 Tab", "الكمية المطلوبة": 10},
        {"اسم الصنف": "Augmentin 1gm 14 Tab", "الكمية المطلوبة": 5},
        {"اسم الصنف": "Cataflam 50mg 20 Tab", "الكمية المطلوبة": 15},
        {"اسم الصنف": "Concor 5mg 30 Tab", "الكمية المطلوبة": 8},
        {"اسم الصنف": "Brufen 400mg 30 Tab", "الكمية المطلوبة": 20},
        {"اسم الصنف": "Nexium 40mg 28 Tab", "الكمية المطلوبة": 4},
        {"اسم الصنف": "Flagyl 500mg 20 Tab", "الكمية المطلوبة": 12},
        {"اسم الصنف": "Amaryl 2mg 30 Tab", "الكمية المطلوبة": 6},  # Out of stock item to test review sheet
    ]

    os.makedirs("input/orders", exist_ok=True)
    df_order = pd.DataFrame(order_items)
    df_order.to_excel("input/orders/طلبية_اليوم.xlsx", index=False)
    print("[✓] Sample files generated successfully!")

if __name__ == "__main__":
    generate_samples()
