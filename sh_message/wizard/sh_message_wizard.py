# -*- coding: utf-8 -*-
# Part of Softhealer Technologies.
"""Module for message wizard."""
from odoo import fields, models


class ShMessageWizard(models.TransientModel):
    """ Message wizard to display warnings, alert ,success messages """
    _name = "sh.message.wizard"

    def get_default(self):
        """Get default message from context."""
        if self.env.context.get("message", False):
            return self.env.context.get("message")
        return False

    name = fields.Text(string="Message", readonly=True, default=get_default)
