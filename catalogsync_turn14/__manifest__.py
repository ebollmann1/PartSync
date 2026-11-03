# -*- coding: utf-8 -*-
{
    "name": "CatalogSync - Turn 14",
    "summary": "Native Odoo 19 Turn 14 API catalog and inventory synchronization",
    "version": "19.0.4.0.0",
    "category": "Inventory/Inventory",
    "icon": "/catalogsync_turn14/static/description/icon.png",
    "author": "Briem Automotive / Antigravity",
    "license": "LGPL-3",
    "depends": [
        "purchase_stock",
        "website_sale",
        "mmy_ir_segment",
        "project_cars_enhancement",
        "queue_job",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
    "data": [
        "data/queue.xml",
        "data/cron.xml",
        "views/res_config_settings_views.xml",
        "views/res_company_views.xml",
        "views/stock_location_views.xml",
        "views/product_views.xml",
        "views/product_attribute_views.xml",
        "views/menu.xml",
    ],
    "application": False,
    "installable": True,
}
