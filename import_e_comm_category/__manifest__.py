# -*- coding: utf-8 -*-
{
    'name': 'Import E-Commerce Categories',
    'version': '1.0.0',
    'category': 'Website/Website',
    'summary': 'Import multi-level eCommerce categories via XLSX file',
    'description': """
Import E-Commerce Categories
============================
This module allows importing unlimited-level category hierarchy from XLSX file.
Supports:
 - Category → Subcategory → Child hierarchy
 - Batch processing
 - Logging
    """,
    'author': 'MP Technolabs',
    'website': 'https://www.mptechnolabs.com',
    'depends': ['project_cars_enhancement'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/import_ecom_category_view.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}