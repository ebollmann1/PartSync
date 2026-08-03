# -*- coding: utf-8 -*-
{
    'name': "EBizCharge Website Payment",
    'author': "EBizCharge by Century Business Solutions",
    'website': "https://ebizcharge.com",
    'summary': "Payment Provider: EBizCharge Implementation",
    'category': 'Website/Payment',
    'description': """EBizCharge Payment Gateway""",
    'version': '1.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'website_sale', 'payment_ebizcharge_crm'],

    # always loaded
    'data': [
        'views/ebizcharge_instance_config_view.xml',
        'views/payment_ebizcharge_templates.xml',
        'views/ebiz_payment_portal_templates.xml',
        'views/transaction_portal_template.xml',
    ],
    'images': [
        'static/description/banner.png',
    ],
    'price': 0,
    'currency': 'USD',
    'external_dependencies': {'python': ['zeep']},
    'assets': {
        'web.assets_frontend': [
            'payment_ebizcharge_portal/static/src/interactions/payment_form.js',
            'payment_ebizcharge_portal/static/src/js/ebiz_manage_form.js',
            'payment_ebizcharge_portal/static/src/js/confirm_account_number.js',
            'payment_ebizcharge_portal/static/lib/jquery.payment/jquery.payment.js',
            'payment_ebizcharge_portal/static/src/js/payment_portal.js',
            'payment_ebizcharge_portal/static/src/scss/portal_payment.scss',
        ],
        'web.assets_backend': [
            'payment_ebizcharge_portal/static/src/scss/backend.scss',
        ],
    },
    'license': 'LGPL-3',

}

