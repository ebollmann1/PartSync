# -*- coding: utf-8 -*-
# Part of Softhealer Technologies.
{
    "name": "Import Bill of Materials from CSV/Excel file",
    "author": "Softhealer Technologies",
    "website": "https://www.softhealer.com",
    "support": "support@softhealer.com",
    "category": "Manufacturing",
    "summary": "import bill of materials from csv import bill of materials from excel import BOM from xls bill of materials from xlsx import bills Import multiple BOM import BOM import bills of materials import mrp import manufacturing Import multiple BOM Odoo",
    "description": """This module useful to import Bill of Materials from csv/excel. """,
    "version": "0.0.1",
    "depends": [
        "sh_message",
        "mrp"
    ],
    "application": True,
    "data": [
        "security/import_bom_security.xml",
        "security/ir.model.access.csv",
        "wizard/import_bom_wizard.xml",
        "views/mrp_view.xml",

    ],
    "external_dependencies": {
        "python": ["xlrd"],
    },
    "images": ["static/description/background.png", ],
    "auto_install": False,
    "license": "OPL-1",
    "installable": True,
    "price": 18,
    "currency": "EUR"
}
