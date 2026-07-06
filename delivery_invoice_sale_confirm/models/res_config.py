from odoo import models,fields

class ResCompany(models.Model):
    _inherit = "res.company"

    report_configuration_id = fields.Many2one('ir.actions.report', domain="[('model', '=', 'account.move')]")

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    report_configuration_id = fields.Many2one(
        'ir.actions.report',
        readonly=False, domain="[('model', '=', 'account.move')]",
        related='company_id.report_configuration_id',
    )