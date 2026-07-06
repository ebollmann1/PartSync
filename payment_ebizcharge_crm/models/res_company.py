from odoo import fields, models


class ResCompanyInh(models.Model):
    _inherit = 'res.company'

    is_selected = fields.Boolean()


class EBizContactUs(models.Model):
    _name = 'contact.us'
    _description = "Contact Us"
