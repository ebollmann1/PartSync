# -*- coding: utf-8 -*-
{
    "name": "MMY Data Import",
    "summary": "import data from the excel file for mapping.",
    "description": "import data from the excel file for mapping",
    "author": "Aktiv Software",
    "website": "https://www.aktivsoftware.com",
    "version": "19.0.1.0.0",
    "depends": ["base", "queue_job"],
    "data": [
        # security files
        "security/ir.model.access.csv",
        # views files
        "views/mmy_data_import_views.xml",
    ],
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": True,
    "license": "OPL-1",
}
