# -*- coding: utf-8 -*-
{
    'name': 'Update Product Attribute',
    'version': '1.0.0',
    'category': 'product',
    'summary': 'Update Product Attribute',
    'description': """
        Update Product Attribute
    """,
    'depends': ['product', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/update_product_attribute_view.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}