# -*- coding: utf-8 -*-

from odoo import fields, models


class ProductPublicCategory(models.Model):
    _inherit = 'product.public.category'
    
    position = fields.Integer(string="Position")
    partterminology = fields.Integer(string="PartTerminology")
    subcategory = fields.Integer(string="Subcategory")
    category = fields.Integer(string="Category")
    code_master = fields.Integer(string="CodeMasterID")
