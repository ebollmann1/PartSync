# -*- coding: utf-8 -*-

from odoo import fields, models


class CPMValidation(models.Model):
    _name = 'cpm.validation'
    _description = 'CPM Validation'

    name = fields.Char(string="Name")
    code = fields.Char(string="Code")


class ProductAttribute(models.Model):
    _inherit = 'res.company'

    cpm_validation_ids = fields.Many2many(
        comodel_name='cpm.validation',
        relation='company_cpm_validation_ref',
        string="CPM Validation")
