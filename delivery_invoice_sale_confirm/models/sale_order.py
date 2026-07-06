from odoo import models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        if 'validate_invoice_delivery' in self.env.context:
            all_invoices = self.env['account.move']
            for order in self:
                for picking in order.picking_ids.filtered(lambda p: p.state not in ["done", "cancel"]):
                    picking.action_confirm()
                    for move in picking.move_ids:
                        move.quantity = move.product_uom_qty
                    picking.with_context(skip_sms=True).button_validate()

                invoices = order._create_invoices()
                invoices.action_post()
                all_invoices |= invoices

            if self.env.company.report_configuration_id:
                return self.env.company.report_configuration_id.report_action(all_invoices)
            else:
                return self.env.ref("account.account_invoices").report_action(all_invoices)
        else:
            return res