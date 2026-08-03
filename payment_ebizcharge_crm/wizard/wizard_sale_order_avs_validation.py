from odoo import fields, models, _, api


class WizardSaleOrderTransactionValidation(models.TransientModel):
    _name = 'wizard.ebiz.sale.order.transaction.validation'
    _description = "Wizard EBiz Sale Order Transaction Validation"

    wizard_process_id = fields.Many2one('custom.register.payment')
    address = fields.Char('Address', default="Match")
    zip_code = fields.Char('Zip/Postal Code', default="Match")
    card_code = fields.Char('CVV2/CVC', default="Match")
    check_avs_match = fields.Boolean(compute="_compute_avs_validation_resp")
    is_card_denied = fields.Boolean("Is Card Denied")
    denied_message = fields.Char("Denied Message")
    transaction_id = fields.Many2one('payment.transaction')
    full_amount_avs = fields.Boolean("Full Amount AVS")
    order_id = fields.Many2one('sale.order')

    def _compute_avs_validation_resp(self):
        self.check_avs_match = (self.card_code.strip() == 'Match') and (self.address.strip() == 'Match') and (
                    self.zip_code.strip() == 'Match')

    @api.model
    def _set_payment_memo(self, payments):
        for payment in payments:
            if payment.memo:
                memo = " ".join(val for val in [payment.memo, self.order_id.client_order_ref] if val)
            else:
                memo = " ".join(val for val in [self.order_id.name, self.order_id.client_order_ref] if val)
            if payment.payment_token_id:
                memo += ' ' + payment.payment_token_id.get_encrypted_name()
            payment.memo = memo

    def process_transaction_anyway(self):
        if not self.wizard_process_id.payment_token_id:
            token_id = self.create_credit_card_payment_method().id
            self.wizard_process_id.write({'payment_token_id': token_id})
        if not self.transaction_id:
            return self._process_new_transaction()
        return self._process_existing_transaction()

    def _process_new_transaction(self):
        ebiz_method = self.env['account.payment.method.line'].search(
            [('journal_id', '=', self.wizard_process_id.journal_id.id), ('payment_method_id.code', '=', 'ebizcharge')], limit=1)
        payment = self.env['account.payment'].sudo().create({
            'journal_id': self.wizard_process_id.journal_id.id,
            'payment_method_id': ebiz_method.payment_method_id.id,
            'payment_method_line_id': ebiz_method.id,
            'payment_token_id': self.wizard_process_id.payment_token_id.id,
            'amount': abs(self.wizard_process_id.amount),
            'partner_id': self.wizard_process_id.sub_partner_id.id,
            'partner_type': 'customer',
            'payment_type': 'inbound',
            'ebiz_avs_street': self.wizard_process_id.ebiz_avs_street,
            'ebiz_avs_zip': self.wizard_process_id.ebiz_avs_zip,
            'ebiz_send_receipt': self.wizard_process_id.ebiz_send_receipt,
            'ebiz_receipt_emails': self.wizard_process_id.ebiz_receipt_emails,
        })
        transactions = payment.with_context({'default_order_id': self.order_id.id}).sudo()._create_payment_transaction()
        self.write({'transaction_id': transactions.id})
        transactions.sudo().write({
            'payment_id': payment.id,
            'sale_order_ids': [self.wizard_process_id.order_id.id],
            'invoice_ids': False,
            'transaction_type': self.wizard_process_id.transaction_type,
        })
        transactions.with_context({'pre_auth_order': True}).sudo()._send_payment_request()
        self.wizard_process_id.order_id.write({'transaction_ids': [fields.Command.set([transactions.id])]})
        payment.write({'payment_transaction_id': transactions.id})
        if self.wizard_process_id.order_id.partner_id.ebiz_profile_id.payment_memo_setting == 'dn_pon_pm':
            self._set_payment_memo(payment)
        if not self.wizard_process_id.card_save and not self.wizard_process_id.card_id:
            self.wizard_process_id.payment_token_id.delete_payment_method()
            self.wizard_process_id.partner_id.refresh_payment_methods()
        return self.message_wizard(self._build_success_context(payment.payment_transaction_id, payment))

    def _process_existing_transaction(self):
        transactions = self.transaction_id
        self.transaction_id.sudo()._set_authorized()
        self.wizard_process_id.order_id.write({'transaction_ids': [fields.Command.set([transactions.id])]})
        self.transaction_id.payment_id.write({
            'payment_transaction_id': transactions.id,
            'transaction_ref': transactions.reference or self.wizard_process_id.memo,
        })
        if self.wizard_process_id.order_id.partner_id.ebiz_profile_id.payment_memo_setting == 'dn_pon_pm':
            self._set_payment_memo(self.transaction_id.payment_id)
        if not self.wizard_process_id.card_save and not self.wizard_process_id.card_id:
            self.wizard_process_id.payment_token_id.delete_payment_method()
            self.wizard_process_id.partner_id.refresh_payment_methods()
        return self.message_wizard(self._build_success_context(self.transaction_id, self.transaction_id.payment_id))

    def _build_success_context(self, txn, payment):
        context = {
            'message': 'Transaction has been successfully processed!',
            'default_is_ach': self.wizard_process_id.token_type != 'credit',
            'default_currency_id': txn.currency_id.id,
            'default_partner_id': txn.token_id.partner_id.name if txn.token_id else payment.partner_id.name,
            'default_transaction_type': 'Auth Only' if txn.transaction_type == 'pre_auth' else 'Sale',
            'default_surcharge_percent': f"{txn.surcharge_percent:.2f} %",
            'default_document_number': txn.reference,
            'default_reference_number': txn.provider_reference,
            'default_auth_code': txn.ebiz_auth_code,
            'default_payment_method': txn.token_id.get_encrypted_name() if txn.token_id else payment.partner_id.name,
            'default_date_paid': txn.last_state_change,
            'default_subtotal': txn.amount,
            'default_avs_street': payment.ebiz_avs_street or txn.ebiz_avs_street,
            'default_avs_zip_code': payment.ebiz_avs_zip or txn.ebiz_avs_zip_code,
            'default_cvv': txn.ebiz_cvv_resp,
            'default_enable_surcharge': payment.enable_surcharge,
            'default_surcharge_total': txn.amount,
        }
        if payment.partner_id.ebiz_profile_id.is_surcharge_enabled and payment.enable_surcharge:
            eligible = txn.is_pay_method_eligible and txn.is_zip_code_allowed
            context.update({
                'default_is_surcharge': bool(payment.partner_id.ebiz_profile_id.is_surcharge_enabled),
                'default_is_eligible': eligible,
                'default_surcharge_subtotal': payment.amount,
                'default_surcharge_amount': txn.surcharge_amt,
                'default_surcharge_percentage': txn.surcharge_percent,
                'default_surcharge_total': payment.amount + float(txn.surcharge_amt),
            })
        return context

    def show_void_wizard(self):
        return {
            'name': _('Register Payment'),
            'res_model': 'custom.register.payment',
            'res_id': self.wizard_process_id.id,
            'view_mode': 'form',
            'view_id': self.env.ref('payment_ebizcharge_crm.view_custom_register_payment').id,
            'target': 'new',
            'type': 'ir.actions.act_window',
        }

    def create_credit_card_payment_method(self):
        if not self.order_id.partner_id.ebiz_internal_id:
            self.order_id.partner_id.sync_to_ebiz()
        method = self.env.ref('payment_ebizcharge_crm.payment_method_ebizcharge').id
        params = {
            "payment_details": 'XXXXXXXXXXXX%s' % self.wizard_process_id.card_card_number[-4:],
            "account_holder_name": self.wizard_process_id.card_account_holder_name,
            "payment_method_id": method,
            "card_number": self.wizard_process_id.card_card_number,
            "card_exp_year": self.wizard_process_id.card_exp_year,
            "card_exp_month": self.wizard_process_id.card_exp_month,
            "avs_street": self.wizard_process_id.card_avs_street,
            "avs_zip": self.wizard_process_id.card_avs_zip,
            "card_code": self.wizard_process_id.card_card_code,
            "partner_id": self.wizard_process_id.sub_partner_id.id,
            "user_id": self.env.user.id,
            "active": True,
            "provider_ref": "Temp",
            "is_card_save": self.wizard_process_id.card_save,
            'provider_id': self.env['payment.provider'].search(
                [('company_id', '=', self.order_id.company_id.id), ('code', '=', 'ebizcharge')]).id
        }
        self.wizard_process_id.reset_credit_card_fields()
        token = self.env['payment.token'].create(params)
        token.action_sync_token_to_ebiz()
        return token

    def void_transaction(self):
        self.transaction_id.sudo()._send_void_request()
        if self.transaction_id.state != 'cancel':
            self.transaction_id.sudo()._set_canceled()
        if self.transaction_id.payment_id.state != 'cancel':
            self.transaction_id.payment_id.sudo().action_cancel()
        if not self.wizard_process_id.card_save and not self.wizard_process_id.card_id:
            self.wizard_process_id.payment_token_id.delete_payment_method()
            self.wizard_process_id.partner_id.refresh_payment_methods()

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
