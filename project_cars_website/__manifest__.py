# -*- coding: utf-8 -*-

{
    'name': "Project Cars Website",
    'summary': """
        Project Cars Website.""",
    'description': """
        Project Cars Website.
    """,
    'author': "MP Technolabs",
    'website': "https://www.mptechnolabs.com/",
    'category': 'Website ',
    'version': '19.0.1.0',
    'license': 'LGPL-3',
    'depends': [
        'website','website_sale', 'website_sale_wishlist', 'website_sale_comparison', 'project_cars_enhancement', 'mmy_config'
    ],
    'data': [
        'views/template.xml',
        'views/website_view.xml',
        'wizard/import_customer_product_master_view.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'project_cars_website/static/src/js/jquery.tablesort.js',
            'project_cars_website/static/src/js/tableManager.js',
            ('after', 'website_sale/static/src/interactions/website_sale.js','project_cars_website/static/src/js/VariantMixin.js'),
            'project_cars_website/static/src/css/category_style.css',
            'project_cars_website/static/src/xml/custom_filter_item.xml',
            'project_cars_website/static/src/js/product_fitment_sort.js',
            'project_cars_website/static/src/js/request_info.js',
        ],
        # 'web.assets_backend': [
        #     'project_cars_website/static/src/js/edit_website.js'
        # ],
    },
    'demo': [],
}
