# -*- coding: utf-8 -*-
{
    'name': 'Import Viking Attribute',
    'version': '1.0.0',
    'category': 'Product',
    'summary': '',
    'description': """ """,
    'author': 'MP Technolabs',
    'website': 'https://www.mptechnolabs.com',
    'depends': ['product', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/import_viking_product_view.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}