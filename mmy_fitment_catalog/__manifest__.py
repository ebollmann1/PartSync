# -*- coding: utf-8 -*-
{
    'name': "MMY Fitment Catalog",
    'summary': "Make/Model/Year fitment filters for Product Catalog",
    'version': '19.0.1.0.0',
    'author': "MP Technolabs",
    'website': "https://www.mptechnolabs.com/",
    'license': 'LGPL-3',
    'category': 'Sales/Catalog',
    'depends': [
        'sale_management',
        'project_cars_enhancement',
    ],
    'data': [
        'views/product_catalog_search_view.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mmy_fitment_catalog/static/src/js/search_panel.js',
            'mmy_fitment_catalog/static/src/scss/search_panel.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
