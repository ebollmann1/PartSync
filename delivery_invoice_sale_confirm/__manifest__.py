# -*- coding: utf-8 -*-
{
    'name': 'Create Delivery and Invoice From Sale Confirm',
    'version': '1.0',
    'summary': 'This module adds a button in the sale order form to confirm the entire sale process, including order, delivery, and invoice confirmation.',
    'description': '''
        This module adds a button in the sale order form to confirm the entire sale process, including order, delivery, and invoice confirmation.
    ''',
    'category': 'sale',
    'author': "MMYauto",
    'website': "www.mmybusiness.com",
    'depends': ['account','sale_stock','sale_management'],
    'data': [
        'views/res_config_view.xml'
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}