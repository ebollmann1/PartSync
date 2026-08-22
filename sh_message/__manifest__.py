# -*- coding: utf-8 -*-
# Part of Softhealer Technologies.
{
    "name": "Popup Message",
    "author": "Softhealer Technologies",
    "website": "https://www.softhealer.com",
    "support": "support@softhealer.com",
    "category": "Extra Tools",
    "license": "OPL-1",
    "summary":
        """create Success message create warnings message create alert message
    box wizard success popup message alert popup email popup module odoo
    custom popup message custom pop up message""",
    "description":
        """This module is useful to create a custom popup message Wasting
    your important time to make popup message wizard-like Alert, Success,
    Warnings? We will help you to make this procedure quick, just add a
    few lines of code in your project to open the popup message
    wizard.""",
    "version": "0.0.1",
    "depends": ["base", "web"],
    "application": True,
    "data": [
        "security/ir.model.access.csv",
        "wizard/sh_message_wizard.xml",
    ],
    "images": ["static/description/background.jpg", ],
    "auto_install": False,
    "installable": True,
    "price": 0.010,
    "currency": "EUR"
}
