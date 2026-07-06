# -*- coding: utf-8 -*-

{
    'name': "Portal Vehicle Information",
    'summary': """
        Portal Vehicle Information.""",
    'description': """
        Portal Vehicle Information.
    """,
    'author': "MP Technolabs",
    'website': "https://www.mptechnolabs.com/",
    'category': 'website ',
    'version': '19.0.1.0',
    'license': 'LGPL-3',
    'depends': ['project_cars_enhancement', 'project_cars_website', 'mmy_config'],
    'data': [
        'views/portal_templates.xml',
    ],
    'demo': [],
    'assets': {
        'web.assets_frontend': [
    #         'portal_vehicle_info/static/src/js/vehicle_portal.js',
            'portal_vehicle_info/static/src/js/vehicle_info_save.js',
        ],
    },
}
