from odoo import fields, models, api, _


class MessageConfirmWizard(models.TransientModel):
    _name = 'message.confirm.wizard'
    _description = "Message confirm Wizard"

    name = fields.Char('Message Name', readonly=True)
    text = fields.Text('Message', readonly=True)
    wizard_id = fields.Many2one('ebiz.download.payments', readonly=True)
    is_sale = fields.Boolean(string='Sales Order')


    def action_confirm(self):
        self.wizard_id.regenerate_line_ids()

    def action_apply_pay(self):
        if self.env.context.get('line_ids') and self.env.context.get('line_model') and self.env.context.get('need_payment_on_account_ids'):
            need_payment_on_account_ids = self.env[self.env.context.get('line_model')].browse(self.env.context.get('need_payment_on_account_ids'))
            need_payment_on_account_ids.is_payment_on_account = True
            line_ids = self.env[self.env.context.get('line_model')].browse(self.env.context.get('line_ids'))
            line_ids.mark_as_applied()
        else:
            self.wizard_id.regenerate_line_ids()