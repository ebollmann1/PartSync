# -*- coding: utf-8 -*-

{
    'name': "Project Cars Enhancement",
    'summary': """
        Project Cars Enhancement.""",
    'description': """
        Project Cars Enhancement.
    """,
    'author': "MP Technolabs",
    'website': "https://www.mptechnolabs.com/",
    'category': 'product ',
    'version': '19.0.1.0',
    'license': 'LGPL-3',
    'depends': [
        'web', 'sale_management', 'product', 'mrp', 'project', 'mmy_config'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_attribute_view.xml',
        'views/fitment_view.xml',
        'views/company_view.xml',
        'wizard/import_customer_product_master_view.xml',
        'wizard/import_fitment_view.xml',
        'views/vehicle_info_view.xml',
        'wizard/import_year_view.xml',
        'wizard/check_product_fitment_view.xml',
        'views/sale_order_view.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'project_cars_enhancement/static/src/scss/button_style_change.scss',
        ],
        'web.assets_backend': [
            'project_cars_enhancement/static/src/scss/button_style_change.scss',
        ],
    },
    'demo': [],
}
