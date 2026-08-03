
import logging

from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import ValidationError, UserError
from odoo.tools import format_amount

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'
    _description = "Payment Transactions"

    _ebizcharge_valid_tx_status = 1
    _ebizcharge_pending_tx_status = 4
    _ebizcharge_cancel_tx_status = 2

    ebiz_auth_code = fields.Char(string='Auth Code')
    security_code = fields.Char(string="Security Code")
    transaction_type = fields.Selection([
        ('pre_auth', 'Pre-Authorize'),
        ('deposit', 'Deposit'),
    ], string='Transaction Type', index=True)
    surcharge_percent = fields.Float(string='Surcharge %')
    is_pay_method_eligible = fields.Boolean(string='Card Eligible')
    is_zip_code_allowed = fields.Boolean(string='Zip Code Allowed')
    surcharge_amt = fields.Monetary(string='Surcharge Amount')
    emv_transaction = fields.Boolean(string='EMV', default=False)

    reminder_amount = fields.Monetary(string='Reminder Amount')
    captured_amount = fields.Monetary(string='Captured Amount')
    ebiz_avs_street = fields.Char(string='AVS Street')
    ebiz_avs_zip_code = fields.Char(string='AVS Zip Code')
    ebiz_cvv_resp = fields.Char(string='CVV Resp')
    ebiz_transaction_status = fields.Char(string='Transaction Status')
    ebiz_transaction_result = fields.Char(string='Result')

    def _check_amount_and_confirm_order(self):
        confirmed_orders = self.env['sale.order']
        for tx in self:
            if len(tx.sale_order_ids) == 1:
                quotation = tx.sale_order_ids.filtered(lambda so: so.state in ('draft', 'sent'))
                if quotation and quotation._is_confirmation_amount_reached():
                    quotation.action_confirm()
                    confirmed_orders |= quotation
        return confirmed_orders

    def _send_invoice(self):
        template_id = int(self.env['ir.config_parameter'].sudo().get_param(
            'sale.default_invoice_email_template',
            default=0
        ))
        if not template_id:
            return
        template = self.env['mail.template'].browse(template_id).exists()
        if not template:
            return

        for tx in self:
            if tx.provider_id.code != 'ebizcharge':
                tx = tx.with_company(tx.company_id).with_context(
                    company_id=tx.company_id.id,
                )
                invoice_to_send = tx.invoice_ids.filtered(
                    lambda i: not i.is_move_sent and i.state == 'posted' and i._is_ready_to_be_sent()
                )
                invoice_to_send.is_move_sent = True
                invoice_to_send.with_user(SUPERUSER_ID)._generate_pdf_and_send_invoice(template)

    @api.model_create_multi
    def create(self, val_list):
        # Tokens we temporarily reactivated only to satisfy _check_token_is_active during create.
        # Restored to archived after create completes — preserves user intent for is_card_save=False
        # (true one-time cards), while saved tokens stay active as a corrupt-state recovery.
        tokens_to_restore = self.env['payment.token']
        for vals in val_list:
            if 'provider_id' in vals:
                acquirer = self.env['payment.provider'].browse(vals['provider_id'])
                if acquirer.code == 'ebizcharge':
                    # Defensive: ebizcharge tokens can end up archived between s2s_process and
                    # the portal's transaction-create call (mass-archive sites in
                    # payment_token.unlink and res_partner.ebiz_get_payment_methods cascade in
                    # race conditions). Without this, Odoo core's _check_token_is_active
                    # blocks the transaction with "Creating a transaction from an archived
                    # token is forbidden." TOKEN-ARCHIVE-DIAG logging at the archive sites
                    # still captures the root cause whenever it fires.
                    if vals.get('token_id'):
                        token = self.env['payment.token'].sudo().browse(vals['token_id'])
                        if token and not token.active:
                            token.write({'active': True})
                            if not token.is_card_save:
                                tokens_to_restore |= token
                            else:
                                _logger.warning(
                                    "[TOKEN-ARCHIVE-DIAG] reactivated archived saved token id=%s "
                                    "partner=%s before transaction create — corrupt-state recovery, "
                                    "leaving active.", token.id, token.partner_id.id,
                                )
                    if 'payment_data' in self.env.context and 'invoice_ids' in vals:
                        vals.pop('invoice_ids')
                    if vals.get('reference') and 'invoice_ids' not in vals:
                        if 'payment_data' in self.env.context and 'invoice_id' in self.env.context['payment_data']:
                            vals['invoice_ids'] = [fields.Command.set(self.env.context['payment_data']['invoice_id'])]
                        else:
                            if 'payment_id' in vals:
                                if self.env.context.get('active_id'):
                                    inv_dett = self.env['account.move'].search([('id', '=', self.env.context.get('active_id'))]).ids
                                    if inv_dett:
                                        vals['invoice_ids'] = [fields.Command.set(inv_dett)]
                                elif self.env.context.get('active_model', '') == 'account.move.line':
                                    invoice_ids = self.env['account.move'].search(
                                        [('line_ids', '=', self.env.context.get('active_ids'))]).ids
                                    vals['invoice_ids'] = [fields.Command.set(invoice_ids)]
                                else:
                                    invoice_ref = self.env['account.payment'].search(
                                        [('id', '=', vals['payment_id'])]).payment_reference
                                    vals['invoice_ids'] = [
                                        fields.Command.set(self.env['account.move'].search(
                                            [('name', '=', invoice_ref)]).ids)]
                            else:
                                vals['invoice_ids'] = [
                                    fields.Command.set(
                                        self.env['account.move'].search([('invoice_origin', '=', vals['reference'])]).ids)]
                    if 'default_order_id' in self.env.context:
                        vals['sale_order_ids'] = [fields.Command.link(self.env.context['default_order_id'])]
        try:
            res = super().create(val_list)
            for trans in res:
                if trans.provider_id.code == 'ebizcharge':
                    prefix = trans.reference.split('-')[0]
                    if not prefix or prefix == 'tx':
                        payment_id = trans.payment_id
                        if payment_id and payment_id.payment_type == 'inbound':
                            prefix = self.env['ir.sequence'].next_by_code('advance.payment.transaction',
                                                                          sequence_date=trans.last_state_change)
                        if payment_id and payment_id.payment_type == 'outbound':
                            prefix = self.env['ir.sequence'].next_by_code('advance.payment.transaction',
                                                                          sequence_date=trans.last_state_change)
        finally:
            if tokens_to_restore:
                tokens_to_restore.sudo().write({'active': False})
        return res

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'ebizcharge' or len(tx) == 1:
            return tx
        _logger.info(notification_data)
        reference = notification_data.get("TransactionLookupKey")
        if not reference:
            error_msg = _('EBizCharge: received data with missing reference (%s)') % (reference)
            _logger.info(error_msg)
            raise ValidationError(error_msg)
        tx = self.search([('reference', '=', reference)])
        _logger.info(str(tx))
        if not tx or len(tx) > 1:
            error_msg = 'EBizCharge: received data for reference %s' % (reference)
            if not tx:
                error_msg += '; no order found'
            else:
                error_msg += '; multiple order found'
            _logger.info(error_msg)
            raise ValidationError(error_msg)
        return tx

    def _get_sent_message(self):
        self.ensure_one()
        message = super()._get_sent_message()
        if self.provider_code != 'ebizcharge':
            return message
        if self.operation not in ('online_redirect', 'online_direct', 'online_token', 'offline'):
            return message
        token_ebiz = self.env.context.get('token_ebiz') or {}
        bank_data = token_ebiz.get('bankData')
        card_data = token_ebiz.get('cardData')
        is_ach = False
        token_display = None
        if bank_data:
            is_ach = True
            token_display = f"*{bank_data.get('accountNumber')[-4:]}"
        elif card_data:
            token_display = f"*{card_data.get('cardNumber')[-4:]}"
        elif self.token_id:
            is_ach = self.token_id.token_type == 'ach'
            token_display = self.token_id._build_display_name()
        if token_display:
            return _(
                "A transaction with reference %(ref)s has been initiated using the %(payment_method)s "
                "%(token)s (%(provider_name)s). %(warning)s",
                ref=self.reference,
                payment_method='bank account payment' if is_ach else 'card payment',
                token=token_display,
                provider_name=self.provider_id.name,
                warning='Bank account payments require bank verification and may take 2–5 business days to clear. Please note that funds are not guaranteed until clearance is complete.' if is_ach else '',
            )
        return _(
            "A transaction with reference %(ref)s has been initiated (%(provider_name)s).",
            ref=self.reference, provider_name=self.provider_id.name,
        )

    def _get_received_message(self):
        self.ensure_one()
        if self.provider_code != 'ebizcharge':
            return super()._get_received_message()
        if 'from_invoice' in self.env.context:
            formatted_amount = self.env.context.get('invoice_id').amount_residual if self.env.context.get(
                'invoice_id').payment_state != 'paid' else self.env.context.get('invoice_id').amount_total
        else:
            formatted_amount = format_amount(self.env, self.amount, self.currency_id)
        if self.state == 'pending':
            message = _(
                "The transaction with reference %(ref)s for amount %(amount)s is pending (%(acq_name)s).",
                ref=self.reference, amount=formatted_amount, acq_name=self.provider_id.name
            )
        elif self.state == 'authorized':
            msg = 'authorized'
            if 'from_invoice' in self.env.context:
                msg = 'captured'
            message = _(
                "The transaction with reference %(ref)s for amount %(amount)s has been %(msg)s "
                "(%(acq_name)s).", ref=self.reference, msg=msg, amount=formatted_amount,
                acq_name=self.provider_id.name
            )
        elif self.state == 'done':
            msg = 'confirmed'
            if self.transaction_type == 'deposit':
                msg = 'deposited'
            if self.transaction_type == 'pre_auth':
                msg = 'captured'
            message = _(
                "The transaction with reference %(ref)s for amount %(amount)s has been  %(msg)s "
                "(%(acq_name)s).", ref=self.reference, msg=msg, amount=formatted_amount,
                acq_name=self.provider_id.name
            )
        elif self.state == 'error':
            message = _(
                "The transaction with reference %(ref)s for amount %(amount)s encountered an error"
                " (%(acq_name)s).",
                ref=self.reference, amount=formatted_amount, acq_name=self.provider_id.name
            )
            if self.state_message:
                message += "<br />" + _("Error: %s", self.state_message)
        else:
            # provider_reference is populated only when EBizCharge actually returned a
            # response (their RefNum). If it's empty, the cancel happened locally without
            # the gateway being involved — don't misattribute the cancel to EBizCharge.
            came_from_ebiz = bool(self.provider_reference)
            if came_from_ebiz:
                if self.state_message:
                    message = _(
                        "The transaction with reference %(ref)s for amount %(amount)s is canceled "
                        "(%(acq_name)s): %(reason)s",
                        ref=self.reference, amount=formatted_amount,
                        acq_name=self.provider_id.name, reason=self.state_message,
                    )
                else:
                    message = _(
                        "The transaction with reference %(ref)s for amount %(amount)s is canceled "
                        "(%(acq_name)s).",
                        ref=self.reference, amount=formatted_amount,
                        acq_name=self.provider_id.name,
                    )
            else:
                message = _(
                    "The transaction with reference %(ref)s for amount %(amount)s is canceled.",
                    ref=self.reference, amount=formatted_amount,
                )
                if self.state_message:
                    message += "<br />" + _("Reason: %s", self.state_message)
        if self.reference == 'EBiz_EMV':
            message = "EMV Device Transaction Completed"
        return message

    def run_ebiz_transaction_with_bank_data(self, token_ebiz=None):
        if self.provider_code != 'ebizcharge':
            return
        if token_ebiz is not None and 'bankData' in token_ebiz:
            self.ensure_one()
            command = 'Check'
            token_latest = self.env['payment.token'].search([('partner_id', '=', self.partner_id.id)],
                                                            order='create_date DESC',
                                                            limit=1)
            if self.sale_order_ids:
                resp = self.sale_order_ids.run_ebiz_transaction(token_latest, command,
                                                                token_ebiz=token_ebiz['bankData'])
                if 'full_amount' not in self.env.context and resp['ResultCode'] not in ["D", "E"]:
                    self._set_authorized()
                if 'set_done' in self.env.context and resp['ResultCode'] not in ["D", "E"]:
                    self._set_done()
                resp['x_type'] = 'Check'
            elif self.invoice_ids:
                command = 'Check'
                if self.env.context.get('run_transaction') and 'bankData' in token_ebiz:
                    resp = self.invoice_ids.with_context({'run_transaction': True}).run_ebiz_transaction(token_latest, command, token_ebiz=token_ebiz['bankData'])
                else:
                    resp = self.invoice_ids.run_ebiz_transaction(token_latest, command,
                                                                 token_ebiz=token_ebiz['bankData'])
                resp['x_type'] = command
                self.invoice_ids[0].is_payment_processed = True
                if self.invoice_ids[0].save_payment_link:
                    self.invoice_ids[0].delete_ebiz_invoice()
            else:
                ebiz = self.get_ebiz_charge_obj(website_id=self.env['website'].get_current_website(fallback=False),
                                                instance=self.partner_id.ebiz_profile_id)
                resp = ebiz.run_transaction_without_invoice(self)
                resp['x_type'] = 'Check'

            if self.invoice_ids and self.invoice_ids[0].move_type == 'out_refund':
                resp['x_type'] = 'refunded'
            self._ebizcharge_s2s_validate_tree(resp)
            self.write({
                'state_message': resp['Error'],
                "provider_reference": resp['RefNum'],
                "ebiz_auth_code": resp['AuthCode']
            })
            if 'web_pay' in self.env.context and self.env.context['web_pay'] == '1' and resp['ResultCode'] not in ["D", "E"]:
                self._set_authorized()
                if self.sale_order_ids:
                    self._set_done()
                    self._post_process()
                if self.invoice_ids:
                    self._set_done()
            return resp

    def _log_sent_message(self, token_ebiz=None):
        super()._log_sent_message()
        if self.provider_code != 'ebizcharge':
            return
        if token_ebiz is not None and 'cardData' in token_ebiz:
            self.ensure_one()
            command = 'Sale'
            token_latest = self.env['payment.token'].search([('partner_id', '=', self.partner_id.id)], order='create_date DESC',
                                                           limit=1)
            if self.sale_order_ids:
                if 'pre_auth_order' not in self.env.context:
                    if self.partner_id.ebiz_profile_id.ebiz_website_allowed_command == 'pre-auth':
                        command = "AuthOnly"
                    else:
                        command = "Sale"
                else:
                    command = "AuthOnly"
                    if self.transaction_type == 'deposit':
                        command = "Sale"
                        self.payment_id.action_post()
                resp = self.sale_order_ids.run_ebiz_transaction(token_latest, command, token_ebiz=token_ebiz['cardData'])
                if command == "AuthOnly" and resp['ResultCode'] not in ["D", "E"]:
                    self.write({'transaction_type': 'pre_auth'})
                if 'full_amount' not in self.env.context and resp['ResultCode'] not in ["D", "E"]:
                    self._set_authorized()
                if not self.security_code and 'set_done' in self.env.context and resp['ResultCode'] not in ["D", "E"] and self.partner_id.ebiz_profile_id.ebiz_website_allowed_command != 'pre-auth' and 'pre_auth_order' not in self.env.context:
                    self._set_done()
                resp['x_type'] = 'capture' if command == "Sale" else command
            elif self.invoice_ids:
                command = 'Sale'
                if self.env.context.get('run_transaction') and 'cardData' in token_ebiz:
                    resp = self.invoice_ids.with_context({'run_transaction': True}).run_ebiz_transaction(token_latest,
                                                                                                         command,
                                                                                                         token_ebiz=token_ebiz['cardData'])
                else:
                    resp = self.invoice_ids.run_ebiz_transaction(token_latest, command, token_ebiz=token_ebiz['cardData'])
                resp['x_type'] = command
                self.invoice_ids[0].is_payment_processed = True
                if self.invoice_ids[0].save_payment_link:
                    self.invoice_ids[0].delete_ebiz_invoice()
            else:
                ebiz = self.get_ebiz_charge_obj(website_id=self.env['website'].get_current_website(fallback=False),
                                                instance=self.partner_id.ebiz_profile_id)
                resp = ebiz.run_transaction_without_invoice(self)
                resp['x_type'] = 'Sale'

            if self.invoice_ids and self.invoice_ids[0].move_type == 'out_refund':
                resp['x_type'] = 'refunded'
            self._ebizcharge_s2s_validate_tree(resp)
            self.write({
                'state_message': resp['Error'],
                "provider_reference": resp['RefNum'],
                "ebiz_auth_code": resp['AuthCode']
            })
            if 'web_pay' in self.env.context and self.env.context['web_pay'] == '1' and resp['ResultCode'] not in ["D","E"]:
                self._set_authorized()
                if self.sale_order_ids and self.partner_id.ebiz_profile_id.ebiz_website_allowed_command != 'pre-auth':
                    self._set_done()
                if self.invoice_ids:
                    self._set_done()
            self.get_surcharge_amount_new(card_num=token_ebiz['cardData']['cardNumber'], zip_code=token_ebiz['cardData']['zip'])
            return resp
        elif token_ebiz is not None and 'bankData' in token_ebiz:
            self.run_ebiz_transaction_with_bank_data(token_ebiz)

    def get_surcharge_amount_new(self, card_num=None, zip_code=None):
        instance = (
            self.partner_id.ebiz_profile_id
            or self.env.user.partner_id.ebiz_profile_id
            or self.env['ebizcharge.instance.config'].search(
                [('is_valid_credential', '=', True), ('is_default', '=', True)], limit=1)
            or None
        )
        ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
        if zip_code and card_num and ebiz:
            params = {
                'securityToken': ebiz._generate_security_json(),
                'customerInternalId': self.partner_id.ebiz_internal_id,
                'amount': self.amount,
                'cardNumber': card_num,
                'cardZipCode': zip_code,
            }
            resp = ebiz.client.service.CalculateSurchargeAmount(**params)
            self.write({
                'is_zip_code_allowed': resp['IsSurchargeAllowedForZipCode'],
                'is_pay_method_eligible': resp['IsSurchargeAllowedForPaymentMethod'],
                'surcharge_percent': float(resp['SurchargePercentage']) if resp['IsSurchargeEnabled'] else 0,
                'surcharge_amt': float(resp['SurchargeAmount']) if resp['IsSurchargeEnabled'] else 0,
            })

    def get_avs_street_zip(self, resp):
        avs = resp['AvsResultCode']
        address, zip_code = 'No Match', 'No Match'

        if avs in ['YYY', 'Y', 'YYA', 'YYD']:
            address = zip_code = 'Match'
        if avs in ['NYZ', 'Z']:
            zip_code = 'Match'
        if avs in ['YNA', 'A', 'YNY']:
            address = 'Match'
        if avs in ['YYX', 'X']:
            address = zip_code = 'Match'
        if avs in ['NYW', 'W']:
            zip_code = 'Match'
        if avs in ['GGG', 'D']:
            address = zip_code = 'Match'
        if avs in ['YGG', 'P']:
            zip_code = 'Match'
        if avs in ['YYG', 'B', 'M']:
            address = 'Match'

        self.ebiz_avs_street = address
        self.ebiz_avs_zip_code = zip_code
        return address.strip(), zip_code.strip()

    def _send_payment_request(self):
        super()._send_payment_request()
        if self.provider_code != 'ebizcharge':
            return
        if not self.token_id:
            raise UserError("EBizCharge: " + _("The transaction is not linked to a token."))
        self.ensure_one()
        if self.sale_order_ids:
            if 'pre_auth_order' not in self.env.context:
                if self.partner_id.ebiz_profile_id.ebiz_website_allowed_command == 'pre-auth':
                    command = "AuthOnly"
                else:
                    command = "Sale"
            else:
                command = "AuthOnly"
                if self.transaction_type == 'deposit':
                    command = "Sale"
                    self.payment_id.action_post()
            command_with_surcharge = command
            ebiz_profile_id = self.sale_order_ids.partner_id.ebiz_profile_id
            if not self.sale_order_ids.sale_enable_sur and ebiz_profile_id.merchant_toggle_sur_per_txn and self.env.context.get('web_pay') != '1':
                command_with_surcharge += ';IsSurchargeEnabled=false'
            resp = self.sale_order_ids.run_ebiz_transaction(self.token_id, command_with_surcharge)
            if command == "AuthOnly" and resp['ResultCode'] not in ["D", "E"]:
                self.write({'transaction_type': 'pre_auth'})
            if 'full_amount' not in self.env.context and resp['ResultCode'] not in ["D", "E"]:
                self._set_authorized()
            if not self.security_code and 'set_done' in self.env.context and resp['ResultCode'] not in ["D", "E"] and self.partner_id.ebiz_profile_id.ebiz_website_allowed_command != 'pre-auth' and 'pre_auth_order' not in self.env.context:
                self._set_done()
            resp['x_type'] = 'capture' if command == "Sale" else command
        elif self.invoice_ids:
            command = 'Credit' if self.invoice_ids[0].move_type == 'out_refund' else 'Sale'
            command_with_surcharge = command
            ebiz_profile_id = self.invoice_ids[0].partner_id.ebiz_profile_id
            if not self.invoice_ids[0].inv_enable_sur and ebiz_profile_id.merchant_toggle_sur_per_txn and self.env.context.get('web_pay') != '1':
                command_with_surcharge += ';IsSurchargeEnabled=false'
            if self.env.context.get('run_transaction'):
                resp = self.invoice_ids.with_context({'run_transaction': True}).run_ebiz_transaction(self.token_id,
                                                                                                     command_with_surcharge,
                                                                                                     self.env.context.get('card'))
            else:
                resp = self.invoice_ids.run_ebiz_transaction(self.token_id, command_with_surcharge)

            self.invoice_ids[0].is_payment_processed = True
            if self.invoice_ids[0].save_payment_link:
                self.invoice_ids[0].delete_ebiz_invoice()
            resp['x_type'] = command
        else:
            web_sale = self.env['ir.module.module'].sudo().search(
                [('name', '=', 'website_sale'), ('state', 'in', ['installed', 'to upgrade', 'to remove'])])
            website = self.env['website'].get_current_website(fallback=False) if web_sale else False
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(website_id=website,
                                            instance=self.partner_id.ebiz_profile_id)
            resp = ebiz.run_transaction_without_invoice(self)
            resp['x_type'] = 'Sale'

        if self.invoice_ids and self.invoice_ids[0].move_type == 'out_refund':
            resp['x_type'] = 'refunded'
        self._ebizcharge_s2s_validate_tree(resp)
        result = self.get_avs_street_zip(resp)
        self.write({
            'state_message': resp['Error'],
            "provider_reference": resp['RefNum'],
            "ebiz_auth_code": resp['AuthCode'],
            "ebiz_avs_street": result[0],
            "ebiz_avs_zip_code": result[1],
            "ebiz_cvv_resp": resp['CardCodeResult'],
            "ebiz_transaction_status": resp['Status'],
            "ebiz_transaction_result": resp['Result'],
        })

        if 'web_pay' in self.env.context and self.env.context['web_pay'] == '1' and resp['ResultCode'] not in ["D", "E"]:
            self._set_authorized()
            if self.sale_order_ids and self.partner_id.ebiz_profile_id.ebiz_website_allowed_command != 'pre-auth':
                self._set_done()
            if self.invoice_ids:
                self._set_done()
        if self.token_id.token_type == 'credit' and self.partner_id.ebiz_profile_id.is_surcharge_enabled and self.partner_id.ebiz_profile_id.surcharge_type_id == 'DailyDiscount':
            self.get_surcharge_amount()
        return resp

    def get_surcharge_amount(self):
        ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=self.partner_id.ebiz_profile_id)
        params = {
            'securityToken': ebiz._generate_security_json(),
            'customerInternalId': self.token_id.partner_id.ebiz_internal_id,
            'paymentMethodId': self.token_id.ebizcharge_profile,
            'amount': self.amount,
            'cardZipCode': self.token_id.avs_zip,
        }
        resp = ebiz.client.service.CalculateSurchargeAmount(**params)
        self.write({
            'is_zip_code_allowed': resp['IsSurchargeAllowedForZipCode'],
            'is_pay_method_eligible': resp['IsSurchargeAllowedForPaymentMethod'],
            'surcharge_percent': float(resp['SurchargePercentage']) if resp['IsSurchargeEnabled'] else 0,
            'surcharge_amt': float(resp['SurchargeAmount']) if resp['IsSurchargeEnabled'] else 0,
        })
        return resp

    def _send_capture_request(self, amount_to_capture=None):
        child_capture_tx = super()._send_capture_request()
        if self.provider_code != 'ebizcharge':
            return child_capture_tx
        for trans in self:
            ebiz_obj = self.env['ebiz.charge.api']
            if trans.payment_id:
                sale_order_ids = trans.sale_order_ids
                web_sale = self.env['ir.module.module'].sudo().search(
                    [('name', '=', 'website_sale'), ('state', 'in', ['installed', 'to upgrade', 'to remove'])])

                if web_sale:
                    ebiz = ebiz_obj.get_ebiz_charge_obj(sale_order_ids.website_id,
                                                              instance=self.partner_id.ebiz_profile_id)
                else:
                    ebiz = ebiz_obj.get_ebiz_charge_obj(instance=self.partner_id.ebiz_profile_id)
                if 'from_invoice' in self.env.context and self.env.context.get('invoice_id'):
                    invoice_id = self.env.context.get('invoice_id')
                    order_id = sale_order_ids.filtered(lambda so: invoice_id.id in so.invoice_ids.ids)
                    invoice_id.inv_enable_sur = order_id.sale_enable_sur
                    emv_trans = self.env.context.get('emv_trans') if trans.emv_transaction else None
                    tree = ebiz.capture_transaction(trans, invoice=invoice_id,
                                                    ebiz_transaction_amt=trans.amount,
                                                    emv_trans=emv_trans)
                    if trans.emv_transaction:
                        trans.captured_amount = trans.amount
                    else:
                        capture_amount_calc = invoice_id.amount_residual if invoice_id.payment_state != 'paid' else invoice_id.amount_total
                        trans.captured_amount += capture_amount_calc
                        trans.reminder_amount = trans.amount - trans.captured_amount
                        trans.payment_id.amount = capture_amount_calc
                else:
                    if trans.emv_transaction:
                        tree = ebiz.capture_transaction(trans, emv_trans=self.env.context.get('emv_trans'))
                        trans.captured_amount = trans.amount
                    elif sale_order_ids:
                        tree = ebiz.capture_transaction(trans, sale=sale_order_ids)
                        trans.captured_amount = trans.amount

                if trans.payment_id.state == 'draft':
                    trans.payment_id.action_post()
                if tree:
                    tree['x_type'] = 'capture'
                    trans._ebizcharge_s2s_validate_tree(tree)

                if trans.sale_order_ids.invoice_ids:
                    trans.sale_order_ids.invoice_ids.filtered(lambda i: i.state == 'draft').action_post()
                    trans.sale_order_ids.invoice_ids.action_capture_reconcile(trans.payment_id)
                if not trans.sale_order_ids.invoice_ids and trans.invoice_ids.filtered(lambda i: i.payment_state == 'not_paid'):
                    trans.invoice_ids.action_capture_reconcile(trans.payment_id)

            else:
                sale_order_ids = trans.sale_order_ids
                if not sale_order_ids and trans.source_transaction_id:
                    sale_order_ids = trans.source_transaction_id.sale_order_ids
                    if sale_order_ids:
                        trans.write({'sale_order_ids': [(6, 0, sale_order_ids.ids)]})
                ebiz = ebiz_obj.get_ebiz_charge_obj(sale_order_ids.website_id if sale_order_ids else None,
                                                          instance=self.partner_id.ebiz_profile_id)
                if sale_order_ids:
                    if 'from_invoice' in self.env.context:
                        invoice_id = self.env.context.get('invoice_id')
                        order_id = sale_order_ids.filtered(lambda so: invoice_id.id in so.invoice_ids.ids)
                        invoice_id.inv_enable_sur = order_id.sale_enable_sur
                        tree = ebiz.capture_transaction(trans, invoice=invoice_id,
                                                        ebiz_transaction_amt=trans.amount)
                        capture_amount_calc = invoice_id.amount_residual if invoice_id.payment_state != 'paid' else invoice_id.amount_total
                        trans.captured_amount += capture_amount_calc
                    else:
                        tree = ebiz.capture_transaction(trans, sale=sale_order_ids)
                        trans.captured_amount = trans.amount
                else:
                    tree = ebiz.capture_transaction(trans)
                tree['x_type'] = 'capture'
                trans._ebizcharge_s2s_validate_tree(tree)
                if trans.sale_order_ids.invoice_ids:
                    trans.sale_order_ids.invoice_ids.filtered(lambda i: i.state == 'draft').action_post()
                    trans.sale_order_ids.invoice_ids.action_capture_reconcile(trans.payment_id)
                if not trans.sale_order_ids.invoice_ids and trans.invoice_ids.filtered(
                        lambda i: i.payment_state == 'not_paid'):
                    trans.invoice_ids.action_capture_reconcile(trans.payment_id)
        return child_capture_tx

    def ebizcharge_s2s_capture_transaction(self):
        for trans in self:
            sale_order_ids = trans.sale_order_ids
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(sale_order_ids.website_id,
                                                      instance=self.partner_id.ebiz_profile_id)
            tree = ebiz.capture_transaction(trans)
            tree['x_type'] = 'capture'
            is_validated = trans._ebizcharge_s2s_validate_tree(tree)
        return is_validated

    def _send_void_request(self, amount_to_void=None):
        super()._send_void_request()
        if self.provider_code != 'ebizcharge':
            return
        self.ensure_one()
        ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=self.partner_id.ebiz_profile_id)
        tree = ebiz.void_transaction(self, self)
        tree['x_type'] = 'void'
        return self._ebizcharge_s2s_validate_tree(tree)

    def _create_refund_transaction(self, amount_to_refund=False, **kwargs):
        rec = super()._create_refund_transaction(amount_to_refund=amount_to_refund)
        if self.provider_code == 'ebizcharge':
            self.ensure_one()
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=self.partner_id.ebiz_profile_id)
            kwargs["ref_num"] = self.provider_reference
            resp = ebiz.return_transaction(**kwargs)
            resp['x_type'] = "refunded"
            return self._ebizcharge_s2s_validate_tree(resp)
        else:
            return rec

    def _ebizcharge_s2s_validate_tree(self, tree):
        return self._ebizcharge_s2s_validate(tree)

    def _ebizcharge_s2s_validate(self, tree, command="authorized"):
        self.ensure_one()
        if tree['ResultCode'] == "A":
            if tree['x_type'] in ['AuthOnly', 'sale', 'Sale']:
                self.write({
                    'provider_reference': tree['RefNum'],
                    'ebiz_auth_code': tree['AuthCode'],
                    'last_state_change': fields.Datetime.now(),
                })
                if 'full_amount' not in self.env.context:
                    self._set_authorized()
                return True
            if tree['x_type'] in ['capture', 'Check']:
                self.write({
                    'provider_reference': tree['RefNum'],
                    'ebiz_auth_code': tree['AuthCode'],
                })
                return self._set_done()
            if tree['x_type'] == 'void':
                self._set_canceled()
            if tree['x_type'] == 'refunded':
                self.write({
                    'provider_reference': tree['RefNum'],
                    'ebiz_auth_code': tree['AuthCode'],
                })
            return True

        if tree['ResultCode'] in ["D", "E"]:
            self.write({
                'state_message': tree['Error'],
                'provider_reference': tree['RefNum'],
                'ebiz_auth_code': tree['AuthCode'],
            })
            self._set_canceled()
            if self.payment_id.state not in ['posted', 'cancel']:
                self.payment_id.action_cancel()

    def _set_authorized(self, state_message=None, **kwargs):
        trans_type = "Authorized"
        if self.provider_code != 'ebizcharge':
            return super(PaymentTransaction, self)._set_authorized()
        self._ebiz_create_application_transaction(trans_type)
        return super(PaymentTransaction, self)._set_authorized()

    def _set_done(self):
        if self.provider_code != 'ebizcharge':
            return super(PaymentTransaction, self)._set_done()
        trans_type = "Captured" if self.state == 'authorized' else "Sale"
        self._ebiz_create_application_transaction(trans_type)
        return super(PaymentTransaction, self)._set_done()

    def _set_canceled(self, state_message=None, **kwargs):
        if self.provider_code != 'ebizcharge':
            return super()._set_canceled(state_message=state_message, **kwargs)
        if self.state == 'authorized':
            self._ebiz_create_application_transaction('Voided')
        return super()._set_canceled(state_message=state_message, **kwargs)

    def _ebiz_create_application_transaction(self, trans_type):
        if self.sale_order_ids:
            params = {
                "partner_id": self.sale_order_ids[0].partner_id.id,
                "sale_order_id": self.sale_order_ids[0].id,
                "transaction_id": self.id,
                "transaction_type": trans_type
            }
            app_trans = self.env['ebiz.application.transaction'].create(params)
            if self.sale_order_ids.ebiz_internal_id:
                app_trans.ebiz_add_application_transaction()
        return True

    def _create_payment(self, **extra_create_values):
        invoice_id = self.env.context.get('invoice_id')
        if invoice_id:
            extra_create_values['payment_reference'] = invoice_id.name
            # Use the invoice residual amount so the payment matches what was
            # actually captured (EBizCharge captures amount_residual, not trans.amount).
            if invoice_id.payment_state != 'paid' and invoice_id.amount_residual > 0:
                extra_create_values['amount'] = invoice_id.amount_residual
        return super()._create_payment(**extra_create_values)

    def _create_child_transaction(self, amount, is_refund=False, **custom_create_values):
        if self.provider_code == 'ebizcharge':
            if self.emv_transaction:
                custom_create_values.setdefault('emv_transaction', True)
            # When the parent token has been archived (one-time card with Save Card
            # unchecked), _check_token_is_active blocks creating the child.
            # Reactivate the token only for the duration of the child create, then
            # restore the archived state. The child ends up with the same token
            # reference as the parent, keeping all downstream reads working.
            if (
                self.provider_code == 'ebizcharge'
                and self.token_id
                and not self.token_id.active
            ):
                token_sudo = self.token_id.sudo()
                token_sudo.write({'active': True})
                try:
                    return super()._create_child_transaction(amount, is_refund=is_refund, **custom_create_values)
                finally:
                    token_sudo.write({'active': False})
        return super()._create_child_transaction(amount, is_refund=is_refund, **custom_create_values)

    @api.model
    def _set_payment_memo(self):
        memo = ''
        if len(self.invoice_ids) == 1:
            memo = self.invoice_ids.name + ' ' + (self.invoice_ids.ref or '')
            if self.token_id:
                memo += ' ' + self.token_id.get_encrypted_name()
        elif len(self.invoice_ids) > 1:
            for invoice in self.invoice_ids:
                memo = '(' + invoice.name + ' ' + (invoice.ref or '') + ')'
                if self.token_id:
                    memo += ' ' + self.token_id.get_encrypted_name() + ' '
        if len(self.sale_order_ids) == 1:
            memo = self.sale_order_ids.name + ' ' + (self.sale_order_ids.client_order_ref or '')
            if self.token_id:
                memo += ' ' + self.token_id.get_encrypted_name()
        elif len(self.sale_order_ids) > 1:
            for order_id in self.sale_order_ids:
                memo = '(' + order_id.name + ' ' + (order_id.client_order_ref or '') + ')'
                if self.token_id:
                    memo += ' ' + self.token_id.get_encrypted_name() + ' '
        if memo:
            self.payment_id.memo = memo

    def _post_process(self):
        super(PaymentTransaction, self)._post_process()
        if self.provider_code == 'ebizcharge':
            if self.partner_id.ebiz_profile_id.payment_memo_setting == 'dn_pon_pm':
                self._set_payment_memo()
            for inv in self.invoice_ids:
                inv.sync_to_ebiz()

    def _post_process_transactions(self):
        for tx in self:
            if tx.payment_id and tx.payment_id.state in ['draft', 'in_process']:
                tx.payment_id.action_post()
            tx._post_process()
