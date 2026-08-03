from odoo import fields, models, api, _
from ..models.ebiz_charge import message_wizard


class WizardTransactionValidation(models.TransientModel):
    _name = 'wizard.ebiz.transaction.validation'
    _description = "Wizard EBiz Transaction Validation"

    transaction_id = fields.Many2one('payment.transaction')
    wizard_process_id = fields.Many2one('wizard.order.process.transaction')
    transaction_result = fields.Html('Html field')
    address = fields.Char('Address', default="Match")
    zip_code = fields.Char('Zip/Postal Code', default="Match")
    card_code = fields.Char('CVV2/CVC', default="Match")
    check_avs_match = fields.Boolean()
    is_card_denied = fields.Boolean("Is Card Denied")
    denied_message = fields.Char("Denied Message")
    payment_id = fields.Many2one("account.payment")
    full_amount_avs = fields.Boolean("Full Amount AVS")    

    def void_transaction(self):
        if self.payment_id and self.payment_id.move_id:
            receipts_exists = self.env['account.move.receipts'].search([])
            if receipts_exists:
                if int(self.env['account.move.receipts'].search([])[-1].invoice_id) in self.env['account.move'].search([('name', '=', self.payment_id.payment_reference)]).ids:
                    receipts_exists[-1].unlink()
            if self.transaction_id:
                if 'payment_data' in self.env.context:
                    if not self.env.context['payment_data']['card_save'] or not self.env.context['payment_data']['ach_save']:
                        self.transaction_id.token_id.delete_payment_method()
                        self.transaction_id.partner_id.refresh_payment_methods()
                return self.transaction_id.sudo()._send_void_request()

        if self.payment_id:
            if self.env.context.get('my_full_amount'):
                token_id = self.payment_id.create_credit_card_payment_method().id
                self.payment_id.payment_token_id = token_id
            if 'payment_data' in self.env.context:
                if not self.env.context['payment_data']['card_save'] or not self.env.context['payment_data']['ach_save']:
                    if 'customer_token_to_dell' in self.env.context and 'payment_method_id_to_dell' in self.env.context:
                        token_to_delete = self.env['payment.token'].search([('ebizcharge_profile', '=', self.env.context.get('payment_method_id_to_dell')),('partner_id', '=', self.payment_id.partner_id.id)])
                        if token_to_delete:
                            token_to_delete.delete_payment_method()
                            token_to_delete.partner_id.refresh_payment_methods()
            return self.payment_id.sudo().action_cancel()
        return True

    def _build_success_context(self):
        payment_txn = self.payment_id.payment_transaction_id
        invoice_ids = self.payment_id.invoice_ids
        token_id = payment_txn.token_id
        register = self.env['account.payment.register'].browse(self.env.context['active_id'])
        eligible = payment_txn.is_pay_method_eligible and payment_txn.is_zip_code_allowed
        context = {
            'message': 'Transaction has been successfully processed!',
            'default_is_ach': register.token_type != 'credit',
            'default_currency_id': self.env.company.currency_id.id,
            'default_partner_id': token_id.partner_id.name if token_id else self.payment_id.partner_id.name,
            'default_transaction_type': 'Auth Only' if payment_txn.transaction_type == 'pre_auth' else 'Sale',
            'default_surcharge_percent': f"{payment_txn.surcharge_percent:.2f} %",
            'default_document_number': invoice_ids.name if len(invoice_ids) == 1 else payment_txn.reference,
            'default_reference_number': payment_txn.provider_reference,
            'default_auth_code': payment_txn.ebiz_auth_code,
            'default_payment_method': token_id.get_encrypted_name() if token_id else self.payment_id.partner_id.name,
            'default_date_paid': payment_txn.last_state_change,
            'default_subtotal': payment_txn.amount,
            'default_avs_street': self.payment_id.ebiz_avs_street,
            'default_avs_zip_code': self.payment_id.ebiz_avs_zip,
            'default_cvv': payment_txn.ebiz_cvv_resp,
            'default_enable_surcharge': self.payment_id.enable_surcharge,
        }
        if self.payment_id.partner_id.ebiz_profile_id.is_surcharge_enabled and self.payment_id.enable_surcharge and any(
                inv.move_type == 'out_invoice' for inv in invoice_ids):
            context.update({
                'default_is_surcharge': True,
                'default_is_eligible': eligible,
                'default_surcharge_subtotal': self.payment_id.amount,
                'default_surcharge_amount': payment_txn.surcharge_amt,
                'default_surcharge_percentage': payment_txn.surcharge_percent,
                'default_surcharge_total': self.payment_id.amount + float(payment_txn.surcharge_amt),
            })
        else:
            context['default_surcharge_total'] = payment_txn.amount
        return context

    def proceed_with_transaction(self):
        if self.wizard_process_id.card_id:
            return True

        if 'active_id' in self.env.context and not self.env['account.payment.register'].browse(self.env.context['active_id']).card_id and not self.transaction_id:
            token_id = self.payment_id.create_credit_card_payment_method().id
            self.payment_id.write({'payment_token_id': token_id})

        if self.payment_id:
            if not self.transaction_id:
                if self.env.context.get('my_full_amount'):
                    self.payment_id.sudo().with_context({'active_model': 'account.move', 'active_id': self.env['account.payment.register'].browse(self.env.context['active_id']).line_ids[0].move_id.id,'avs_bypass': True, 'bypass_card_creation': True, 'payment_data': self.env.context['payment_data']}).action_post()
                elif self.env.context.get('ebiz_charge_profile'):
                    self.payment_id.sudo().with_context({'active_model': 'account.move', 'active_id': self.env['account.payment.register'].browse(self.env.context['active_id']).line_ids[0].move_id.id, 'avs_bypass': True, 'get_customer_profile': self.env.context.get('ebiz_charge_profile'), 'payment_data': self.env.context['payment_data']}).action_post()
                else:
                    self.payment_id.sudo().with_context({'active_model': 'account.move', 'active_id': self.env['account.payment.register'].browse(self.env.context['active_id']).line_ids[0].move_id.id,'avs_bypass': True, 'payment_data': self.env.context['payment_data']}).action_post()
                if not self.payment_id.is_reconciled and 'payment_data' in self.env.context:
                    if 'to_reconcile' in self.env.context['payment_data']:
                        self.payment_id.ebiz_reconcile_payment(source=self.env.context['payment_data'])
                for inv in self.payment_id.invoice_ids:
                    inv.sync_to_ebiz()
                return self.message_wizard(self._build_success_context())

            if self.payment_id.transaction_command == "Sale":
                self.payment_id.sudo().with_context({'avs_bypass': True, 'payment_data': self.env.context['payment_data']}).action_post()
                self.transaction_id.sudo()._set_done()
                for inv in self.payment_id.invoice_ids:
                    inv.sync_to_ebiz()
                if 'payment_data' in self.env.context:
                    if not self.env.context['payment_data']['card_save'] or not self.env.context['payment_data']['ach_save']:
                        if 'customer_token_to_dell' in self.env.context and 'payment_method_id_to_dell' in self.env.context:
                            token_to_delete = self.env['payment.token'].search([('ebizcharge_profile', '=', self.env.context.get('payment_method_id_to_dell')), ('partner_id', '=', self.payment_id.partner_id.id)])
                            if token_to_delete:
                                token_to_delete.delete_payment_method()
                                token_to_delete.partner_id.refresh_payment_methods()
                return self.message_wizard(self._build_success_context())

        else:
            self.wizard_process_id.process_new_card_transaction()
            return message_wizard('Successful!')


    def update_and_retry(self):
        if self.wizard_process_id:
            self.wizard_process_id.write({
                "card_id": None,
                "card_card_number": "",
                "card_exp_year": "",
                "card_exp_month": "",
                "card_card_code": "",
                })
            action = self.env.ref('payment_ebizcharge_crm.action_process_ebiz_transaction').read()[0]
            action['res_id'] = self.wizard_process_id.id
            return action
        else:
            self.payment_id.write({
                "card_id": None,
                "card_card_number": "",
                "card_exp_year": "",
                "card_exp_month": "",
                "card_card_code": "",
                })
            context = dict(self.env.context)
            context['active_model'] = 'account.move'
            if self.payment_id:
                self.payment_id.action_cancel()
            return {
                'name': _('Register Payment'),
                'res_model': 'account.payment.register',
                'res_id': context['active_id'],
                'view_mode': 'form',
                'view_id': self.env.ref('account.view_account_payment_register_form').id,
                'context': context,
                'target': 'new',
                'type': 'ir.actions.act_window',
            }

    def show_void_wizard(self):
        wiz = self.env['wizard.ebiz.transaction.void'].create({
            'transaction_id': self.transaction_id.id,
            'wizard_process_id': self.wizard_process_id.id})
        action = self.env.ref('payment_ebizcharge_crm.action_ebiz_transaction_void_form').read()[0]
        action['res_id'] = wiz.id
        return action

    def message_wizard(self, context):
        return {
            'name': 'Success',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'message.wizard',
            'view_id': False,
            'type': 'ir.actions.act_window',
            'target': 'new',
            'context': context
        }
