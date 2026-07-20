# Part of Odoo, Aktiv Software.
# See LICENSE file for full copyright & licensing details.

# Author: Aktiv Software.
# mail:   odoo@aktivsoftware.com
# Copyright (C) 2015-Present Aktiv Software PVT. LTD.
# Contributions:
#           Aktiv Software:
#              - Kuldip Trapasiya
#              - Tanvi Gajera

{
    "name": "Tree View Advanced Search / Direct Filter in List",
    "version": "0.1",
    "category": "Advanced search on Tree view",
    "summary": """This module allows a user to directly filter on the Tree / List View.
    The data will be filtered Runtime.
    List Filter ,
    Filter List,
    Column Filter,
    Tree Filter,
    Filter Tree,
    Advance Search,
    Search Advance,
    Tree Search,
    Direct Search,
    Fast Search,
    Quick Search,
    Dynamic Search,
    Dynamic Tree,
    Data Search,
    Search Data,
    Data search in Tree,
    X2many search,
    X2many search in Tree
    """,
    "description": """
        This module allows a user to directly single/multiple filter on the Tree / List View.
    The data will be filtered Runtime. Columns can be directly searched on the Tree View.
    List Filter
    Column Filter
    Tree Filter
    Advance Search
    Tree Search
    Direct Search
    Fast Search
    Quick Search
    Dynamic Search
    Dynamic Tree
    Data Search
    Data search in Tree
    X2many search
    X2many search in Tree
    """,
    "author": "Aktiv Software",
    "website": "http://www.aktivsoftware.com",
    "license": "OPL-1",
    "price": 95.00,
    "currency": "USD",
    "depends": ["web", "sale_management"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            # Custum Library
            "tree_view_advanced_filter/static/src/js/*.js",
            "tree_view_advanced_filter/static/src/css/main.scss",
        ]
    },
    "images": ["static/description/banner.jpg"],
    "installable": True,
    "auto_install": False,
    "application": False,
}
