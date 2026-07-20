{
    'name': 'Website Product Document Preview',
    'version': '1.0',
    'category': 'Website/Website',
    'summary': 'Preview product documents in a modal popup',
    'description': """
        This module changes the behavior of product documents on the website.
        When clicked, documents will open in a modal popup for preview instead of downloading.
    """,
    'author': "MMYauto",
    'website': "www.mmybusiness.com",
    'depends': ['website_sale'],
    'data': [
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'mmy_website_product_document_preview/static/src/js/document_preview.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
